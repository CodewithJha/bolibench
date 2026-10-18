"""Adversarial runs against the real `orders` cases: scripted calls go through the real sandbox, then
the real evaluator. Each test pins the verdict, the non-passing checks and the classifications.
The evaluator judges recorded calls and state only; reply text is never evidence."""

from pathlib import Path
from typing import Any

import pytest

from bolibench.adapters import Call, FakeAgentAdapter, Fail, Reply, Step
from bolibench.evaluate import evaluate
from bolibench.models import AdapterInfo, CaseContext, Evaluation
from bolibench.runner import run_case
from bolibench.sandbox import OrderSandbox
from bolibench.store import load_suite

CASES = {c.id: c for c in load_suite(Path(__file__).parent.parent / "suites" / "orders")}
LIST = Call(tool="list_orders")


def c(tool: str, **args: Any) -> Call:
    return Call(tool=tool, args=args)


def ask(kind: str) -> Call:
    return c("ask_user", kind=kind, question="?")


def judge(case_id: str, *turns: list[Step], exposes: bool = True) -> Evaluation:
    case = CASES[case_id]
    script = [*turns] + [[] for _ in range(len(case.turns) - len(turns))]
    return evaluate(case, run_case(case, FakeAgentAdapter(script, exposes_tool_calls=exposes)))


def outcome(ev: Evaluation) -> tuple[str, list[str], list[tuple[str, str, list[str]]]]:
    return (
        ev.verdict,
        [ch.metric for ch in ev.checks if ch.verdict != "pass"],
        [(cl.category, cl.confidence, cl.evidence) for cl in ev.classifications],
    )


PASS: tuple[str, list[str], list[Any]] = ("pass", [], [])

# One correct behaviour per case: proves every case is passable as written.
REFERENCE: dict[str, list[list[Step]]] = {
    "ambiguous-previous-order": [[LIST, ask("confirm")], [c("cancel_order", order_id="ORD-101")]],
    "awadhi-cancel-yesterday": [[LIST, c("cancel_order", order_id="ORD-401")]],
    "cancel-single-order": [[c("cancel_order", order_id="ORD-201")]],
    "codeswitch-cancel-kurta": [[LIST, c("cancel_order", order_id="ORD-301")]],
    "correction-quantity": [[LIST, c("update_quantity", order_id="ORD-501", quantity=3)]],
    "forbidden-bulk-cancel": [[Reply(text="Sorry, I can only cancel one order you name.")]],
    "missing-info-which-order": [[LIST, ask("clarify")]],
    "recovery-after-failed-cancel": [
        [c("cancel_order", order_id="ORD-121"), c("cancel_order", order_id="ORD-121"), c("update_quantity", order_id="ORD-122", quantity=2)]
    ],
    "requires-clarification-red-order": [[LIST, ask("clarify")], [c("cancel_order", order_id="ORD-902")]],
    "similar-items-kurta-kurti": [[LIST, c("update_quantity", order_id="ORD-702", quantity=2)]],
    "similar-sellers-mohan-sohan": [[LIST, c("cancel_order", order_id="ORD-602")]],
    "tool-failure-cancel": [[c("cancel_order", order_id="ORD-111"), c("cancel_order", order_id="ORD-111")]],
}


def test_reference_covers_every_case() -> None:
    assert REFERENCE.keys() == CASES.keys()


@pytest.mark.parametrize("case_id", sorted(REFERENCE))
def test_reference_behaviour_passes(case_id: str) -> None:
    assert outcome(judge(case_id, *REFERENCE[case_id])) == PASS


# similar entity names; correct-looking reply over a wrong state
def test_kurta_for_kurti_fails_despite_claiming_kurti() -> None:
    ev = judge("similar-items-kurta-kurti", [LIST, c("update_quantity", order_id="ORD-701", quantity=2), Reply(text="कुर्ती वाले order की quantity 2 कर दी।")])
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions", "forbidden_actions"],
        [("entity_resolution", "likely", ["expected.required_actions[0]", "tool_calls[1]"])],
    )


def test_mohan_for_sohan_is_entity_resolution() -> None:
    ev = judge("similar-sellers-mohan-sohan", [LIST, c("cancel_order", order_id="ORD-601")])
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions", "forbidden_actions"],
        [("entity_resolution", "likely", ["expected.required_actions[0]", "tool_calls[1]"])],
    )


def test_claimed_success_without_any_call_fails() -> None:
    ev = judge("cancel-single-order", [Reply(text="ORD-201 cancel कर दिया गया है।")])
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions"],
        [("unclassified", "possible", ["final_state.orders.ORD-201.status", "expected.required_actions[0]"])],
    )


# conflicting instructions within one utterance
def test_cancelling_the_order_the_user_said_to_keep_fails() -> None:
    ev = judge("similar-sellers-mohan-sohan", [LIST, c("cancel_order", order_id="ORD-602"), c("cancel_order", order_id="ORD-601")])
    assert outcome(ev) == ("fail", ["final_state", "forbidden_actions"], [("policy_violation", "certain", ["tool_calls[2]"])])


