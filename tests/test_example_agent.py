import builtins
import contextlib
import hashlib
import importlib.util
import json
import sys
import threading
import urllib.error
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from bolibench.models import AgentIdentity

SPEC = importlib.util.spec_from_file_location("ollama_agent", Path(__file__).parent.parent / "examples" / "ollama_agent.py")
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)  # defines functions only; nothing is contacted

TOOLS = {"list_orders": [], "get_order": ["order_id"], "cancel_order": ["order_id"],
         "update_quantity": ["order_id", "quantity"], "ask_user": ["kind", "question"]}
TOOLS_URL = "http://127.0.0.1:9/runs/token/tools"
OLLAMA = agent.Config("qwen3:8b")
GEMMA = agent.Config("gemma3:4b", tool_mode="json")


def call(name: str, **args: Any) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": args}}


def request(conversation: str, utterance: str = "मेरा ऑर्डर cancel करो") -> dict[str, Any]:
    return {"conversation": conversation, "turn": 0, "utterance": utterance, "context": {"today": "2026-10-17", "policy": None},
            "tools_url": TOOLS_URL, "tools": TOOLS}


def test_identity_is_own_file_hash_plus_model() -> None:
    digest = hashlib.sha256(Path(agent.__file__).read_bytes()).hexdigest()[:12]
    assert agent.identity("qwen3:8b") == {"name": "bolibench-example-ollama-agent", "version": f"{digest}+qwen3:8b"}
    AgentIdentity.model_validate(agent.identity("qwen3:8b"))  # accepted by BoliBench as-is


def test_identity_names_a_non_default_backend_or_tool_mode() -> None:
    digest = hashlib.sha256(Path(agent.__file__).read_bytes()).hexdigest()[:12]
    assert agent.identity("gemma3:4b", "ollama", "json")["version"] == f"{digest}+gemma3:4b+ollama-json"
    assert agent.identity("m", "openai", "native")["version"] == f"{digest}+m+openai-native"
    assert agent.identity("gemma-4-31b-it", "openai", "native", "minimal")["version"] == f"{digest}+gemma-4-31b-it+openai-native+reasoning-minimal"
    AgentIdentity.model_validate(agent.identity("gemma3:4b", "openai", "json"))
    AgentIdentity.model_validate(agent.identity("gemma-4-31b-it", "openai", "json", "minimal"))


def test_ask_user_ends_the_turn_and_drops_later_calls() -> None:
    ask = call("ask_user", kind="confirm", question="ORD-1 cancel कर दूँ?")
    assert agent.plan({"tool_calls": [call("list_orders"), ask, call("cancel_order", order_id="ORD-1")]}) == (
        [call("list_orders"), ask],
        "ORD-1 cancel कर दूँ?",
    )
    assert agent.plan({"tool_calls": [call("list_orders")]}) == ([call("list_orders")], None)
    assert agent.plan({"content": "हो गया"}) == ([], "हो गया")


@pytest.mark.parametrize("text", [
    '{"tool_calls": [{"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}]}',
    '  ```json\n{"tool_calls": [{"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}]}\n```\n',
    '```\n{"tool_calls": [{"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}]}\n```',
])
def test_json_tool_calls_accepts_only_the_exact_shape(text: str) -> None:
    assert agent.json_tool_calls(text) == [call("cancel_order", order_id="ORD-1")]


@pytest.mark.parametrize("text", [
    "ORD-1 cancel हो गया",
    'Sure! {"tool_calls": [{"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}]}',  # text around it
    '{"tool_calls": [{"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}]',  # truncated
    '{"tool_calls": [{"name": "cancel_order", "arguments": "ORD-1"}]}',  # arguments not an object
    '{"tool_calls": [{"name": "cancel_order"}]}',  # missing arguments
    '{"tool_calls": [{"tool": "cancel_order", "arguments": {}}]}',  # wrong key
    '{"tool_calls": [{"name": "cancel_order", "arguments": {}, "id": 1}]}',  # extra key
    '{"tool_calls": {"name": "cancel_order", "arguments": {}}}',  # not a list
    '{"tool_calls": [], "reply": "hi"}',  # extra top-level key
    '{"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}',  # bare call
    '[{"name": "cancel_order", "arguments": {}}]',
    "```json\n{\"tool_calls\": []}\n``` and then some text",
])
def test_malformed_json_tool_call_is_no_call(text: str) -> None:
    assert agent.json_tool_calls(text) == []
    assert agent.plan(agent.parse_reply(GEMMA, {"message": {"role": "assistant", "content": text}})) == ([], text)


