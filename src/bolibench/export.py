"""Shared loading and record shaping for the optional database exporters (`export_mongo`, `export_tiger`).

Read-only: a run directory is loaded and validated with the artifact models, never modified. Local JSON
stays the source of truth; nothing here runs unless an exporter is invoked explicitly.
"""

import hashlib
import importlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from bolibench.models import Artifact, Summary


class ExportError(ValueError):
    """Bad input or configuration (incl. no local embedding model). Always raised before any database connection."""


@dataclass(frozen=True)
class CaseArtifact:
    artifact: Artifact
    raw: bytes  # the file's exact bytes


@dataclass(frozen=True)
class Run:
    run_id: str  # run directory name, `<UTC timestamp>-<random>`; never a path
    summary: Summary
    cases: list[CaseArtifact]


M = TypeVar("M", bound=BaseModel)


def _read(path: Path, model: type[M]) -> tuple[bytes, M]:
    try:
        raw = path.read_bytes()
        return raw, model.model_validate_json(raw)
    except (OSError, ValidationError) as e:
        raise ExportError(f"{path}: {e}") from e


def load_run(run_dir: Path) -> Run:
    """A complete `bolibench run` directory: valid artifacts plus a summary.json that agrees with them."""
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise ExportError(f"{run_dir}: no summary.json, not a complete bolibench run directory")
    summary = _read(summary_path, Summary)[1]
    cases = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "summary.json":
            continue
        raw, artifact = _read(path, Artifact)
        if not artifact.case_id == artifact.run.case_id == path.stem:
            raise ExportError(f"{path}: case_id does not match the file name")
        cases.append(CaseArtifact(artifact, raw))
    verdicts = {c.artifact.case_id: c.artifact.evaluation.verdict for c in cases}
    if summary.total != len(cases) or summary.cases != verdicts:
        raise ExportError(f"{summary_path}: does not match the artifacts next to it")
    return Run(run_dir.resolve().name, summary, cases)


def case_record(run: Run, case: CaseArtifact) -> dict[str, Any]:
    """Denormalized per-case fields shared by both exporters. None = not observed, never a guessed 0."""
    a, r = case.artifact, case.artifact.run
    agent = r.adapter.self_reported_agent
    calls = r.tool_calls if r.exposes_tool_calls else None  # unexposed: an empty list is not evidence
    return {
        "key": f"{run.run_id}/{a.case_id}",  # idempotency key: one record per case artifact
        "run_id": run.run_id,
        "config_id": run.summary.config_id,
        "case_id": a.case_id,
        "verdict": a.evaluation.verdict,
        "passed": a.evaluation.verdict == "pass",
        "categories": sorted({c.category for c in a.evaluation.classifications}),
        "adapter": {"name": r.adapter.name, "version": r.adapter.version},
        "agent": agent.model_dump() if agent else None,  # self-reported, unverified
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "duration_ms": round((r.finished_at - r.started_at).total_seconds() * 1000, 3) if r.finished_at else None,
        "n_tool_calls": None if calls is None else len(calls),
        "n_rejected": None if calls is None else sum(c.status == "rejected" for c in calls),
        "artifact_sha256": hashlib.sha256(case.raw).hexdigest(),
    }


def require_env(name: str) -> str:
    if not (value := os.environ.get(name)):
        raise ExportError(f"{name} is not set; it is read from the environment only")
    return value


def require_driver(module: str, extra: str, package: str) -> ModuleType:
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise ExportError(f"{module} is not installed; install bolibench[{extra}] or run with `uv run --with {package!r} ...`") from e


def redact(text: str, secret: str) -> str:
    """Drop the connection string and any credentials embedded in a URL or conninfo from a message."""
    text = text.replace(secret, "<redacted>")
    text = re.sub(r"(://)[^@/\s]+@", r"\1<redacted>@", text)
    return re.sub(r"(password\s*=\s*)\S+", r"\1<redacted>", text, flags=re.IGNORECASE)


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=lambda o: o.isoformat())
