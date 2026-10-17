import argparse
import asyncio
import contextlib
import shutil
from collections import Counter
from datetime import timedelta
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from bolibench import temporal_run as tr
from bolibench.adapters import AdapterError, AgentAdapter
from bolibench.cli import main
from bolibench.models import AdapterInfo, Artifact, CaseContext, TestCase
from bolibench.sandbox import OrderSandbox

ROOT = Path(__file__).parent.parent
SUITE = ROOT / "suites" / "orders"
EXAMPLE = ROOT / "examples" / "scripts" / "ambiguous-previous-order.json"
SCRIPTS = {
    "ambiguous-previous-order": EXAMPLE.read_text(encoding="utf-8"),
    "tool-failure-cancel": '[[{"tool": "cancel_order", "args": {"order_id": "ORD-111"}}, {"text": "हो गया"}]]',
    "cancel-single-order": '[[{"tool": "cancel_order", "args": {"order_id": "ORD-201"}}, {"text": "हो गया"}]]',
}


def unreachable() -> AdapterError:
    try:
        raise URLError(ConnectionRefusedError(61, "Connection refused"))
    except URLError as cause:
        try:
            raise AdapterError(f"agent request failed: {cause}") from cause
        except AdapterError as e:
            return e


class Down:
    info = AdapterInfo(name="down", version="1")
    exposes_tool_calls = True

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        raise unreachable()


def setup(tmp_path: Path) -> argparse.Namespace:
    """A 3-case suite with scripts, as `start`/`run` arguments."""
    (tmp_path / "suite").mkdir()
    (tmp_path / "scripts").mkdir()
    for case_id, script in SCRIPTS.items():
        shutil.copy(SUITE / f"{case_id}.json", tmp_path / "suite")
        (tmp_path / "scripts" / f"{case_id}.json").write_text(script, encoding="utf-8")
    return argparse.Namespace(
        cases=tmp_path / "suite", scripts=tmp_path / "scripts", agent_url=None, timeout=30.0, output=tmp_path / "temporal", max_attempts=3
    )


def task(args: argparse.Namespace, case_id: str, max_attempts: int = 3) -> tr.CaseTask:
    suite = tr.suite_input(args)
    [case] = [c for c in suite.cases if c.case_id == case_id]
    return tr.CaseTask(suite.output, "run-1", case, "", 30.0, max_attempts)


def comparable(run_dir: Path) -> dict[str, Any]:
    """Artifacts minus what differs between any two runs (run_id, timestamps), plus summary.json verbatim."""
    out: dict[str, Any] = {"summary.json": (run_dir / "summary.json").read_text(encoding="utf-8")}
    for p in sorted(run_dir.glob("*.json")):
        if p.name != "summary.json":
            out[p.name] = Artifact.model_validate_json(p.read_text(encoding="utf-8")).model_dump(
                mode="json", exclude={"run": {"run_id", "started_at", "finished_at"}}
            )
    return out


# --- pure helpers: no temporalio needed ---


def test_case_timeout_covers_every_turn_deadline() -> None:
    assert tr.case_timeout(2, 30.0) == timedelta(seconds=90)
    assert tr.case_timeout(1, 120.0) == timedelta(seconds=150)


@pytest.mark.parametrize("name", ["", "../x", "a/b", ".hidden", "x" * 129])
def test_run_dir_rejects_unsafe_workflow_ids(name: str) -> None:
    with pytest.raises(ValueError, match="safe directory name"):
        tr.run_dir_for("/out", name)


def test_run_dir_is_output_slash_workflow_id() -> None:
    name = tr.new_run_name()
    assert tr.run_dir_for("/out", name) == Path("/out") / name


@pytest.mark.parametrize(
    "error,retry",
    [
        (unreachable(), True),
        (AdapterError("agent request failed"), False),
        (AdapterError("turn deadline exceeded: no reply within 30.0s"), False),
    ],
)
def test_only_connection_failures_are_unreachable(error: AdapterError, retry: bool) -> None:
    assert tr.is_unreachable(error) is retry


