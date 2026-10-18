"""Example local agent for `bolibench run --agent-url` whose model runs on Backboard (backboard.io): each
turn is a Backboard thread message with tool definitions, and every tool call Backboard asks for is
executed only through the turn's `tools_url`, then its result is submitted back. Stdlib only. Same
prompt and tool schemas as examples/ollama_agent.py. An example, not part of the package; run against
the real API on 2026-10-18 (docs/audits/backboard-2026-10-18.md) and tested offline against a stub.

Every case starts a new thread on a dedicated assistant whose name must start with `bolibench-`:
without `assistant_id` Backboard would use the account's first assistant, with its documents.

    export BACKBOARD_API_KEY=...                   # read from the environment only, never logged
    python examples/backboard_agent.py --assistant-id <uuid> --provider openrouter --model qwen/qwen3-235b-a22b-2507 --port 8000
    uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# OPENER (and so post) never follows redirects, which would carry the API key elsewhere, and ignores proxies
from ollama_agent import CONTEXT, LOCAL_HOSTS, OPENER, SYSTEM, post, schema

API = "https://app.backboard.io/api"
MAX_BODY = 64 * 1024
MAX_ROUNDS = 8
NOT_SENT = {"ok": False, "result": None, "error": "not sent: ask_user ended this turn"}
BAD_ARGS = {"ok": False, "result": None, "error": "not sent: arguments are not a JSON object"}
threads: dict[str, str] = {}  # BoliBench conversation -> Backboard thread_id; ponytail: never evicted


class Backboard:
    def __init__(self, api_key: str, assistant: str, provider: str, model: str, base: str = API) -> None:
        self.assistant, self.provider, self.model, self.base = assistant, provider, model, base
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    def __repr__(self) -> str:  # keeps the key out of tracebacks and logs
        return f"Backboard({self.assistant} {self.provider}/{self.model} at {self.base})"

    def send(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST `payload` as JSON, or GET when it is None."""
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=self._headers, method="GET" if data is None else "POST")
        with OPENER.open(request, timeout=150) as response:
            return json.loads(response.read())


def check_assistant(backboard: Backboard) -> str:
    """The assistant's name; refuses any assistant not named `bolibench-*` (it may belong to another app)."""
    name = str(backboard.send(f"/assistants/{backboard.assistant}").get("name"))
    if not name.startswith("bolibench-"):
        raise SystemExit(f"assistant {backboard.assistant} is named {name!r}: use a dedicated assistant named bolibench-*")
    return name


def identity(provider: str, model: str) -> dict[str, str]:
    """Self-reported identity: sha256 prefix of this file and the prompt file it imports, plus the model."""
    files = Path(__file__).read_bytes() + (Path(__file__).parent / "ollama_agent.py").read_bytes()
    return {"name": "bolibench-backboard-agent", "version": f"{hashlib.sha256(files).hexdigest()[:12]}+{provider}/{model}"}


def call_tool(tools_url: str, call: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(arguments, gateway reply) for one Backboard tool call. Non-object arguments are not sent."""
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        args = None
    if not isinstance(args, dict):
        return {}, BAD_ARGS
    return args, post(tools_url, {"tool": call["function"]["name"], "args": args}, 30)


def turn(req: dict[str, Any], backboard: Backboard) -> str:
    parts = urlsplit(req["tools_url"])
    if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
        raise ValueError(f"tools_url must be http on localhost: {req['tools_url']!r}")
    context = "".join(" " + CONTEXT.get(k, k + ": {}.").format(v) for k, v in req["context"].items() if v is not None)
    message: dict[str, Any] = {
        "content": req["utterance"],
        "system_prompt": SYSTEM + context,  # not persisted by Backboard: sent every turn
        "tools": [schema(name, params) for name, params in req["tools"].items()],
        "llm_provider": backboard.provider,
        "model_name": backboard.model,
        "memory": "off",  # memory is shared by all threads of an assistant: on, facts would leak across cases
        "stream": False,
    }
    if req["turn"] > 0:
        message["thread_id"] = threads[req["conversation"]]
    else:  # a new thread for every case
        message["assistant_id"] = backboard.assistant
    response = backboard.send("/threads/messages", message)
    thread = threads[req["conversation"]] = response["thread_id"]
    run = response.get("run_id")
    question: str | None = None  # set once ask_user ran: the turn is over, later calls are not sent
    answered: dict[str, str] = {}  # tool_call_id -> output; a run's tool_calls repeat every earlier call of the run
    for _ in range(MAX_ROUNDS):
        if response.get("status") == "COMPLETED":
            return question or (response.get("content") or "").strip()
        if response.get("status") != "REQUIRES_ACTION":
            raise RuntimeError(f"Backboard run {response.get('status')}: {response.get('error') or response.get('content')}")
        run = response.get("run_id") or run
        if not run:  # checked before any tool runs: without it the outputs cannot be submitted
            raise RuntimeError("Backboard run REQUIRES_ACTION without a run_id: cannot submit tool outputs")
        for call in response["tool_calls"]:  # Backboard needs an output for every call of the round
            if call["id"] in answered:
                continue
            result = NOT_SENT
            if question is None:
                args, result = call_tool(req["tools_url"], call)
                if call["function"]["name"] == "ask_user" and result is not BAD_ARGS:
                    question = str(args.get("question") or "")
            answered[call["id"]] = json.dumps(result, ensure_ascii=False)
        outputs = [{"tool_call_id": call["id"], "output": answered[call["id"]]} for call in response["tool_calls"]]
        # not /threads/tool-outputs: it drops this message's tools, and the model then writes later calls as plain text
        response = backboard.send(f"/threads/{thread}/runs/{run}/submit-tool-outputs", {"tool_outputs": outputs, "tools": message["tools"]})
    return question or "Sorry, I could not finish that."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assistant-id", required=True, help="a dedicated Backboard assistant named bolibench-*")
    parser.add_argument("--provider", required=True, help="Backboard llm_provider, e.g. openrouter")
    parser.add_argument("--model", required=True, help="Backboard model_name, e.g. qwen/qwen3-235b-a22b-2507")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    api_key = os.environ.get("BACKBOARD_API_KEY")
    if not api_key:
        parser.error("BACKBOARD_API_KEY is not set")
    backboard = Backboard(api_key, args.assistant_id, args.provider, args.model)
    print(f"assistant {args.assistant_id} ({check_assistant(backboard)})")
    agent = identity(args.provider, args.model)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.send_json(413, {"error": f"body exceeds {MAX_BODY} bytes"})
            try:
                self.send_json(200, {"reply": turn(json.loads(self.rfile.read(length)), backboard), "agent": agent})
            except Exception as e:  # BoliBench records the 500 as an AdapterError: the case becomes `error`
                print(f"turn failed: {type(e).__name__}: {e}", file=sys.stderr)
                self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

        def send_json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    print(f"{agent['name']} {agent['version']} on http://127.0.0.1:{args.port}/turn")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
