from datetime import datetime, timezone
from typing import Any

from bolibench.evaluate import (
    check_ask_policy,
    check_final_state,
    check_forbidden_actions,
    check_required_actions,
    evaluate,
)
from bolibench.models import RunRecord, TestCase, ToolCall


def orders(ord101: str = "placed", ord102: str = "placed") -> dict[str, Any]:
    return {
        "orders": [
            {"id": "ORD-101", "item": "Kurta", "status": ord101},
            {"id": "ORD-102", "item": "Kurti", "status": ord102},
        ]
    }


def make_case(tags: list[str] | None = None, inject_failures: list | None = None, **expected: Any) -> TestCase:
    return TestCase.model_validate(
        {
            "id": "test-case",
            "status": "proposed",
            "tags": tags or [],
            "turns": ["भइया, पिछला वाला order cancel कर दो, नया वाला नहीं।", "हाँ, कर दो"],
            "initial_state": orders(),
            "expected": expected,
            "inject_failures": inject_failures or [],
            "provenance": "test",
        }
    )


def call(tool: str, turn: int = 0, error: str | None = None, injected: bool = False, **args: Any) -> ToolCall:
    status = "ok" if error is None else "injected_failure" if injected else "rejected"
    return ToolCall(turn=turn, tool=tool, args=args, status=status, error=error)


def run(
    *calls: ToolCall,
    final_state: dict[str, Any] | None = None,
    exposes: bool = True,
    error: str | None = None,
) -> RunRecord:
    return RunRecord(
        run_id="r1",
        case_id="test-case",
        adapter={"name": "hand", "version": "0", "config": {}},
        started_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        tool_calls=list(calls),
        final_state=final_state,
        exposes_tool_calls=exposes,
        execution_error=error,
    )


CANCEL_101 = {"tool": "cancel_order", "args": {"order_id": "ORD-101"}}
CANCEL_102 = {"tool": "cancel_order", "args": {"order_id": "ORD-102"}}
AMBIGUOUS = make_case(
    tags=["ambiguous_reference"],
    final_state={"orders.ORD-101.status": "cancelled", "orders.ORD-102.status": "placed"},
    required_actions=[CANCEL_101],
    forbidden_actions=[CANCEL_102],
    ask_before={"cancel_order": "confirm"},
)
ASK = call("ask_user", kind="confirm", question="Kurta वाला order cancel कर दूँ?")


def categories(case: TestCase, record: RunRecord) -> list[tuple[str, str]]:
    return [(c.category, c.confidence) for c in evaluate(case, record).classifications]


def test_final_state_check() -> None:
    assert check_final_state(AMBIGUOUS, run(final_state=orders("cancelled"))).verdict == "pass"
    wrong = check_final_state(AMBIGUOUS, run(final_state=orders("placed", "cancelled")))
    assert wrong.verdict == "fail"
    assert wrong.evidence == ["final_state.orders.ORD-101.status", "final_state.orders.ORD-102.status"]
    assert check_final_state(AMBIGUOUS, run(final_state={"orders": []})).verdict == "fail"
    assert check_final_state(AMBIGUOUS, run(final_state=None)).verdict == "inconclusive"


def test_required_actions_need_a_successful_superset_call() -> None:
    assert check_required_actions(AMBIGUOUS, run(call("cancel_order", order_id="ORD-101", reason="x"))).verdict == "pass"
    assert check_required_actions(AMBIGUOUS, run(call("cancel_order", order_id="ORD-102"))).verdict == "fail"
    errored = run(call("cancel_order", order_id="ORD-101", error="503", injected=True))
    assert check_required_actions(AMBIGUOUS, errored).verdict == "fail"


def test_forbidden_actions_empty_args_means_any_call_and_failed_attempts_count() -> None:
    case = make_case(forbidden_actions=[{"tool": "cancel_order"}])
    assert check_forbidden_actions(case, run(call("list_orders"))).verdict == "pass"
    hit = check_forbidden_actions(case, run(call("list_orders"), call("cancel_order", order_id="ORD-102")))
    assert hit.verdict == "fail" and hit.evidence == ["tool_calls[1]"]
    injected = check_forbidden_actions(case, run(call("cancel_order", order_id="ORD-102", error="503", injected=True)))
    assert injected.verdict == "fail" and injected.evidence == ["tool_calls[0]"]


def test_ask_policy_requires_matching_ask_in_an_earlier_turn() -> None:
    assert check_ask_policy(AMBIGUOUS, run(ASK, call("cancel_order", turn=1, order_id="ORD-101"))).verdict == "pass"
    assert check_ask_policy(AMBIGUOUS, run(ASK, call("cancel_order", turn=0, order_id="ORD-101"))).verdict == "fail"
    clarify = call("ask_user", kind="clarify", question="कौन सा?")
    assert check_ask_policy(AMBIGUOUS, run(clarify, call("cancel_order", turn=1, order_id="ORD-101"))).verdict == "fail"
    assert check_ask_policy(AMBIGUOUS, run(call("list_orders"))).verdict == "pass"


def test_correct_run_passes_without_classifications() -> None:
    result = evaluate(AMBIGUOUS, run(ASK, call("cancel_order", turn=1, order_id="ORD-101"), final_state=orders("cancelled")))
    assert result.verdict == "pass"
    assert {c.verdict for c in result.checks} == {"pass"}
    assert result.classifications == []


