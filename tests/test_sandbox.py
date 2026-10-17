import pytest

from bolibench.models import InjectedFailure, RefusedRequest
from bolibench.sandbox import OrderSandbox


def initial() -> dict:
    return {
        "orders": [
            {"id": "ORD-1", "item": "Kurta", "quantity": 1, "status": "placed"},
            {"id": "ORD-2", "item": "Kurti", "quantity": 1, "status": "placed"},
        ]
    }


def test_calls_are_recorded_with_results() -> None:
    sb = OrderSandbox(initial())
    sb.call("list_orders", 0)
    sb.call("ask_user", 0, kind="confirm", question="Kurta वाला cancel कर दूँ?")
    sb.call("cancel_order", 1, order_id="ORD-1")

    assert [(c.turn, c.tool, c.error, c.status) for c in sb.tool_calls] == [
        (0, "list_orders", None, "ok"),
        (0, "ask_user", None, "ok"),
        (1, "cancel_order", None, "ok"),
    ]
    assert len(sb.tool_calls[0].result) == 2
    assert sb.tool_calls[1].args == {"kind": "confirm", "question": "Kurta वाला cancel कर दूँ?"}
    assert sb.tool_calls[2].result["status"] == "cancelled"
    assert sb.state["orders"][0]["status"] == "cancelled"


def test_invalid_operations_are_recorded_errors() -> None:
    sb = OrderSandbox(initial())
    sb.call("cancel_order", 0, order_id="ORD-1")
    bad = [
        sb.call("delete_everything", 0),
        sb.call("get_order", 0, order_id="ORD-9"),
        sb.call("cancel_order", 0, order_id="ORD-1"),
        sb.call("cancel_order", 0),
        sb.call("update_quantity", 0, order_id="ORD-2", quantity=0),
        sb.call("update_quantity", 0, order_id="ORD-1", quantity=2),
        sb.call("ask_user", 0, kind="maybe", question="?"),
    ]
    assert all(c.error and c.result is None and c.status == "rejected" for c in bad)
    assert len(sb.tool_calls) == 8
    assert sb.state["orders"] == [
        {"id": "ORD-1", "item": "Kurta", "quantity": 1, "status": "cancelled"},
        {"id": "ORD-2", "item": "Kurti", "quantity": 1, "status": "placed"},
    ]


def test_injected_failure_hits_nth_call_and_leaves_state_unchanged() -> None:
    sb = OrderSandbox(initial(), [InjectedFailure(tool="cancel_order", call=2, error="503 busy")])
    first = sb.call("cancel_order", 0, order_id="ORD-1")
    second = sb.call("cancel_order", 0, order_id="ORD-2")
    assert first.error is None and first.status == "ok"
    assert second.error == "503 busy" and second.status == "injected_failure" and second.result is None
    assert sb.state["orders"][1]["status"] == "placed"

    third = sb.call("cancel_order", 1, order_id="ORD-2")
    assert third.error is None
    assert sb.state["orders"][1]["status"] == "cancelled"


def test_initial_state_and_results_are_not_aliased() -> None:
    state = initial()
    sb = OrderSandbox(state)
    sb.call("get_order", 0, order_id="ORD-1").result["status"] = "tampered"
    sb.call("cancel_order", 0, order_id="ORD-2")
    sb.state["orders"].clear()

    assert state == initial()
    assert [o["status"] for o in sb.state["orders"]] == ["placed", "cancelled"]


def test_closed_sandbox_refuses_calls_and_late_refusals() -> None:
    sb = OrderSandbox(initial())
    assert sb.refuse(RefusedRequest(status=409, reason="stale")) is True
    assert sb.close() == [RefusedRequest(status=409, reason="stale")]
    assert sb.refuse(RefusedRequest(status=409, reason="late")) is False and len(sb.refused) == 1
    with pytest.raises(RuntimeError, match="closed"):
        sb.call("cancel_order", 0, order_id="ORD-1")
    assert sb.tool_calls == [] and sb.state == initial()