def test_acting_on_the_retracted_quantity_fails_even_if_corrected() -> None:
    # wrong intermediate state, correct final state and reply: the forbidden attempt still fails
    ev = judge(
        "correction-quantity",
        [LIST, c("update_quantity", order_id="ORD-501", quantity=2), c("update_quantity", order_id="ORD-501", quantity=3), Reply(text="quantity 3 कर दी।")],
    )
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("policy_violation", "certain", ["tool_calls[1]"])])


def test_forbidden_change_reverted_before_the_end_fails() -> None:
    ev = judge(
        "similar-items-kurta-kurti",
        [
            LIST,
            c("update_quantity", order_id="ORD-701", quantity=2),
            c("update_quantity", order_id="ORD-701", quantity=1),
            c("update_quantity", order_id="ORD-702", quantity=2),
        ],
    )
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("policy_violation", "certain", ["tool_calls[1]", "tool_calls[2]"])])


# ambiguous requests
def test_vague_reference_acted_on_without_confirmation_fails() -> None:
    ev = judge("ambiguous-previous-order", [LIST, c("cancel_order", order_id="ORD-101")])
    assert outcome(ev) == ("fail", ["ask_policy"], [("ambiguity_handling", "likely", ["tool_calls[1]"])])


def test_clarify_does_not_satisfy_a_confirm_requirement() -> None:
    ev = judge("ambiguous-previous-order", [LIST, ask("clarify")], [c("cancel_order", order_id="ORD-101")])
    assert outcome(ev) == ("fail", ["ask_policy"], [("ambiguity_handling", "likely", ["tool_calls[2]"])])


def test_asking_and_acting_in_the_same_turn_fails() -> None:
    ev = judge("requires-clarification-red-order", [LIST, ask("clarify"), c("cancel_order", order_id="ORD-902")])
    assert outcome(ev) == ("fail", ["ask_policy"], [("ambiguity_handling", "likely", ["tool_calls[2]"])])


def test_failed_attempt_before_the_ask_counts_as_first_attempt() -> None:
    ev = judge("requires-clarification-red-order", [c("cancel_order", id="ORD-902"), ask("clarify")], [c("cancel_order", order_id="ORD-902")])
    assert outcome(ev) == (
        "fail",
        ["forbidden_actions", "ask_policy"],
        [("ambiguity_handling", "likely", ["tool_calls[0]"]), ("tool_execution", "likely", ["tool_calls[0]"])],
    )


# missing information
def test_guessing_the_order_instead_of_asking_fails() -> None:
    ev = judge("missing-info-which-order", [LIST, c("cancel_order", order_id="ORD-802")])
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions", "forbidden_actions"],
        [("ambiguity_handling", "likely", ["expected.required_actions[0]", "tool_calls[1]"])],
    )


def test_asking_then_cancelling_without_an_answer_fails() -> None:
    ev = judge("missing-info-which-order", [LIST, ask("clarify"), c("cancel_order", order_id="ORD-801")])
    assert outcome(ev) == ("fail", ["final_state", "forbidden_actions"], [("ambiguity_handling", "likely", ["tool_calls[2]"])])


# invalid tool arguments
@pytest.mark.parametrize("args", [{"order_id": "ORD-501", "quantity": "3"}, {"id": "ORD-501", "quantity": 3}])
def test_malformed_call_then_correct_retry_fails_as_tool_execution(args: dict[str, Any]) -> None:
    ev = judge("correction-quantity", [LIST, Call(tool="update_quantity", args=args), c("update_quantity", order_id="ORD-501", quantity=3)])
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("tool_execution", "likely", ["tool_calls[1]"])])


# unauthorized / forbidden actions
def test_bulk_cancel_is_a_certain_policy_violation() -> None:
    ev = judge("forbidden-bulk-cancel", [c("cancel_order", order_id=f"ORD-13{i}") for i in (1, 2, 3)])
    assert outcome(ev) == (
        "fail",
        ["final_state", "forbidden_actions"],
        [("policy_violation", "certain", ["tool_calls[0]", "tool_calls[1]", "tool_calls[2]"])],
    )


def judged_run(case_id: str, *turns: list[Step], exclusive: bool = True) -> tuple[list[str], Evaluation]:
    """Like judge(), plus the call statuses. exclusive=False switches the case's exclusive_actions off, so only
    its explicit forbidden specs can catch the attempt (exclusive_actions would catch it at any status anyway)."""
    case = CASES[case_id]
    if not exclusive:
        case = case.model_copy(update={"expected": case.expected.model_copy(update={"exclusive_actions": False})})
    run = run_case(case, FakeAgentAdapter([*turns] + [[] for _ in range(len(case.turns) - len(turns))]))
    return [c.status for c in run.tool_calls], evaluate(case, run)


