from dataclasses import dataclass, field
from typing import Any, Protocol

from bolibench.models import AdapterInfo, CaseContext, Model
from bolibench.sandbox import OrderSandbox


class AdapterError(Exception):
    """The one failure an adapter may report; the runner turns it into an `error` verdict, never `fail`."""


class AgentAdapter(Protocol):
    info: AdapterInfo
    # True only if every tool the agent uses goes through the given sandbox. Otherwise the sandbox log
    # is a partial view and is not recorded as evidence.
    exposes_tool_calls: bool

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        """Handle one user turn, calling tools via `sandbox.call(tool, turn, **args)`; return the reply.

        `context` is the same frozen object on every turn of a case. Expectations are never passed in.
        """
        ...


class Call(Model):
    tool: str
    args: dict[str, Any] = {}


class Reply(Model):
    text: str


class Fail(Model):
    reason: str


Step = Call | Reply | Fail


@dataclass
class FakeAgentAdapter:
    """Scripted test harness, not an agent: replays fixed steps per turn and never reads the utterance."""

    script: list[list[Step]]  # one list of steps per case turn
    exposes_tool_calls: bool = True
    info: AdapterInfo = field(default_factory=lambda: AdapterInfo(name="fake-scripted", version="1"))

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        replies: list[str] = []
        for step in self.script[turn]:
            match step:
                case Call():
                    sandbox.call(step.tool, turn, **step.args)
                case Reply():
                    replies.append(step.text)
                case Fail():
                    raise AdapterError(step.reason)
        return " ".join(replies)