def test_dropped_connection_is_unreachable_but_http_errors_and_timeouts_are_results() -> None:
    def chained(cause: BaseException) -> AdapterError:
        e = AdapterError("agent request failed")
        e.__cause__ = cause
        return e

    assert tr.is_unreachable(chained(RemoteDisconnected("closed")))
    assert not tr.is_unreachable(chained(URLError(TimeoutError("timed out"))))
    assert not tr.is_unreachable(chained(HTTPError("http://127.0.0.1", 500, "boom", {}, None)))  # type: ignore[arg-type]


def test_unreachable_agent_escapes_run_case_until_the_final_attempt(tmp_path: Path) -> None:
    args = setup(tmp_path)
    down = lambda *_: contextlib.nullcontext(Down())  # noqa: E731
    with pytest.raises(tr.AgentUnavailable):
        tr.run_case_task(task(args, "cancel-single-order", max_attempts=2), 1, down)
    assert not list(tr.run_dir_for(str(args.output), "run-1").glob("*.json"))  # nothing written
    outcome = tr.run_case_task(task(args, "cancel-single-order", max_attempts=2), 2, down)
    artifact = tr.completed(Path(outcome.path).parent, "cancel-single-order")
    assert outcome.verdict == "error" and artifact is not None
    assert artifact.run.execution_error is not None and artifact.run.execution_error.startswith("AdapterError: agent request failed")


def test_a_written_case_is_never_run_or_written_again(tmp_path: Path) -> None:
    args = setup(tmp_path)
    first = tr.run_case_task(task(args, "ambiguous-previous-order"), 1)
    before = Path(first.path).read_bytes()

    def must_not_run(*_: object) -> contextlib.AbstractContextManager[AgentAdapter]:
        raise AssertionError("re-ran a completed case")

    again = tr.run_case_task(task(args, "ambiguous-previous-order"), 2, must_not_run)
    assert (first.verdict, first.reused) == ("pass", False)
    assert (again.verdict, again.reused, again.path) == ("pass", True, first.path)
    assert Path(first.path).read_bytes() == before


def test_partial_artifact_is_not_treated_as_done(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "cancel-single-order.json").write_text('{"schema_version": 1, "case_', encoding="utf-8")
    with pytest.raises(ValueError):  # pydantic ValidationError; the file stays for a human to inspect
        tr.completed(run_dir, "cancel-single-order")


def test_offline_tasks_match_bolibench_run(tmp_path: Path) -> None:
    args = setup(tmp_path)
    assert main(["run", str(args.cases), "--scripts", str(args.scripts), "--output", str(tmp_path / "cli")]) == 1
    for case_id in SCRIPTS:
        tr.run_case_task(task(args, case_id), 1)
    summary = tr.summary_task(str(args.output), "run-1")
    assert tr.summary_task(str(args.output), "run-1") == summary  # idempotent
    [cli_dir] = (tmp_path / "cli").iterdir()
    assert comparable(Path(summary).parent) == comparable(cli_dir)


def test_suite_input_mirrors_run_input_checks(tmp_path: Path) -> None:
    args = setup(tmp_path)
    (args.scripts / "cancel-single-order.json").unlink()
    with pytest.raises(ValueError, match="no script for"):
        tr.suite_input(args)
    args.scripts, args.agent_url = None, "http://example.com/turn"
    with pytest.raises(ValueError, match="agent URL must be"):
        tr.suite_input(args)


# --- Temporal integration: `uv run --with temporalio pytest tests/test_temporal_run.py` ---


def run_workflow(suite: Any, adapter_for: tr.AdapterFactory = tr.default_adapter, workflow_id: str = "run-1", runs: int = 1) -> list[Any]:
    pytest.importorskip("temporalio")
    from concurrent.futures import ThreadPoolExecutor

    from temporalio.testing import WorkflowEnvironment

    async def go() -> list[Any]:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(1) as pool:
                async with tr.make_worker(env.client, "bolibench-test", tr.CaseActivities(adapter_for), pool):
                    return [await tr.start(env.client, suite, workflow_id, "bolibench-test") for _ in range(runs)]

    return asyncio.run(go())