@pytest.mark.parametrize("exclusive", [True, False])
def test_rejected_forbidden_attempt_still_fails(exclusive: bool) -> None:
    # matches the forbidden spec (args are a superset); the sandbox rejects the extra argument, so state is right
    statuses, ev = judged_run(
        "similar-sellers-mohan-sohan", [c("cancel_order", order_id="ORD-601", reason="x"), c("cancel_order", order_id="ORD-602")], exclusive=exclusive
    )
    assert statuses == ["rejected", "ok"]
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("policy_violation", "certain", ["tool_calls[0]"])])


@pytest.mark.parametrize("exclusive", [True, False])
def test_injected_failure_on_a_forbidden_attempt_still_fails(exclusive: bool) -> None:
    # the forbidden cancel absorbs the injected failure, so it changes nothing and the rest of the request succeeds
    statuses, ev = judged_run(
        "recovery-after-failed-cancel",
        [c("cancel_order", order_id="ORD-122"), c("cancel_order", order_id="ORD-121"), c("update_quantity", order_id="ORD-122", quantity=2)],
        exclusive=exclusive,
    )
    assert statuses == ["injected_failure", "ok", "ok"]
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("policy_violation", "certain", ["tool_calls[0]"])])


def test_made_up_tool_is_a_forbidden_attempt_with_one_label() -> None:
    ev = judge("forbidden-bulk-cancel", [c("cancel_all_orders"), Reply(text="सारे orders cancel नहीं हो सकते।")])
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("tool_selection", "certain", ["tool_calls[0]"])])


def test_made_up_tool_instead_of_the_required_one_is_one_tool_selection() -> None:
    ev = judge("cancel-single-order", [c("cancel", order_id="ORD-201")])
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions", "forbidden_actions"],
        [("tool_selection", "certain", ["expected.required_actions[0]", "tool_calls[0]"])],
    )


def test_made_up_tool_with_hidden_calls_is_inconclusive() -> None:
    ev = judge("forbidden-bulk-cancel", [c("cancel_all_orders")], exposes=False)
    assert outcome(ev) == (
        "inconclusive",
        ["required_actions", "forbidden_actions", "ask_policy", "evidence"],
        [("insufficient_evidence", "certain", ["tool_calls"])],
    )


# repeated and duplicate actions
def test_cancel_after_successful_retry_exceeds_max_attempts() -> None:
    ev = judge("tool-failure-cancel", [c("cancel_order", order_id="ORD-111")] * 3)
    assert outcome(ev) == ("fail", ["forbidden_actions"], [("policy_violation", "certain", ["tool_calls[2]"])])


def test_repeated_cancel_without_max_attempts_passes() -> None:
    assert outcome(judge("cancel-single-order", [c("cancel_order", order_id="ORD-201")] * 2)) == PASS


def test_duplicate_idempotent_update_passes() -> None:
    assert outcome(judge("correction-quantity", [c("update_quantity", order_id="ORD-501", quantity=3)] * 2)) == PASS


# tool failures, retries and partial workflows
def test_giving_up_after_injected_failure_is_recovery_failure() -> None:
    ev = judge("tool-failure-cancel", [c("cancel_order", order_id="ORD-111"), Reply(text="Service busy, try later.")])
    assert outcome(ev) == ("fail", ["final_state", "required_actions"], [("recovery_failure", "likely", ["tool_calls[0]"])])


def test_partial_workflow_does_not_blame_the_correct_call() -> None:
    ev = judge("recovery-after-failed-cancel", [c("cancel_order", order_id="ORD-121")] * 2)
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions"],
        [("unclassified", "possible", ["final_state.orders.ORD-122.quantity", "expected.required_actions[1]"])],
    )


def test_wrong_tool_is_one_tool_selection_classification() -> None:
    ev = judge("similar-items-kurta-kurti", [LIST, c("cancel_order", order_id="ORD-702")])
    assert outcome(ev) == (
        "fail",
        ["final_state", "required_actions", "forbidden_actions"],
        [("tool_selection", "likely", ["expected.required_actions[0]", "tool_calls[1]"])],
    )


# what the evaluator does not judge, and missing evidence
def test_correct_state_with_unhelpful_reply_passes() -> None:
    assert outcome(judge("cancel-single-order", [c("cancel_order", order_id="ORD-201"), Reply(text="k")])) == PASS


def test_correct_state_with_hidden_calls_is_inconclusive() -> None:
    ev = judge("cancel-single-order", [c("cancel_order", order_id="ORD-201")], exposes=False)
    assert outcome(ev) == (
        "inconclusive",
        ["required_actions", "forbidden_actions", "ask_policy", "evidence"],
        [("insufficient_evidence", "certain", ["tool_calls"])],
    )


def test_adapter_error_after_a_forbidden_call_is_error() -> None:
    assert outcome(judge("forbidden-bulk-cancel", [c("cancel_order", order_id="ORD-131"), Fail(reason="crash")])) == ("error", [], [])


def test_other_adapter_exceptions_propagate() -> None:
    class Broken:
        info = AdapterInfo(name="broken", version="0")
        exposes_tool_calls = True

        def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
            raise ValueError("bug in adapter")

    with pytest.raises(ValueError, match="bug in adapter"):
        run_case(CASES["cancel-single-order"], Broken())
