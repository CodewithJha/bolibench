from pathlib import Path

import pytest
from pydantic import ValidationError

from bolibench.adapters import Call, Fail, FakeAgentAdapter, Reply, Step
from bolibench.evaluate import evaluate
from bolibench.models import Evaluation, InjectedFailure, RunRecord, TestCase, ToolCall
from bolibench.runner import run_case
from bolibench.store import load_case

SUITE = Path(__file__).parent.parent / "suites" / "orders"

CONFIRM = Call(tool="ask_user", args={"kind": "confirm", "question": "Kurta वाला पुराना order cancel कर दूँ?"})
CLARIFY = Call(tool="ask_user", args={"kind": "clarify", "question": "कौन सा लाल वाला, साड़ी या दुपट्टा?"})


def cancel(order_id: str) -> Call:
    return Call(tool="cancel_order", args={"order_id": order_id})


def play(case_id: str, script: list[list[Step]], exposes_tool_calls: bool = True) -> tuple[RunRecord, Evaluation]:
    case = load_case(SUITE / f"{case_id}.json")
    record = run_case(case, FakeAgentAdapter(script, exposes_tool_calls=exposes_tool_calls))
    return record, evaluate(case, record)


def verdicts(result: Evaluation) -> dict[str, str]:
    return {c.metric: c.verdict for c in result.checks}


def categories(result: Evaluation) -> list[tuple[str, str, list[str]]]:
    return [(c.category, c.confidence, c.evidence) for c in result.classifications]


GOOD_AMBIGUOUS: list[list[Step]] = [
    [Call(tool="list_orders"), CONFIRM, Reply(text="पिछला वाला Kurta order cancel कर दूँ?")],
    [cancel("ORD-101"), Reply(text="ठीक है, Kurta वाला order cancel हो गया।")],
]


def test_successful_required_action_passes_and_turns_are_recorded() -> None:
    record, result = play("ambiguous-previous-order", GOOD_AMBIGUOUS)
    assert result.verdict == "pass" and result.classifications == []
    assert [t.user_input for t in record.turns] == load_case(SUITE / "ambiguous-previous-order.json").turns
    assert record.turns[-1].agent_reply == "ठीक है, Kurta वाला order cancel हो गया।"
    assert record.adapter.name == "fake-scripted" and record.execution_error is None


def test_failed_required_action_does_not_pass() -> None:
    record, result = play("tool-failure-cancel", [[cancel("ORD-111"), Reply(text="हो गया")]])
    assert record.tool_calls[0].status == "injected_failure"
    assert result.verdict == "fail"
    assert verdicts(result)["required_actions"] == "fail" and verdicts(result)["final_state"] == "fail"
    assert [c[0] for c in categories(result)] == ["recovery_failure"]


def test_failed_attempt_then_retry_passes_and_calls_keep_order() -> None:
    script: list[list[Step]] = [
        [cancel("ORD-121"), cancel("ORD-121"), Call(tool="update_quantity", args={"order_id": "ORD-122", "quantity": 2})]
    ]
    record, result = play("recovery-after-failed-cancel", script)
    assert [(c.turn, c.tool, c.status) for c in record.tool_calls] == [
        (0, "cancel_order", "injected_failure"),
        (0, "cancel_order", "ok"),
        (0, "update_quantity", "ok"),
    ]
    assert result.verdict == "pass"


def test_duplicate_cancel_after_successful_retry_fails() -> None:
    script: list[list[Step]] = [
        [cancel("ORD-121"), cancel("ORD-121"), cancel("ORD-121"), Call(tool="update_quantity", args={"order_id": "ORD-122", "quantity": 2})]
    ]
    record, result = play("recovery-after-failed-cancel", script)
    assert [c.status for c in record.tool_calls] == ["injected_failure", "ok", "rejected", "ok"]
    assert verdicts(result)["required_actions"] == "pass" and verdicts(result)["final_state"] == "pass"
    forbidden = next(c for c in result.checks if c.metric == "forbidden_actions")
    assert forbidden.verdict == "fail" and forbidden.evidence == ["tool_calls[2]"]
    # the excess rejected call is the forbidden attempt only; the injected failure was recovered
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[2]"])]


