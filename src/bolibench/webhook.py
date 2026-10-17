"""Webhook adapter: an external agent gets each turn over HTTP and calls sandbox tools back through a
BoliBench-run gateway, so every tool attempt is recorded by the sandbox, not reported by the agent.

Localhost binding is a development safeguard, not a security boundary, and the per-turn token only
scopes calls to the active turn; neither is authentication.

Lifecycle: a call is executed only if its token is the active turn's, checked under the same lock
that serializes execution, so every accepted call belongs to exactly one case and turn. The token is
invalidated under that lock before respond() returns, raises, or gives up at the turn deadline.
Everything else is refused, never executed, and kept as a RefusedRequest: on the owning case's
sandbox while that case runs (the run becomes `error`), otherwise in `stray_calls`.
"""

import http.client
import inspect
import json
import secrets
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from pydantic import Field, ValidationError

from bolibench.adapters import AdapterError
from bolibench.models import AdapterInfo, AgentIdentity, CaseContext, Model, RefusedRequest
from bolibench.sandbox import OrderSandbox

BAD_JSON = object()
MAX_BODY = 64 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TOOL_ARGS = {name: list(inspect.signature(fn).parameters)[1:] for name, fn in OrderSandbox._TOOLS.items()}


class ToolRequest(Model):
    tool: str = Field(max_length=64)
    args: dict[str, Any] = {}


class TurnReply(Model):
    reply: str
    agent: AgentIdentity | None = None


def handle_tool_request(sandbox: OrderSandbox, turn: int, payload: Any) -> tuple[int, dict[str, Any]]:
    """Transport-neutral gateway core. A malformed request (400) is not a tool attempt and is not recorded;
    a well-formed one always is, and the sandbox rejects unknown tools and bad arguments itself."""
    try:
        request = ToolRequest.model_validate(payload)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'body'}: {err['msg']}" for err in e.errors())
        return 400, {"error": f"malformed tool request: {problems}"}
    call = sandbox.call(request.tool, turn, **request.args)
    # rejected and injected failures look the same to the agent: injection must not be detectable
    return 200, {"ok": call.status == "ok", "result": call.result, "error": call.error}


def check_agent_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS or parts.username or parts.password:
        raise ValueError(f"agent URL must be http:// on 127.0.0.1, localhost or [::1], without credentials: {url!r}")
    parts.port  # raises ValueError on a malformed port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect could leave localhost; urllib then raises HTTPError


