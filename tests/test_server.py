import html
import http.client
import json
import shutil
import threading
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from bolibench.server import (
    LIVE_DISABLED,
    MAX_BODY,
    MAX_STEPS,
    REFUSE_AGENT_URL,
    DemoServer,
    Live,
    RateLimiter,
    live_from_env,
    load_demo,
    scrub,
)

ROOT = Path(__file__).parent.parent
DEMO = ROOT / "demo"
LABELS = [
    "qwen3-8b-baseline-2026-10-17",
    "qwen3-8b-agent-v2-2026-10-17",
    "qwen3-8b-agent-v3-2026-10-17",
    "gemma-gemma3-4b-2026-10-17",
    "mastra-qwen3-8b-2026-10-17",
]
CASE = "ambiguous-previous-order"
GOOD = json.loads((ROOT / "examples" / "scripts" / f"{CASE}.json").read_text(encoding="utf-8"))
WRONG = [GOOD[0], [{"tool": "cancel_order", "args": {"order_id": "ORD-102"}}, {"text": "हो गया"}]]
DEMO_DATA = load_demo(ROOT / "suites" / "orders", DEMO)

Response = tuple[int, dict[str, str], bytes]


def start(**kwargs: Any) -> DemoServer:
    server = DemoServer(("127.0.0.1", 0), DEMO_DATA, **kwargs)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


@pytest.fixture(scope="module")
def server() -> Iterator[DemoServer]:
    s = start(limiter=RateLimiter(burst=1000), max_concurrent=32)
    yield s
    s.shutdown()
    s.server_close()


def request(server: DemoServer, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> Response:
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    out = (r.status, dict(r.getheaders()), r.read())
    conn.close()
    return out


def get_json(server: DemoServer, path: str) -> Any:
    status, _, body = request(server, "GET", path)
    assert status == 200, body
    return json.loads(body)


def post(server: DemoServer, payload: Any) -> tuple[int, Any]:
    status, _, body = request(server, "POST", "/api/evaluate", json.dumps(payload).encode())
    return status, json.loads(body)


def test_health(server: DemoServer) -> None:
    assert get_json(server, "/health") == {"status": "ok", "cases": 12, "runs": len(LABELS), "live": False}


def test_cases_are_served_whole(server: DemoServer) -> None:
    cases = {c["id"]: c for c in get_json(server, "/api/cases")}
    assert len(cases) == 12
    assert cases[CASE]["turns"][1] == "हाँ, कर दो"
    assert cases[CASE]["expected"]["required_actions"] == [{"tool": "cancel_order", "args": {"order_id": "ORD-101"}, "max_attempts": None}]


def test_runs_match_their_summaries(server: DemoServer) -> None:
    runs = get_json(server, "/api/runs")
    assert [r["label"] for r in runs] == LABELS
    for r in runs:
        summary = json.loads((DEMO / "runs" / r["label"] / "summary.json").read_text(encoding="utf-8"))
        assert (r["counts"], r["total"], r["config_id"], r["cases"]) == (summary["counts"], summary["total"], summary["config_id"], summary["cases"])
        assert r["note"].startswith("single unseeded run")


def test_artifact_fetch(server: DemoServer) -> None:
    artifact = get_json(server, f"/api/runs/{LABELS[1]}/{CASE}")
    on_disk = json.loads((DEMO / "runs" / LABELS[1] / f"{CASE}.json").read_text(encoding="utf-8"))
    assert artifact == on_disk
    assert artifact["evaluation"]["verdict"] == "fail"


@pytest.mark.parametrize(
    "path",
    [
        f"/api/runs/nope/{CASE}",
        f"/api/runs/{LABELS[0]}/nope",
        f"/api/runs/{LABELS[0]}/summary",
        f"/api/runs/{LABELS[0]}/{CASE}.json",
        "/api/runs/../../pyproject.toml",
        f"/api/runs/{LABELS[0]}/../../../pyproject.toml",
        "/api/runs/%2e%2e/%2e%2e/pyproject.toml",
        f"/api/runs/{LABELS[0]}/..%2f..%2fsummary",
        "/demo/runs/index.json",
        "//etc/passwd",
    ],
)
def test_unknown_and_traversal_paths_404(server: DemoServer, path: str) -> None:
    status, headers, body = request(server, "GET", path)
    assert status == 404
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body) == {"error": "not found"}


