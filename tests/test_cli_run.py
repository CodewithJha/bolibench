import json
from pathlib import Path
from typing import Any

import pytest

from bolibench import cli
from bolibench.adapters import Fail, FakeAgentAdapter
from bolibench.cli import main
from bolibench.evaluate import evaluate
from bolibench.models import Artifact, Evaluation, Summary
from bolibench.runner import write_artifact
from bolibench.store import SuiteError, load_case

ROOT = Path(__file__).parent.parent
SUITE = ROOT / "suites" / "orders"
EXAMPLE = ROOT / "examples" / "scripts" / "ambiguous-previous-order.json"
CASE = SUITE / "ambiguous-previous-order.json"


def script(directory: Path, case_id: str, turns: list[list[dict[str, Any]]]) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / f"{case_id}.json"
    path.write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")
    return path


def artifacts(output: Path) -> dict[str, Artifact]:
    [run_dir] = output.iterdir()
    paths = sorted(p for p in run_dir.glob("*.json") if p.name != "summary.json")
    return {p.stem: Artifact.model_validate_json(p.read_text(encoding="utf-8")) for p in paths}


def all_scripts(directory: Path) -> None:
    """A deliberately naive script for every case: one reply per turn, no tool calls."""
    for case_path in sorted(SUITE.glob("*.json")):
        case = load_case(case_path)
        script(directory, case.id, [[{"text": "ठीक है"}] for _ in case.turns])


def test_single_case_writes_one_complete_artifact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(CASE), "--scripts", str(EXAMPLE), "--output", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "not an AI agent" in out and "pass         ambiguous-previous-order" in out
    [run_dir] = tmp_path.iterdir()
    text = (run_dir / "ambiguous-previous-order.json").read_text(encoding="utf-8")
    assert "भइया" in text and "\\u" not in text
    raw = json.loads(text)
    assert raw["schema_version"] == 1 and raw["case_id"] == "ambiguous-previous-order"
    run, result = raw["run"], raw["evaluation"]
    assert run["adapter"] == {"name": "fake-scripted", "version": "1", "config": {"script": str(EXAMPLE)}, "seed": None}
    assert [(c["turn"], c["tool"], c["status"]) for c in run["tool_calls"]] == [
        (0, "list_orders", "ok"),
        (0, "ask_user", "ok"),
        (1, "cancel_order", "ok"),
    ]
    assert run["final_state"]["orders"][0]["status"] == "cancelled" and run["exposes_tool_calls"] is True
    assert run["execution_error"] is None and len(run["turns"]) == 2
    assert result["verdict"] == "pass" and {c["metric"] for c in result["checks"]} == {
        "final_state",
        "required_actions",
        "forbidden_actions",
        "ask_policy",
        "evidence",
    }


def test_suite_writes_one_artifact_per_case_and_failures_do_not_abort(tmp_path: Path) -> None:
    all_scripts(tmp_path / "scripts")
    assert main(["run", str(SUITE), "--scripts", str(tmp_path / "scripts"), "--output", str(tmp_path / "out")]) == 1
    written = artifacts(tmp_path / "out")
    assert sorted(written) == sorted(p.stem for p in SUITE.glob("*.json"))
    assert {a.evaluation.verdict for a in written.values()} == {"pass", "fail"}


@pytest.mark.parametrize(
    "steps,expected",
    [
        ([[{"tool": "cancel_order", "args": {"order_id": "ORD-111"}}, {"text": "हो गया"}]], "fail"),
        ([[{"reason": "websocket closed"}]], "error"),
    ],
)
def test_verdicts_match_direct_evaluation(tmp_path: Path, steps: list, expected: str) -> None:
    case_path = SUITE / "tool-failure-cancel.json"
    path = script(tmp_path / "scripts", "tool-failure-cancel", steps)
    assert main(["run", str(case_path), "--scripts", str(path), "--output", str(tmp_path / "out")]) == 1
    artifact = artifacts(tmp_path / "out")["tool-failure-cancel"]
    assert artifact.evaluation.verdict == expected
    assert artifact.evaluation == evaluate(load_case(case_path), artifact.run)
    if expected == "error":
        assert artifact.run.execution_error == "AdapterError: websocket closed"


