"""Public demo server: bundled run artifacts, the suite, a bounded scripted evaluator, and an optional
token-gated live mode. Stdlib only.

GET responses are built once at startup from files and served from memory by exact path, so no
request ever touches the filesystem. POST /api/evaluate replays a user-supplied FakeAgentAdapter
script against a fresh in-memory sandbox: no network, no file writes. Requests never choose an agent
URL. Live mode (POST /api/live-run) queues one suite case and returns 202 at once; a background thread
runs it through the webhook adapter against the agent hosted next to this server, at a URL fixed at
startup, and GET /api/live-runs/<run_id> reports its status and, when done, the artifact.
"""

import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import Field, ValidationError

from bolibench.adapters import FakeAgentAdapter, Step
from bolibench.evaluate import evaluate
from bolibench.models import AdapterInfo, Artifact, Model, Summary, TestCase
from bolibench.runner import run_case
from bolibench.store import load_suite
from bolibench.webhook import WebhookAgentAdapter, check_agent_url

MAX_BODY = 32 * 1024
MAX_STEPS = 64  # across all turns of one script
MAX_CONCURRENT = 4
RATE_BURST = 10.0
RATE_PER_S = 1 / 6  # sustained 10 evaluations per minute per client
READ_TIMEOUT_S = 10.0  # per socket read; evaluation itself is bounded by MAX_BODY and MAX_STEPS
JSON = "application/json; charset=utf-8"
ABS_PATH = re.compile(r"^(/|~/|[A-Za-z]:[\\/])")
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'"
LIVE_DISABLED = "live mode is disabled on this deployment: no hosted agent or no demo token is configured"
REFUSE_AGENT_URL = (
    "agent_url is refused: requests never choose the agent; live runs use the agent hosted with this server, "
    "and your own agent runs locally via `bolibench run --agent-url`"
)
M = TypeVar("M", bound=Model)


@dataclass(frozen=True)
class Live:
    """Live-mode settings, fixed at startup. The agent URL never comes from a request."""

    token: str = field(repr=False)
    agent_url: str
    turn_timeout: float = 240.0  # per turn: a hosted model call with retries can take ~180 s
    daily_cap: int = 50
    run_timeout: float = 600.0  # whole run; past it the run is reported as error
    keep: int = 20  # live runs kept in memory for GET /api/live-runs

    def __post_init__(self) -> None:
        if len(self.token) < 16:
            raise ValueError("BOLIBENCH_DEMO_TOKEN must be at least 16 characters")
        if not 0 < self.turn_timeout <= 600:  # also rejects nan
            raise ValueError("BOLIBENCH_LIVE_TURN_TIMEOUT must be between 0 and 600 seconds")
        if not 0 < self.run_timeout <= 3600:
            raise ValueError("BOLIBENCH_LIVE_RUN_TIMEOUT must be between 0 and 3600 seconds")
        if self.daily_cap < 1:
            raise ValueError("BOLIBENCH_LIVE_DAILY_CAP must be at least 1")
        check_agent_url(self.agent_url)


class BundledRun(Model):
    label: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$")  # also the directory name under demo/runs/
    source: str
    date: str
    model: str
    agent: str
    note: str


class RunIndex(Model):
    runs: list[BundledRun]


IntegrationStatus = Literal["deployed", "hosted-api", "local", "partial", "offline", "implemented", "blocked"]
# the legend on the page and in docs/deployment.md; keys must equal IntegrationStatus (checked in tests)
STATUSES = {
    "deployed": "exercised by this deployed app",
    "hosted-api": "a real hosted provider API, called from a laptop; not in the deployed app",
    "local": "real software or models run on a laptop; not in the deployed app",
    "partial": "real calls work, but the intended setup could not run in full",
    "offline": "checked only against fakes, stubs or in-memory transports; no real service called",
    "implemented": "code in the repo, not exercised against anything",
    "blocked": "cannot be exercised yet: a credential or account is missing",
}


