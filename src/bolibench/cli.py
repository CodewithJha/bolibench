import argparse
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from bolibench.adapters import AgentAdapter, FakeAgentAdapter, Step
from bolibench.evaluate import evaluate
from bolibench.models import ActionSpec, AdapterInfo, Artifact, CaseContext, TestCase
from bolibench.runner import new_run_dir, run_case, write_artifact, write_summary
from bolibench.store import SuiteError, load_case, load_suite
from bolibench.webhook import WebhookAgentAdapter, check_agent_url

SCRIPT = TypeAdapter(list[list[Step]])
RUN_EPILOG = """\
scripts: --scripts DIR reads DIR/<case_id>.json for every case; --scripts FILE is allowed for a single
case. A script is a JSON list with one list of steps per case turn; a step is {"tool": ..., "args": {...}},
{"text": ...} (reply) or {"reason": ...} (adapter failure). Every script is checked before anything runs.

webhook: --agent-url must be http on 127.0.0.1/localhost/[::1]; see README "Webhook adapter".
--timeout bounds the whole turn (request, tool calls, reply); past it the turn's token is revoked
and the case is an error. No retries.

speech: --speech elevenlabs sends each utterance through ElevenLabs TTS -> STT and gives the agent the
transcript (synthetic audio, not real speakers); needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID.
--speech-audio-dir DIR caches the audio so reruns hear identical audio. See docs/integrations/elevenlabs.md.

artifacts: <output>/<UTC timestamp>-<random>/<case_id>.json plus summary.json, never overwritten.

exit codes: 0 every case passed; 1 any case failed, errored or was inconclusive;
2 input error (bad case, bad or missing script, existing output); nothing runs on exit 2."""


def load_cases(path: Path) -> list[TestCase]:
    return load_suite(path) if path.is_dir() else [load_case(path)]


def load_scripts(scripts: Path, cases: list[TestCase]) -> dict[str, tuple[Path, list[list[Step]]]]:
    """All-or-nothing: a missing or invalid script is an input error, never a silently skipped case."""
    if scripts.is_file():
        if len(cases) != 1:
            raise SuiteError(f"{scripts}: a script file needs exactly one case; pass a directory of <case_id>.json")
        paths = {cases[0].id: scripts}
    else:
        paths = {c.id: scripts / f"{c.id}.json" for c in cases}
    if missing := [str(p) for p in paths.values() if not p.is_file()]:
        raise SuiteError("no script for: " + ", ".join(missing))
    loaded: dict[str, tuple[Path, list[list[Step]]]] = {}
    for case in cases:
        path = paths[case.id]
        try:
            script = SCRIPT.validate_json(path.read_bytes())
        except ValidationError as e:
            raise SuiteError(f"{path}: {e}") from e
        if len(script) != len(case.turns):
            raise SuiteError(f"{path}: scripts {len(script)} turns but case {case.id} has {len(case.turns)}")
        loaded[case.id] = (path, script)
    return loaded


def execute(cases: list[TestCase], adapter_for: Callable[[TestCase], AgentAdapter], output: Path) -> int:
    """Run every case, write one artifact each, print one line each. Only AdapterError is contained."""
    try:
        run_dir = new_run_dir(output)
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    verdicts: Counter[str] = Counter()
    for case in cases:
        record = run_case(case, adapter_for(case))
        result = evaluate(case, record)
        path = write_artifact(run_dir, Artifact(case_id=case.id, run=record, evaluation=result))
        verdicts[result.verdict] += 1
        print(f"{result.verdict:<12} {case.id}  {path}")
    summary = write_summary(run_dir)
    print(f"{len(cases)} cases: " + ", ".join(f"{n} {v}" for v, n in sorted(verdicts.items())) + f"; summary {summary}")
    return 0 if verdicts["pass"] == len(cases) else 1


def scripted_adapter(path: Path, script: list[list[Step]]) -> FakeAgentAdapter:
    return FakeAgentAdapter(script, info=AdapterInfo(name="fake-scripted", version="1", config={"script": str(path)}))


Wrap = Callable[[AgentAdapter], AgentAdapter]


def run_scripted(cases: list[TestCase], scripts: dict[str, tuple[Path, list[list[Step]]]], output: Path, wrap: Wrap = lambda a: a) -> int:
    print("adapter: fake-scripted (replays a fixed script; a test harness, not an AI agent)")
    return execute(cases, lambda case: wrap(scripted_adapter(*scripts[case.id])), output)


def run_webhook(cases: list[TestCase], agent_url: str, timeout: float, output: Path, wrap: Wrap = lambda a: a) -> int:
    with WebhookAgentAdapter(agent_url, timeout) as webhook:
        print(f"adapter: webhook -> {agent_url} (tool gateway {webhook.gateway_url})")
        adapter = wrap(webhook)
        code = execute(cases, lambda _: adapter, output)
        # ponytail: printed only; requests arriving after this line are not seen at all
        for s in webhook.stray_calls:
            print(f"warning: refused {s.status} outside any running case: {s.reason} (tool {s.tool}, token turn {s.token_turn})", file=sys.stderr)
        return code


def run(args: argparse.Namespace) -> int:
    try:  # input checks only; nothing below this block runs a case
        cases = load_cases(args.cases)
        if args.agent_url is None:
            scripts = load_scripts(args.scripts, cases)
        else:
            check_agent_url(args.agent_url)
        if args.speech_audio_dir is not None and args.speech is None:
            raise ValueError("--speech-audio-dir needs --speech")
        wrap: Wrap = lambda a: a
        if args.speech is not None:
            from bolibench.speech import SpeechAdapter, elevenlabs_from_env

            tts, stt = elevenlabs_from_env()
            wrap = lambda a: SpeechAdapter(a, tts, stt, audio_dir=args.speech_audio_dir)
    except ValueError as e:  # SuiteError, a bad --agent-url or speech config
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.speech is not None:
        print(f"speech: {args.speech} TTS -> STT, the agent hears the transcript (synthetic audio, not real speakers)")
    if args.agent_url is None:
        return run_scripted(cases, scripts, args.output, wrap)
    return run_webhook(cases, args.agent_url, args.timeout, args.output, wrap)


