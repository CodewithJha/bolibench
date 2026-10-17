import copy
import inspect
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from bolibench.models import CallStatus, InjectedFailure, RefusedRequest, ToolCall

BAD_ARGS = "bad arguments for"  # prefix of every rejection for arguments that do not fit the tool


class ToolError(Exception):
    pass


class OrderSandbox:
    """In-memory order store for one case. Every tool call is recorded here; the agent's own account is
    not evidence. Requests a gateway refused never reach `call`; they are kept apart in `refused`."""

    def __init__(self, initial_state: dict[str, Any], inject_failures: Iterable[InjectedFailure] = ()) -> None:
        self._state = copy.deepcopy(initial_state)
        self._failures = {(f.tool, f.call): f.error for f in inject_failures}
        self._counts: Counter[str] = Counter()
        self.tool_calls: list[ToolCall] = []
        self.refused: list[RefusedRequest] = []
        self._closed = False
        self._lock = threading.Lock()

    @property
    def state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def refuse(self, request: RefusedRequest) -> bool:
        """Record a refused request against this case; False if the case has already ended."""
        with self._lock:
            if not self._closed:
                self.refused.append(request)
            return not self._closed

    def close(self) -> list[RefusedRequest]:
        """End the case: later calls raise and later refusals are not recorded here."""
        with self._lock:
            self._closed = True
            return list(self.refused)

    # positional-only so agent args named "tool" or "turn" land in **args
    def call(self, tool: str, turn: int, /, **args: Any) -> ToolCall:
        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox is closed: its case has ended")
            return self._call(tool, turn, args)

    def _call(self, tool: str, turn: int, args: dict[str, Any]) -> ToolCall:
        self._counts[tool] += 1
        result = None
        error = self._failures.get((tool, self._counts[tool]))
        status: CallStatus = "ok" if error is None else "injected_failure"
        if error is None:
            try:
                result = self._run(tool, args)
            except ToolError as e:
                error, status = str(e), "rejected"
        record = ToolCall(turn=turn, tool=tool, args=copy.deepcopy(args), status=status, result=result, error=error)
        self.tool_calls.append(record)
        return record

    def _run(self, tool: str, args: dict[str, Any]) -> Any:
        fn = self._TOOLS.get(tool)
        if fn is None:
            raise ToolError(f"unknown tool: {tool}")
        try:
            inspect.signature(fn).bind(self, **args)
        except TypeError as e:
            raise ToolError(f"{BAD_ARGS} {tool}: {e}") from e
        return fn(self, **args)

    def _order(self, order_id: str) -> dict[str, Any]:
        for order in self._state.get("orders", []):
            if order.get("id") == order_id:
                return order
        raise ToolError(f"no such order: {order_id}")

    def _open_order(self, order_id: str, action: str) -> dict[str, Any]:
        order = self._order(order_id)
        if order.get("status") != "placed":
            raise ToolError(f"cannot {action} {order_id}: status is {order.get('status')}")
        return order

    def _list_orders(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._state.get("orders", []))

    def _get_order(self, order_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._order(order_id))

    def _cancel_order(self, order_id: str) -> dict[str, Any]:
        order = self._open_order(order_id, "cancel")
        order["status"] = "cancelled"
        return copy.deepcopy(order)

    def _update_quantity(self, order_id: str, quantity: int) -> dict[str, Any]:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ToolError(f"{BAD_ARGS} update_quantity: quantity must be a positive integer, got {quantity!r}")
        order = self._open_order(order_id, "update")
        order["quantity"] = quantity
        return copy.deepcopy(order)

    def _ask_user(self, kind: str, question: str) -> None:
        if kind not in ("confirm", "clarify"):
            raise ToolError(f"ask_user kind must be confirm or clarify, got {kind!r}")

    _TOOLS: dict[str, Callable[..., Any]] = {
        "list_orders": _list_orders,
        "get_order": _get_order,
        "cancel_order": _cancel_order,
        "update_quantity": _update_quantity,
        "ask_user": _ask_user,
    }