def counting(attempts: Counter[str], down_for: dict[str, int]) -> tr.AdapterFactory:
    """Real scripted adapters, except the first `down_for[case]` attempts of a case find the agent unreachable."""

    def adapter_for(task: tr.CaseTask, case: TestCase) -> contextlib.AbstractContextManager[AgentAdapter]:
        attempts[case.id] += 1
        if attempts[case.id] <= down_for.get(case.id, 0):
            return contextlib.nullcontext(Down())
        return tr.default_adapter(task, case)

    return adapter_for


def test_workflow_matches_bolibench_run_and_resumes_without_rerunning(tmp_path: Path) -> None:
    args = setup(tmp_path)
    suite = tr.suite_input(args)
    assert main(["run", str(args.cases), "--scripts", str(args.scripts), "--output", str(tmp_path / "cli")]) == 1
    attempts: Counter[str] = Counter()
    first, again = run_workflow(suite, counting(attempts, {}), runs=2)
    [cli_dir] = (tmp_path / "cli").iterdir()
    assert comparable(args.output / "run-1") == comparable(cli_dir)
    assert {o.case_id: o.verdict for o in first.cases} == {
        "ambiguous-previous-order": "pass",
        "tool-failure-cancel": "fail",
        "cancel-single-order": "pass",
    }
    assert tr.report(first) == 1 and not any(o.reused for o in first.cases)
    assert all(o.reused for o in again.cases) and again.summary == first.summary
    assert attempts == Counter(SCRIPTS.keys())  # every case ran exactly once across both workflow runs


def test_unreachable_agent_is_retried_but_a_fail_verdict_is_not(tmp_path: Path) -> None:
    attempts: Counter[str] = Counter()
    [result] = run_workflow(tr.suite_input(setup(tmp_path)), counting(attempts, {"ambiguous-previous-order": 1}))
    assert attempts == {"ambiguous-previous-order": 2, "tool-failure-cancel": 1, "cancel-single-order": 1}
    verdicts = {o.case_id: o.verdict for o in result.cases}
    assert verdicts["ambiguous-previous-order"] == "pass" and verdicts["tool-failure-cancel"] == "fail"
    artifact = tr.completed(args_dir := tmp_path / "temporal" / "run-1", "ambiguous-previous-order")
    assert artifact is not None and artifact.run.adapter.name == "fake-scripted"
    assert sorted(p.name for p in args_dir.iterdir()) == sorted([*(f"{c}.json" for c in SCRIPTS), "summary.json"])


def test_exhausted_retries_record_an_error_verdict(tmp_path: Path) -> None:
    attempts: Counter[str] = Counter()
    args = setup(tmp_path)
    args.max_attempts = 2
    [result] = run_workflow(tr.suite_input(args), counting(attempts, {"cancel-single-order": 99}))
    assert attempts["cancel-single-order"] == 2
    assert {o.case_id: o.verdict for o in result.cases}["cancel-single-order"] == "error"


def test_programming_errors_fail_the_workflow_without_retry(tmp_path: Path) -> None:
    pytest.importorskip("temporalio")
    from temporalio.client import WorkflowFailureError

    calls: list[str] = []

    def broken(task: tr.CaseTask, case: TestCase) -> contextlib.AbstractContextManager[AgentAdapter]:
        calls.append(case.id)
        raise RuntimeError("bug")

    with pytest.raises(WorkflowFailureError):
        run_workflow(tr.suite_input(setup(tmp_path)), broken)
    assert calls == ["ambiguous-previous-order"]


@pytest.mark.parametrize("command", ["worker", "start"])
def test_unreachable_server_is_an_error_line_not_a_traceback(command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("temporalio")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "127.0.0.1:1")
    args = setup(tmp_path)
    argv = ["worker"] if command == "worker" else ["start", str(args.cases), "--scripts", str(args.scripts), "--output", str(args.output)]
    with pytest.raises(SystemExit) as exit_info:
        tr.main(argv)
    assert exit_info.value.code == 2
    assert "error: cannot connect to Temporal at 127.0.0.1:1" in capsys.readouterr().err
    assert not args.output.exists()