def test_missing_script_aborts_before_running(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script(tmp_path / "scripts", "cancel-single-order", [[{"text": "ok"}]])
    code = main(["run", str(SUITE), "--scripts", str(tmp_path / "scripts"), "--output", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert code == 2 and "no script for:" in err and "ambiguous-previous-order.json" in err
    assert "cancel-single-order.json" not in err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "turns,message",
    [([[{"text": "ok"}]], "scripts 1 turns but case"), ([[{"tool": "x", "text": "y"}], []], "validation error")],
)
def test_invalid_script_is_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str], turns: list, message: str) -> None:
    path = script(tmp_path, "ambiguous-previous-order", turns)
    assert main(["run", str(CASE), "--scripts", str(path), "--output", str(tmp_path / "out")]) == 2
    assert message in capsys.readouterr().err


def test_script_file_needs_a_single_case(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(SUITE), "--scripts", str(EXAMPLE), "--output", str(tmp_path)]) == 2
    assert "exactly one case" in capsys.readouterr().err


def test_missing_case_file_is_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(tmp_path / "nope.json"), "--scripts", str(EXAMPLE), "--output", str(tmp_path)]) == 2
    assert "nope.json" in capsys.readouterr().err


def test_artifacts_are_never_overwritten(tmp_path: Path) -> None:
    args = ["run", str(CASE), "--scripts", str(EXAMPLE), "--output", str(tmp_path)]
    assert main(args) == 0 and main(args) == 0
    assert len(list(tmp_path.iterdir())) == 2
    run_dir = next(tmp_path.iterdir())
    existing = Artifact.model_validate_json((run_dir / "ambiguous-previous-order.json").read_text(encoding="utf-8"))
    with pytest.raises(FileExistsError):
        write_artifact(run_dir, existing)


def test_summary_is_derived_from_the_written_artifacts(tmp_path: Path) -> None:
    all_scripts(tmp_path / "scripts")
    main(["run", str(SUITE), "--scripts", str(tmp_path / "scripts"), "--output", str(tmp_path / "out")])
    written = artifacts(tmp_path / "out")
    [run_dir] = (tmp_path / "out").iterdir()
    summary = Summary.model_validate_json((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary.total == 12 and summary.cases == {k: a.evaluation.verdict for k, a in written.items()}
    assert sum(summary.counts.values()) == 12 and set(summary.counts) == {"pass", "fail", "error", "inconclusive"}
    assert len(summary.adapters) == 12 and all(a.name == "fake-scripted" for a in summary.adapters)
    assert len(summary.config_id) == 16


def test_summary_keeps_error_and_inconclusive_apart(tmp_path: Path) -> None:
    case = load_case(CASE)
    good = cli.SCRIPT.validate_json(EXAMPLE.read_bytes())
    adapters = {
        "pass": FakeAgentAdapter(good),
        "inconclusive": FakeAgentAdapter(good, exposes_tool_calls=False),
        "error": FakeAgentAdapter([[Fail(reason="websocket closed")], []]),
    }
    for verdict, adapter in adapters.items():
        assert cli.execute([case], lambda _: adapter, tmp_path / verdict) in (0, 1)
        [run_dir] = (tmp_path / verdict).iterdir()
        summary = Summary.model_validate_json((run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary.counts[verdict] == 1 and summary.cases == {case.id: verdict}
    first = Summary.model_validate_json(next((tmp_path / "pass").iterdir()).joinpath("summary.json").read_text())
    again = cli.execute([case], lambda _: FakeAgentAdapter(good), tmp_path / "again")
    second = Summary.model_validate_json(next((tmp_path / "again").iterdir()).joinpath("summary.json").read_text())
    assert again == 0 and first.config_id == second.config_id


def test_case_id_summary_is_reserved(tmp_path: Path) -> None:
    data = json.loads(CASE.read_text(encoding="utf-8")) | {"id": "summary"}
    (tmp_path / "summary.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SuiteError, match="reserved"):
        load_case(tmp_path / "summary.json")


def test_programming_errors_propagate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object) -> Evaluation:
        raise RuntimeError("bug")

    monkeypatch.setattr(cli, "evaluate", broken)
    with pytest.raises(RuntimeError, match="bug"):
        main(["run", str(CASE), "--scripts", str(EXAMPLE), "--output", str(tmp_path)])