class Integration(Model):
    name: str
    category: str
    status: IntegrationStatus  # the highest level actually reached, with evidence in the repo
    evidence: str  # repo-relative paths or a plain-text pointer
    note: str


class IntegrationIndex(Model):
    as_of: str
    integrations: list[Integration] = Field(min_length=1)


class EvaluateRequest(Model):
    case_id: str
    script: list[list[Step]]


class LiveRunRequest(Model):
    case_id: str


def scrub(value: Any) -> Any:
    """Replace whole-string absolute paths (e.g. a scripted run's config.script) with their file name."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and ABS_PATH.match(value):
        return re.split(r"[\\/]", value)[-1]
    return value


def dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode()


@dataclass(frozen=True)
class Demo:
    cases: dict[str, TestCase]
    runs: int
    pages: dict[str, tuple[str, bytes]]  # exact request path -> (content type, body)


def load_demo(suite_dir: Path, demo_dir: Path) -> Demo:
    """Load and validate everything up front; any inconsistency stops startup instead of being served."""
    cases = {c.id: c for c in load_suite(suite_dir)}
    index = RunIndex.model_validate_json((demo_dir / "runs" / "index.json").read_bytes())
    pages: dict[str, tuple[str, bytes]] = {}
    runs: list[dict[str, Any]] = []
    verdicts: dict[str, dict[str, tuple[str, list[str]]]] = {}
    for entry in index.runs:
        run_dir = demo_dir / "runs" / entry.label
        summary = Summary.model_validate_json((run_dir / "summary.json").read_bytes())
        paths = [p for p in sorted(run_dir.glob("*.json")) if p.name != "summary.json"]
        if {p.stem for p in paths} != set(summary.cases):
            raise ValueError(f"{run_dir}: artifact files do not match summary.json cases")
        cells: dict[str, tuple[str, list[str]]] = {}
        for p in paths:
            raw = p.read_bytes()
            artifact = Artifact.model_validate_json(raw)
            pages[f"/api/runs/{entry.label}/{p.stem}"] = (JSON, dumps(scrub(json.loads(raw))))
            cells[p.stem] = (artifact.evaluation.verdict, [c.category for c in artifact.evaluation.classifications])
        verdicts[entry.label] = cells
        runs.append(
            entry.model_dump()
            | {
                "config_id": summary.config_id,
                "total": summary.total,
                "counts": summary.counts,
                "cases": summary.cases,
                "adapters": [a.model_dump(mode="json") for a in summary.adapters],
            }
        )
    integrations = IntegrationIndex.model_validate_json((demo_dir / "integrations.json").read_bytes())
    pages["/api/cases"] = (JSON, dumps(scrub([c.model_dump(mode="json") for c in cases.values()])))
    pages["/api/runs"] = (JSON, dumps(scrub(runs)))
    pages["/api/integrations"] = (JSON, dumps(scrub(integrations.model_dump())))
    example = (demo_dir / "example-request.json").read_text(encoding="utf-8")
    page = render_index(cases, index.runs, verdicts, example, integrations)
    pages["/"] = ("text/html; charset=utf-8", page.encode())
    return Demo(cases, len(runs), pages)


def render_index(
    cases: dict[str, TestCase],
    runs: list[BundledRun],
    verdicts: dict[str, dict[str, tuple[str, list[str]]]],
    example: str,
    integrations: IntegrationIndex,
) -> str:
    e = html.escape
    case_ids = sorted(set(cases) | {c for cells in verdicts.values() for c in cells})
    head = "".join(f"<th>{e(r.label)}<br><small>{e(r.model)}<br>{e(r.note)}</small></th>" for r in runs)
    totals = "".join(
        f"<th>{sum(v == 'pass' for v, _ in verdicts[r.label].values())} of {len(verdicts[r.label])} pass</th>" for r in runs
    )
    integration_rows = "".join(
        f'<tr><td>{e(i.name)}<br><small>{e(i.category)}</small></td><td class="{"pass" if i.status.startswith("live") else ""}">'
        f"{e(i.status)}</td><td><small>{e(i.evidence)}</small></td><td><small>{e(i.note)}</small></td></tr>"
        for i in integrations.integrations
    )
    rows = []
    for cid in case_ids:
        if cid in cases:
            tags = e(", ".join(cases[cid].tags)) + f"<br>user: {e(cases[cid].turns[0])}"
        else:
            tags = "(not in current suite)"
        cells = []
        for r in runs:
            if cid not in verdicts[r.label]:
                cells.append("<td>-</td>")
                continue
            verdict, cats = verdicts[r.label][cid]
            cells.append(
                f'<td class="{e(verdict)}"><a href="/api/runs/{e(r.label)}/{e(cid)}">{e(verdict)}</a>'
                f"<br><small>{e(', '.join(cats))}</small></td>"
            )
        rows.append(f"<tr><td><code>{e(cid)}</code><br><small>{tags}</small></td>{''.join(cells)}</tr>")
    options = "".join(f'<option{" selected" if c == "ambiguous-previous-order" else ""}>{e(c)}</option>' for c in cases)
    script = json.dumps(json.loads(example)["script"], ensure_ascii=False, indent=1)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BoliBench demo</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;max-width:72rem;margin:2rem auto;padding:0 1rem;color:#1d1d1f}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.4rem;vertical-align:top;text-align:left}}
.pass{{background:#e6f4ea}}.fail{{background:#fdecea}}.error,.inconclusive{{background:#fff4e5}}
textarea{{width:100%;font:13px ui-monospace,monospace}}pre{{background:#f5f5f7;padding:1rem;overflow:auto;max-height:40rem}}
</style></head><body>
<h1>BoliBench</h1>
<p>BoliBench is an open-source benchmark for conversational agents that act through tools. Each case is a short
order-management conversation in Hindi-English code-switching or Awadhi ("cancel the old kurta order", "which
order?"). The agent talks to a sandboxed shop: BoliBench records every tool call it makes and the final state of
the orders, and the verdict comes from those observations (right order cancelled, nothing else touched, asked
when it was ambiguous), not from what the agent claims in its reply. Failures are classified, e.g.
<code>entity_resolution</code> for acting on the wrong order.</p>
<p>On this page: the {len(case_ids)} cases with real bundled runs side by side, which integrations are
verified and how far, a scripted evaluator anyone can try, and a token-gated live run.
JSON: <a href="/api/cases">/api/cases</a> · <a href="/api/runs">/api/runs</a> ·
<a href="/api/integrations">/api/integrations</a> · <a href="/health">/health</a></p>
<h2>Cases and bundled runs</h2>
<p>One row per case, one column per bundled run. Each run is a single unseeded run, so per-case differences
may be sampling noise.</p>
<table><tr><th>case</th>{head}</tr>{''.join(rows)}<tr><th>total</th>{totals}</tr></table>
<p><small>Verdicts and failure classifications are from each run's artifact, judged when the run was made.
Click a verdict for the full artifact (turns, tool calls, final state, checks).</small></p>
<h2>Integrations</h2>
<p>What each integration has actually been checked against, as of {e(integrations.as_of)}:
<b>implemented</b> (code in the repo), <b>offline-tested</b> (tests against fakes, stubs or local test
servers), <b>live-verified</b> (a real call to the service or a real run of the model, locally or on a hosted
deployment), <b>not verified</b>. Anything that needs an account or key is not live-verified until it says so.</p>
<table><tr><th>integration</th><th>status</th><th>evidence (in the repo)</th><th>note</th></tr>{integration_rows}</table>
<h2>Evaluate a script</h2>
<p>A script is one list of steps per user turn: <code>{{"tool": ..., "args": {{...}}}}</code>,
<code>{{"text": ...}}</code> (reply) or <code>{{"reason": ...}}</code> (adapter failure). It replays against a fresh
sandbox and the real evaluator. No network calls; a request can never name an agent URL.
Limits: {MAX_BODY // 1024} KiB body, {MAX_STEPS} steps, {RATE_BURST:.0f} requests burst per client.</p>
<form id="f"><p><label>case <select name="case_id">{options}</select></label></p>
<textarea name="script" rows="16">{e(script)}</textarea>
<p><button>Evaluate</button></p></form>
<pre id="out">(result appears here)</pre>
<h2>Live: a hosted open-weight model agent</h2>
<p>On a configured deployment an example agent backed by an open-weight model runs in this container, and
BoliBench drives one suite case through it over the webhook adapter, recording every tool call in its own
sandbox. Runs need the demo owner's token and are capped per day; every run, pass or not, is listed below.
A run is queued and runs in the background (a hosted model can take minutes); this page polls its status.</p>
<p id="live-status">checking live mode...</p>
<form id="lf" hidden><label>case <select name="case_id">{options}</select></label>
<label>token <input name="token" type="password" autocomplete="off"></label> <button>Run live</button></form>
<pre id="lout" hidden></pre>
<table id="lruns" hidden><tr><th>queued (UTC)</th><th>case</th><th>status</th><th>verdict</th><th>agent (self-reported)</th><th>classifications / error</th></tr></table>
<script>
const $ = (id) => document.getElementById(id);
$("f").onsubmit = async (ev) => {{
  ev.preventDefault();
  const f = ev.target, out = $("out");
  let script;
  try {{ script = JSON.parse(f.script.value); }} catch (err) {{ out.textContent = "script is not valid JSON: " + err.message; return; }}
  const r = await fetch("/api/evaluate", {{method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{case_id: f.case_id.value, script}})}});
  out.textContent = r.status + "\\n" + JSON.stringify(await r.json(), null, 2);
}};
async function loadLive() {{
  const d = await (await fetch("/api/live-runs")).json();
  if (!d.enabled) {{ $("live-status").textContent = d.reason; return; }}
  $("live-status").textContent = `Enabled: ${{d.runs_today}} of ${{d.daily_cap}} live runs used today (UTC), one at a time` +
    (d.busy ? " (one is running now)." : ".");
  $("lf").hidden = false;
  $("lruns").hidden = d.runs.length === 0;
  $("lruns").querySelectorAll("tr.r").forEach((tr) => tr.remove());
  for (const r of d.runs) {{
    const tr = $("lruns").insertRow();
    tr.className = "r " + (r.verdict || "");
    const agent = r.agent ? r.agent.name + " " + r.agent.version : "-";
    const detail = r.artifact ? r.artifact.evaluation.classifications.map((c) => c.category).join(", ") : (r.error || "");
    for (const v of [r.queued_at, r.case_id, r.status, r.verdict || "-", agent, detail])
      tr.insertCell().textContent = v;
  }}
}}
$("lf").onsubmit = async (ev) => {{
  ev.preventDefault();
  const f = ev.target, out = $("lout");
  out.hidden = false;
  out.textContent = "submitting " + f.case_id.value + " ...";
  const r = await fetch("/api/live-run", {{method: "POST", headers: {{"Content-Type": "application/json", "Authorization": "Bearer " + f.token.value}},
    body: JSON.stringify({{case_id: f.case_id.value}})}});
  let d = await r.json();
  out.textContent = r.status + "\\n" + JSON.stringify(d, null, 2);
  if (r.status !== 202) {{ loadLive(); return; }}
  const started = Date.now();
  while (d.status === "queued" || d.status === "running") {{
    loadLive();
    await new Promise((ok) => setTimeout(ok, 3000));
    const p = await fetch("/api/live-runs/" + encodeURIComponent(d.run_id));
    if (!p.ok) {{ out.textContent = p.status + "\\n" + JSON.stringify(await p.json(), null, 2); break; }}
    d = await p.json();
    out.textContent = `${{d.status}} after ${{Math.round((Date.now() - started) / 1000)}} s\\n` + JSON.stringify(d, null, 2);
  }}
  loadLive();
}};
loadLive();
</script>
</body></html>
"""


