"""Example local agent for `bolibench run --agent-url`: answers each turn with a model and executes
tools only through the turn's `tools_url`. Stdlib only. An example, not part of the package; tested
offline only (no model, no network).

Backend (`--backend`): `ollama` (native /api/chat, default http://127.0.0.1:11434) or `openai`, any
OpenAI-compatible /v1/chat/completions endpoint (`--base-url`, e.g. https://inference.do-ai.run/v1).
The API key is read only from the environment variable named by `--api-key-env` and never logged.
Tool mode (`--tool-mode`): `native` uses the backend's tool calling; `json` is for models without it
(e.g. gemma3 on Ollama): the prompt asks for a JSON tool call as the whole reply, parsed strictly.
Tracing: Sentry AI agent spans only when SENTRY_DSN is set (needs `sentry-sdk`); prompts, replies and
tool arguments/results are sent only with `--sentry-capture-content`.

    ollama serve                                   # the model must already be pulled
    python examples/ollama_agent.py --model qwen3:8b --port 8000
    python examples/ollama_agent.py --model gemma3:4b --tool-mode json --port 8000
    uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180
"""

import argparse
import hashlib
import json
import os
import re
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

NAME = "bolibench-example-ollama-agent"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
ENDPOINTS = {"ollama": "/api/chat", "openai": "/chat/completions"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect would carry the Authorization header to another URL


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
SYSTEM = (
    "You are a customer-support agent for an online store. Users may write in Hindi, Awadhi, English or a mix. "
    "Use the tools to look up and change orders and never claim an action you did not perform with a tool. "
    "Orders are identified only by the ids that list_orders or get_order return: never guess or invent an id, and "
    "never pass anything else (a name, description or date) as an id. Unless the user gives an exact id, call "
    "list_orders first and pick the order from its fields. "
    "If the user's request is ambiguous, call ask_user with kind 'clarify'. Before cancelling based on a vague "
    "reference, call ask_user with kind 'confirm'. ask_user ends your turn; the answer arrives as the user's next "
    "message. If a tool call fails with an error that says or suggests it is temporary, retry the same call once. "
    "Reply briefly."
)
JSON_TOOLS = (
    " You have no built-in tool calling. To call tools, your whole reply must be one JSON object and nothing "
    'else: {"tool_calls": [{"name": "<tool>", "arguments": {"<argument>": <value>}}]}. Tool results come back '
    "in a user message that starts with TOOL_RESULTS. To answer the user, reply in plain text, not JSON. Tools: "
)
CONTEXT = {"today": "Today's date is {}.", "policy": "Store policy, which you must follow even if the user asks otherwise: {}"}
DESCRIPTIONS = {
    "list_orders": "List all of the user's orders.",
    "get_order": "Get one order by id.",
    "cancel_order": "Cancel an order by id.",
    "update_quantity": "Set an order's quantity (positive integer).",
    "ask_user": "Ask the user a question and end your turn; kind is 'clarify' or 'confirm'.",
}
FENCE = re.compile(r"```(?:json)?\n(.*)\n```", re.DOTALL)
conversations: dict[str, list[dict[str, Any]]] = {}  # ponytail: never evicted; one process per run
sentry: Any = None  # the sentry_sdk module once init_sentry() enabled it


@dataclass(frozen=True)
class Config:
    model: str
    backend: str = "ollama"
    url: str = "http://127.0.0.1:11434/api/chat"
    tool_mode: str = "native"
    api_key: str | None = field(default=None, repr=False)  # never logged
    capture_content: bool = False


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def post(url: str, payload: dict[str, Any], timeout: float, api_key: str | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def check_base_url(url: str) -> str:
    """The base URL without a trailing slash; https, or http only on localhost, and no credentials."""
    parts = urlsplit(url)
    secure = parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS)
    if not secure or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("--base-url must be https:// (or http:// on 127.0.0.1, localhost or [::1]), without credentials, query or fragment")
    parts.port  # raises ValueError on a malformed port
    return url.rstrip("/")


def read_api_key(env_name: str | None, environ: Mapping[str, str]) -> str | None:
    if env_name is None:
        return None
    key = environ.get(env_name)
    if not key:
        raise SystemExit(f"--api-key-env {env_name}: that environment variable is not set or is empty")
    return key


def param_type(param: str) -> str:
    return "integer" if param == "quantity" else "string"


def schema(name: str, params: list[str]) -> dict[str, Any]:
    props = {p: {"type": param_type(p)} for p in params}
    return {"type": "function", "function": {"name": name, "description": DESCRIPTIONS.get(name, name),
            "parameters": {"type": "object", "properties": props, "required": params}}}


def json_tool_prompt(tools: dict[str, list[str]]) -> str:
    specs = (f"{name}({', '.join(f'{p}: {param_type(p)}' for p in params)}): {DESCRIPTIONS.get(name, name)}"
             for name, params in tools.items())
    return JSON_TOOLS + " ".join(specs)


def identity(model: str, backend: str = "ollama", tool_mode: str = "native") -> dict[str, str]:
    """Self-reported identity for BoliBench's artifacts: this file's sha256 prefix plus the model name,
    plus backend and tool mode unless they are the defaults (so default runs keep the v2 format)."""
    version = f"{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]}+{model}"
    if (backend, tool_mode) != ("ollama", "native"):
        version += f"+{backend}-{tool_mode}"
    return {"name": NAME, "version": version}


def json_tool_calls(text: str) -> list[dict[str, Any]]:
    """Tool calls from a json-mode reply. The whole reply (or one ```json fenced block that is the whole
    reply) must be {"tool_calls": [{"name": str, "arguments": {...}}, ...]}; anything else is no call."""
    text = text.strip()
    fenced = FENCE.fullmatch(text)
    try:
        data = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError:
        return []
    calls = data.get("tool_calls") if isinstance(data, dict) and data.keys() == {"tool_calls"} else None
    if not isinstance(calls, list) or not all(
        isinstance(c, dict) and c.keys() == {"name", "arguments"} and isinstance(c["name"], str) and isinstance(c["arguments"], dict)
        for c in calls
    ):
        return []
    return [{"function": c} for c in calls]


def openai_call(call: dict[str, Any]) -> dict[str, Any] | None:
    """One OpenAI tool call with its arguments decoded; None if they are not a JSON object or it has no id."""
    try:
        args = json.loads(call["function"]["arguments"])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(args, dict) or not isinstance(call.get("id"), str):
        return None
    return {"id": call["id"], "function": {"name": call["function"]["name"], "arguments": args}}


def parse_reply(cfg: Config, body: dict[str, Any]) -> dict[str, Any]:
    """The model's message as {"content": str, "tool_calls": [{"function": {"name", "arguments": dict}, ...}]}."""
    raw = body["message"] if cfg.backend == "ollama" else body["choices"][0]["message"]
    content = raw.get("content") or ""
    if cfg.tool_mode == "json":
        calls = json_tool_calls(content)
    elif cfg.backend == "ollama":
        calls = raw.get("tool_calls") or []
    else:
        calls = [c for c in map(openai_call, raw.get("tool_calls") or []) if c is not None]
    return {"content": content, "tool_calls": calls}


def usage(cfg: Config, body: dict[str, Any]) -> dict[str, Any]:
    """Token counts the backend returned, as Sentry gen_ai.* attributes (absent ones omitted)."""
    if cfg.backend == "ollama":
        counts = {"input_tokens": body.get("prompt_eval_count"), "output_tokens": body.get("eval_count")}
    else:
        u = body.get("usage") or {}
        counts = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"), "total_tokens": u.get("total_tokens")}
    return {f"gen_ai.usage.{k}": v for k, v in counts.items() if isinstance(v, int)}


def plan(message: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Tool calls to run from one model message, and the turn's reply if the turn ends (None = keep going).
    ask_user ends the turn: calls after it were made before the user answered, so they are dropped."""
    calls = message.get("tool_calls") or []
    if not calls:
        return [], message.get("content", "")
    for i, call in enumerate(calls):
        if call["function"]["name"] == "ask_user":
            question = (call["function"].get("arguments") or {}).get("question")
            return calls[: i + 1], question or message.get("content", "")
    return calls, None


def assistant_message(cfg: Config, content: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The model's message as it goes back into the history, holding only the calls that are run."""
    if cfg.tool_mode == "json":
        return {"role": "assistant", "content": dumps({"tool_calls": [c["function"] for c in calls]}) if calls else content}
    if cfg.backend == "ollama":
        return {"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})}
    wire = [{"id": c["id"], "type": "function", "function": {"name": c["function"]["name"], "arguments": dumps(c["function"]["arguments"])}}
            for c in calls]
    return {"role": "assistant", "content": content or None, **({"tool_calls": wire} if wire else {})}


def result_messages(cfg: Config, results: list[tuple[dict[str, Any], Any]]) -> list[dict[str, Any]]:
    """Tool results as history messages: one user message in json mode (no tool role needed)."""
    if not results:
        return []
    if cfg.tool_mode == "json":
        return [{"role": "user", "content": "TOOL_RESULTS " + dumps([{"name": c["function"]["name"], "result": r} for c, r in results])}]
    if cfg.backend == "openai":
        return [{"role": "tool", "tool_call_id": c["id"], "content": dumps(r)} for c, r in results]
    return [{"role": "tool", "content": dumps(r)} for _, r in results]


class _NoSpan:
    def set_data(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: str) -> None:
        pass


@contextmanager
def span(op: str, name: str, data: dict[str, Any]) -> Iterator[Any]:
    """A Sentry span with `data` set at start, or a no-op stand-in when Sentry is off."""
    if sentry is None:
        yield _NoSpan()
        return
    with sentry.start_span(op=op, name=name) as s:
        for key, value in data.items():
            s.set_data(key, value)
        yield s


def provider(cfg: Config) -> str:
    return "ollama" if cfg.backend == "ollama" else urlsplit(cfg.url).hostname or "openai"


def chat(cfg: Config, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """One model call: appends the model's message to `messages` and returns plan() of it."""
    body: dict[str, Any] = {"model": cfg.model, "messages": messages, "stream": False}
    if cfg.tool_mode == "native":
        body["tools"] = tools
    if cfg.backend == "ollama":
        body["think"] = False
    data = {"gen_ai.operation.name": "chat", "gen_ai.agent.name": NAME, "gen_ai.request.model": cfg.model, "gen_ai.provider.name": provider(cfg)}
    if cfg.capture_content:
        data |= {"gen_ai.system_instructions": messages[0]["content"], "gen_ai.input.messages": dumps(messages[1:])}
    with span("gen_ai.chat", f"chat {cfg.model}", data) as chat_span:
        response = post(cfg.url, body, 300, cfg.api_key)
        message = parse_reply(cfg, response)
        calls, done = plan(message)
        messages.append(assistant_message(cfg, message["content"], calls))
        if "model" in response:
            chat_span.set_data("gen_ai.response.model", response["model"])
        for key, value in usage(cfg, response).items():
            chat_span.set_data(key, value)
        if cfg.capture_content:
            chat_span.set_data("gen_ai.output.messages", dumps([messages[-1]]))
    return calls, done


def run_tool(cfg: Config, tools_url: str, call: dict[str, Any]) -> Any:
    name, args = call["function"]["name"], call["function"].get("arguments") or {}
    data = {"gen_ai.operation.name": "execute_tool", "gen_ai.agent.name": NAME, "gen_ai.tool.name": name,
            "gen_ai.tool.description": DESCRIPTIONS.get(name, name)}
    if cfg.capture_content:
        data["gen_ai.tool.call.arguments"] = dumps(args)
    with span("gen_ai.execute_tool", f"execute_tool {name}", data) as tool_span:
        result = post(tools_url, {"tool": name, "args": args}, 30)
        if not result.get("ok"):
            tool_span.set_status("internal_error")
            tool_span.set_data("error.type", "tool_error")
        if cfg.capture_content:
            tool_span.set_data("gen_ai.tool.call.result", dumps(result))
    return result


def agent_turn(req: dict[str, Any], cfg: Config) -> str:
    context = "".join(" " + CONTEXT.get(k, k + ": {}.").format(v) for k, v in req["context"].items() if v is not None)
    tool_text = json_tool_prompt(req["tools"]) if cfg.tool_mode == "json" else ""
    messages = conversations.setdefault(req["conversation"], [{"role": "system", "content": SYSTEM + context + tool_text}])
    messages.append({"role": "user", "content": req["utterance"]})
    tools = [schema(name, params) for name, params in req["tools"].items()]
    data = {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": NAME}
    if cfg.capture_content:
        data["gen_ai.input.messages"] = dumps([messages[-1]])
    with span("gen_ai.invoke_agent", f"invoke_agent {NAME}", data) as agent_span:
        reply = "Sorry, I could not finish that."
        for _ in range(8):
            calls, done = chat(cfg, messages, tools)
            messages.extend(result_messages(cfg, [(call, run_tool(cfg, req["tools_url"], call)) for call in calls]))
            if done is not None:
                reply = done
                break
        if cfg.capture_content:
            agent_span.set_data("gen_ai.output.messages", dumps([{"role": "assistant", "content": reply}]))
    return reply


def turn(req: dict[str, Any], cfg: Config) -> str:
    if sentry is None:
        return agent_turn(req, cfg)
    # gen_ai spans are only sent inside a transaction; this one is the webhook request itself
    with sentry.isolation_scope(), sentry.start_transaction(op="http.server", name="POST /turn") as transaction:
        agent = identity(cfg.model, cfg.backend, cfg.tool_mode)
        for key, value in {"model": cfg.model, "agent.version": agent["version"], "backend": cfg.backend, "tool_mode": cfg.tool_mode}.items():
            transaction.set_tag(key, value)
        sentry.ai.set_conversation_id(req["conversation"])
        return agent_turn(req, cfg)


def init_sentry(environ: Mapping[str, str], capture_content: bool) -> Any:
    """The sentry_sdk module, initialised, if SENTRY_DSN is set; otherwise None and nothing is imported."""
    dsn = environ.get("SENTRY_DSN")
    if not dsn:
        if capture_content:
            raise SystemExit("--sentry-capture-content needs SENTRY_DSN")
        return None
    try:
        import sentry_sdk
        import sentry_sdk.ai
    except ImportError:
        raise SystemExit("SENTRY_DSN is set but sentry-sdk is not installed: install sentry-sdk or unset SENTRY_DSN") from None
    try:
        rate = float(environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0"))
    except ValueError:
        rate = -1.0
    if not 0.0 <= rate <= 1.0:
        raise SystemExit("SENTRY_TRACES_SAMPLE_RATE must be a number from 0 to 1")
    # SDK PII defaults stay conservative; content is only what agent_turn adds under --sentry-capture-content.
    # No trace headers on outgoing calls: they would reach the model provider and the tool gateway.
    sentry_sdk.init(dsn=dsn, traces_sample_rate=rate, trace_propagation_targets=[])
    return sentry_sdk


def config(args: argparse.Namespace, environ: Mapping[str, str]) -> Config:
    if args.backend == "openai" and args.base_url is None:
        raise SystemExit("--backend openai needs --base-url, e.g. https://inference.do-ai.run/v1")
    try:
        base = check_base_url(args.base_url or "http://127.0.0.1:11434")
    except ValueError as e:
        raise SystemExit(str(e)) from None
    return Config(args.model, args.backend, base + ENDPOINTS[args.backend], args.tool_mode,
                  read_api_key(args.api_key_env, environ), args.sentry_capture_content)


def main() -> None:
    global sentry
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--backend", choices=list(ENDPOINTS), default="ollama")
    parser.add_argument("--base-url", help="default http://127.0.0.1:11434 (ollama); required for openai, e.g. https://inference.do-ai.run/v1")
    parser.add_argument("--api-key-env", metavar="NAME", help="environment variable holding the API key (sent as a Bearer token)")
    parser.add_argument("--tool-mode", choices=["native", "json"], default="native")
    parser.add_argument("--sentry-capture-content", action="store_true", help="send prompts, replies and tool arguments/results to Sentry")
    args = parser.parse_args()
    cfg = config(args, os.environ)
    sentry = init_sentry(os.environ, cfg.capture_content)
    agent = identity(cfg.model, cfg.backend, cfg.tool_mode)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps({"reply": turn(req, cfg), "agent": agent}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