def test_evaluate_passes_example_script(server: DemoServer) -> None:
    status, artifact = post(server, {"case_id": CASE, "script": GOOD})
    assert status == 200
    assert artifact["evaluation"]["verdict"] == "pass"
    assert artifact["run"]["adapter"] == {"name": "fake-scripted", "version": "1", "config": {"source": "POST /api/evaluate"}, "seed": None}


def test_evaluate_fails_wrong_entity(server: DemoServer) -> None:
    status, artifact = post(server, {"case_id": CASE, "script": WRONG})
    assert status == 200
    assert artifact["evaluation"]["verdict"] == "fail"
    assert "entity_resolution" in {c["category"] for c in artifact["evaluation"]["classifications"]}


def test_oversized_body_413(server: DemoServer) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    conn.putrequest("POST", "/api/evaluate")
    conn.putheader("Content-Length", str(MAX_BODY + 1))
    conn.endheaders()  # body never sent: the server must answer from the header alone
    r = conn.getresponse()
    assert r.status == 413
    assert "error" in json.loads(r.read())
    conn.close()


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (b"{not json", "invalid request"),
        (b"[]", "invalid request"),
        (json.dumps({"case_id": CASE}).encode(), "invalid request"),
        (json.dumps({"case_id": CASE, "script": [[{"tool": "list_orders", "bogus": 1}], []]}).encode(), "invalid request"),
        (json.dumps({"case_id": CASE, "script": [[]]}).encode(), "turns"),
        (json.dumps({"case_id": CASE, "script": [[{"text": "x"}] * (MAX_STEPS + 1), []]}).encode(), "steps"),
        (json.dumps({"case_id": CASE, "script": GOOD, "agent_url": "http://127.0.0.1:8000/turn"}).encode(), REFUSE_AGENT_URL),
        (b"[" * 5000 + b"]" * 5000, "invalid request"),
    ],
)
def test_bad_requests_400(server: DemoServer, body: bytes, fragment: str) -> None:
    status, _, raw = request(server, "POST", "/api/evaluate", body)
    assert status == 400
    assert fragment in json.loads(raw)["error"]


def test_unknown_case_404(server: DemoServer) -> None:
    assert post(server, {"case_id": "nope", "script": GOOD})[0] == 404


def test_rate_limit_429() -> None:
    s = start(limiter=RateLimiter(burst=2, per_second=0.001))
    try:
        assert [post(s, {"case_id": CASE, "script": GOOD})[0] for _ in range(3)] == [200, 200, 429]
        status, headers, _ = request(s, "POST", "/api/evaluate", b"{}")
        assert (status, headers["Retry-After"]) == (429, "1000")
        assert request(s, "GET", "/health")[0] == 200  # reads are not rate limited
    finally:
        s.shutdown()
        s.server_close()


def test_rate_limit_uses_configured_client_ip_header() -> None:
    s = start(limiter=RateLimiter(burst=1, per_second=0.001), client_ip_header="True-Client-IP")
    try:
        body = json.dumps({"case_id": CASE, "script": GOOD}).encode()
        codes = [request(s, "POST", "/api/evaluate", body, {"True-Client-IP": ip})[0] for ip in ("1.1.1.1", "2.2.2.2", "1.1.1.1")]
        assert codes == [200, 200, 429]
    finally:
        s.shutdown()
        s.server_close()


def test_concurrent_requests_get_fresh_sandboxes(server: DemoServer) -> None:
    scripts = [GOOD, WRONG] * 12
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda sc: post(server, {"case_id": CASE, "script": sc}), scripts))
    for sc, (status, artifact) in zip(scripts, results, strict=True):
        assert status == 200
        statuses = {o["id"]: o["status"] for o in artifact["run"]["final_state"]["orders"]}
        if sc is GOOD:
            assert (artifact["evaluation"]["verdict"], statuses) == ("pass", {"ORD-101": "cancelled", "ORD-102": "placed"})
        else:
            assert (artifact["evaluation"]["verdict"], statuses) == ("fail", {"ORD-101": "placed", "ORD-102": "cancelled"})
        assert len(artifact["run"]["tool_calls"]) == 3