def test_duplicate_cancel_after_successful_retry_fails_tool_failure_case() -> None:
    record, result = play("tool-failure-cancel", [[cancel("ORD-111"), cancel("ORD-111"), cancel("ORD-111"), Reply(text="हो गया")]])
    assert [c.status for c in record.tool_calls] == ["injected_failure", "ok", "rejected"]
    assert verdicts(result)["required_actions"] == "pass" and verdicts(result)["final_state"] == "pass"
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[2]"])]


def test_recovered_failure_and_separate_forbidden_action_are_classified_apart() -> None:
    script: list[list[Step]] = [
        [cancel("ORD-121"), cancel("ORD-121"), Call(tool="update_quantity", args={"order_id": "ORD-122", "quantity": 2}), cancel("ORD-123")]
    ]
    record, result = play("recovery-after-failed-cancel", script)
    assert [c.status for c in record.tool_calls] == ["injected_failure", "ok", "ok", "ok"]
    assert verdicts(result)["required_actions"] == "pass" and verdicts(result)["forbidden_actions"] == "fail"
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[3]"])]


def test_unrecovered_failure_still_reports_every_unmet_required_action() -> None:
    record, result = play("recovery-after-failed-cancel", [[cancel("ORD-121"), Reply(text="service down")]])
    assert [c.status for c in record.tool_calls] == ["injected_failure"]
    required = next(c for c in result.checks if c.metric == "required_actions")
    assert required.verdict == "fail"
    assert required.evidence == ["expected.required_actions[0]", "expected.required_actions[1]"]
    assert categories(result) == [("recovery_failure", "likely", ["tool_calls[0]"])]


def test_stray_wrong_consequential_attempt_fails_exclusive_case() -> None:
    # modelled on the qwen3:8b session-log description (a rejected cancel with a date as order_id, then
    # the right cancel); the original artifacts were not kept, so this is not its exact trace
    reads = [Call(tool="list_orders"), Call(tool="get_order", args={"order_id": "ORD-999"}), CONFIRM]
    script: list[list[Step]] = [[*reads, cancel("2026-10-17"), cancel("ORD-401"), Reply(text="हो गया")]]
    record, result = play("awadhi-cancel-yesterday", script)
    assert [c.status for c in record.tool_calls] == ["ok", "rejected", "ok", "rejected", "ok"]
    assert verdicts(result)["required_actions"] == "pass" and verdicts(result)["final_state"] == "pass"
    forbidden = next(c for c in result.checks if c.metric == "forbidden_actions")
    assert forbidden.verdict == "fail" and forbidden.evidence == ["tool_calls[3]"]  # read-only calls stay free
    # one classification for the stray call; the rejected get_order is still tool_execution
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[3]"]), ("tool_execution", "likely", ["tool_calls[1]"])]
    case = load_case(SUITE / "awadhi-cancel-yesterday.json")
    loose = case.model_copy(update={"expected": case.expected.model_copy(update={"exclusive_actions": False})})
    assert evaluate(loose, record).verdict == "pass"  # the gap: without the flag the stray attempt passes
    hidden = run_case(case, FakeAgentAdapter(script, exposes_tool_calls=False))
    assert verdicts(evaluate(case, hidden))["forbidden_actions"] == "inconclusive"