class RateLimiter:
    """In-memory token bucket per client key."""

    # ponytail: per-process state; with several instances or restarts each has its own buckets.
    # Use a shared store (or the platform's edge rate limiting) if this ever runs on more than one instance.
    def __init__(self, burst: float = RATE_BURST, per_second: float = RATE_PER_S, max_keys: int = 10_000) -> None:
        self.burst, self.per_second, self.max_keys = burst, per_second, max_keys
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) >= self.max_keys:
                self._buckets.clear()  # ponytail: bounds memory; a flood of new keys resets everyone's bucket
            tokens, last = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.per_second)
            allowed = tokens >= 1
            self._buckets[key] = (tokens - 1 if allowed else tokens, now)
            return allowed


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        demo: Demo,
        limiter: RateLimiter | None = None,
        max_concurrent: int = MAX_CONCURRENT,
        client_ip_header: str | None = None,
        live: Live | None = None,
    ) -> None:
        super().__init__(address, Handler)
        self.demo = demo
        self.limiter = limiter or RateLimiter()
        self.slots = threading.BoundedSemaphore(max_concurrent)
        self.client_ip_header = client_ip_header
        self.live = live
        # held from a run's POST until its worker has finished: one live run at a time; also guards live_day
        self.live_lock = threading.Lock()
        self.runs_lock = threading.Lock()  # serializes writers of live_runs
        # both replaced, never mutated (nor their dicts), so readers need no lock
        # ponytail: in memory; a restart or free-plan spin-down resets the daily count and forgets every run
        self.live_day: tuple[str, int] = ("", 0)  # (UTC date, live runs started that day)
        self.live_runs: tuple[dict[str, Any], ...] = ()  # newest first, at most live.keep

    def runs_today(self) -> int:
        day, count = self.live_day
        return count if day == datetime.now(timezone.utc).date().isoformat() else 0

    def _put_run(self, run_id: str, **fields: Any) -> None:
        assert self.live is not None
        with self.runs_lock:
            if any(r["run_id"] == run_id for r in self.live_runs):
                self.live_runs = tuple(r | fields if r["run_id"] == run_id else r for r in self.live_runs)
            else:
                self.live_runs = ({"run_id": run_id} | fields, *self.live_runs)[: self.live.keep]

    def run_live(self, run_id: str, case: TestCase) -> None:
        """Background thread of one live run; releases live_lock when its worker has finished."""
        live = self.live
        assert live is not None
        result: list[dict[str, Any]] = []

        def work() -> None:
            try:
                with WebhookAgentAdapter(live.agent_url, live.turn_timeout) as adapter:
                    record = run_case(case, adapter)
                artifact = Artifact(case_id=case.id, run=record, evaluation=evaluate(case, record))
                agent = record.adapter.self_reported_agent
                result.append({"status": "done", "verdict": artifact.evaluation.verdict,
                               "agent": agent.model_dump() if agent else None, "artifact": artifact.model_dump(mode="json")})
            except Exception as e:  # a server bug: reported as error, traceback to stderr
                traceback.print_exc()
                result.append({"status": "error", "error": f"internal error: {type(e).__name__}"})

        try:
            self._put_run(run_id, status="running", started_at=utc_now())
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            worker.join(live.run_timeout)
            if worker.is_alive():
                self._put_run(run_id, status="error", finished_at=utc_now(),
                              error=f"run deadline exceeded: not finished within {live.run_timeout:g}s")
                worker.join()  # bounded by the adapter's turn deadlines; its late result is discarded
            else:
                self._put_run(run_id, finished_at=utc_now(), **result[0])
        finally:
            self.live_lock.release()


