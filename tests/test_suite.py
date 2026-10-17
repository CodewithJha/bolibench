import json
from pathlib import Path

import pytest

from bolibench.cli import main
from bolibench.evaluate import MISSING, resolve
from bolibench.models import Review
from bolibench.store import SuiteError, load_case, load_suite

SUITE = Path(__file__).parent.parent / "suites" / "orders"


def test_orders_suite_is_valid_and_consistent() -> None:
    cases = load_suite(SUITE)
    assert len(cases) == 12
    assert all(c.status == "proposed" and c.provenance == "hand-written synthetic" for c in cases)
    assert all(c.expected.exclusive_actions for c in cases)
    for case in cases:
        order_ids = {o["id"] for o in case.initial_state["orders"]}
        for path in case.expected.final_state:
            assert resolve(case.initial_state, path) is not MISSING, (case.id, path)
        for spec in case.expected.required_actions + case.expected.forbidden_actions:
            assert spec.args.get("order_id", next(iter(order_ids))) in order_ids, (case.id, spec)


def write(directory: Path, stem: str, **overrides: object) -> Path:
    data = {"id": stem, "status": "proposed", "turns": ["हाँ"], "initial_state": {}, "expected": {}, "provenance": "test"}
    path = directory / f"{stem}.json"
    path.write_text(json.dumps(data | overrides, ensure_ascii=False), encoding="utf-8")
    return path


def test_bad_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(SuiteError, match="evil.json"):
        load_case(write(tmp_path, "evil", id="../evil"))
    with pytest.raises(SuiteError, match="Bad_Id.json"):
        load_case(write(tmp_path, "Bad_Id"))


def test_id_must_match_filename(tmp_path: Path) -> None:
    write(tmp_path, "case-one", id="case-two")
    with pytest.raises(SuiteError, match="does not match filename"):
        load_suite(tmp_path)


def test_existing_cases_are_unreviewed_by_default() -> None:
    assert all(c.review == Review() for c in load_suite(SUITE))
    assert Review().behavior == "unreviewed" and Review().linguistic == "unreviewed"


@pytest.mark.parametrize(
    "review",
    [{"behavior": "approved"}, {"linguistic": "reviewed"}, {"reviewer": 3}, {"signed_off": True}, "reviewed"],
)
def test_malformed_review_metadata_is_rejected(tmp_path: Path, review: object) -> None:
    with pytest.raises(SuiteError, match="review"):
        load_case(write(tmp_path, "bad-review", review=review))


@pytest.mark.parametrize(
    "review",
    [{}, {"behavior": "reviewed"}, {"linguistic": "native_reviewed"}, {"behavior": "reviewed", "linguistic": "needs_changes"}],
)
def test_trusted_requires_behavior_and_native_review(tmp_path: Path, review: dict[str, str]) -> None:
    with pytest.raises(SuiteError, match="trusted"):
        load_case(write(tmp_path, "trusted-case", status="trusted", review=review))


def test_trusted_with_both_reviews_loads(tmp_path: Path) -> None:
    review = {"behavior": "reviewed", "linguistic": "native_reviewed", "language_claim": "Hindi", "reviewer": "t"}
    assert load_case(write(tmp_path, "trusted-case", status="trusted", review=review)).review.linguistic == "native_reviewed"


def test_max_attempts_is_rejected_on_forbidden_actions(tmp_path: Path) -> None:
    expected = {"forbidden_actions": [{"tool": "cancel_order", "max_attempts": 1}]}
    with pytest.raises(SuiteError, match="max_attempts"):
        load_case(write(tmp_path, "bad-max", expected=expected))


def test_review_sheet_covers_every_case(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["review-sheet", str(SUITE)]) == 0
    out = capsys.readouterr().out
    for case in load_suite(SUITE):
        assert f"## {case.id}" in out and all(t in out for t in case.turns)
    assert out.count("native-speaker review: unreviewed") == 12 and "Sounds natural?" in out
    assert "must cancel ORD-101 (Kurta, Rangoli Fashions, placed 2026-10-10)" in out
    assert "must not even try to cancel any order" in out
    assert out.count("must not even try any other cancellation or quantity change") == 12
    assert "not a completed validation" in out
    assert out.count("- Simulated tool failure (not announced to the agent): cancel_order call 1 fails with") == 2


def test_cli_validate_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(SUITE)]) == 0
    assert "12 cases ok" in capsys.readouterr().out
    write(tmp_path, "broken-case", turns=[])
    assert main(["validate", str(tmp_path)]) == 1
    assert "broken-case.json" in capsys.readouterr().err