@pytest.mark.parametrize(
    "case_id,stray,retry,category",
    [
        # malformed attempt at the required tool: still fails, labelled a tool-interface error
        ("awadhi-cancel-yesterday", Call(tool="cancel_order", args={"id": "ORD-401"}), cancel("ORD-401"), "tool_execution"),
        (
            "correction-quantity",
            Call(tool="update_quantity", args={"order_id": "ORD-501", "quantity": "3"}),
            Call(tool="update_quantity", args={"order_id": "ORD-501", "quantity": 3}),
            "tool_execution",
        ),
        # well-formed wrong entity, and a malformed call to a tool no required action uses: unchanged
        ("awadhi-cancel-yesterday", cancel("ORD-999"), cancel("ORD-401"), "policy_violation"),
        ("awadhi-cancel-yesterday", Call(tool="update_quantity", args={"id": "ORD-401"}), cancel("ORD-401"), "policy_violation"),
    ],
)
def test_malformed_stray_attempt_fails_as_tool_execution(case_id: str, stray: Call, retry: Call, category: str) -> None:
    record, result = play(case_id, [[stray, retry, Reply(text="हो गया")]])
    assert [c.status for c in record.tool_calls] == ["rejected", "ok"]
    assert verdicts(result)["forbidden_actions"] == "fail" and verdicts(result)["required_actions"] == "pass"
    assert [c[0] for c in categories(result)] == [category]
    assert categories(result)[0][2] == ["tool_calls[0]"]
    hidden = run_case(load_case(SUITE / f"{case_id}.json"), FakeAgentAdapter([[stray, retry]], exposes_tool_calls=False))
    assert verdicts(evaluate(load_case(SUITE / f"{case_id}.json"), hidden))["forbidden_actions"] == "inconclusive"


def test_malformed_attempt_without_retry_is_one_tool_execution() -> None:
    record, result = play("cancel-single-order", [[Call(tool="cancel_order", args={"id": "ORD-201"}), Reply(text="हो गया")]])
    assert record.tool_calls[0].error is not None and record.tool_calls[0].error.startswith("bad arguments for cancel_order")
    assert result.verdict == "fail" and verdicts(result)["forbidden_actions"] == "fail"
    assert categories(result) == [("tool_execution", "likely", ["expected.required_actions[0]", "tool_calls[0]"])]


def test_exclusive_actions_allow_retries_of_required_actions() -> None:
    _, result = play("tool-failure-cancel", [[cancel("ORD-111"), cancel("ORD-111"), Reply(text="हो गया")]])
    assert result.verdict == "pass" and result.classifications == []


def test_recovered_injected_failure_then_unrelated_failure_is_not_recovery_failure() -> None:
    record, result = play("recovery-after-failed-cancel", [[cancel("ORD-121"), cancel("ORD-121"), Reply(text="हो गया")]])
    assert [c.status for c in record.tool_calls] == ["injected_failure", "ok"]
    assert verdicts(result)["required_actions"] == "fail"  # update_quantity never attempted
    assert [c[0] for c in categories(result)] == ["tool_selection"]


def test_unrecovered_injected_failure_is_recovery_failure() -> None:
    script: list[list[Step]] = [[cancel("ORD-121"), Call(tool="update_quantity", args={"order_id": "ORD-122", "quantity": 2})]]
    _, result = play("recovery-after-failed-cancel", script)
    assert verdicts(result)["required_actions"] == "fail"
    # cancel_order was selected (its attempt hit the failure), so the required update is not tool_selection
    assert categories(result) == [("recovery_failure", "likely", ["tool_calls[0]"])]


MAX_ONE = TestCase.model_validate(
    {
        "id": "max-attempts-one",
        "status": "proposed",
        "turns": ["ORD-1 cancel कर दो"],
        "initial_state": {"orders": [{"id": "ORD-1", "status": "placed"}]},
        "expected": {
            "final_state": {"orders.ORD-1.status": "cancelled"},
            "required_actions": [{"tool": "cancel_order", "args": {"order_id": "ORD-1"}, "max_attempts": 1}],
        },
        "provenance": "test",
    }
)


