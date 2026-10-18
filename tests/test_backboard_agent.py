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
ASSISTANT = "0ae0bcca-0000-4000-8000-000000000000"
TOOLS = {"list_orders": [], "cancel_order": ["order_id"], "ask_user": ["kind", "question"]}


class Stub:
    """Scripted Backboard (/threads/...) plus a BoliBench tool gateway (/runs/t/tools) on one local port."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.requests: list[tuple[str, Message, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                stub.requests.append((self.path, self.headers, None))
                self.reply(stub.replies.pop(0))

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append((self.path, self.headers, body))
                self.reply({"ok": True, "result": [], "error": None} if self.path == "/runs/t/tools" else stub.replies.pop(0))

            def reply(self, reply: Any) -> None:
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
    "stub", [[{"status": "REQUIRES_ACTION", "thread_id": "thr-1", "run_id": "run-1", "tool_calls": CALLS},
              {"status": "COMPLETED", "thread_id": "thr-1", "run_id": "run-1", "content": "ok"}]],
    indirect=True,
)
def test_ask_user_ends_the_turn_and_later_calls_are_not_sent(stub: Stub) -> None:
    reply = agent.turn(turn_req(stub), agent.Backboard(KEY, ASSISTANT, "openrouter", "qwen/qwen3-8b", base=stub.url))
    assert reply == ASK["question"]
    assert stub.paths() == ["/threads/messages", "/runs/t/tools", "/runs/t/tools", "/threads/thr-1/runs/run-1/submit-tool-outputs"]
    _, headers, message = stub.requests[0]
    assert headers["X-API-Key"] == KEY and headers["Content-Type"] == "application/json" and set(message) <= MESSAGE_FIELDS
    assert (message["llm_provider"], message["model_name"], message["memory"], "thread_id" in message) == ("openrouter", "qwen/qwen3-8b", "off", False)
    assert message["assistant_id"] == ASSISTANT  # never the account's first assistant
    assert message["system_prompt"].endswith("Today's date is 2026-10-17.")
    assert [t["function"]["name"] for t in message["tools"]] == list(TOOLS)
    assert [body for path, _, body in stub.requests if path == "/runs/t/tools"] == [{"tool": "list_orders", "args": {}}, {"tool": "ask_user", "args": ASK}]
    outputs = stub.requests[3][2]
    assert set(outputs) == {"tool_outputs", "tools"}  # the run endpoint's schema; tools are resent or later calls arrive as text
    assert outputs["tools"] == message["tools"] and [o["tool_call_id"] for o in outputs["tool_outputs"]] == ["call_0", "call_1", "call_2"]
    assert all(set(o) == {"tool_call_id", "output"} and isinstance(o["output"], str) for o in outputs["tool_outputs"])
    assert json.loads(outputs["tool_outputs"][2]["output"]) == agent.NOT_SENT


@pytest.mark.parametrize(
    "stub", [[{"status": "COMPLETED", "thread_id": "thr-9", "content": "कौन सा order?"}, {"status": "COMPLETED", "thread_id": "thr-9", "content": "हो गया"}]],
    indirect=True,
)
def test_later_turns_continue_the_thread(stub: Stub) -> None:
    backboard = agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url)
    assert agent.turn(turn_req(stub), backboard) == "कौन सा order?"
    assert agent.turn(turn_req(stub, 1, "नीला वाला"), backboard) == "हो गया"
    assert stub.requests[1][2]["thread_id"] == "thr-9" and "assistant_id" not in stub.requests[1][2]


# Real responses from 2026-10-18 (openrouter dots-studio/dots-3-note-preview:free), ids shortened, nulls kept.
SEEN = {"message": "Message added successfully", "assistant_id": ASSISTANT, "system_one": None, "message_id": "m-1", "role": "assistant",
        "run_id": "r-1", "memory_operation_id": None, "retrieved_memories": None, "retrieved_files": None, "retrieved_files_count": 0,
        "model_provider": "openrouter", "model_name": "dots-studio/dots-3-note-preview:free", "input_tokens": 208, "output_tokens": 78,
        "total_tokens": 286, "attachments": None, "generated_media": None, "voice_records": None,
        "context_usage": {"used_tokens": 169, "context_limit": 512000, "percent": 0.0, "summary_tokens": 0, "model": "dots-studio/dots-3-note-preview:free"}}
SEEN_CALL = {"id": "call_56c7f88ee9f64215a4dc8f63", "type": "function", "function": {"name": "list_orders", "arguments": "{}"}}
SEEN_CANCEL = {"id": "call_93fe99599dbc4a56b3143357", "type": "function", "function": {"name": "cancel_order", "arguments": '{"order_id": "ORD-1"}'}}
SEEN_ACTION = SEEN | {"thread_id": "thr-5", "content": None, "status": "REQUIRES_ACTION", "tool_calls": [SEEN_CALL], "reasoning": "I'll call the tool."}
# every reply of a run lists all of the run's calls so far, answered ones included; content starts with blank lines
SEEN_ACTION_2 = SEEN_ACTION | {"message": "Tool outputs submitted successfully", "content": "", "tool_calls": [SEEN_CALL, SEEN_CANCEL]}
SEEN_DONE = SEEN | {"message": "Tool outputs submitted successfully", "thread_id": "thr-5", "content": "\n\nYou have 3 orders.", "status": "COMPLETED",
                    "tool_calls": [SEEN_CALL], "reasoning": "I used the tool."}
# billing refusal: HTTP 200, status FAILED, the reason in content, no error field, no tokens
SEEN_BILLING = SEEN | {"thread_id": "thr-6", "status": "FAILED", "tool_calls": None, "model_provider": None, "model_name": None,
                       "input_tokens": None, "output_tokens": None, "total_tokens": None,
                       "content": "Your free credit is reserved for Memory & RAG, so it can't cover LLM chat. Add credits or start a subscription on the Billing page to continue."}


@pytest.mark.parametrize("stub", [[SEEN_ACTION, SEEN_ACTION_2, SEEN_DONE]], indirect=True)
def test_observed_shapes_run_each_call_once_and_strip_the_reply(stub: Stub) -> None:
    assert agent.turn(turn_req(stub), agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url)) == "You have 3 orders."
    submit = "/threads/thr-5/runs/r-1/submit-tool-outputs"
    assert stub.paths() == ["/threads/messages", "/runs/t/tools", submit, "/runs/t/tools", submit]  # each call reaches the gateway once
    assert [body for path, _, body in stub.requests if path == "/runs/t/tools"] == [{"tool": "list_orders", "args": {}},
                                                                                   {"tool": "cancel_order", "args": {"order_id": "ORD-1"}}]
    output = json.dumps({"ok": True, "result": [], "error": None})
    assert stub.requests[2][2]["tool_outputs"] == [{"tool_call_id": SEEN_CALL["id"], "output": output}]
    assert stub.requests[4][2]["tool_outputs"] == [{"tool_call_id": SEEN_CALL["id"], "output": output},  # resubmitted, not rerun
                                                   {"tool_call_id": SEEN_CANCEL["id"], "output": output}]


@pytest.mark.parametrize("stub", [[{"status": "FAILED", "thread_id": "thr-2", "error": "model unavailable"}], [SEEN_BILLING]], indirect=True)
def test_a_failed_run_fails_the_turn(stub: Stub) -> None:
    with pytest.raises(RuntimeError, match="FAILED: (model unavailable|Your free credit is reserved)"):
        agent.turn(turn_req(stub), agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url))
    assert stub.paths() == ["/threads/messages"]


@pytest.mark.parametrize("stub", [[SEEN_ACTION | {"run_id": None}], [{k: v for k, v in SEEN_ACTION.items() if k != "run_id"}]], indirect=True)
def test_tool_calls_without_a_run_id_fail_the_turn_before_any_tool_runs(stub: Stub) -> None:
    with pytest.raises(RuntimeError, match="without a run_id"):
        agent.turn(turn_req(stub), agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url))
    assert stub.paths() == ["/threads/messages"]  # no tool call, no post to /runs/None/...


@pytest.mark.parametrize("stub", [[401], [429], [502]], indirect=True)
def test_an_http_error_fails_the_turn_once_without_the_key(stub: Stub) -> None:
    with pytest.raises(urllib.error.HTTPError) as e:
        agent.turn(turn_req(stub), agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url))
    assert stub.paths() == ["/threads/messages"]  # no retry, no tool call
    assert KEY not in str(e.value) and KEY not in repr(e.value)


@pytest.mark.parametrize("stub", [[{"name": "bolibench-agent", "assistant_id": ASSISTANT}]], indirect=True)
def test_a_bolibench_assistant_is_accepted(stub: Stub) -> None:
    assert agent.check_assistant(agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url)) == "bolibench-agent"
    path, headers, body = stub.requests[0]
    assert (path, headers["X-API-Key"], body) == (f"/assistants/{ASSISTANT}", KEY, None)


@pytest.mark.parametrize("stub", [[{"name": "Nivara business memory", "assistant_id": ASSISTANT}]], indirect=True)
def test_another_apps_assistant_is_refused(stub: Stub) -> None:
    with pytest.raises(SystemExit, match="Nivara business memory"):
        agent.check_assistant(agent.Backboard(KEY, ASSISTANT, "openrouter", "m", base=stub.url))


def test_identity_is_accepted_and_the_key_stays_out_of_reprs() -> None:
    AgentIdentity.model_validate(agent.identity("openrouter", "qwen/qwen3-235b-a22b-2507"))
    assert KEY not in repr(agent.Backboard(KEY, ASSISTANT, "openrouter", "m"))