def utc_now() -> str:
    return f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"


class Handler(BaseHTTPRequestHandler):
    server: DemoServer
    timeout = READ_TIMEOUT_S

    def version_string(self) -> str:
        return "bolibench-demo"

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._json(code, {"error": message or HTTPStatus(code).phrase})

    def _send(self, status: int, content_type: str, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, value: Any, headers: dict[str, str] | None = None) -> None:
        self._send(status, JSON, dumps(value), headers)

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        s = self.server
        if route == "/health":
            self._json(200, {"status": "ok", "cases": len(s.demo.cases), "runs": s.demo.runs, "live": s.live is not None})
        elif route == "/api/live-runs":
            if s.live is None:
                self._json(200, {"enabled": False, "reason": LIVE_DISABLED, "runs": []})
            else:
                status = {"enabled": True, "busy": s.live_lock.locked(), "daily_cap": s.live.daily_cap, "runs_today": s.runs_today(),
                          "turn_timeout_s": s.live.turn_timeout, "run_timeout_s": s.live.run_timeout}
                self._json(200, status | {"runs": list(s.live_runs)})
        elif route.startswith("/api/live-runs/"):
            run_id = route.removeprefix("/api/live-runs/")
            if s.live is None:
                self._json(404, {"error": LIVE_DISABLED})
            elif (run := next((r for r in s.live_runs if r["run_id"] == run_id), None)) is None:
                self._json(404, {"error": f"unknown run_id (only the last {s.live.keep} runs since the last restart are kept)"})
            else:
                self._json(200, run)
        elif (page := s.demo.pages.get(route)) is not None:
            self._send(200, *page)
        else:
            self._json(404, {"error": "not found"})

    do_HEAD = do_GET

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/api/live-run" and self.server.live is None:
            self._json(404, {"error": LIVE_DISABLED})
            return
        if route not in ("/api/evaluate", "/api/live-run"):
            self._json(404, {"error": "not found"})
            return
        client = self.headers.get(self.server.client_ip_header or "") or self.client_address[0]
        if not self.server.limiter.allow(client.strip()):
            self._json(429, {"error": "rate limit exceeded"}, {"Retry-After": str(round(1 / self.server.limiter.per_second))})
            return
        if route == "/api/live-run" and not self._authorized():
            self._json(401, {"error": "a valid Authorization: Bearer <demo token> header is required"}, {"WWW-Authenticate": "Bearer"})
            return
        length = self.headers.get("Content-Length", "")
        if "Transfer-Encoding" in self.headers or not length.isdigit():
            self._json(400, {"error": "a Content-Length body is required"})
            return
        if int(length) > MAX_BODY:
            self._json(413, {"error": f"body exceeds {MAX_BODY} bytes"})
            return
        body = self.rfile.read(int(length))
        if route == "/api/live-run":
            self._live_run(body)
            return
        if not self.server.slots.acquire(blocking=False):
            self._json(503, {"error": "busy, retry shortly"}, {"Retry-After": "1"})
            return
        try:
            self._evaluate(body)
        finally:
            self.server.slots.release()

    def _authorized(self) -> bool:
        assert self.server.live is not None
        expected = f"Bearer {self.server.live.token}".encode()
        return hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected)

    def _parse(self, model: type[M], body: bytes) -> M | None:
        """The validated request, or None after sending the 400."""
        try:
            return model.model_validate_json(body)
        except ValidationError as e:
            errors = e.errors(include_url=False, include_input=False, include_context=False)
            if any(err["loc"][:1] == ("agent_url",) for err in errors):
                self._json(400, {"error": REFUSE_AGENT_URL})
            else:
                self._json(400, {"error": "invalid request", "details": [{"loc": err["loc"], "msg": err["msg"]} for err in errors]})
            return None

    def _case(self, case_id: str) -> TestCase | None:
        case = self.server.demo.cases.get(case_id)
        if case is None:
            self._json(404, {"error": f"unknown case_id: {case_id}"})
        return case

    def _evaluate(self, body: bytes) -> None:
        if (req := self._parse(EvaluateRequest, body)) is None or (case := self._case(req.case_id)) is None:
            return
        if len(req.script) != len(case.turns):
            self._json(400, {"error": f"script has {len(req.script)} turns but case {case.id} has {len(case.turns)}"})
            return
        if sum(map(len, req.script)) > MAX_STEPS:
            self._json(400, {"error": f"script has more than {MAX_STEPS} steps"})
            return
        info = AdapterInfo(name="fake-scripted", version="1", config={"source": "POST /api/evaluate"})
        record = run_case(case, FakeAgentAdapter(req.script, info=info))
        artifact = Artifact(case_id=case.id, run=record, evaluation=evaluate(case, record))
        self._send(200, JSON, artifact.model_dump_json(indent=2).encode())

    def _live_run(self, body: bytes) -> None:
        if (req := self._parse(LiveRunRequest, body)) is None or (case := self._case(req.case_id)) is None:
            return
        s, live = self.server, self.server.live
        assert live is not None
        if not s.live_lock.acquire(blocking=False):
            self._json(503, {"error": "a live run is in progress, retry shortly"}, {"Retry-After": "30"})
            return
        today, count = datetime.now(timezone.utc).date().isoformat(), s.runs_today()
        if count >= live.daily_cap:
            s.live_lock.release()
            self._json(429, {"error": f"daily live-run cap of {live.daily_cap} reached; resets at 00:00 UTC"})
            return
        s.live_day = (today, count + 1)  # counted before running: errored runs used the agent too
        run_id = secrets.token_hex(8)
        try:
            s._put_run(run_id, status="queued", case_id=case.id, queued_at=utc_now())
            threading.Thread(target=s.run_live, args=(run_id, case), daemon=True).start()  # releases live_lock
        except BaseException:
            s.live_lock.release()
            raise
        self._json(202, {"run_id": run_id, "status": "queued"}, {"Location": f"/api/live-runs/{run_id}"})


