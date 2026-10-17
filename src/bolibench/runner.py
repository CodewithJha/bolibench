import hashlib
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bolibench.adapters import AdapterError, AgentAdapter
from bolibench.models import AdapterInfo, Artifact, RunRecord, Summary, TestCase, TurnRecord
from bolibench.sandbox import OrderSandbox


def run_case(case: TestCase, adapter: AgentAdapter) -> RunRecord:
    """Drive the adapter through the case's turns against a fresh sandbox and record the evidence."""
    sandbox = OrderSandbox(case.initial_state, case.inject_failures)
    started_at = datetime.now(timezone.utc)
    turns: list[TurnRecord] = []
    error: str | None = None
    try:
        for i, utterance in enumerate(case.turns):
            reply = adapter.respond(i, utterance, case.context, sandbox)
            # speech adapters expose the transcript the agent acted on; every other adapter records None
            asr_text, speech = getattr(adapter, "asr_text", None), getattr(adapter, "last_turn", None)
            turns.append(TurnRecord(user_input=utterance, asr_text=asr_text, agent_reply=reply, speech=speech))
    except AdapterError as e:
        error = f"AdapterError: {e}"
    refused = sandbox.close()
    if error is None and refused:
        error = "refused tool requests: " + "; ".join(f"turn {r.token_turn}: {r.reason}" for r in refused)
    return RunRecord(
        run_id=uuid.uuid4().hex,
        case_id=case.id,
        adapter=adapter.info,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        turns=turns,
        tool_calls=list(sandbox.tool_calls) if adapter.exposes_tool_calls else [],
        final_state=sandbox.state,
        exposes_tool_calls=adapter.exposes_tool_calls,
        execution_error=error,
        refused_requests=refused,
    )


def new_run_dir(output: Path) -> Path:
    """Create a fresh `<output>/<UTC timestamp>-<random>` directory; raises FileExistsError rather than reuse one."""
    run_dir = output / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True)
    return run_dir


def write_artifact(run_dir: Path, artifact: Artifact) -> Path:
    path = run_dir / f"{artifact.case_id}.json"
    with path.open("x", encoding="utf-8") as f:  # "x": never overwrite an artifact
        f.write(artifact.model_dump_json(indent=2) + "\n")
    return path


def write_summary(run_dir: Path) -> Path:
    """Write `summary.json` from the artifacts already in `run_dir` (counts only, no statistics)."""
    artifacts = [Artifact.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(run_dir.glob("*.json"))]
    infos = list(dict.fromkeys(a.run.adapter.model_dump_json() for a in artifacts))
    counts = Counter(a.evaluation.verdict for a in artifacts)
    summary = Summary(
        total=len(artifacts),
        counts={v: counts[v] for v in ("pass", "fail", "error", "inconclusive")},
        cases={a.case_id: a.evaluation.verdict for a in artifacts},
        adapters=[AdapterInfo.model_validate_json(i) for i in infos],
        config_id=hashlib.sha256("\n".join(infos).encode()).hexdigest()[:16],
    )
    path = run_dir / "summary.json"
    with path.open("x", encoding="utf-8") as f:
        f.write(summary.model_dump_json(indent=2) + "\n")
    return path
