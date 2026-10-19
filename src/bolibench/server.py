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
from urllib.parse import urlsplit

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
    model: str = ""  # display only: the hosted agent's model id
    provider: str = ""  # display only: host name of the agent's model endpoint, never its key

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


def load_examples(cases: dict[str, TestCase], demo_dir: Path, scripts_dir: Path | None) -> dict[str, Any]:
    """Example scripts for the evaluator form: demo/example-request.json plus <scripts_dir>/<case id>.json."""
    request = json.loads((demo_dir / "example-request.json").read_text(encoding="utf-8"))
    examples = {request["case_id"]: request["script"]}
    for cid in cases:
        if scripts_dir and (p := scripts_dir / f"{cid}.json").is_file():
            examples[cid] = json.loads(p.read_text(encoding="utf-8"))
    for cid, script in examples.items():
        EvaluateRequest.model_validate({"case_id": cid, "script": script})
        if cid not in cases or len(script) != len(cases[cid].turns):
            raise ValueError(f"example script for {cid} does not match a suite case's turn count")
    return examples


def load_demo(suite_dir: Path, demo_dir: Path, scripts_dir: Path | None = None) -> Demo:
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
    examples = load_examples(cases, demo_dir, scripts_dir)
    page = render_index(cases, index.runs, verdicts, examples, integrations)
    pages["/"] = ("text/html; charset=utf-8", page.encode())
    return Demo(cases, len(runs), pages)


