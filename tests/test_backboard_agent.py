import importlib.util
import json
import sys
import threading
import urllib.error
from collections.abc import Iterator
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from bolibench.models import AgentIdentity

EXAMPLES = Path(__file__).parent.parent / "examples"
sys.path.insert(0, str(EXAMPLES))  # backboard_agent imports ollama_agent, as when run as a script
SPEC = importlib.util.spec_from_file_location("backboard_agent", EXAMPLES / "backboard_agent.py")
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)  # defines functions only; nothing is contacted

KEY = "bb-test-key-not-real"
TOOLS = {"list_orders": [], "cancel_order": ["order_id"], "ask_user": ["kind", "question"]}


class Stub:
    """Scripted Backboard (/threads/...) plus a BoliBench tool gateway (/runs/t/tools) on one local port."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.requests: list[tuple[str, Message, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append((self.path, self.headers, body))
                reply = {"ok": True, "result": [], "error": None} if self.path == "/runs/t/tools" else stub.replies.pop(0)
                status = reply if isinstance(reply, int) else 200  # an int in the script is an HTTP error
                data = json.dumps({"detail": "stub error"} if isinstance(reply, int) else reply).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def paths(self) -> list[str]:
        return [path for path, _, _ in self.requests]


@pytest.fixture
def stub(request: pytest.FixtureRequest) -> Iterator[Stub]:
    s = Stub(request.param)
    yield s
    s.server.shutdown()
    s.server.server_close()


def tool_call(i: int, name: str, **args: Any) -> dict[str, Any]:
    return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def turn_req(stub: Stub, turn: int = 0, utterance: str = "kurta वाला order cancel कर दो") -> dict[str, Any]:
    return {"conversation": "c1", "turn": turn, "utterance": utterance, "context": {"today": "2026-10-17", "policy": None},
            "tools_url": f"{stub.url}/runs/t/tools", "tools": TOOLS}


# request fields of POST /threads/messages (application/json) in Backboard's OpenAPI, read 2026-10-18
MESSAGE_FIELDS = {"thread_id", "assistant_id", "content", "system_prompt", "llm_provider", "model_name", "stream", "tools", "memory",
                  "memory_pro", "web_search", "send_to_llm", "json_output", "thinking", "metadata", "custom_timestamp"}
ASK = {"kind": "confirm", "question": "Kurta वाला cancel कर दूँ?"}
CALLS = [tool_call(0, "list_orders"), tool_call(1, "ask_user", **ASK), tool_call(2, "cancel_order", order_id="ORD-1")]


@pytest.mark.parametrize(
    "stub", [[{"status": "REQUIRES_ACTION", "thread_id": "thr-1", "tool_calls": CALLS}, {"status": "COMPLETED", "thread_id": "thr-1", "content": "ok"}]],
    indirect=True,
)
def test_ask_user_ends_the_turn_and_later_calls_are_not_sent(stub: Stub) -> None:
    reply = agent.turn(turn_req(stub), agent.Backboard(KEY, "openrouter", "qwen/qwen3-8b", base=stub.url))
    assert reply == ASK["question"]
    assert stub.paths() == ["/threads/messages", "/runs/t/tools", "/runs/t/tools", "/threads/tool-outputs"]
    _, headers, message = stub.requests[0]
    assert headers["X-API-Key"] == KEY and headers["Content-Type"] == "application/json" and set(message) <= MESSAGE_FIELDS
    assert (message["llm_provider"], message["model_name"], message["memory"], "thread_id" in message) == ("openrouter", "qwen/qwen3-8b", "off", False)
    assert message["system_prompt"].endswith("Today's date is 2026-10-17.")
    assert [t["function"]["name"] for t in message["tools"]] == list(TOOLS)
    assert [body for path, _, body in stub.requests if path == "/runs/t/tools"] == [{"tool": "list_orders", "args": {}}, {"tool": "ask_user", "args": ASK}]
    outputs = stub.requests[3][2]
    assert set(outputs) == {"thread_id", "tool_outputs"}  # the schema has additionalProperties: false
    assert outputs["thread_id"] == "thr-1" and [o["tool_call_id"] for o in outputs["tool_outputs"]] == ["call_0", "call_1", "call_2"]
    assert all(set(o) == {"tool_call_id", "output"} and isinstance(o["output"], str) for o in outputs["tool_outputs"])
    assert json.loads(outputs["tool_outputs"][2]["output"]) == agent.NOT_SENT


@pytest.mark.parametrize(
    "stub", [[{"status": "COMPLETED", "thread_id": "thr-9", "content": "कौन सा order?"}, {"status": "COMPLETED", "thread_id": "thr-9", "content": "हो गया"}]],
    indirect=True,
)
def test_later_turns_continue_the_thread(stub: Stub) -> None:
    backboard = agent.Backboard(KEY, "openrouter", "m", base=stub.url)
    assert agent.turn(turn_req(stub), backboard) == "कौन सा order?"
    assert agent.turn(turn_req(stub, 1, "नीला वाला"), backboard) == "हो गया"
    assert stub.requests[1][2]["thread_id"] == "thr-9"


@pytest.mark.parametrize("stub", [[{"status": "FAILED", "thread_id": "thr-2", "error": "model unavailable"}]], indirect=True)
def test_a_failed_run_fails_the_turn(stub: Stub) -> None:
    with pytest.raises(RuntimeError, match="FAILED: model unavailable"):
        agent.turn(turn_req(stub), agent.Backboard(KEY, "openrouter", "m", base=stub.url))


@pytest.mark.parametrize("stub", [[401], [429], [502]], indirect=True)
def test_an_http_error_fails_the_turn_once_without_the_key(stub: Stub) -> None:
    with pytest.raises(urllib.error.HTTPError) as e:
        agent.turn(turn_req(stub), agent.Backboard(KEY, "openrouter", "m", base=stub.url))
    assert stub.paths() == ["/threads/messages"]  # no retry, no tool call
    assert KEY not in str(e.value) and KEY not in repr(e.value)


def test_identity_is_accepted_and_the_key_stays_out_of_reprs() -> None:
    AgentIdentity.model_validate(agent.identity("openrouter", "qwen/qwen3-235b-a22b-2507"))
    assert KEY not in repr(agent.Backboard(KEY, "openrouter", "m"))