def test_openai_tool_call_needs_object_arguments_and_an_id() -> None:
    ok = {"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": "ORD-1"}'}}
    assert agent.openai_call(ok) == {"id": "c1", "function": {"name": "get_order", "arguments": {"order_id": "ORD-1"}}}
    for bad in ['"ORD-1"', "{order_id: 1}", "", None, "[]"]:
        assert agent.openai_call({**ok, "function": {"name": "get_order", "arguments": bad}}) is None
    assert agent.openai_call({k: v for k, v in ok.items() if k != "id"}) is None


@pytest.mark.parametrize("url", ["https://inference.do-ai.run/v1/", "http://127.0.0.1:11434", "http://localhost:8080/v1", "http://[::1]:1/v1"])
def test_base_url_accepts_https_or_local_http(url: str) -> None:
    assert agent.check_base_url(url) == url.rstrip("/")


@pytest.mark.parametrize("url", ["http://inference.do-ai.run/v1", "http://10.0.0.5:11434", "https://user:pw@example.com/v1",
                                 "https://example.com/v1?key=x", "ftp://example.com", "https://", "inference.do-ai.run/v1",
                                 "https://example.com:notaport/v1"])
def test_base_url_refuses_plain_http_off_localhost_and_credentials(url: str) -> None:
    with pytest.raises(ValueError) as e:
        agent.check_base_url(url)
    assert "pw" not in str(e.value) and "key=x" not in str(e.value)


def test_api_key_comes_only_from_the_named_env_var_and_is_never_shown() -> None:
    assert agent.read_api_key(None, {"MODEL_ACCESS_KEY": "sk-secret"}) is None
    assert agent.read_api_key("MODEL_ACCESS_KEY", {"MODEL_ACCESS_KEY": "sk-secret"}) == "sk-secret"
    for env in [{}, {"MODEL_ACCESS_KEY": ""}]:
        with pytest.raises(SystemExit, match="MODEL_ACCESS_KEY"):
            agent.read_api_key("MODEL_ACCESS_KEY", env)
    assert "sk-secret" not in repr(agent.Config("m", api_key="sk-secret"))


def args(**kw: Any) -> Any:
    defaults = {"model": "m", "backend": "ollama", "base_url": None, "api_key_env": None, "tool_mode": "native",
                "sentry_capture_content": False, "reasoning_effort": None}
    return type("Args", (), defaults | kw)()


def test_config_builds_endpoints_and_requires_a_base_url_for_openai() -> None:
    assert agent.config(args(), {}).url == "http://127.0.0.1:11434/api/chat"
    cfg = agent.config(args(backend="openai", base_url="https://inference.do-ai.run/v1", api_key_env="K"), {"K": "sk-secret"})
    assert (cfg.url, cfg.api_key) == ("https://inference.do-ai.run/v1/chat/completions", "sk-secret")
    with pytest.raises(SystemExit, match="needs --base-url"):
        agent.config(args(backend="openai"), {})
    with pytest.raises(SystemExit, match="https"):
        agent.config(args(backend="openai", base_url="http://inference.do-ai.run/v1"), {})
    with pytest.raises(SystemExit, match="--reasoning-effort needs --backend openai"):
        agent.config(args(reasoning_effort="minimal"), {})