class WebhookAgentAdapter:
    """Sends each turn to `agent_url` and serves a tool gateway on 127.0.0.1. Use as a context manager."""

    exposes_tool_calls = True  # the sandbox is in-process and the gateway is the only way to reach it

    def __init__(self, agent_url: str, timeout: float = 30.0, tool_read_timeout: float = 5.0) -> None:
        check_agent_url(agent_url)
        self.agent_url = agent_url
        self.timeout = timeout  # whole-turn deadline
        self._base_info = AdapterInfo(name="webhook", version="1", config={"agent_url": agent_url, "timeout": timeout})
        self.info = self._base_info  # per case: plus the identity the agent reported on turn 0
        # refused requests no running case can own: unknown tokens, or tokens of a case that has ended
        self.stray_calls: list[RefusedRequest] = []
        self._lock = threading.Lock()
        self._active: tuple[str, int, OrderSandbox] | None = None
        # ponytail: one entry per turn ever served, never pruned; fine for suite-sized runs
        self._issued: dict[str, tuple[OrderSandbox, int, float]] = {}
        self._crash: Exception | None = None
        self._conversation = ""
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self, tool_read_timeout))
        self._server.daemon_threads = True
        # close() blocks for up to one poll interval
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    @property
    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "WebhookAgentAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        if turn == 0:
            self._conversation = secrets.token_hex(8)
            self.info = self._base_info  # a case that fails before any reply has no identity
        token = secrets.token_urlsafe(16)
        payload = {
            "conversation": self._conversation,
            "turn": turn,
            "utterance": utterance,
            "context": context.model_dump(mode="json"),
            "tools_url": f"{self.gateway_url}/runs/{token}/tools",
            "tools": TOOL_ARGS,
        }
        with self._lock:
            self._active = (token, turn, sandbox)
            self._issued[token] = (sandbox, turn, time.monotonic())
        # the turn runs on a worker so it can be abandoned at the deadline; an abandoned worker ends
        # by its own socket timeout and its late reply is discarded
        pool = ThreadPoolExecutor(1)
        future = pool.submit(self._post_turn, payload)
        pool.shutdown(wait=False)
        try:
            reply: TurnReply | None = future.result(timeout=self.timeout)
        except FutureTimeout:
            reply = None
        finally:
            with self._lock:  # token dies before respond returns or raises: later calls get 409
                self._active = None
                crash, self._crash = self._crash, None
        if crash is not None:
            raise crash
        if reply is None:
            raise AdapterError(f"turn deadline exceeded: no reply within {self.timeout}s")
        if turn == 0:
            self.info = self._base_info.model_copy(update={"self_reported_agent": reply.agent})
        elif reply.agent != self.info.self_reported_agent:
            # one case must be attributable to one agent identity
            raise AdapterError(f"agent identity changed on turn {turn}: {self.info.self_reported_agent} -> {reply.agent}")
        return reply.reply

    def _post_turn(self, payload: dict[str, Any]) -> TurnReply:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.agent_url, data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            # +1s so the turn deadline, not a socket timeout, is what a stalled agent hits first
            with self._opener.open(request, timeout=self.timeout + 1) as response:
                body = response.read(MAX_BODY + 1)
        except (OSError, http.client.HTTPException) as e:  # URLError, HTTPError and timeouts are OSErrors
            raise AdapterError(f"agent request failed: {e}") from e
        if len(body) > MAX_BODY:
            raise AdapterError(f"agent reply exceeds {MAX_BODY} bytes")
        try:
            return TurnReply.model_validate_json(body)
        except ValidationError as e:
            raise AdapterError(f"bad agent reply: {e.errors()[0]['msg']}") from e

    def dispatch(self, path: str, length: str | None, body: BinaryIO) -> tuple[int, dict[str, Any]]:
        parts = path.split("/")
        if len(parts) != 4 or parts[:2] != ["", "runs"] or parts[3] != "tools":
            return 404, {"error": "unknown endpoint"}
        token = parts[2]
        if length is None or not length.isdigit():
            return self._refuse(token, 411, "Content-Length required")
        if int(length) > MAX_BODY:
            return self._refuse(token, 413, f"body exceeds {MAX_BODY} bytes")
        raw = body.read(int(length))
        try:
            payload: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            payload = BAD_JSON
        with self._lock:
            if self._active is None or not secrets.compare_digest(token, self._active[0]):
                return self._refuse_locked(token, 409, "tool request outside an active turn", payload)
            if payload is BAD_JSON:
                return self._refuse_locked(token, 400, "body is not valid JSON", None)
            _, turn, sandbox = self._active
            try:
                status, response = handle_tool_request(sandbox, turn, payload)
            except Exception as e:  # not swallowed: respond() re-raises it on the runner's thread
                self._crash = e
                return 500, {"error": "internal error"}
            if status != 200:
                return self._refuse_locked(token, status, response["error"], payload)
            return status, response

    def _refuse(self, token: str, status: int, reason: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            return self._refuse_locked(token, status, reason, None)

    def _refuse_locked(self, token: str, status: int, reason: str, payload: Any) -> tuple[int, dict[str, Any]]:
        """Attribute a refusal to the case its token was issued for, while that case is still running;
        otherwise it is a stray. Only the tool name is kept: args may hold anything."""
        tool = payload.get("tool") if isinstance(payload, dict) else None
        entry = RefusedRequest(status=status, reason=reason, tool=tool[:64] if isinstance(tool, str) else None)
        issued = self._issued.get(token)
        if issued is not None:
            entry.token_turn = issued[1]
            entry.token_age_s = round(time.monotonic() - issued[2], 3)
        if issued is None or not issued[0].refuse(entry):
            self.stray_calls.append(entry)
        return status, {"error": reason}


def _handler(adapter: WebhookAgentAdapter, read_timeout: float) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        timeout = read_timeout  # per socket read, so a stalled client cannot hold a worker forever

        def do_POST(self) -> None:
            status, response = adapter.dispatch(self.path, self.headers.get("Content-Length"), self.rfile)
            data = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler
