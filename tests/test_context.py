from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from bolibench.models import AdapterInfo, CaseContext, Review, TestCase
from bolibench.runner import run_case
from bolibench.sandbox import OrderSandbox
from bolibench.store import load_case, load_suite

SUITE = Path(__file__).parent.parent / "suites" / "orders"
CONTEXT_FIELDS = {"today", "policy"}


@dataclass
class RecordingAdapter:
    exposes_tool_calls: bool = True
    info: AdapterInfo = field(default_factory=lambda: AdapterInfo(name="recording", version="0"))
    seen: list[tuple[int, str, CaseContext, dict]] = field(default_factory=list)

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        self.seen.append((turn, utterance, context, sandbox.state))
        return ""


def test_cases_without_context_get_an_empty_context() -> None:
    minimal = {"id": "no-context", "status": "proposed", "turns": ["हाँ"], "initial_state": {}, "expected": {}, "provenance": "t"}
    case = TestCase.model_validate(minimal)
    assert case.context == CaseContext() and case.context.today is None and case.context.policy is None
    untouched = [c for c in load_suite(SUITE) if c.id not in {"awadhi-cancel-yesterday", "forbidden-bulk-cancel"}]
    assert len(untouched) == 10 and all(c.context == CaseContext() for c in untouched)


def test_migrated_context_lives_outside_sandbox_state() -> None:
    awadhi = load_case(SUITE / "awadhi-cancel-yesterday.json")
    bulk = load_case(SUITE / "forbidden-bulk-cancel.json")
    assert awadhi.context.today == date(2026, 10, 17) and awadhi.context.policy is None
    assert bulk.context.policy and bulk.context.policy.startswith("Bulk cancellation is not allowed") and bulk.context.today is None
    assert all(set(c.initial_state) == {"orders"} for c in load_suite(SUITE))


def test_context_is_frozen_and_strict() -> None:
    ctx = CaseContext(today=date(2026, 10, 17))
    with pytest.raises(ValidationError):
        ctx.today = date(2026, 10, 18)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        CaseContext.model_validate({"today": "kal"})
    with pytest.raises(ValidationError):
        CaseContext.model_validate({"expected": {}})


def test_same_context_reaches_every_turn_without_evaluator_fields() -> None:
    base = load_case(SUITE / "requires-clarification-red-order.json")
    case = base.model_copy(update={"context": CaseContext(today=date(2026, 10, 17), policy="ask first")})
    adapter = RecordingAdapter()
    run_case(case, adapter)
    assert [(t, u) for t, u, _, _ in adapter.seen] == list(enumerate(case.turns))
    contexts = [c for _, _, c, _ in adapter.seen]
    assert all(c is case.context for c in contexts)
    assert all(set(c.model_dump()) == CONTEXT_FIELDS for c in contexts)
    assert all(state == case.initial_state for _, _, _, state in adapter.seen)


def test_review_metadata_never_reaches_the_adapter() -> None:
    base = load_case(SUITE / "ambiguous-previous-order.json")
    case = base.model_copy(update={"review": Review(notes="REVIEW-NOTE-XYZ", reviewer="REVIEWER-XYZ")})
    adapter = RecordingAdapter()
    run_case(case, adapter)
    assert len(adapter.seen) == 2 and "XYZ" not in repr(adapter.seen)


def test_no_context_case_passes_empty_context_not_sandbox_state() -> None:
    adapter = RecordingAdapter()
    run_case(load_case(SUITE / "cancel-single-order.json"), adapter)
    [(_, _, context, _)] = adapter.seen
    assert context.model_dump() == {"today": None, "policy": None}
