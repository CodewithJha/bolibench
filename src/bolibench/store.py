from pathlib import Path

from pydantic import ValidationError

from bolibench.models import TestCase


class SuiteError(ValueError):
    pass


def load_case(path: str | Path) -> TestCase:
    path = Path(path)
    try:
        case = TestCase.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as e:
        raise SuiteError(f"{path}: {e}") from e
    if case.id != path.stem:
        raise SuiteError(f"{path}: id {case.id!r} does not match filename stem {path.stem!r}")
    if case.id == "summary":
        raise SuiteError(f"{path}: id 'summary' is reserved for the run's summary.json")
    return case


def load_suite(directory: str | Path) -> list[TestCase]:
    """A suite is a directory of <id>.json files. id == filename stem, so ids are unique by construction."""
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise SuiteError(f"{directory}: no *.json cases found")
    return [load_case(p) for p in paths]