PLAIN = {
    "cancel_order": "cancel {order}",
    "update_quantity": "set the quantity of {order} to {quantity}",
    "ask_user": "ask the user a {kind} question",
    "list_orders": "list the orders",
    "get_order": "look up {order}",
}


class _AnyArg(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return f"any {key}"


def plain(case: TestCase, spec: ActionSpec) -> str:
    args = _AnyArg(spec.args)
    order = next((o for o in case.initial_state.get("orders", []) if o.get("id") == spec.args.get("order_id")), None)
    if order is not None:
        args["order"] = f"{order['id']} ({order.get('item')}, {order.get('seller')}, placed {order.get('placed_on')})"
    limit = f" (at most {spec.max_attempts} attempts, failed ones included)" if spec.max_attempts else ""
    return PLAIN[spec.tool].format_map(args) + limit


def review_sheet(cases: list[TestCase]) -> str:
    out = ["# BoliBench case review sheet", "", "A blank sheet generated from the case JSON, not a completed validation. Fill in the blank lines; a case counts as reviewed only once its status line says so.", ""]
    for c in cases:
        e = c.expected
        asks = set(e.ask_before.values()) | {s.args.get("kind") for s in e.required_actions if s.tool == "ask_user"}
        out += [f"## {c.id}", "", "Utterances (one per user turn):", *[f"{i + 1}. {t}" for i, t in enumerate(c.turns)], ""]
        out += [f"- Claimed language/dialect: {c.review.language_claim or 'not stated; tags: ' + (', '.join(c.tags) or 'none')}"]
        out += [f"- Context shown to the agent: {c.context.model_dump(mode='json', exclude_none=True)}"] if c.context != CaseContext() else []
        out += [f"- Simulated tool failure (not announced to the agent): {f.tool} call {f.call} fails with {f.error!r}" for f in c.inject_failures]
        out += ["- Expected agent behavior (the case's intended interpretation):"]
        out += [f"  - must {plain(c, s)}" for s in e.required_actions] + [f"  - must not even try to {plain(c, s)}" for s in e.forbidden_actions]
        out += ["  - must not even try any other cancellation or quantity change"] if e.exclusive_actions else []
        out += [f"  - must ask a {k} question in an earlier turn than the first {t} attempt" for t, k in e.ask_before.items()]
        out += [f"  - afterwards: {p} = {v}" for p, v in e.final_state.items()]
        out += [f"- Case expects clarification/confirmation: {', '.join(sorted(map(str, asks))) or 'no'}"]
        out += [f"- Current status: {c.status}; behavior review: {c.review.behavior}; native-speaker review: {c.review.linguistic}", ""]
        out += ["- Sounds natural? (y/n, notes):", "- Same interpretation as above? Clarification needed? (y/n, notes):", "- Problems found:", "- Your verdict (native_reviewed / needs_changes) and name:", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bolibench")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate every case in a suite directory")
    validate.add_argument("suite_dir", type=Path)
    sheet = commands.add_parser("review-sheet", help="print a Markdown review sheet for a suite (for native-speaker review)")
    sheet.add_argument("suite_dir", type=Path)
    run_cmd = commands.add_parser(
        "run",
        help="run cases and write one JSON artifact per case",
        epilog=RUN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_cmd.add_argument("cases", type=Path, help="suite directory or single case file")
    adapter = run_cmd.add_mutually_exclusive_group(required=True)
    adapter.add_argument("--scripts", type=Path, help="fake adapter: script directory, or one script file for one case")
    adapter.add_argument("--agent-url", help="webhook adapter: local agent endpoint, e.g. http://127.0.0.1:8000/turn")
    run_cmd.add_argument("--timeout", type=float, default=30.0, help="webhook: whole-turn deadline in seconds (default 30)")
    run_cmd.add_argument("--output", type=Path, default=Path("runs"), help="artifact root (default: runs/)")
    run_cmd.add_argument("--speech", choices=["elevenlabs"], help="speech round-trip: TTS -> STT before the agent (needs ELEVENLABS_* env)")
    run_cmd.add_argument("--speech-audio-dir", type=Path, help="with --speech: save and reuse each turn's audio here")
    # every other export argument goes to the exporter untouched; `export --to mongo --help` lists them
    export = commands.add_parser("export", help="export run directories to MongoDB or Tiger Data (optional extras)", add_help=False)
    export.add_argument("--to", choices=["mongo", "tiger"], required=True)
    commands.add_parser("serve", help="serve the public demo (python -m bolibench.server; env in docs/deployment.md)")
    args, rest = parser.parse_known_args(argv)
    if args.command == "export":
        if args.to == "mongo":
            from bolibench.export_mongo import main as exporter
        else:
            from bolibench.export_tiger import main as exporter
        return exporter(rest)
    if rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
    if args.command == "run":
        return run(args)
    if args.command == "serve":
        from bolibench.server import main as serve

        serve()
        return 0

    try:
        cases = load_suite(args.suite_dir)
    except SuiteError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(review_sheet(cases) if args.command == "review-sheet" else f"{args.suite_dir}: {len(cases)} cases ok")
    return 0