VERDICTS = {
    "pass": "every check passed",
    "fail": "at least one check failed: a wrong, missing or forbidden action, a wrong final state, or no question when one was required",
    "error": "the run did not complete (agent or adapter error, or a timeout), so no checks were run",
    "inconclusive": "no check failed, but evidence one of them needs was missing",
}
DEVANAGARI = re.compile("[\u0900-\u097f]")
# Acid Lab x Digital Archaeology: warm paper, ink, selective lime/violet; text pairs checked for WCAG AA contrast
CSS = """
:root{--bg:#F4F0E8;--s1:#EAE6DD;--s2:#FFFEF9;--line:#D9D5CC;--ink:#171717;--control:#6E6A5E;--text:#171717;--muted:#5A564C;
--accent:#6255E7;--lime:#D7FF3F;--pass:#236B45;--pass-bg:#DFEEE2;--fail:#A81C0D;--fail-bg:#FBE3DE;--error:#F04438;
--inc:#6255E7;--inc-bg:#F0EEFF;color-scheme:light}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans","Noto Sans Devanagari",sans-serif}
.wrap{max-width:76rem;margin:0 auto;padding:0 1.5rem}
h1{font-size:2.4rem;line-height:.95;margin:.2rem 0 .7rem;font-weight:900;letter-spacing:-.03em;text-transform:uppercase}
h1 .mark{display:inline-block;background:var(--lime);border:2px solid var(--ink);padding:.05em .18em;margin-right:.25em;
box-shadow:4px 4px 0 var(--ink);font-size:.72em;vertical-align:.08em}
.kicker{font:700 .72rem/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.14em;text-transform:uppercase;
color:var(--ink);margin:0}
.kicker::before{content:"";display:inline-block;width:.65em;height:.65em;background:var(--accent);margin-right:.55em}
h2{font-size:1.35rem;line-height:1.25;margin:0 0 .75rem;font-weight:850;letter-spacing:-.01em;text-transform:uppercase}
h2 .sec{display:inline-block;background:var(--ink);color:var(--lime);font:700 .78rem/1 ui-monospace,Menlo,Consolas,monospace;
padding:.35em .45em;margin-right:.5em;vertical-align:.18em}
h3{font-size:1rem;margin:1.5rem 0 .5rem}
p{margin:0 0 .75rem;max-width:72ch}
a{color:var(--accent);text-underline-offset:2px;font-weight:600}
code,pre,textarea{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
code{font-size:.95em;overflow-wrap:anywhere}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;padding:.5rem .75rem;background:var(--lime);color:var(--ink);z-index:9}
header.top{background:var(--bg);border-bottom:3px solid var(--ink);padding:2rem 0 1.4rem}
.lede{color:var(--text);max-width:68ch}
.facts,.stats,nav ul{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:.5rem}
.facts li{border:1.5px solid var(--ink);background:var(--s2);padding:.25rem .6rem;color:var(--ink);
font:600 .78rem/1.5 ui-monospace,Menlo,Consolas,monospace}
nav ul{margin-top:1.1rem}
nav a{display:inline-block;padding:.42rem .8rem;border:1.5px solid var(--ink);color:var(--ink);text-decoration:none;
font-weight:700;background:var(--s2)}
nav a:hover{background:var(--lime)}
section{padding:2rem 0;border-bottom:2px solid var(--ink)}
.stats{margin-bottom:1rem}
.stats li{background:var(--s1);border:1.5px solid var(--ink);padding:.55rem 1rem;color:var(--muted);min-width:8.5rem}
.stats li:first-child{box-shadow:5px 5px 0 var(--lime)}
.stats b{display:block;font-size:1.55rem;color:var(--text);font-variant-numeric:tabular-nums;
font-family:ui-monospace,Menlo,Consolas,monospace}
.caveats{background:var(--s1);border:1.5px solid var(--ink);border-left:8px solid var(--accent);padding:.8rem 1rem;margin-bottom:1rem}
.caveats ul{margin:0;padding-left:1.2rem}.caveats li{margin:.2rem 0}
.note{color:var(--muted);font-size:14px}
.err{color:var(--fail);font-weight:600}
.sub{display:block;font-size:13px;color:var(--muted);font-weight:400}
.sig{display:block;margin-top:.35rem;font:600 .72rem/1.5 ui-monospace,Menlo,Consolas,monospace;color:var(--ink);
border-top:1px dashed var(--control);padding-top:.3rem;overflow-wrap:anywhere}
.sig::before{content:"SIG ";background:var(--lime);padding:.05em .3em;margin-right:.4em}
.scroll{overflow-x:auto;max-width:100%;border:1.5px solid var(--ink);background:var(--s2);margin-bottom:.75rem}
table{border-collapse:separate;border-spacing:0;width:100%}
caption{text-align:left;padding:.6rem .75rem;color:var(--muted);font-size:13px;
font-family:ui-monospace,Menlo,Consolas,monospace}
th,td{padding:.55rem .75rem;text-align:left;vertical-align:top;border-top:1px solid var(--line)}
thead th{background:var(--ink);font-size:13px;font-weight:700;color:var(--bg)}
tbody th{font-weight:400}
tfoot th,tfoot td{font-weight:700;background:var(--s1)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.summary th,.summary td{white-space:nowrap}
.matrix thead th{white-space:nowrap}
.matrix td{min-width:9.5rem}
.matrix tbody th,.matrix thead th:first-child,.matrix tfoot th{position:sticky;left:0;z-index:1;background:var(--s1);
min-width:16rem;max-width:20rem;border-right:1.5px solid var(--ink)}
.matrix thead th:first-child{background:var(--ink);white-space:normal}
.case code{display:block;font-weight:700;color:var(--text);overflow-wrap:normal;font-size:.98rem}
.utt{display:block;margin:.2rem 0}
.v{display:inline-block;padding:0 .55rem;border:1.5px solid var(--ink);font-size:13px;font-weight:700;line-height:1.6;text-decoration:none;color:var(--ink)}
a.v:hover{text-decoration:underline;background:var(--lime)}
.v-pass{color:var(--pass);background:var(--pass-bg);border-color:var(--pass)}
.v-fail{color:var(--fail);background:var(--fail-bg);border-color:var(--error)}
.v-error{color:var(--fail);background:var(--fail-bg);border-color:var(--error);border-style:dashed}
.v-inconclusive{color:var(--inc);background:var(--inc-bg);border-color:var(--inc)}
.cls{display:block;margin-top:.3rem;font-size:13px;color:var(--muted);overflow-wrap:anywhere}
.st{display:inline-block;padding:0 .5rem;border:1.5px solid var(--ink);background:var(--s2);color:var(--text);
font:600 13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap}
.st::before{margin-right:.4em;font-size:.85em}
.st-deployed::before{content:"\25CF"}.st-hosted-api::before{content:"\25B2"}.st-local::before{content:"\25A0"}
.st-partial::before{content:"\25D1"}.st-offline::before{content:"\25CB"}.st-implemented::before{content:"\25A1"}
.st-blocked::before{content:"\2715"}
.st-deployed{box-shadow:3px 3px 0 var(--lime)}.st-offline,.st-implemented,.st-blocked{border-style:dashed}
.int th[scope=row]{min-width:12rem}.int td:nth-child(4){min-width:20rem;font-size:14px}
.int .sub{margin-top:.35rem;overflow-wrap:anywhere}.int details{margin-top:.25rem}.int summary{font-size:13px}
dl.legend,dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:.4rem 1rem;margin:0 0 1rem}
dl.legend dd,dl.kv dd{margin:0;color:var(--muted)}
dl.legend>*,dl.kv>*{min-width:0;overflow-wrap:anywhere}
dl.kv dt{font-weight:700}
dl.wide{grid-template-columns:minmax(10rem,max-content) 1fr;font-size:14px}
details summary{cursor:pointer;color:var(--accent);padding:.25rem 0;font-weight:600}
details[open] summary{margin-bottom:.5rem}
form label{display:block;font-weight:700;margin:.75rem 0 .3rem}
select,input,textarea,button{font:inherit;color:var(--text);background:var(--s2);border:1.5px solid var(--ink);
padding:.5rem .65rem;max-width:100%}
select,input{min-height:2.75rem;min-width:16rem}
textarea{display:block;width:100%;font-size:13px;line-height:1.5;resize:vertical;border-width:2px}
button{min-height:2.75rem;padding:.55rem 1.2rem;background:var(--lime);border:2px solid var(--ink);color:var(--ink);
font-weight:800;cursor:pointer;box-shadow:4px 4px 0 var(--ink)}
button:hover{transform:translate(-1px,-1px);box-shadow:5px 5px 0 var(--ink)}
button:disabled{opacity:.55;cursor:not-allowed;transform:none}
button.ghost{background:var(--s2);box-shadow:none;font-weight:700;margin-left:.5rem}
#lrun-btn{background:var(--accent);color:#fff}
.out{margin-top:.5rem}
.result{background:var(--s2);border:2px solid var(--ink);padding:.85rem 1rem;box-shadow:6px 6px 0 var(--s1)}
.result ul{margin:0;padding-left:1.2rem}.result li{margin:.25rem 0}
.timeline{list-style:none;margin:.5rem 0 1rem;padding:0;border-left:3px solid var(--ink)}
.timeline li{padding:.35rem 0 .35rem .9rem;position:relative;overflow-wrap:anywhere}
.timeline li::before{content:"";position:absolute;left:-.42rem;top:.75em;width:.6rem;height:.6rem;background:var(--lime);border:2px solid var(--ink)}
.tl-k{display:block;font:700 .68rem/1.4 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.1em;color:var(--muted)}
.tl-v{display:block}
pre{background:var(--s1);border:1.5px solid var(--ink);padding:.75rem;overflow:auto;max-height:28rem;font-size:13px}
footer{padding:1.5rem 1.5rem 3rem;color:var(--muted);font-size:14px}

.spec-strip{display:flex;flex-wrap:wrap;gap:0;margin-top:1rem;border:1.5px solid var(--ink);background:var(--s2)}
.spec-strip span{padding:.4rem .7rem;font:700 .7rem/1.5 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.08em;
text-transform:uppercase;border-right:1.5px solid var(--ink)}
.spec-strip span:last-child{border-right:0;background:var(--lime)}
.spec-strip b{color:var(--accent)}
.dist{margin:0 0 1rem;border:1.5px solid var(--ink);background:var(--s2);padding:.7rem .9rem}
.dist h3{margin:0 0 .6rem;font:700 .72rem/1.4 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.12em;text-transform:uppercase}
.dist-row{display:grid;grid-template-columns:13rem 1fr 11rem;gap:.7rem;align-items:center;margin:.35rem 0}
.dist-name{font:600 .78rem/1.4 ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
.dist-bar{display:flex;height:1.05rem;border:1.5px solid var(--ink);overflow:hidden;background:var(--s1)}
.dist-bar i{display:block;height:100%}
.dist-bar .d-pass{background:var(--pass)}.dist-bar .d-fail{background:var(--error)}
.dist-bar .d-error{background:var(--ink)}
.dist-bar .d-inconclusive{background:var(--accent)}
.dist-num{font:600 .78rem/1.4 ui-monospace,Menlo,Consolas,monospace;text-align:right}
.case-no{display:inline-block;background:var(--ink);color:var(--bg);font:700 .7rem/1 ui-monospace,Menlo,Consolas,monospace;
padding:.3em .4em;margin:0 .45em .3em 0;vertical-align:.1em}
.matrix tbody tr:hover th,.matrix tbody tr:hover td{background:#F8F3DF}
.matrix tbody tr:hover th{box-shadow:inset 4px 0 0 var(--lime)}
.chip{display:inline-block;border:1.2px solid var(--ink);background:var(--s2);padding:.05em .4em;margin:.1em .1em .1em 0;font-weight:700}
.sig .arr{font-weight:900;color:var(--accent)}
.foot-mark{font-weight:900;font-size:clamp(2.4rem,8vw,5.2rem);line-height:.95;letter-spacing:-.03em;text-transform:uppercase;
color:transparent;-webkit-text-stroke:1.5px var(--ink);margin:.4rem 0 .6rem}
@media (max-width:768px){.dist-row{grid-template-columns:1fr;gap:.2rem}.dist-num{text-align:left}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{transition:none!important;animation:none!important}}
@media (max-width:1024px){.wrap{padding:0 1.25rem}.matrix tbody th,.matrix thead th:first-child,.matrix tfoot th{min-width:14rem}}
@media (max-width:768px){header.top{padding:1.5rem 0 1rem}h1{font-size:1.9rem}section{padding:1.5rem 0}
.matrix tbody th,.matrix thead th:first-child,.matrix tfoot th{min-width:11rem;max-width:12rem}
.int td:nth-child(4){min-width:18rem}dl.wide{grid-template-columns:1fr}}
@media (max-width:480px){.wrap{padding:0 1rem}footer{padding:1.25rem 1rem 2rem}h1{font-size:1.6rem}h2{font-size:1.15rem}
dl.legend,dl.kv{grid-template-columns:1fr;gap:.15rem}dl.legend dd,dl.kv dd{margin-bottom:.5rem}
select,input,button{width:100%;min-width:0}button.ghost{margin-left:0;margin-top:.5rem}
.matrix tbody th,.matrix thead th:first-child,.matrix tfoot th{min-width:9.5rem;max-width:10rem}.matrix td{min-width:7.5rem}
.int th[scope=row]{min-width:9rem}.int td:nth-child(4){min-width:13rem}}

/* v3: typography, masthead plate, sticky nav, filters */
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Devanagari",sans-serif}
h1,h2,.foot-mark{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:-.035em;text-wrap:balance}
h1{font-size:clamp(2.6rem,6.5vw,4.4rem)}
code,pre,textarea,.kicker,.facts li,caption,.sig,.dist-name,.dist-num,.tl-k,.st,.plate-k,.plate-meta{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
header.top{background-image:radial-gradient(var(--line) 1.1px, transparent 1.3px);background-size:22px 22px}
.mast{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(17rem,.9fr);gap:2.2rem;align-items:start}
.plate{background:var(--ink);color:var(--bg);border:2px solid var(--ink);box-shadow:9px 9px 0 var(--lime);padding:1.05rem 1.1rem}
.plate-k{font-size:.68rem;letter-spacing:.13em;text-transform:uppercase;color:var(--lime);margin:0 0 .7rem;font-weight:600}
.plate-utt{font-family:system-ui,sans-serif;letter-spacing:-.02em;font-size:1.35rem;line-height:1.3;font-weight:600;margin:0 0 .9rem}
.plate-flow{margin:0 0 .8rem;line-height:2}
.p-chip{border:1.5px solid var(--bg);padding:.18em .45em;font-family:ui-monospace,Menlo,monospace;font-size:.75rem;white-space:nowrap}
.plate .arr{color:var(--lime);font-weight:900}
.plate-meta{font-size:.72rem;color:#CFC9BC;margin:0;line-height:1.6}
.topnav{position:sticky;top:0;z-index:40;background:var(--bg);border-bottom:2.5px solid var(--ink)}
.topnav ul{margin:0;padding:.55rem 0}
.topnav a{background:var(--bg)}
section{position:relative}
h2{font-size:clamp(1.4rem,3vw,1.9rem)}
.filters{display:flex;flex-wrap:wrap;gap:.6rem 1rem;align-items:end;margin:0 0 .8rem}
.filters label{font-weight:800;margin:0}
.filters input{flex:1 1 16rem;border-width:2px;background:var(--s2)}
.filters .note{margin:0;flex-basis:100%}
tr[hidden]{display:none}
@media (max-width:900px){.mast{grid-template-columns:1fr}.plate{max-width:32rem}}

"""
SCRIPT = """
const $ = (id) => document.getElementById(id);
function el(tag, props, ...kids) {
  const node = Object.assign(document.createElement(tag), props || {});
  node.append(...kids.filter((k) => k !== null && k !== undefined && k !== false));
  return node;
}
const pill = (v) => el("span", {className: "v v-" + v, textContent: v});
const err = (text) => el("p", {className: "err", textContent: text});
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const WAKE = "The server may be waking up from idle (free-plan instances can take about a minute); try again shortly.";

async function call(url, opts) {
  // {status, data}: status 0 means the request never got a response; data is null when the body is not JSON
  let r;
  try { r = await fetch(url, opts); } catch (e) { return {status: 0, data: null}; }
  let data = null;
  try { data = await r.json(); } catch (e) { /* e.g. a proxy's HTML error page */ }
  return {status: r.status, data};
}
function problem(res) {
  if (res.status === 0) return "Could not reach the server. " + WAKE;
  if (res.data && res.data.error) return `HTTP ${res.status}: ${res.data.error}`;
  return `HTTP ${res.status}: unexpected response.` + (res.status >= 500 ? " " + WAKE : "");
}
function renderArtifact(a, about, raw) {
  const ev = a.evaluation, passed = ev.checks.filter((c) => c.verdict === "pass").length;
  const checks = el("ul", {}, ...ev.checks.map((c) => el("li", {}, pill(c.verdict), " ", el("code", {textContent: c.metric}), c.detail ? " — " + c.detail : "")));
  const classes = el("ul", {}, ...ev.classifications.map((c) => el("li", {}, el("code", {textContent: c.category}), ` (${c.confidence}, ${c.stage})`)));
  return el("div", {className: "result"},
    el("p", {}, el("b", {textContent: "Verdict: "}), pill(ev.verdict), ev.checks.length ? ` ${passed} of ${ev.checks.length} checks passed` : ""),
    el("p", {}, "Case ", el("code", {textContent: a.case_id}), " · " + about),
    a.run && a.run.execution_error ? err("Execution error: " + a.run.execution_error) : null,
    renderTimeline(a),
    el("h3", {textContent: "Checks"}),
    ev.checks.length ? checks : el("p", {className: "note", textContent: "No checks were run: the run did not complete."}),
    el("h3", {textContent: "Classifications"}),
    ev.classifications.length ? classes : el("p", {className: "note", textContent: "None."}));
}

function renderTimeline(a) {
  const run = a.run || {}, ev = a.evaluation, items = [];
  (run.turns || []).forEach((t, i) => {
    items.push(["Request \u00b7 turn " + (i + 1), t.user_input || ""]);
    (run.tool_calls || []).filter((c) => c.turn === i).forEach((c) =>
      items.push(["Agent action", c.tool + " " + JSON.stringify(c.args) + " \u2192 " + c.status + (c.error ? ": " + c.error : "")]));
    if (t.agent_reply) items.push(["Agent reply", t.agent_reply]);
  });
  (ev.checks || []).forEach((c) => items.push(["Evaluation check", c.metric + " \u2014 " + c.verdict + (c.detail ? ": " + c.detail : "")]));
  items.push(["Verdict", ev.verdict]);
  return el("div", {}, el("h3", {textContent: "Evidence timeline"}),
    el("ol", {className: "timeline"}, ...items.map(([k, v]) => el("li", {}, el("span", {className: "tl-k", textContent: k}), el("span", {className: "tl-v", textContent: v})))));
}

// --- case evidence viewer (bundled runs) ---
const artifactView = $("artifact-view");
document.querySelectorAll(".matrix a.v").forEach((link) => {
  link.addEventListener("click", async (ev) => {
    ev.preventDefault();
    artifactView.replaceChildren(el("p", {className: "note", textContent: "Loading evidence\u2026"}));
    artifactView.scrollIntoView({block: "nearest"});
    const res = await call(link.getAttribute("href"));
    if (res.status !== 200 || !res.data) { artifactView.replaceChildren(err(problem(res))); return; }
    artifactView.replaceChildren(renderArtifact(res.data, "bundled run \u00b7 recorded tool calls and final state", null));
  });
});

// --- script evaluation ---
const EXAMPLES = JSON.parse($("examples").textContent);
const form = $("f"), out = $("out");
const formatScript = (s) => "[\\n" + s.map((t) => "  [\\n" + t.map((step) => "    " + JSON.stringify(step)).join(",\\n") + "\\n  ]").join(",\\n") + "\\n]";
function loadScript() {
  const ex = EXAMPLES[form.case_id.value];
  const script = ex.script || Array.from({length: ex.turns}, (_, i) => [{text: `placeholder reply for user turn ${i + 1}`}]);
  form.script.value = formatScript(script);
  $("script-note").textContent = ex.script
    ? "Loaded this case's example script; it is expected to pass."
    : `No example script exists for this case yet. This placeholder has one reply step for each of the case's ${ex.turns} user turn(s), so it can be submitted, but it makes no tool calls: it is an editable starting point, not a correct answer.`;
  out.replaceChildren(el("p", {className: "note", textContent: "The result appears here."}));
}
function checkScript(text, turns) {
  let s;
  try { s = JSON.parse(text); } catch (e) { return "The script is not valid JSON: " + e.message; }
  const isStep = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
  if (!Array.isArray(s) || !s.every((t) => Array.isArray(t) && t.every(isStep)))
    return "The script must be a list of turns, each a list of step objects.";
  if (s.length !== turns) return `This case has ${turns} user turn(s) but the script has ${s.length}.`;
  return s;
}
form.case_id.onchange = loadScript;
$("reset-btn").onclick = loadScript;
form.onsubmit = async (ev) => {
  ev.preventDefault();
  const id = form.case_id.value, script = checkScript(form.script.value, EXAMPLES[id].turns);
  if (typeof script === "string") { out.replaceChildren(err(script)); return; }
  const btn = $("eval-btn");
  btn.disabled = true;
  out.replaceChildren(el("p", {className: "note", textContent: "Evaluating…"}));
  try {
    const res = await call("/api/evaluate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({case_id: id, script})});
    if (res.status === 200 && res.data && res.data.evaluation) out.replaceChildren(renderArtifact(res.data, "scripted replay (fake-scripted adapter), not an AI agent"));
    else out.replaceChildren(err(problem(res)), res.data && res.data.details ? rawJSON(res.data) : null);
  } finally { btn.disabled = false; }
};
loadScript();

// --- specimen filter (cases matrix) ---
const filterInput = $("case-filter"), filterCount = $("filter-count");
const caseRows = [...document.querySelectorAll(".matrix tbody tr")];
function applyFilter() {
  const q = filterInput.value.trim().toLowerCase();
  let shown = 0;
  caseRows.forEach((r) => { const hit = !q || r.textContent.toLowerCase().includes(q); r.hidden = !hit; if (hit) shown += 1; });
  filterCount.textContent = q ? shown + " of " + caseRows.length + " specimens match \u2014 clear the filter to see all." : "";
}
if (filterInput) filterInput.addEventListener("input", applyFilter);

// --- live demo ---
let liveCfg = null, liveActive = false;
async function loadLive(attempt = 0) {
  const res = await call("/api/live-runs"), status = $("live-status");
  if (res.status !== 200 || !res.data) {
    if (attempt >= 5) { status.textContent = problem(res) + " Reload the page to try again."; return; }
    const wait = 3 * 2 ** attempt;
    status.textContent = `${problem(res)} Retrying in ${wait} s…`;
    setTimeout(() => loadLive(attempt + 1), wait * 1000);
    return;
  }
  const d = res.data;
  if (!d.enabled) {
    status.textContent = (d.reason ? d.reason[0].toUpperCase() + d.reason.slice(1) : "Live mode is disabled") + ". Nothing is sent to a model provider.";
    return;
  }
  liveCfg = d;
  status.textContent = `Live mode is on: ${d.runs_today} of ${d.daily_cap} runs used today (UTC)` + (d.busy ? "; a run is in progress now." : ".");
  $("lf").hidden = false;
  $("lrun-btn").disabled = liveActive || d.busy || d.runs_today >= d.daily_cap;
  $("lruns-wrap").hidden = d.runs.length === 0;
  $("lruns-body").replaceChildren(...d.runs.map((r) => {
    const agent = r.agent ? r.agent.name + " " + r.agent.version : "-";
    const detail = r.artifact ? r.artifact.evaluation.classifications.map((c) => c.category).join(", ") : (r.error || "");
    return el("tr", {}, ...[r.queued_at, r.case_id, r.status].map((v) => el("td", {textContent: v || "-"})),
      el("td", {}, r.verdict ? pill(r.verdict) : "-"), el("td", {textContent: agent}), el("td", {textContent: detail}));
  }));
}
$("lf").onsubmit = async (ev) => {
  ev.preventDefault();
  if (liveActive) return;
  const f = ev.target, out = $("lout"), btn = $("lrun-btn"), say = (...nodes) => out.replaceChildren(...nodes);
  liveActive = true;
  btn.disabled = true;
  out.hidden = false;
  say(el("p", {textContent: `Submitting ${f.case_id.value}…`}));
  try {
    const res = await call("/api/live-run", {method: "POST",
      headers: {"Content-Type": "application/json", "Authorization": "Bearer " + f.token.value}, body: JSON.stringify({case_id: f.case_id.value})});
    if (res.status !== 202 || !res.data) { say(err(problem(res))); return; }
    const id = res.data.run_id, started = Date.now(), limit = ((liveCfg ? liveCfg.run_timeout_s : 600) + 60) * 1000;
    let run = res.data, failures = 0;
    say(el("p", {textContent: `Run ${id} queued; polling every 3 s…`}));
    while (run.status === "queued" || run.status === "running") {
      await sleep(failures ? Math.min(30, 3 * 2 ** failures) * 1000 : 3000);
      const secs = Math.round((Date.now() - started) / 1000);
      if (Date.now() - started > limit) { say(err(`Stopped polling after ${secs} s. The run may still finish: reload the page later to see it in the list.`)); return; }
      const p = await call("/api/live-runs/" + encodeURIComponent(id));
      if (p.status === 200 && p.data) { failures = 0; run = p.data; say(el("p", {textContent: `Run ${id}: ${run.status} after ${secs} s…`})); }
      else if (p.status === 404) { say(err("The server no longer knows this run: it probably restarted, which clears live history.")); return; }
      else { failures += 1; say(err(`Polling failed (${problem(p)}). Retrying, attempt ${failures}…`)); }
    }
    const agent = run.agent ? `agent ${run.agent.name} ${run.agent.version}` : "agent did not report itself";
    say(run.artifact ? renderArtifact(run.artifact, `live run ${id}, ${agent}`, run) : err(`Run ${id} ended with status ${run.status}: ${run.error || "no detail"}`), run.artifact ? null : rawJSON(run));
  } finally {
    liveActive = false;
    loadLive();
  }
};
loadLive();
"""