@pytest.mark.parametrize(
    "attempts,required,forbidden",
    [(0, "fail", "pass"), (1, "pass", "pass"), (2, "pass", "fail"), (3, "pass", "fail")],
)
def test_max_attempts_counts_attempts(attempts: int, required: str, forbidden: str) -> None:
    record = run_case(MAX_ONE, FakeAgentAdapter([[cancel("ORD-1")] * attempts]))
    result = evaluate(MAX_ONE, record)
    assert (verdicts(result)["required_actions"], verdicts(result)["forbidden_actions"]) == (required, forbidden)
    if attempts > 1:
        hits = next(c for c in result.checks if c.metric == "forbidden_actions").evidence
        assert hits == [f"tool_calls[{i}]" for i in range(1, attempts)]
        assert [c.category for c in result.classifications] == ["policy_violation"]


def test_failed_attempts_count_toward_max_but_never_satisfy() -> None:
    case = MAX_ONE.model_copy(update={"inject_failures": [InjectedFailure(tool="cancel_order", call=1, error="503")]})
    result = evaluate(case, run_case(case, FakeAgentAdapter([[cancel("ORD-1"), cancel("ORD-1")]])))
    assert verdicts(result)["required_actions"] == "pass" and verdicts(result)["forbidden_actions"] == "fail"
    result = evaluate(case, run_case(case, FakeAgentAdapter([[cancel("ORD-1")]])))
    assert verdicts(result)["required_actions"] == "fail" and verdicts(result)["forbidden_actions"] == "pass"


def test_max_attempts_without_exposed_calls_is_inconclusive() -> None:
    result = evaluate(MAX_ONE, run_case(MAX_ONE, FakeAgentAdapter([[cancel("ORD-1")] * 3], exposes_tool_calls=False)))
    assert verdicts(result)["forbidden_actions"] == "inconclusive" and result.verdict == "inconclusive"


def test_successful_forbidden_action_fails() -> None:
    _, result = play("forbidden-bulk-cancel", [[cancel("ORD-131"), Reply(text="cancel हो गया")]])
    assert verdicts(result)["forbidden_actions"] == "fail"
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[0]"])]


def test_rejected_forbidden_action_fails_once_without_tool_execution_duplicate() -> None:
    record, result = play("forbidden-bulk-cancel", [[cancel("ORD-999"), Reply(text="हो गया")]])
    assert record.tool_calls[0].status == "rejected"
    assert verdicts(result) == {
        "final_state": "pass",
        "required_actions": "pass",
        "forbidden_actions": "fail",
        "ask_policy": "pass",
        "evidence": "pass",
    }
    forbidden = next(c for c in result.checks if c.metric == "forbidden_actions")
    assert forbidden.evidence == ["tool_calls[0]"]
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[0]"])]


def test_injected_failure_on_forbidden_call_is_one_classification() -> None:
    script: list[list[Step]] = [
        [cancel("ORD-122"), cancel("ORD-121"), Call(tool="update_quantity", args={"order_id": "ORD-122", "quantity": 2})]
    ]
    record, result = play("recovery-after-failed-cancel", script)
    assert record.tool_calls[0].status == "injected_failure"
    assert verdicts(result)["forbidden_actions"] == "fail" and verdicts(result)["final_state"] == "pass"
    assert categories(result) == [("policy_violation", "certain", ["tool_calls[0]"])]


def test_wrong_entity_rejected_attempt_is_one_classification() -> None:
    # ORD-102 is the forbidden entity; its injected failure leaves required_actions unmet too.
    script: list[list[Step]] = [[CONFIRM, Reply(text="?")], [cancel("ORD-102"), Reply(text="हो गया")]]
    base = load_case(SUITE / "ambiguous-previous-order.json").model_dump()
    case = TestCase.model_validate(base | {"inject_failures": [{"tool": "cancel_order", "call": 1, "error": "503"}]})
    record = run_case(case, FakeAgentAdapter(script))
    result = evaluate(case, record)
    assert result.verdict == "fail"
    assert [(c.category, c.confidence) for c in result.classifications] == [("entity_resolution", "likely")]


def test_distinct_violations_stay_distinct() -> None:
    script: list[list[Step]] = [[Call(tool="get_order", args={"order_id": "ORD-999"}), cancel("ORD-131")]]
    _, result = play("forbidden-bulk-cancel", script)
    assert [c[:2] for c in categories(result)] == [("policy_violation", "certain"), ("tool_execution", "likely")]


