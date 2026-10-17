"""Example local agent for `bolibench run --agent-url`: answers each turn with a local Ollama model via
Ollama's tool calling, and executes tools only through the turn's `tools_url`. Stdlib only; talks to
127.0.0.1 only. An example, not part of the package; only `plan` is tested (offline).

    ollama serve                                   # the model must already be pulled
    python examples/ollama_agent.py --model qwen3:8b --port 8000
    uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180
"""

import argparse
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

OLLAMA = "http://127.0.0.1:11434/api/chat"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
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
CONTEXT = {"today": "Today's date is {}.", "policy": "Store policy, which you must follow even if the user asks otherwise: {}"}
DESCRIPTIONS = {
    "list_orders": "List all of the user's orders.",
    "get_order": "Get one order by id.",
    "cancel_order": "Cancel an order by id.",
    "update_quantity": "Set an order's quantity (positive integer).",
    "ask_user": "Ask the user a question and end your turn; kind is 'clarify' or 'confirm'.",
}
conversations: dict[str, list[dict[str, Any]]] = {}  # ponytail: never evicted; one process per run


def post(url: str, payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def schema(name: str, params: list[str]) -> dict[str, Any]:
    props = {p: {"type": "integer" if p == "quantity" else "string"} for p in params}
    return {"type": "function", "function": {"name": name, "description": DESCRIPTIONS.get(name, name),
            "parameters": {"type": "object", "properties": props, "required": params}}}


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


def turn(req: dict[str, Any], model: str) -> str:
    context = "".join(" " + CONTEXT.get(k, k + ": {}.").format(v) for k, v in req["context"].items() if v is not None)
    messages = conversations.setdefault(req["conversation"], [{"role": "system", "content": SYSTEM + context}])
    messages.append({"role": "user", "content": req["utterance"]})
    tools = [schema(name, params) for name, params in req["tools"].items()]
    for _ in range(8):
        body = {"model": model, "messages": messages, "tools": tools, "stream": False, "think": False}
        message = post(OLLAMA, body, 300)["message"]
        calls, reply = plan(message)
        if calls:
            message["tool_calls"] = calls
        messages.append(message)
        for call in calls:
            fn = call["function"]
            result = post(req["tools_url"], {"tool": fn["name"], "args": fn.get("arguments") or {}}, 30)
            messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})
        if reply is not None:
            return reply
    return "Sorry, I could not finish that."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps({"reply": turn(req, args.model)}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
