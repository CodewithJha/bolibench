import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, get_args
from urllib.parse import urlsplit

import pytest

from bolibench.cli import main
from bolibench.evaluate import evaluate
from bolibench.models import AdapterInfo, AgentIdentity, CaseContext, Evaluation, Review, RunRecord, TestCase, Tool
from bolibench.runner import run_case
from bolibench.sandbox import OrderSandbox
from bolibench.store import load_case
from bolibench.webhook import MAX_BODY, TOOL_ARGS, WebhookAgentAdapter, check_agent_url, handle_tool_request

SUITE = Path(__file__).parent.parent / "suites" / "orders"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TURN_KEYS = {"conversation", "turn", "utterance", "context", "tools_url", "tools"}
# raw (status, headers, body) or a JSON object sent with 200
Behavior = Callable[[dict[str, Any]], dict[str, Any] | tuple[int, dict[str, str], bytes]]


def post(url: str, body: bytes | dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def tool(req: dict[str, Any], name: str, **args: Any) -> tuple[int, dict[str, Any]]:
    return post(req["tools_url"], {"tool": name, "args": args})


@contextmanager
def fake_agent(behavior: Behavior) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """An external agent on 127.0.0.1: `behavior` sees each turn request and may call tools_url."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(request)
            out = behavior(request)
            status, headers, data = out if isinstance(out, tuple) else (200, {}, json.dumps(out).encode())
            try:
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the adapter gave up (timeout test)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/turn", seen
    finally:
        server.shutdown()
        server.server_close()


def play(case: str | TestCase, behavior: Behavior, timeout: float = 2.0) -> tuple[RunRecord, Evaluation, list[dict[str, Any]]]:
    case = case if isinstance(case, TestCase) else load_case(SUITE / f"{case}.json")
    with fake_agent(behavior) as (url, seen), WebhookAgentAdapter(url, timeout=timeout) as adapter:
        record = run_case(case, adapter)
    return record, evaluate(case, record), seen


def verdicts(result: Evaluation) -> dict[str, str]:
    return {c.metric: c.verdict for c in result.checks}


def test_successful_calls_pass_and_turn_payload_has_no_evaluator_fields() -> None:
    responses: list[tuple[int, dict[str, Any]]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        if req["turn"] == 0:
            responses.append(tool(req, "list_orders"))
            responses.append(tool(req, "ask_user", kind="confirm", question="Kurta वाला cancel कर दूँ?"))
            return {"reply": "पिछला वाला Kurta order cancel कर दूँ?"}
        responses.append(tool(req, "cancel_order", order_id="ORD-101"))
        return {"reply": "हो गया"}

    record, result, seen = play("ambiguous-previous-order", agent)
    assert result.verdict == "pass" and verdicts(result)["required_actions"] == "pass"
    assert [(c.turn, c.tool, c.status) for c in record.tool_calls] == [
        (0, "list_orders", "ok"),
        (0, "ask_user", "ok"),
        (1, "cancel_order", "ok"),
    ]
    assert [s for s, _ in responses] == [200, 200, 200] and responses[2][1]["result"]["status"] == "cancelled"
    assert [t.agent_reply for t in record.turns] == ["पिछला वाला Kurta order cancel कर दूँ?", "हो गया"]
    assert all(set(r) == TURN_KEYS for r in seen)
    assert seen[0]["conversation"] == seen[1]["conversation"] and seen[0]["tools_url"] != seen[1]["tools_url"]
    assert all(r["context"] == {"today": None, "policy": None} for r in seen)
    assert seen[0]["tools"] == TOOL_ARGS and record.adapter.name == "webhook"


def test_context_reaches_the_agent_unchanged() -> None:
    _, _, seen = play("awadhi-cancel-yesterday", lambda req: {"reply": "?"})
    assert seen[0]["context"] == {"today": "2026-10-17", "policy": None}
    _, _, seen = play("forbidden-bulk-cancel", lambda req: {"reply": "?"})
    assert seen[0]["context"]["policy"].startswith("Bulk cancellation is not allowed")
    text = json.dumps(seen)
    assert "expected" not in text and "forbidden" not in text and "ORD-131" not in text
    reviewed = load_case(SUITE / "cancel-single-order.json").model_copy(update={"review": Review(notes="REVIEW-NOTE-XYZ")})
    _, _, seen = play(reviewed, lambda req: {"reply": "?"})
    assert "review" not in json.dumps(seen) and "XYZ" not in json.dumps(seen)


def test_rejected_forbidden_attempt_is_forbidden_and_does_not_mutate() -> None:
    responses: list[tuple[int, dict[str, Any]]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        responses.append(tool(req, "cancel_order", order_id="ORD-999"))
        return {"reply": "सब cancel हो गया"}

    record, result, _ = play("forbidden-bulk-cancel", agent)
    assert responses == [(200, {"ok": False, "result": None, "error": "no such order: ORD-999"})]
    assert record.tool_calls[0].status == "rejected"
    assert record.final_state == load_case(SUITE / "forbidden-bulk-cancel.json").initial_state
    assert verdicts(result)["forbidden_actions"] == "fail" and verdicts(result)["final_state"] == "pass"
    assert [(c.category, c.confidence) for c in result.classifications] == [("policy_violation", "certain")]


def test_invalid_args_and_unknown_tools_are_recorded_rejections() -> None:
    responses: list[tuple[int, dict[str, Any]]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        responses.append(tool(req, "cancel_order", id="ORD-201"))
        responses.append(tool(req, "delete_everything"))
        responses.append(tool(req, "__import__('os').system", cmd="rm -rf /"))
        responses.append(tool(req, "update_quantity", order_id="ORD-201", quantity="3"))
        return {"reply": "done"}

    record, result, _ = play("cancel-single-order", agent)
    assert [s for s, _ in responses] == [200] * 4 and not any(r["ok"] for _, r in responses)
    assert [c.status for c in record.tool_calls] == ["rejected"] * 4
    assert "bad arguments" in (record.tool_calls[0].error or "")
    assert record.tool_calls[1].error == "unknown tool: delete_everything"
    assert record.final_state == load_case(SUITE / "cancel-single-order.json").initial_state
    assert result.verdict == "fail" and record.execution_error is None


def test_injected_failure_is_indistinguishable_from_rejection_to_the_agent() -> None:
    responses: list[tuple[int, dict[str, Any]]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        responses.append(tool(req, "cancel_order", order_id="ORD-111"))
        responses.append(tool(req, "cancel_order", order_id="ORD-111"))
        return {"reply": "retry किया, हो गया"}

    record, result, _ = play("tool-failure-cancel", agent)
    assert set(responses[0][1]) == {"ok", "result", "error"} and responses[0][1]["ok"] is False
    assert [c.status for c in record.tool_calls] == ["injected_failure", "ok"]
    assert result.verdict == "pass"


def test_repeated_calls_are_recorded_in_order() -> None:
    def agent(req: dict[str, Any]) -> dict[str, Any]:
        for _ in range(3):
            tool(req, "cancel_order", order_id="ORD-201")
        return {"reply": "ok"}

    record, result, _ = play("cancel-single-order", agent)
    assert [c.status for c in record.tool_calls] == ["ok", "rejected", "rejected"]
    assert verdicts(result)["required_actions"] == "pass" and verdicts(result)["final_state"] == "pass"


def test_reply_claiming_success_without_tool_calls_fails() -> None:
    record, result, _ = play("cancel-single-order", lambda req: {"reply": "ORD-201 cancel कर दिया।"})
    assert record.tool_calls == [] and record.exposes_tool_calls
    assert verdicts(result)["required_actions"] == "fail" and verdicts(result)["final_state"] == "fail"


@pytest.mark.parametrize(
    "body,status",
    [
        (b"{not json", 400),
        (b"[" * 50_000, 400),
        (json.dumps({"tool": 1}).encode(), 400),
        (json.dumps({"tool": "cancel_order", "args": ["ORD-201"]}).encode(), 400),
        (json.dumps({"tool": "cancel_order", "args": {}, "note": "x"}).encode(), 400),
    ],
)
def test_malformed_tool_requests_are_not_recorded_and_error_the_run(body: bytes, status: int) -> None:
    responses: list[tuple[int, dict[str, Any]]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        responses.append(post(req["tools_url"], body))
        return {"reply": "ok"}

    record, result, _ = play("cancel-single-order", agent)
    assert responses[0][0] == status and record.tool_calls == []
    assert result.verdict == "error" and "turn 0:" in (record.execution_error or "")


def test_oversized_body_is_refused_unread() -> None:
    statuses: list[int] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        url = urlsplit(req["tools_url"])
        conn = http.client.HTTPConnection(url.hostname or "", url.port, timeout=2)
        conn.putrequest("POST", url.path)
        conn.putheader("Content-Length", str(MAX_BODY + 1))
        conn.endheaders()
        statuses.append(conn.getresponse().status)
        conn.close()
        return {"reply": "ok"}

    record, result, _ = play("cancel-single-order", agent)
    assert statuses == [413] and record.tool_calls == []
    assert result.verdict == "error" and "exceeds" in (record.execution_error or "")


CANCEL_201 = {"tool": "cancel_order", "args": {"order_id": "ORD-201"}}


def test_turn_deadline_is_error_and_later_calls_are_refused_without_mutation() -> None:
    release, done = threading.Event(), threading.Event()
    late: list[tuple[int, dict[str, Any]]] = []

    def stalled(req: dict[str, Any]) -> dict[str, Any]:
        release.wait(5)
        late.append(post(req["tools_url"], CANCEL_201))
        done.set()
        return {"reply": "हो गया"}

    case = load_case(SUITE / "cancel-single-order.json")
    with fake_agent(stalled) as (url, _), WebhookAgentAdapter(url, timeout=0.2) as adapter:
        started = time.monotonic()
        record = run_case(case, adapter)
        elapsed = time.monotonic() - started
        release.set()
        assert done.wait(5)
    assert record.execution_error == "AdapterError: turn deadline exceeded: no reply within 0.2s" and elapsed < 1
    assert evaluate(case, record).verdict == "error" and record.turns == []
    assert late[0][0] == 409 and record.tool_calls == [] and record.final_state == case.initial_state
    assert [(s.status, s.tool, s.token_turn) for s in adapter.stray_calls] == [(409, "cancel_order", 0)]


def test_calls_made_before_the_deadline_stay_in_the_log() -> None:
    release = threading.Event()

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        tool(req, "cancel_order", order_id="ORD-201")
        release.wait(5)
        return {"reply": "late"}

    try:
        record, result, _ = play("cancel-single-order", agent, timeout=0.2)
    finally:
        release.set()
    assert [(c.turn, c.status) for c in record.tool_calls] == [(0, "ok")]
    assert result.verdict == "error" and "turn deadline exceeded" in (record.execution_error or "")


def test_late_call_from_an_earlier_case_is_refused_and_next_case_is_unaffected() -> None:
    first_url: list[str] = []
    statuses: list[int] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        if not first_url:
            first_url.append(req["tools_url"])
            return {"reply": "?"}
        statuses.append(post(first_url[0], CANCEL_201)[0])
        statuses.append(tool(req, "cancel_order", order_id="ORD-201")[0])
        return {"reply": "हो गया"}

    case = load_case(SUITE / "cancel-single-order.json")
    with fake_agent(agent) as (url, _), WebhookAgentAdapter(url, timeout=2) as adapter:
        first = run_case(case, adapter)
        second = run_case(case, adapter)
    assert statuses == [409, 200]
    assert first.tool_calls == [] and first.refused_requests == [] and evaluate(case, first).verdict == "fail"
    assert second.execution_error is None and second.refused_requests == [] and evaluate(case, second).verdict == "pass"
    assert [(c.turn, c.tool, c.status) for c in second.tool_calls] == [(0, "cancel_order", "ok")]
    assert [(s.status, s.token_turn) for s in adapter.stray_calls] == [(409, 0)]


def test_call_between_turns_of_the_same_case_is_refused_and_errors_the_run() -> None:
    statuses: list[int] = []

    @dataclass
    class PokeBetweenTurns:
        inner: WebhookAgentAdapter
        seen: list[dict[str, Any]]
        exposes_tool_calls: bool = True

        @property
        def info(self) -> AdapterInfo:
            return self.inner.info

        def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
            if turn == 1:  # turn 0 has returned, turn 1 has not started
                statuses.append(post(self.seen[0]["tools_url"], {"tool": "cancel_order", "args": {"order_id": "ORD-101"}})[0])
            return self.inner.respond(turn, utterance, context, sandbox)

    case = load_case(SUITE / "ambiguous-previous-order.json")
    with fake_agent(lambda req: {"reply": "?"}) as (url, seen), WebhookAgentAdapter(url, timeout=2) as adapter:
        record = run_case(case, PokeBetweenTurns(adapter, seen))
    assert statuses == [409] and record.tool_calls == [] and len(record.turns) == 2
    assert [(r.status, r.tool, r.token_turn) for r in record.refused_requests] == [(409, "cancel_order", 0)]
    assert record.execution_error == "refused tool requests: turn 0: tool request outside an active turn"
    assert evaluate(case, record).verdict == "error" and adapter.stray_calls == []


def test_concurrent_requests_in_a_turn_are_serialized_in_arrival_order() -> None:
    barrier = threading.Barrier(5)
    responses: list[dict[str, Any]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        def fire() -> None:
            barrier.wait(5)
            responses.append(post(req["tools_url"], CANCEL_201)[1])

        threads = [threading.Thread(target=fire) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        return {"reply": "ok"}

    record, result, _ = play("cancel-single-order", agent)
    assert [c.status for c in record.tool_calls] == ["ok"] + ["rejected"] * 4
    assert sorted(r["ok"] for r in responses) == [False] * 4 + [True]
    assert result.verdict == "pass" and record.refused_requests == []


@pytest.mark.parametrize(
    "response",
    [
        (500, {}, b'{"reply": "x"}'),
        (200, {}, b"not json"),
        (200, {}, b'{"reply": "x", "tool_calls": [{"tool": "cancel_order"}]}'),
        (200, {}, b'{"text": "x"}'),
        (200, {}, b"x" * (MAX_BODY + 1)),
    ],
)
def test_agent_failures_are_errors(response: tuple[int, dict[str, str], bytes]) -> None:
    record, result, _ = play("cancel-single-order", lambda req: response)
    assert result.verdict == "error" and result.checks == [] and record.execution_error


def test_redirects_are_not_followed() -> None:
    with fake_agent(lambda req: {"reply": "followed"}) as (elsewhere, _):
        record, result, _ = play("cancel-single-order", lambda req: (307, {"Location": elsewhere}, b"{}"))
    assert result.verdict == "error" and record.turns == []


def test_stale_token_from_an_earlier_turn_is_rejected_and_errors_the_run() -> None:
    first_url: list[str] = []
    responses: list[tuple[int, dict[str, Any]]] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        if req["turn"] == 0:
            first_url.append(req["tools_url"])
            return {"reply": "पिछला वाला?"}
        responses.append(post(first_url[0], {"tool": "cancel_order", "args": {"order_id": "ORD-101"}}))
        return {"reply": "हो गया"}

    record, result, _ = play("ambiguous-previous-order", agent)
    assert responses[0][0] == 409 and record.tool_calls == []
    assert result.verdict == "error" and "outside an active turn" in (record.execution_error or "")
    [refused] = record.refused_requests
    assert (refused.status, refused.tool, refused.token_turn) == (409, "cancel_order", 0) and refused.token_age_s is not None
    assert "ORD-101" not in refused.model_dump_json()  # args are never kept


def test_calls_after_the_case_ended_are_rejected() -> None:
    with fake_agent(lambda req: {"reply": "ok"}) as (url, seen), WebhookAgentAdapter(url, timeout=2) as adapter:
        record = run_case(load_case(SUITE / "cancel-single-order.json"), adapter)
        status, _ = post(seen[0]["tools_url"], {"tool": "cancel_order", "args": {"order_id": "ORD-201"}})
        garbage, _ = post(seen[0]["tools_url"].replace("/runs/", "/runs/x"), {"tool": "list_orders"})
    assert status == 409 and garbage == 409 and record.tool_calls == [] and record.refused_requests == []
    assert [(s.tool, s.token_turn) for s in adapter.stray_calls] == [("cancel_order", 0), ("list_orders", None)]


def test_sandbox_bugs_propagate_from_gateway_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: OrderSandbox, tool: str, turn: int, /, **args: Any) -> None:
        raise RuntimeError("sandbox bug")

    monkeypatch.setattr(OrderSandbox, "call", broken)
    statuses: list[int] = []

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        statuses.append(tool(req, "list_orders")[0])
        return {"reply": "ok"}

    with pytest.raises(RuntimeError, match="sandbox bug"):
        play("cancel-single-order", agent)
    assert statuses == [500]


def test_core_handler_is_transport_neutral() -> None:
    sandbox = OrderSandbox({"orders": [{"id": "ORD-1", "status": "placed"}]})
    assert handle_tool_request(sandbox, 0, {"tool": "cancel_order", "args": {"order_id": "ORD-1"}})[0] == 200
    status, body = handle_tool_request(sandbox, 0, "cancel everything")
    assert status == 400 and "malformed" in body["error"]
    assert [c.status for c in sandbox.tool_calls] == ["ok"]


def test_registered_tools_match_the_tool_type() -> None:
    assert set(TOOL_ARGS) == set(get_args(Tool))
    assert TOOL_ARGS["update_quantity"] == ["order_id", "quantity"]


@pytest.mark.parametrize(
    "url",
    ["http://example.com/turn", "https://127.0.0.1/turn", "http://user:pw@127.0.0.1/turn", "http://127.0.0.1:x/", "file:///etc/passwd"],
)
def test_non_local_agent_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError):
        check_agent_url(url)


def test_cli_runs_a_case_against_a_webhook_agent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def agent(req: dict[str, Any]) -> dict[str, Any]:
        tool(req, "cancel_order", order_id="ORD-201")
        return {"reply": "हो गया"}

    with fake_agent(agent) as (url, _):
        code = main(["run", str(SUITE / "cancel-single-order.json"), "--agent-url", url, "--output", str(tmp_path)])
    assert code == 0 and "pass         cancel-single-order" in capsys.readouterr().out
    assert main(["run", str(SUITE), "--agent-url", "http://example.com/", "--output", str(tmp_path)]) == 2
    assert len(list(tmp_path.iterdir())) == 1


AGENT_ID = {"name": "test-agent", "version": "abc123+model"}


def test_self_reported_identity_is_recorded_per_case_and_absence_is_ok() -> None:
    replies = iter([{"reply": "x", "agent": AGENT_ID}, {"reply": "y"}])
    cases = [load_case(SUITE / "cancel-single-order.json"), load_case(SUITE / "tool-failure-cancel.json")]
    with fake_agent(lambda _: next(replies)) as (url, _), WebhookAgentAdapter(url, timeout=2.0) as adapter:
        first, second = run_case(cases[0], adapter), run_case(cases[1], adapter)
    assert first.execution_error is None and first.adapter.self_reported_agent == AgentIdentity(**AGENT_ID)
    assert json.loads(first.adapter.model_dump_json())["self_reported_agent"] == AGENT_ID
    assert second.execution_error is None and second.adapter.self_reported_agent is None
    assert "self_reported_agent" not in second.adapter.model_dump_json()  # absent: pre-identity JSON


@pytest.mark.parametrize(
    "agent",
    [
        {"name": "test-agent"},
        AGENT_ID | {"build": "x"},
        {"name": "x" * 65, "version": "1"},
        {"name": "test-agent", "version": "1\n"},
        "test-agent",
    ],
)
def test_malformed_identity_is_a_bad_reply_error(agent: object) -> None:
    record, result, _ = play("cancel-single-order", lambda _: {"reply": "x", "agent": agent})
    assert result.verdict == "error" and "bad agent reply" in (record.execution_error or "")
    assert record.adapter.self_reported_agent is None


@pytest.mark.parametrize("later", [AGENT_ID | {"version": "other"}, None])
def test_identity_change_between_turns_is_an_error(later: dict[str, str] | None) -> None:
    def agent(req: dict[str, Any]) -> dict[str, Any]:
        reported = AGENT_ID if req["turn"] == 0 else later
        return {"reply": "?"} | ({"agent": reported} if reported else {})

    record, result, _ = play("ambiguous-previous-order", agent)
    assert result.verdict == "error" and "agent identity changed on turn 1" in (record.execution_error or "")
    assert record.adapter.self_reported_agent == AgentIdentity(**AGENT_ID) and len(record.turns) == 1
    same, result, _ = play("ambiguous-previous-order", lambda _: {"reply": "?", "agent": AGENT_ID})
    assert same.execution_error is None and same.adapter.self_reported_agent == AgentIdentity(**AGENT_ID)


def test_config_id_follows_self_reported_version(tmp_path: Path) -> None:
    version = ["1"]
    ids: dict[str, str] = {}
    # one fake agent server, so the agent URL (part of config_id) is the same for every run
    with fake_agent(lambda _: {"reply": "x", "agent": AGENT_ID | {"version": version[0]}}) as (url, _):
        for out, version[0] in (("v1", "1"), ("v1-again", "1"), ("v2", "2")):
            main(["run", str(SUITE / "cancel-single-order.json"), "--agent-url", url, "--output", str(tmp_path / out)])
            [run_dir] = (tmp_path / out).iterdir()
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            assert summary["adapters"][0]["self_reported_agent"]["version"] == version[0]
            ids[out] = summary["config_id"]
    assert ids["v1"] == ids["v1-again"] != ids["v2"]


def test_cli_artifact_shows_turn_deadline_and_suite_continues(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    release = threading.Event()

    def agent(req: dict[str, Any]) -> dict[str, Any]:
        if "ORD-201" in req["utterance"]:
            release.wait(5)
            return {"reply": "late"}
        tool(req, "cancel_order", order_id="ORD-111")
        tool(req, "cancel_order", order_id="ORD-111")
        return {"reply": "हो गया"}

    cases = tmp_path / "cases"
    cases.mkdir()
    for name in ("cancel-single-order", "tool-failure-cancel"):
        (cases / f"{name}.json").write_bytes((SUITE / f"{name}.json").read_bytes())
    try:
        with fake_agent(agent) as (url, _):
            code = main(["run", str(cases), "--agent-url", url, "--timeout", "0.2", "--output", str(tmp_path / "out")])
    finally:
        release.set()
    [run_dir] = (tmp_path / "out").iterdir()
    timed_out = json.loads((run_dir / "cancel-single-order.json").read_text(encoding="utf-8"))
    assert code == 1 and timed_out["evaluation"]["verdict"] == "error"
    assert timed_out["run"]["execution_error"] == "AdapterError: turn deadline exceeded: no reply within 0.2s"
    assert timed_out["run"]["adapter"]["config"] == {"agent_url": url, "timeout": 0.2}
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["cases"] == {"cancel-single-order": "error", "tool-failure-cancel": "pass"}
    assert "error        cancel-single-order" in capsys.readouterr().out