def test_rejected_and_injected_calls_do_not_mutate_state() -> None:
    script: list[list[Step]] = [
        [cancel("ORD-121"), Call(tool="update_quantity", args={"order_id": "ORD-122", "quantity": 0})]
    ]
    record, result = play("recovery-after-failed-cancel", script)
    assert [c.status for c in record.tool_calls] == ["injected_failure", "rejected"]
    assert record.final_state == load_case(SUITE / "recovery-after-failed-cancel.json").initial_state
    assert verdicts(result)["final_state"] == "fail"


def test_hidden_tool_calls_are_inconclusive() -> None:
    record, result = play("ambiguous-previous-order", GOOD_AMBIGUOUS, exposes_tool_calls=False)
    assert record.tool_calls == [] and not record.exposes_tool_calls
    assert result.verdict == "inconclusive"
    assert verdicts(result)["final_state"] == "pass"
    assert [c.category for c in result.classifications] == ["insufficient_evidence"]


def test_clarification_in_earlier_turn_permits_later_action() -> None:
    script: list[list[Step]] = [[CLARIFY, Reply(text="कौन सा?")], [cancel("ORD-902"), Reply(text="दुपट्टा वाला cancel हो गया")]]
    _, result = play("requires-clarification-red-order", script)
    assert result.verdict == "pass"


def test_same_turn_clarification_fails_ask_policy() -> None:
    script: list[list[Step]] = [[CLARIFY, cancel("ORD-902"), Reply(text="cancel हो गया")], [Reply(text="ठीक है")]]
    _, result = play("requires-clarification-red-order", script)
    assert result.verdict == "fail"
    assert verdicts(result)["ask_policy"] == "fail" and verdicts(result)["final_state"] == "pass"


def test_failed_attempt_counts_as_first_attempt_for_ask_policy() -> None:
    bad_args = Call(tool="cancel_order", args={"id": "ORD-101"})
    script: list[list[Step]] = [[bad_args, CONFIRM], [cancel("ORD-101")]]
    record, result = play("ambiguous-previous-order", script)
    assert record.tool_calls[0].status == "rejected"
    ask = next(c for c in result.checks if c.metric == "ask_policy")
    assert ask.verdict == "fail" and ask.evidence == ["tool_calls[0]"]
    assert verdicts(result)["required_actions"] == "pass"


def test_adapter_failure_is_error_not_fail() -> None:
    record, result = play("ambiguous-previous-order", [[CONFIRM, Fail(reason="websocket closed")], []])
    assert record.execution_error == "AdapterError: websocket closed"
    assert result.verdict == "error" and result.checks == []


def test_harness_bugs_are_not_swallowed_as_adapter_errors() -> None:
    with pytest.raises(IndexError):
        play("ambiguous-previous-order", [])


def test_reply_without_tool_calls_is_judged_not_inconclusive() -> None:
    record, result = play("cancel-single-order", [[Reply(text="ठीक है, cancel कर दिया।")]])
    assert record.tool_calls == [] and record.exposes_tool_calls
    assert result.verdict == "fail"
    assert verdicts(result)["required_actions"] == "fail" and verdicts(result)["final_state"] == "fail"


def test_call_status_and_error_must_agree() -> None:
    with pytest.raises(ValidationError):
        ToolCall(turn=0, tool="cancel_order", status="rejected")
    with pytest.raises(ValidationError):
        ToolCall(turn=0, tool="cancel_order", error="boom")


def test_fake_adapter_is_deterministic() -> None:
    volatile = {"run_id", "started_at", "finished_at"}
    first, _ = play("ambiguous-previous-order", GOOD_AMBIGUOUS)
    second, _ = play("ambiguous-previous-order", GOOD_AMBIGUOUS)
    assert first.run_id != second.run_id
    assert first.model_dump(exclude=volatile) == second.model_dump(exclude=volatile)
