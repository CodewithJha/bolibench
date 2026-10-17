import importlib.util
from pathlib import Path
from typing import Any

SPEC = importlib.util.spec_from_file_location("ollama_agent", Path(__file__).parent.parent / "examples" / "ollama_agent.py")
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)  # defines functions only; nothing is contacted


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": args}}


def test_ask_user_ends_the_turn_and_drops_later_calls() -> None:
    ask = call("ask_user", kind="confirm", question="ORD-1 cancel कर दूँ?")
    assert agent.plan({"tool_calls": [call("list_orders"), ask, call("cancel_order", order_id="ORD-1")]}) == (
        [call("list_orders"), ask],
        "ORD-1 cancel कर दूँ?",
    )
    assert agent.plan({"tool_calls": [call("list_orders")]}) == ([call("list_orders")], None)
    assert agent.plan({"content": "हो गया"}) == ([], "हो गया")