def test_execution_error_is_error_not_fail() -> None:
    result = evaluate(AMBIGUOUS, run(error="adapter crashed"))
    assert result.verdict == "error" and result.checks == []


def test_hidden_tool_calls_are_inconclusive_never_pass() -> None:
    result = evaluate(AMBIGUOUS, run(final_state=orders("cancelled"), exposes=False))
    assert result.verdict == "inconclusive"
    assert {c.metric: c.verdict for c in result.checks} == {
        "final_state": "pass",
        "required_actions": "inconclusive",
        "forbidden_actions": "inconclusive",
        "ask_policy": "inconclusive",
        "evidence": "inconclusive",
    }
    assert categories(AMBIGUOUS, run(final_state=orders("cancelled"), exposes=False)) == [("insufficient_evidence", "certain")]


def test_fail_beats_inconclusive() -> None:
    assert evaluate(AMBIGUOUS, run(call("cancel_order", order_id="ORD-102"), final_state=None)).verdict == "fail"


def test_wrong_order_is_entity_resolution() -> None:
    record = run(ASK, call("cancel_order", turn=1, order_id="ORD-102"), final_state=orders("placed", "cancelled"))
    assert categories(AMBIGUOUS, record) == [("entity_resolution", "likely")]


def test_missing_ask_depends_on_ambiguity_tags() -> None:
    record = run(call("cancel_order", order_id="ORD-101"), final_state=orders("cancelled"))
    assert categories(AMBIGUOUS, record) == [("ambiguity_handling", "likely")]
    plain = AMBIGUOUS.model_copy(update={"tags": []})
    assert categories(plain, record) == [("policy_violation", "certain")]


def test_missing_clarify_and_cancel_is_ambiguity_handling() -> None:
    case = make_case(
        tags=["missing_information"],
        final_state={"orders.ORD-101.status": "placed"},
        required_actions=[{"tool": "ask_user", "args": {"kind": "clarify"}}],
        forbidden_actions=[{"tool": "cancel_order"}],
    )
    assert categories(case, run(call("cancel_order", order_id="ORD-101"), final_state=orders("cancelled"))) == [
        ("ambiguity_handling", "likely")
    ]


def test_bulk_cancel_is_certain_policy_violation() -> None:
    case = make_case(final_state={"orders.ORD-101.status": "placed"}, forbidden_actions=[{"tool": "cancel_order"}])
    record = run(
        call("cancel_order", order_id="ORD-101"),
        call("cancel_order", order_id="ORD-102"),
        final_state=orders("cancelled", "cancelled"),
    )
    [cls] = evaluate(case, record).classifications
    assert (cls.category, cls.confidence, cls.evidence) == ("policy_violation", "certain", ["tool_calls[0]", "tool_calls[1]"])


def test_unrecovered_injected_failure_is_recovery_failure() -> None:
    case = make_case(
        inject_failures=[{"tool": "cancel_order", "call": 1, "error": "503"}],
        final_state={"orders.ORD-101.status": "cancelled"},
        required_actions=[CANCEL_101],
    )
    record = run(call("cancel_order", order_id="ORD-101", error="503", injected=True), final_state=orders())
    assert categories(case, record) == [("recovery_failure", "likely")]


def test_failed_retry_of_injected_failure_is_recovery_failure() -> None:
    case = make_case(
        inject_failures=[{"tool": "cancel_order", "call": 1, "error": "503"}, {"tool": "cancel_order", "call": 2, "error": "503"}],
        final_state={"orders.ORD-101.status": "cancelled"},
        required_actions=[CANCEL_101],
    )
    failed = call("cancel_order", order_id="ORD-101", error="503", injected=True)
    [cls] = evaluate(case, run(failed, failed, final_state=orders())).classifications
    assert (cls.category, cls.evidence) == ("recovery_failure", ["tool_calls[0]", "tool_calls[1]"])


def test_recovered_failure_with_unrelated_final_state_mismatch_is_state_transition() -> None:
    case = make_case(
        inject_failures=[{"tool": "cancel_order", "call": 1, "error": "503"}],
        final_state={"orders.ORD-101.status": "cancelled", "orders.ORD-102.status": "placed"},
        required_actions=[CANCEL_101],
    )
    record = run(
        call("cancel_order", order_id="ORD-101", error="503", injected=True),
        call("cancel_order", order_id="ORD-101"),
        final_state=orders("cancelled", "cancelled"),
    )
    assert categories(case, record) == [("state_transition", "likely")]


def test_wrong_tool_and_tool_errors() -> None:
    case = make_case(required_actions=[CANCEL_101])
    wrong_tool = run(call("update_quantity", order_id="ORD-101", quantity=1), final_state=orders())
    assert categories(case, wrong_tool) == [("tool_selection", "likely")]
    broken = run(call("cancel_order", error="bad arguments"), final_state=orders())
    assert categories(case, broken) == [("tool_execution", "likely")]


def test_correction_ignored_is_intent_interpretation() -> None:
    case = make_case(required_actions=[{"tool": "update_quantity", "args": {"order_id": "ORD-101", "quantity": 3}}])
    record = run(call("update_quantity", order_id="ORD-101", quantity=2), final_state=orders())
    assert categories(case, record) == [("intent_interpretation", "likely")]