def test_index_html(server: DemoServer) -> None:
    status, headers, body = request(server, "GET", "/")
    page = body.decode()
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "records every tool call" in page and "the 12 cases" in page
    for label in LABELS:
        assert label in page
        assert f'href="/api/runs/{label}/{CASE}"' in page
    for case in DEMO_DATA.cases.values():
        assert f"<code>{case.id}</code>" in page
    for i in json.loads((DEMO / "integrations.json").read_text(encoding="utf-8"))["integrations"]:
        assert html.escape(i["name"]) in page and html.escape(i["status"]) in page
    # no external resources: every src/href is same-origin
    assert "<script src" not in page and "<link" not in page and 'src="http' not in page and 'href="http' not in page


def test_integrations_endpoint(server: DemoServer) -> None:
    assert get_json(server, "/api/integrations") == json.loads((DEMO / "integrations.json").read_text(encoding="utf-8"))


def test_invalid_integrations_stop_startup(tmp_path: Path) -> None:
    demo = shutil.copytree(DEMO, tmp_path / "demo")
    data = json.loads((demo / "integrations.json").read_text(encoding="utf-8"))
    data["integrations"][0]["status"] = "verified"  # not one of the documented statuses
    (demo / "integrations.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_demo(ROOT / "suites" / "orders", demo)


def test_no_absolute_paths_in_responses(server: DemoServer) -> None:
    paths = ["/", "/health", "/api/cases", "/api/runs", "/api/integrations"] + [f"/api/runs/{label}/{CASE}" for label in LABELS]
    bodies = [request(server, "GET", p)[2] for p in paths] + [request(server, "POST", "/api/evaluate", b"{")[2]]
    bodies.append(request(server, "POST", "/api/evaluate", json.dumps({"case_id": CASE, "script": GOOD}).encode())[2])
    for body in bodies:
        text = body.decode()
        assert str(ROOT) not in text and "/Users/" not in text and "/home/" not in text


def test_scrub_strips_absolute_paths() -> None:
    value = {"config": {"script": "/Users/me/x/s.json", "win": "C:\\x\\s.json", "rel": "scripts/s.json"}, "l": ["~/a/b"]}
    assert scrub(value) == {"config": {"script": "s.json", "win": "s.json", "rel": "scripts/s.json"}, "l": ["b"]}


def test_head_has_headers_only(server: DemoServer) -> None:
    status, headers, body = request(server, "HEAD", "/health")
    assert (status, body) == (200, b"") and int(headers["Content-Length"]) > 0


def test_unsupported_method_is_json(server: DemoServer) -> None:
    status, headers, body = request(server, "PUT", "/api/evaluate", b"{}")
    assert status == 501 and headers["Content-Type"].startswith("application/json")
    assert "error" in json.loads(body)


# --- live mode -------------------------------------------------------------------------------------

TOKEN = "demo-token-0123456789abcdef"
IDENTITY = {"name": "fake-hosted-agent", "version": "1+test-model"}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
Behavior = Callable[[dict[str, Any]], dict[str, Any]]


def tool(req: dict[str, Any], name: str, **args: Any) -> Any:
    data = json.dumps({"tool": name, "args": args}).encode()
    with OPENER.open(urllib.request.Request(req["tools_url"], data=data, method="POST"), timeout=5) as r:
        return json.loads(r.read())


def good_agent(req: dict[str, Any]) -> dict[str, Any]:
    if req["turn"] == 0:
        tool(req, "list_orders")
        tool(req, "ask_user", kind="confirm", question="पुराना Kurta वाला cancel करूँ?")
        return {"reply": "पुराना Kurta वाला cancel करूँ?", "agent": IDENTITY}
    tool(req, "cancel_order", order_id="ORD-101")
    return {"reply": "हो गया", "agent": IDENTITY}


@contextmanager
def fake_agent(behavior: Behavior) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """A hosted agent stand-in on 127.0.0.1 that calls the turn's tools_url like the example agent."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(req)
            data = json.dumps(behavior(req)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    agent = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    agent.daemon_threads = True
    threading.Thread(target=agent.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{agent.server_address[1]}/turn", seen
    finally:
        agent.shutdown()
        agent.server_close()


@contextmanager
def live_server(behavior: Behavior = good_agent, **live: Any) -> Iterator[tuple[DemoServer, str, list[dict[str, Any]]]]:
    with fake_agent(behavior) as (url, seen):
        s = start(limiter=RateLimiter(burst=1000), live=Live(TOKEN, url, **({"turn_timeout": 5.0} | live)))
        try:
            yield s, url, seen
        finally:
            s.shutdown()
            s.server_close()


def live_run(s: DemoServer, case_id: str = CASE, token: str | None = TOKEN, path: str = "/api/live-run", **extra: Any) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    status, _, body = request(s, "POST", path, json.dumps({"case_id": case_id} | extra).encode(), headers)
    return status, json.loads(body)


def test_live_disabled_without_configuration(server: DemoServer) -> None:
    assert live_run(server) == (404, {"error": LIVE_DISABLED})
    assert get_json(server, "/api/live-runs") == {"enabled": False, "reason": LIVE_DISABLED, "runs": []}


def test_live_requires_the_token() -> None:
    with live_server() as (s, _, seen):
        for token in (None, "", "wrong-token-0123456789abcdef", TOKEN + "x", TOKEN.upper()):
            status, body = live_run(s, token=token)
            assert status == 401 and "Bearer" in body["error"]
        assert seen == [] and get_json(s, "/api/live-runs")["runs"] == []


def test_live_run_end_to_end() -> None:
    with live_server() as (s, url, seen):
        assert get_json(s, "/health")["live"] is True
        status, entry = live_run(s)
        assert status == 200
        assert (entry["case_id"], entry["verdict"], entry["agent"]) == (CASE, "pass", IDENTITY)
        run = entry["artifact"]["run"]
        assert run["adapter"]["name"] == "webhook" and run["adapter"]["config"]["agent_url"] == url
        assert run["adapter"]["self_reported_agent"] == IDENTITY
        assert [c["tool"] for c in run["tool_calls"]] == ["list_orders", "ask_user", "cancel_order"]
        assert [r["turn"] for r in seen] == [0, 1]
        listing = get_json(s, "/api/live-runs")
        assert (listing["enabled"], listing["runs_today"], listing["daily_cap"], listing["runs"]) == (True, 1, 50, [entry])


def test_live_agent_url_cannot_come_from_the_request() -> None:
    with live_server() as (s, url, seen):
        assert live_run(s, agent_url="http://127.0.0.1:1/turn") == (400, {"error": REFUSE_AGENT_URL})
        assert seen == []
        status, entry = live_run(s, path="/api/live-run?agent_url=http://127.0.0.1:1/turn")
        assert status == 200 and entry["artifact"]["run"]["adapter"]["config"]["agent_url"] == url and len(seen) == 2


def test_live_unknown_case_404() -> None:
    with live_server() as (s, _, seen):
        assert live_run(s, case_id="nope")[0] == 404 and seen == []


def test_live_run_is_one_at_a_time() -> None:
    entered, release = threading.Event(), threading.Event()

    def slow(req: dict[str, Any]) -> dict[str, Any]:
        entered.set()
        release.wait(5)
        return {"reply": "ठीक है", "agent": IDENTITY}

    with live_server(slow) as (s, _, _seen):
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(live_run, s, "cancel-single-order")
            assert entered.wait(5)
            status, body = live_run(s, "cancel-single-order")
            release.set()
            assert (status, body["error"]) == (503, "a live run is in progress, retry shortly")
            assert first.result()[0] == 200


def test_live_daily_cap_429() -> None:
    with live_server(daily_cap=1) as (s, _, seen):
        assert live_run(s)[0] == 200
        status, body = live_run(s)
        assert status == 429 and "daily live-run cap of 1" in body["error"]
        assert len(seen) == 2  # the refused run never reached the agent


def test_live_results_are_bounded_newest_first() -> None:
    with live_server(keep=2) as (s, _, _seen):
        for case_id in (CASE, "cancel-single-order", "awadhi-cancel-yesterday"):
            assert live_run(s, case_id)[0] == 200
        listing = get_json(s, "/api/live-runs")
        assert [r["case_id"] for r in listing["runs"]] == ["awadhi-cancel-yesterday", "cancel-single-order"]
        assert listing["runs_today"] == 3


def test_live_unreachable_agent_is_an_error_not_a_pass() -> None:
    with fake_agent(good_agent) as (url, _):
        pass  # closed: nothing listens on url any more
    s = start(limiter=RateLimiter(burst=1000), live=Live(TOKEN, url, turn_timeout=2.0))
    try:
        status, entry = live_run(s)
        assert (status, entry["verdict"]) == (200, "error")
        assert entry["artifact"]["run"]["execution_error"].startswith("AdapterError: agent request failed")
    finally:
        s.shutdown()
        s.server_close()


def test_live_secrets_never_leak(monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    api_key = "sk-model-access-key-should-stay-secret"
    monkeypatch.setenv("MODEL_ACCESS_KEY", api_key)
    with live_server() as (s, _, _seen):
        bodies = [live_run(s), live_run(s, token="wrong-token-0123456789abcdef"), live_run(s, agent_url="http://x/")]
        texts = [json.dumps(b) for b in bodies] + [request(s, "GET", p)[2].decode() for p in ("/", "/health", "/api/live-runs")]
    logs = capfd.readouterr()
    for text in [*texts, logs.out, logs.err]:
        assert TOKEN not in text and api_key not in text
    assert TOKEN not in repr(Live(TOKEN, "http://127.0.0.1:1/turn"))


@pytest.mark.parametrize(("token", "url"), [("short", "http://127.0.0.1:8000/turn"), (TOKEN, "https://example.com/turn"), (TOKEN, "http://10.0.0.1/turn")])
def test_live_config_is_checked_at_startup(token: str, url: str) -> None:
    with pytest.raises(ValueError):
        Live(token, url)


AGENT_URL = "http://127.0.0.1:8765/turn"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"BOLIBENCH_DEMO_TOKEN": "", "BOLIBENCH_LIVE_AGENT_URL": "", "BOLIBENCH_LIVE_DAILY_CAP": "", "BOLIBENCH_LIVE_TURN_TIMEOUT": ""},
        {"BOLIBENCH_DEMO_TOKEN": TOKEN},  # no hosted agent (no model key): read-only
        {"BOLIBENCH_LIVE_AGENT_URL": AGENT_URL},
    ],
)
def test_live_off_without_token_or_agent(env: dict[str, str]) -> None:
    assert live_from_env(env) is None


def test_live_from_env_on() -> None:
    env = {"BOLIBENCH_DEMO_TOKEN": TOKEN, "BOLIBENCH_LIVE_AGENT_URL": AGENT_URL, "BOLIBENCH_LIVE_DAILY_CAP": "3"}
    assert live_from_env(env) == Live(TOKEN, AGENT_URL, 40.0, 3)


@pytest.mark.parametrize(
    "env",
    [
        {"BOLIBENCH_LIVE_DAILY_CAP": "lots"},
        {"BOLIBENCH_LIVE_DAILY_CAP": "0"},
        {"BOLIBENCH_LIVE_TURN_TIMEOUT": "nan"},
        {"BOLIBENCH_LIVE_TURN_TIMEOUT": "-1"},
        {"BOLIBENCH_DEMO_TOKEN": "short"},  # rejected even while live mode would be off
        {"BOLIBENCH_DEMO_TOKEN": TOKEN, "BOLIBENCH_LIVE_AGENT_URL": "https://example.com/turn"},
    ],
)
def test_invalid_live_env_fails_loudly(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        live_from_env(env)