def short_label(label: str) -> str:
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", label)


def format_script(script: list[list[Any]]) -> str:
    """One step per line; matches the page script's formatter so both render the same text."""
    turns = (",\n".join("    " + json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in t) for t in script)
    return "[\n" + ",\n".join(f"  [\n{t}\n  ]" for t in turns) + "\n]"


def render_index(
    cases: dict[str, TestCase],
    runs: list[BundledRun],
    verdicts: dict[str, dict[str, tuple[str, list[str]]]],
    examples: dict[str, Any],
    integrations: IntegrationIndex,
) -> str:
    e = html.escape
    case_ids = sorted(set(cases) | {c for cells in verdicts.values() for c in cells})
    unreviewed = sum(c.status == "proposed" and c.review.behavior == c.review.linguistic == "unreviewed" for c in cases.values())
    review_fact = (
        f"{unreviewed} proposed, not yet reviewed cases"
        if unreviewed == len(cases)
        else f"{unreviewed} of {len(cases)} cases proposed, not yet reviewed"
    )
    judged = sum(len(cells) for cells in verdicts.values())
    verdict_heads = "".join(f'<th scope="col" class="num">{k}</th>' for k in VERDICTS)

    def provenance(r: BundledRun) -> str:
        return f"{r.model}. Agent: {r.agent}. {r.note}"

    summary_rows = "".join(
        f'<tr><th scope="row" title="{e(provenance(r))}">{e(short_label(r.label))}</th>'
        f'<td>{e(r.model.split(" (")[0])}</td><td>{e(r.date)}</td>'
        + "".join(f'<td class="num">{sum(v == k for v, _ in verdicts[r.label].values())}</td>' for k in VERDICTS)
        + f'<td class="num">{len(verdicts[r.label])}</td></tr>'
        for r in runs
    )
    head = "".join(
        f'<th scope="col" title="{e(provenance(r))}">{e(short_label(r.label))}<span class="sub">{e(r.date)}</span></th>' for r in runs
    )
    totals = "".join(
        f'<td class="num">{sum(v == "pass" for v, _ in verdicts[r.label].values())} of {len(verdicts[r.label])}</td>' for r in runs
    )
    rows = []
    for num, cid in enumerate(case_ids, 1):
        if (case := cases.get(cid)) is not None:
            lang = (' lang="awa"' if "awadhi" in case.tags else ' lang="hi"') if DEVANAGARI.search(case.turns[0]) else ""
            more = f" (+{len(case.turns) - 1} more turn)" if len(case.turns) > 1 else ""
            exp = case.expected
            steps = [f"ask {kind} → {tool}" for tool, kind in exp.ask_before.items()]
            steps += [f"{a.tool}({', '.join(f'{k}={v}' for k, v in a.args.items())})" for a in exp.required_actions]
            if not steps:
                steps = ["no consequential action"]
            chips = '<span class="arr" aria-hidden="true"> → </span>'.join(f'<span class="chip">{e(st)}</span>' for st in steps)
            signature = f'<span class="sig">{chips}</span>'
            about = f'<span class="utt"{lang}>{e(case.turns[0])}</span><span class="sub">{e(", ".join(case.tags))}{more}</span>{signature}'
        else:
            about = '<span class="sub">(not in current suite)</span>'
        cells = []
        for r in runs:
            if cid not in verdicts[r.label]:
                cells.append("<td>-</td>")
                continue
            verdict, cats = verdicts[r.label][cid]
            name = f"{verdict} — {short_label(r.label)} / {cid}"
            cells.append(
                f'<td><a class="v v-{e(verdict)}" href="/api/runs/{e(r.label)}/{e(cid)}" aria-label="{e(name)}">{e(verdict)}</a>'
                f'<span class="cls">{e(", ".join(cats))}</span></td>'
            )
        rows.append(f'<tr data-search="{e(cid)}"><th scope="row" class="case"><span class="case-no" aria-hidden="true">{num:02d}</span><code>{e(cid)}</code>{about}</th>{"".join(cells)}</tr>')

    dist_rows = "".join(
        f'<div class="dist-row"><span class="dist-name">{e(short_label(r.label))}</span>'
        f'<span class="dist-bar" role="img" aria-label="{e(short_label(r.label))}: '
        + ", ".join(f"{sum(v == k for v, _ in verdicts[r.label].values())} {k}" for k in VERDICTS)
        + '">'
        + "".join(
            f'<i class="d-{k}" style="width:{100 * sum(v == k for v, _ in verdicts[r.label].values()) / max(1, len(verdicts[r.label])):.1f}%"></i>'
            for k in VERDICTS if sum(v == k for v, _ in verdicts[r.label].values())
        )
        + f'</span><span class="dist-num">{sum(v == "pass" for v, _ in verdicts[r.label].values())} pass · {sum(v == "fail" for v, _ in verdicts[r.label].values())} fail</span></div>'
        for r in runs
    )
    dist_block = f'<div class="dist"><h3>Run distribution — share of verdicts per bundled run</h3>{dist_rows}</div>'
    run_legend = "".join(
        f"<dt><code>{e(r.label)}</code></dt><dd>{e(r.model)}<br>Agent: {e(r.agent)}<br>{e(r.note)}</dd>" for r in runs
    )
    integration_rows = "".join(
        f'<tr><th scope="row">{e(i.name)}<span class="sub">{e(i.category)}</span></th>'
        f'<td><span class="st st-{e(i.status)}">{e(i.status)}</span></td><td>{"yes" if i.status == "deployed" else "no"}</td>'
        f'<td>{e(lead)}{"." if rest else ""}<details><summary>Details and evidence</summary>{e(rest)}'
        f'<span class="sub">Evidence: {e(i.evidence)}</span></details></td></tr>'
        for i in integrations.integrations
        for lead, _, rest in [i.note.partition(". ")]
    )
    legend = "".join(f'<dt><span class="st st-{k}">{k}</span></dt><dd>{e(v)}</dd>' for k, v in STATUSES.items())
    verdict_legend = "".join(f'<dt><span class="v v-{k}">{k}</span></dt><dd>{e(v)}</dd>' for k, v in VERDICTS.items())
    default = next(iter(examples))
    options = "".join(f'<option{" selected" if c == default else ""}>{e(c)}</option>' for c in cases)
    form_data = {cid: {"turns": len(c.turns), "script": examples.get(cid)} for cid, c in cases.items()}
    form_json = json.dumps(form_data, ensure_ascii=False).replace("<", "\\u003c")  # cannot close the <script> block

    featured = cases[default]
    f_steps = [f"ask {kind} \u2192 {tool}" for tool, kind in featured.expected.ask_before.items()]
    f_steps += [f"{a.tool}({', '.join(f'{k}={v}' for k, v in a.args.items())})" for a in featured.expected.required_actions]
    plate_steps = '<span class="arr" aria-hidden="true"> \u2192 </span>'.join(f'<span class="p-chip">{e(st)}</span>' for st in f_steps) or '<span class="p-chip">no consequential action</span>'
    plate_html = (
        f'<aside class="plate" aria-label="Featured specimen {e(featured.id)}">'
        f'<p class="plate-k">Lab plate 01 \u00b7 specimen {e(featured.id)}</p>'
        f'<p class="plate-utt">{e(featured.turns[0])}</p>'
        f'<p class="plate-flow">{plate_steps}</p>'
        f'<p class="plate-meta">{" \u00b7 ".join(e(t) for t in featured.tags)} \u00b7 {len(featured.turns)} turn(s) \u00b7 verdict comes from recorded tool calls + final state</p></aside>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BoliBench demo</title>
<style>{CSS}</style></head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap">
<div class="mast"><div class="mast-main">
<p class="kicker">BoliBench / Behavioural Evaluation &mdash; Specimen Ledger</p>
<h1><span class="mark" aria-hidden="true">&#9638;</span>BoliBench</h1>
<p class="lede">An open-source benchmark for tool-using conversational agents. Each case is a short
order-management conversation in Hindi-English code-switching or Awadhi ("cancel the old kurta order", "which
order?") with a sandboxed shop. BoliBench records every tool call the agent makes and the final state of the
orders; the verdict comes from those observations, not from what the agent claims in its reply.</p>
<ul class="facts"><li>{e(review_fact)}</li><li>{len(runs)} bundled runs: single unseeded executions, not rankings</li></ul>
</div>{plate_html}</div>
<div class="spec-strip" aria-label="Benchmark specimen summary"><span>Instrument <b>BB-ORDERS</b></span><span>{len(cases)} specimens</span><span>{len(runs)} bundled runs</span><span>{judged} judged</span><span>Data {e(integrations.as_of)}</span></div>
</div></header>
<nav class="topnav" aria-label="Sections"><div class="wrap"><ul>
<li><a href="#results">Results</a></li><li><a href="#cases">Cases</a></li><li><a href="#integrations">Integrations</a></li>
<li><a href="#evaluate">Script evaluation</a></li><li><a href="#live">Live demo</a></li>
</ul></div></nav>
<main id="main" class="wrap">
<section id="results" aria-labelledby="results-h">
<h2 id="results-h"><span class="sec" aria-hidden="true">01</span>Results</h2>
<ul class="stats"><li><b>{len(cases)}</b> cases</li><li><b>{len(runs)}</b> bundled runs</li><li><b>{judged}</b> judged case runs</li></ul>
{dist_block}
<div class="caveats" role="note" aria-label="Caveats">
<p><b>Read these counts with care.</b></p>
<ul>
<li>Each bundled run is one unseeded execution of one setup. Rerunning it can flip individual cases, so a
difference of a case or two between runs may be sampling noise. The counts are not a score or a ranking.</li>
<li>The cases are hand-written and proposed: not yet reviewed for expected behaviour or by native speakers.</li>
<li>Verdicts were judged when each run was made. The agent's reply text is not judged.</li>
</ul></div>
<div class="scroll" role="region" aria-labelledby="summary-cap" tabindex="0">
<table class="summary"><caption id="summary-cap">Verdict counts per bundled run, from the bundled artifacts</caption>
<thead><tr><th scope="col">Run</th><th scope="col">Model</th><th scope="col">Date</th>{verdict_heads}<th scope="col" class="num">cases</th></tr></thead>
<tbody>{summary_rows}</tbody></table></div>
<h3>Verdicts</h3>
<dl class="legend">{verdict_legend}</dl>
</section>
<section id="cases" aria-labelledby="cases-h">
<h2 id="cases-h"><span class="sec" aria-hidden="true">02</span>Cases and bundled runs</h2>
<p>One row per case, one column per bundled run. Column labels are run labels without the date: hover one, or
open <i>Run provenance</i> below the table, for the model, agent and notes. Select any verdict to see that
case's evidence — what the customer asked, what the agent did, and why it passed or failed — right below
the table. Each run is a single unseeded run, so per-case
differences may be sampling noise.</p>
<div class="filters"><label for="case-filter">Filter specimens</label>
<input id="case-filter" type="search" autocomplete="off" placeholder="Search a case id, tag, or opening line&hellip;">
<p id="filter-count" class="note" aria-live="polite"></p></div>
<div class="scroll" role="region" aria-labelledby="cases-cap" tabindex="0">
<table class="matrix"><caption id="cases-cap">Verdict and failure classification per case and bundled run</caption>
<thead><tr><th scope="col">Case<span class="sub">first user turn, tags</span></th>{head}</tr></thead>
<tbody>{''.join(rows)}</tbody>
<tfoot><tr><th scope="row">Passed</th>{totals}</tr></tfoot></table></div>
<div id="artifact-view" class="out" aria-live="polite"><p class="note">Select any verdict above to see its evidence here.</p></div>
<p class="note">Under each verdict are the failure categories the evaluator assigned, e.g. <code>entity_resolution</code>
for acting on the wrong order. <code>unclassified</code> means a check failed but no classification rule matched it.</p>
<details class="prov"><summary>Run provenance (model, agent, notes)</summary><dl class="legend wide">{run_legend}</dl></details>
</section>
<section id="integrations" aria-labelledby="integrations-h">
<h2 id="integrations-h"><span class="sec" aria-hidden="true">03</span>Integrations</h2>
<p>How far each integration has actually been exercised, as of {e(integrations.as_of)}. This is engineering
status, not a benchmark result. Only <span class="st st-deployed">deployed</span> rows run in this deployed app.</p>
<dl class="legend">{legend}</dl>
<div class="scroll" role="region" aria-labelledby="int-cap" tabindex="0">
<table class="int"><caption id="int-cap">Integration status: the highest level reached, with evidence in the repo</caption>
<thead><tr><th scope="col">Integration</th><th scope="col">Status</th><th scope="col">Exercised by deployed app</th>
<th scope="col">Notes and evidence</th></tr></thead>
<tbody>{integration_rows}</tbody></table></div>
</section>
<section id="evaluate" aria-labelledby="evaluate-h">
<h2 id="evaluate-h"><span class="sec" aria-hidden="true">04</span>Script evaluation</h2>
<p>Replay a hand-written script against a fresh sandbox and the real evaluator. This is a scripted replay, not an
AI agent: no model is called, nothing is stored, and a request can never name an agent URL. A script is one list
of steps per user turn: <code>{{"tool": ..., "args": {{...}}}}</code>, <code>{{"text": ...}}</code> (reply) or
<code>{{"reason": ...}}</code> (adapter failure).</p>
<form id="f" novalidate>
<label for="case">Case</label><select id="case" name="case_id">{options}</select>
<p id="script-note" class="note" aria-live="polite"></p>
<label for="script">Script (JSON)</label>
<textarea id="script" name="script" rows="14" spellcheck="false" autocapitalize="off" aria-describedby="script-note">{e(format_script(examples[default]))}</textarea>
<p><button id="eval-btn" type="submit">Evaluate</button><button id="reset-btn" type="button" class="ghost">Reset example</button></p>
</form>
<div id="out" class="out" aria-live="polite"><p class="note">The result appears here.</p></div>
<script type="application/json" id="examples">{form_json}</script>
</section>
<section id="live" aria-labelledby="live-h">
<h2 id="live-h"><span class="sec" aria-hidden="true">05</span>Live demo</h2>
<p>On a configured deployment, an example agent backed by a hosted model runs in the same container as this
server. A live run drives one suite case through it over the webhook adapter and records every tool call in
BoliBench's own sandbox. Runs need the demo owner's token (only the owner holds one), run one at a time and are
capped per day. A run is queued and runs in the background; this page polls its status.</p>
<p class="note">When a run starts, the case's user turns are sent to the hosted model. Runs are kept in
memory only, so a restart or idle spin-down clears the list and resets the daily count.</p>
<p id="live-status" aria-live="polite">Checking live mode…</p>
<form id="lf" hidden>
<label for="lcase">Case</label><select id="lcase" name="case_id">{options}</select>
<label for="ltoken">Demo token</label><input id="ltoken" name="token" type="password" autocomplete="off" required>
<p><button id="lrun-btn" type="submit">Run live</button></p>
</form>
<div id="lout" class="out" aria-live="polite" hidden></div>
<div id="lruns-wrap" class="scroll" role="region" aria-labelledby="lruns-cap" tabindex="0" hidden>
<table><caption id="lruns-cap">Live runs since the last restart, newest first</caption>
<thead><tr><th scope="col">Queued (UTC)</th><th scope="col">Case</th><th scope="col">Status</th><th scope="col">Verdict</th>
<th scope="col">Agent (self-reported)</th><th scope="col">Classifications / error</th></tr></thead>
<tbody id="lruns-body"></tbody></table></div>
</section>
</main>
<footer class="wrap"><div class="foot-mark" aria-hidden="true">BoliBench</div><p>Data as of {e(integrations.as_of)}. Verdicts come from recorded tool calls and the final state of the orders — never from what an agent says it did.</p></footer>
<script>{SCRIPT}</script>
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
                          "turn_timeout_s": s.live.turn_timeout, "run_timeout_s": s.live.run_timeout,
                          "model": s.live.model or None, "provider": s.live.provider or None}
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
    # display only, the agent's settings from deploy/start.sh: model id and endpoint host (no path, query or credentials)
    model, provider = env.get("AGENT_MODEL", ""), urlsplit(env.get("AGENT_BASE_URL", "")).hostname or ""
    checked = Live(token or "unset-placeholder", agent_url or "http://127.0.0.1:1/turn", timeout, cap, run_timeout, model=model, provider=provider)
    return checked if token and agent_url else None


def main() -> None:
    env = os.environ
    try:
        host = env.get("HOST") or ("0.0.0.0" if "PORT" in env else "127.0.0.1")
        port = int(env.get("PORT") or "8080")
        live = live_from_env(env)
        demo = load_demo(Path(env.get("BOLIBENCH_SUITE") or "suites/orders"), Path(env.get("BOLIBENCH_DEMO") or "demo"), Path("examples/scripts"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"bolibench demo: invalid configuration: {e}") from None
    server = DemoServer((host, port), demo, client_ip_header=env.get("BOLIBENCH_CLIENT_IP_HEADER") or None, live=live)
    print(f"bolibench demo on http://{host}:{server.server_port} ({len(demo.cases)} cases)", flush=True)
    on = f"live mode: on, agent {live.agent_url}, daily cap {live.daily_cap}, turn/run timeout {live.turn_timeout:g}/{live.run_timeout:g}s" if live else ""
    print(on or f"live mode: off ({LIVE_DISABLED})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