class FakeBackend:
    """Stands in for `post`: scripted model responses and tool results, and a copy of every request."""

    def __init__(self, responses: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
        self.responses, self.results, self.sent = responses, results, []

    def __call__(self, url: str, payload: dict[str, Any], timeout: float, api_key: str | None = None) -> Any:
        self.sent.append((url, json.loads(json.dumps(payload)), api_key))
        return self.results.pop(0) if url == TOOLS_URL else self.responses.pop(0)


def ollama(content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message = {"role": "assistant", "content": content, **({"tool_calls": tool_calls} if tool_calls else {})}
    return {"model": "gemma3:4b", "message": message, "prompt_eval_count": 120, "eval_count": 30}


def test_json_mode_turn_sends_no_tools_and_returns_results_as_a_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_call = '```json\n{"tool_calls": [{"name": "list_orders", "arguments": {}}, {"name": "ask_user", "arguments": {"kind": "clarify", "question": "कौन सा?"}}, {"name": "cancel_order", "arguments": {"order_id": "ORD-1"}}]}\n```'
    fake = FakeBackend([ollama(tool_call)], [{"ok": True, "result": [], "error": None}, {"ok": True, "result": None, "error": None}])
    monkeypatch.setattr(agent, "post", fake)
    assert agent.turn(request("json-1"), GEMMA) == "कौन सा?"
    (url, body, _), *tool_requests = fake.sent
    assert url == GEMMA.url and "tools" not in body and body["think"] is False
    assert agent.JSON_TOOLS in body["messages"][0]["content"] and "update_quantity(order_id: string, quantity: integer)" in body["messages"][0]["content"]
    assert [p["tool"] for _, p, _ in tool_requests] == ["list_orders", "ask_user"]  # cancel after ask_user dropped
    history = agent.conversations["json-1"]
    assert json.loads(history[-2]["content"]) == {"tool_calls": [{"name": "list_orders", "arguments": {}},
                                                                 {"name": "ask_user", "arguments": {"kind": "clarify", "question": "कौन सा?"}}]}
    assert history[-1]["role"] == "user" and history[-1]["content"].startswith("TOOL_RESULTS ")


def test_json_mode_malformed_call_is_the_reply_and_runs_no_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    text = 'cancel_order(order_id="ORD-1")'
    fake = FakeBackend([ollama(text)], [])
    monkeypatch.setattr(agent, "post", fake)
    assert agent.turn(request("json-2"), GEMMA) == text
    assert [url for url, _, _ in fake.sent] == [GEMMA.url]


@contextlib.contextmanager
def fake_openai_server(script: list[Any]) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """A local OpenAI-compatible endpoint plus tool gateway; yields its base URL and every request seen."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            reply = script.pop(0) if self.path == "/v1/chat/completions" else {"ok": True, "result": [{"id": "ORD-1"}], "error": None}
            status = reply if isinstance(reply, int) else 200  # an int in the script is an HTTP error
            data = json.dumps({"error": {"message": "stub error", "code": status}} if isinstance(reply, int) else reply).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()


def test_openai_backend_speaks_chat_completions_with_a_bearer_key() -> None:
    first = {"model": "m-2026", "usage": {"prompt_tokens": 50, "completion_tokens": 7, "total_tokens": 57}, "choices": [{"message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "list_orders", "arguments": "{}"}}]}}]}
    second = {"model": "m-2026", "choices": [{"message": {"role": "assistant", "content": "आपके पास ORD-1 है।"}}]}
    with fake_openai_server([first, second]) as (base, seen):
        cfg = agent.config(args(backend="openai", base_url=base + "/v1", api_key_env="K"), {"K": "sk-secret"})
        req = request("openai-1") | {"tools_url": base + "/runs/t/tools"}
        assert agent.turn(req, cfg) == "आपके पास ORD-1 है।"
    model_calls = [s for s in seen if s["path"] == "/v1/chat/completions"]
    assert [s["auth"] for s in seen] == ["Bearer sk-secret", None, "Bearer sk-secret"]  # the key never goes to the tool gateway
    assert [s["body"] for s in seen if s["path"] != "/v1/chat/completions"] == [{"tool": "list_orders", "args": {}}]
    body = model_calls[1]["body"]
    assert "think" not in body and "reasoning_effort" not in body and body["stream"] is False and body["tools"][0]["function"]["name"] == "list_orders"
    assert body["messages"][-2:] == [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "list_orders", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"ok": True, "result": [{"id": "ORD-1"}], "error": None})},
    ]


def openai_cfg(base: str, **kw: Any) -> Any:
    return agent.config(args(backend="openai", base_url=base + "/v1", api_key_env="K", **kw), {"K": "sk-secret"})


def reply(content: str) -> dict[str, Any]:
    return {"model": "gemma-4-31b-it", "choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "RETRY_DELAYS", (0.0, 0.0))


@pytest.mark.parametrize(("status", "attempts"), [(400, 1), (401, 1), (429, 3), (500, 3), (503, 3)])
def test_openai_http_errors_fail_the_turn_after_bounded_retries_without_the_key(no_retry_wait: None, status: int, attempts: int) -> None:
    with fake_openai_server([status] * attempts) as (base, seen):
        with pytest.raises(urllib.error.HTTPError) as e:
            agent.turn(request(f"openai-{status}") | {"tools_url": base + "/runs/t/tools"}, openai_cfg(base))
    assert e.value.code == status and len(seen) == attempts  # 4xx other than 429: no retry; 429/5xx: 3 attempts in all
    assert "sk-secret" not in str(e.value) and "sk-secret" not in repr(e.value)


def test_openai_transient_errors_are_retried_then_the_turn_goes_on(no_retry_wait: None, capsys: pytest.CaptureFixture[str]) -> None:
    with fake_openai_server([500, 429, reply("ठीक है")]) as (base, seen):
        assert agent.turn(request("openai-retry") | {"tools_url": base + "/runs/t/tools"}, openai_cfg(base)) == "ठीक है"
    assert len(seen) == 3 and seen[0]["body"] == seen[2]["body"]
    assert capsys.readouterr().err == "model call: HTTP 500, retrying in 0s\nmodel call: HTTP 429, retrying in 0s\n"


def test_reasoning_effort_is_sent_only_when_set() -> None:
    with fake_openai_server([reply("ठीक है")]) as (base, seen):
        cfg = openai_cfg(base, reasoning_effort="minimal")
        assert agent.turn(request("openai-effort") | {"tools_url": base + "/runs/t/tools"}, cfg) == "ठीक है"
    assert seen[0]["body"]["reasoning_effort"] == "minimal" and cfg.reasoning_effort == "minimal"


class FakeSpan:
    def __init__(self, tracer: "FakeSentry", op: str, name: str) -> None:
        self.tracer, self.op, self.name, self.parent = tracer, op, name, None
        self.data: dict[str, Any] = {}
        self.tags: dict[str, str] = {}
        self.status: str | None = None
        tracer.spans.append(self)

    def __enter__(self) -> "FakeSpan":
        self.parent = self.tracer.stack[-1].op if self.tracer.stack else None
        self.tracer.stack.append(self)
        return self

    def __exit__(self, *exc: object) -> None:
        self.tracer.stack.pop()

    def set_data(self, key: str, value: Any) -> None:
        self.data[key] = value

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def set_status(self, status: str) -> None:
        self.status = status


class FakeSentry:
    """The part of sentry_sdk the agent uses, recording spans in memory."""

    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []
        self.stack: list[FakeSpan] = []
        self.conversation: str | None = None
        self.ai = type("AI", (), {"set_conversation_id": staticmethod(lambda c: setattr(self, "conversation", c))})

    def start_transaction(self, op: str, name: str) -> FakeSpan:
        return FakeSpan(self, op, name)

    def start_span(self, op: str, name: str) -> FakeSpan:
        return FakeSpan(self, op, name)

    def isolation_scope(self) -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()


def traced_turn(monkeypatch: pytest.MonkeyPatch, conversation: str, cfg: Any) -> FakeSentry:
    fake = FakeSentry()
    monkeypatch.setattr(agent, "sentry", fake)
    monkeypatch.setattr(agent, "post", FakeBackend(
        [ollama(tool_calls=[call("cancel_order", order_id="ORD-1")]), ollama("ORD-1 रद्द हो गया")],
        [{"ok": False, "result": None, "error": "temporarily unavailable"}]))
    assert agent.turn(request(conversation), cfg) == "ORD-1 रद्द हो गया"
    return fake


def test_sentry_spans_follow_the_gen_ai_conventions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = traced_turn(monkeypatch, "trace-1", OLLAMA)
    assert [(s.op, s.parent) for s in fake.spans] == [
        ("http.server", None), ("gen_ai.invoke_agent", "http.server"), ("gen_ai.chat", "gen_ai.invoke_agent"),
        ("gen_ai.execute_tool", "gen_ai.invoke_agent"), ("gen_ai.chat", "gen_ai.invoke_agent")]
    transaction, invoke, chat, tool, _ = fake.spans
    assert transaction.tags == {"model": "qwen3:8b", "agent.version": agent.identity("qwen3:8b")["version"], "backend": "ollama", "tool_mode": "native"}
    assert fake.conversation == "trace-1"
    assert (invoke.name, invoke.data) == ("invoke_agent bolibench-example-ollama-agent",
                                          {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "bolibench-example-ollama-agent"})
    assert chat.name == "chat qwen3:8b" and chat.data == {
        "gen_ai.operation.name": "chat", "gen_ai.agent.name": "bolibench-example-ollama-agent", "gen_ai.request.model": "qwen3:8b",
        "gen_ai.provider.name": "ollama", "gen_ai.response.model": "gemma3:4b",
        "gen_ai.usage.input_tokens": 120, "gen_ai.usage.output_tokens": 30}
    assert tool.name == "execute_tool cancel_order" and tool.status == "internal_error" and tool.data == {
        "gen_ai.operation.name": "execute_tool", "gen_ai.agent.name": "bolibench-example-ollama-agent", "gen_ai.tool.name": "cancel_order",
        "gen_ai.tool.description": "Cancel an order by id.", "error.type": "tool_error"}


def test_sentry_gets_no_content_unless_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    system_word = "customer-support"
    for span in traced_turn(monkeypatch, "trace-2", OLLAMA).spans:
        assert not any(word in str(span.data) for word in ("मेरा ऑर्डर", "ORD-1", "temporarily", system_word)), span.op
    spans = traced_turn(monkeypatch, "trace-3", agent.Config("qwen3:8b", capture_content=True)).spans
    data = {key for span in spans for key in span.data}
    assert {"gen_ai.input.messages", "gen_ai.output.messages", "gen_ai.system_instructions",
            "gen_ai.tool.call.arguments", "gen_ai.tool.call.result"} <= data
    assert system_word in spans[2].data["gen_ai.system_instructions"] and "मेरा ऑर्डर" in spans[1].data["gen_ai.input.messages"]


def test_without_dsn_sentry_sdk_is_never_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []
    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **kw: imported.append(name) or real_import(name, *a, **kw))
    assert agent.init_sentry({}, False) is None
    assert agent.init_sentry({"SENTRY_DSN": ""}, False) is None
    assert not [name for name in imported if name.startswith("sentry_sdk")]
    with pytest.raises(SystemExit, match="needs SENTRY_DSN"):
        agent.init_sentry({}, True)


def test_dsn_without_sentry_sdk_exits_instead_of_skipping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)  # makes `import sentry_sdk` raise ImportError
    with pytest.raises(SystemExit, match="sentry-sdk is not installed"):
        agent.init_sentry({"SENTRY_DSN": "https://k@o1.ingest.sentry.io/1"}, False)


@contextlib.contextmanager
def real_sentry(monkeypatch: pytest.MonkeyPatch, capture: bool) -> Iterator[list[Any]]:
    """The real sentry_sdk as init_sentry sets it up, sending every envelope item to a list instead of Sentry."""
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.transport import Transport

    items: list[Any] = []

    class Memory(Transport):
        def capture_envelope(self, envelope: Any) -> None:
            items.extend(item.payload.json for item in envelope.items)

    sdk = agent.init_sentry({"SENTRY_DSN": "https://k@o1.ingest.sentry.io/1"}, capture)
    try:
        sdk.get_client().transport = Memory(sdk.get_client().options)
        monkeypatch.setattr(agent, "sentry", sdk)
        yield items
        sdk.flush()
    finally:
        sentry_sdk.init()  # no DSN: disabled again for the rest of the session


@pytest.mark.parametrize("capture", [False, True])
def test_real_sentry_sdk_sends_gen_ai_spans_to_an_in_memory_transport(monkeypatch: pytest.MonkeyPatch, capture: bool) -> None:
    pytest.importorskip("sentry_sdk")
    with pytest.raises(SystemExit, match="SENTRY_TRACES_SAMPLE_RATE"):
        agent.init_sentry({"SENTRY_DSN": "https://k@o1.ingest.sentry.io/1", "SENTRY_TRACES_SAMPLE_RATE": "2"}, False)
    with real_sentry(monkeypatch, capture) as items:
        monkeypatch.setattr(agent, "post", FakeBackend(
            [ollama(tool_calls=[call("list_orders")]), ollama("ठीक है")], [{"ok": True, "result": [], "error": None}]))
        assert agent.turn(request(f"real-{capture}"), agent.Config("qwen3:8b", capture_content=capture)) == "ठीक है"
    events = json.dumps(items, ensure_ascii=False)
    for op in ["gen_ai.invoke_agent", "gen_ai.chat", "gen_ai.execute_tool"]:
        assert op in events
    assert f"real-{capture}" in events and "qwen3:8b" in events and "gen_ai.usage.input_tokens" in events
    assert ("मेरा ऑर्डर" in events) is capture and ("gen_ai.tool.call.arguments" in events) is capture


def test_real_sentry_sdk_reports_a_failed_model_call_without_content_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with real_sentry(monkeypatch, False) as items, fake_openai_server([401]) as (base, _):
        with pytest.raises(urllib.error.HTTPError):
            agent.turn(request("real-error") | {"tools_url": base + "/runs/t/tools"}, openai_cfg(base))
    [error] = [item for item in items if "exception" in item]
    assert error["exception"]["values"][-1]["type"] == "HTTPError"
    events = json.dumps(items, ensure_ascii=False)
    assert events.count('"error.type": {"value": "HTTPError"') == 2  # the failed chat span and its invoke_agent span
    assert not any(secret in events for secret in ("sk-secret", "मेरा ऑर्डर", "customer-support")), events