def live_from_env(env: Mapping[str, str]) -> Live | None:
    """Live settings, or None when the token or the agent is absent. Empty values count as absent (a platform
    secret left blank); a value that is set but invalid raises, even when live mode would be off anyway."""
    token, agent_url = env.get("BOLIBENCH_DEMO_TOKEN", ""), env.get("BOLIBENCH_LIVE_AGENT_URL", "")
    try:
        timeout = float(env.get("BOLIBENCH_LIVE_TURN_TIMEOUT") or "240")
        cap = int(env.get("BOLIBENCH_LIVE_DAILY_CAP") or "50")
        run_timeout = float(env.get("BOLIBENCH_LIVE_RUN_TIMEOUT") or "600")
    except ValueError as e:
        raise ValueError(f"BOLIBENCH_LIVE_TURN_TIMEOUT / _RUN_TIMEOUT / _DAILY_CAP must be numbers: {e}") from None
    checked = Live(token or "unset-placeholder", agent_url or "http://127.0.0.1:1/turn", timeout, cap, run_timeout)
    return checked if token and agent_url else None


def main() -> None:
    env = os.environ
    try:
        host = env.get("HOST") or ("0.0.0.0" if "PORT" in env else "127.0.0.1")
        port = int(env.get("PORT") or "8080")
        live = live_from_env(env)
        demo = load_demo(Path(env.get("BOLIBENCH_SUITE") or "suites/orders"), Path(env.get("BOLIBENCH_DEMO") or "demo"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"bolibench demo: invalid configuration: {e}") from None
    server = DemoServer((host, port), demo, client_ip_header=env.get("BOLIBENCH_CLIENT_IP_HEADER") or None, live=live)
    print(f"bolibench demo on http://{host}:{server.server_port} ({len(demo.cases)} cases)", flush=True)
    on = f"live mode: on, agent {live.agent_url}, daily cap {live.daily_cap}, turn/run timeout {live.turn_timeout:g}/{live.run_timeout:g}s" if live else ""
    print(on or f"live mode: off ({LIVE_DISABLED})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
