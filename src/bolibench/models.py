from datetime import date, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Tool = Literal["list_orders", "get_order", "cancel_order", "update_quantity", "ask_user"]
CallStatus = Literal["ok", "rejected", "injected_failure"]
AskKind = Literal["confirm", "clarify"]
CheckName = Literal["final_state", "required_actions", "forbidden_actions", "ask_policy", "evidence"]
Confidence = Literal["certain", "likely", "possible"]
Verdict = Literal["pass", "fail", "inconclusive", "error"]
Category = Literal[
    "speech_recognition",
    "intent_interpretation",
    "entity_resolution",
    "ambiguity_handling",
    "tool_selection",
    "tool_execution",
    "policy_violation",
    "state_transition",
    "recovery_failure",
    "insufficient_evidence",
    "unclassified",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionSpec(Model):
    tool: Tool
    args: dict[str, Any] = {}  # subset match; empty matches any call of `tool`
    # required_actions only: matching attempts (any status) beyond this many count as forbidden attempts
    max_attempts: int | None = Field(default=None, ge=1)


class InjectedFailure(Model):
    tool: Tool
    call: int = Field(ge=1)  # 1-based count of calls to `tool`
    error: str


class Expected(Model):
    final_state: dict[str, Any] = {}  # dotted path -> value; list items are addressed by their "id"
    required_actions: list[ActionSpec] = []
    forbidden_actions: list[ActionSpec] = []
    ask_before: dict[Tool, AskKind] = {}
    # True: any cancel_order/update_quantity attempt matching no required spec counts as forbidden
    exclusive_actions: bool = False

    @model_validator(mode="after")
    def _max_attempts_only_on_required(self) -> "Expected":
        if any(s.max_attempts is not None for s in self.forbidden_actions):
            raise ValueError("max_attempts is only allowed on required_actions")
        return self


class Review(Model):
    """Human review state. Evaluator-only: never passed to adapters. Absent = nothing reviewed."""

    behavior: Literal["unreviewed", "reviewed", "needs_changes"] = "unreviewed"  # expected behavior, internal
    linguistic: Literal["unreviewed", "native_reviewed", "needs_changes"] = "unreviewed"  # native speaker
    language_claim: str | None = None
    notes: str | None = None
    reviewer: str | None = None


class CaseContext(Model):
    """Everything an adapter may see besides the utterances. Unset fields stay None; nothing is inferred."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    today: date | None = None
    policy: str | None = None


class TestCase(Model):
    __test__: ClassVar[bool] = False  # keep pytest from collecting this as a test class

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    status: Literal["proposed", "trusted"]
    tags: list[str] = []
    turns: list[str] = Field(min_length=1)
    context: CaseContext = Field(default_factory=CaseContext)
    initial_state: dict[str, Any]  # sandbox-only; reachable by the agent solely through tools
    expected: Expected
    inject_failures: list[InjectedFailure] = []
    provenance: str
    derived_from_run: str | None = None
    checks: list[CheckName] | None = Field(default=None, min_length=1)  # None = all checks
    review: Review = Field(default_factory=Review)

    @model_validator(mode="after")
    def _trusted_needs_both_reviews(self) -> "TestCase":
        if self.status == "trusted" and (self.review.behavior, self.review.linguistic) != ("reviewed", "native_reviewed"):
            raise ValueError("status 'trusted' requires review.behavior 'reviewed' and review.linguistic 'native_reviewed'")
        return self


class ToolCall(Model):
    """One attempted call. Order is position in RunRecord.tool_calls."""

    turn: int = Field(ge=0)  # index into the case's turns
    tool: str
    args: dict[str, Any] = {}
    status: CallStatus = "ok"
    result: Any | None = None
    error: str | None = None  # rejection reason or injected error

    @model_validator(mode="after")
    def _error_iff_not_ok(self) -> "ToolCall":
        if (self.status == "ok") != (self.error is None):
            raise ValueError("error must be set exactly when status is not 'ok'")
        return self


class RefusedRequest(Model):
    """A tool request the gateway refused (never executed). Diagnostics only, never a tool-call attempt."""

    status: int  # HTTP status sent back
    reason: str
    tool: str | None = None  # requested tool name if the body parsed; args are never kept
    token_turn: int | None = None  # turn the token was issued for; None = unknown token
    token_age_s: float | None = None


class TurnRecord(Model):
    user_input: str
    asr_text: str | None = None
    agent_reply: str


class AdapterInfo(Model):
    name: str
    version: str
    config: dict[str, Any] = {}  # must not contain credentials
    seed: int | None = None


class RunRecord(Model):
    """Execution evidence for one case. The final agent response is turns[-1].agent_reply."""

    run_id: str
    case_id: str
    adapter: AdapterInfo
    started_at: datetime
    finished_at: datetime | None = None
    turns: list[TurnRecord] = []
    tool_calls: list[ToolCall] = []
    final_state: dict[str, Any] | None = None  # None = not observed
    exposes_tool_calls: bool  # False = tool_calls is not evidence that nothing was called
    execution_error: str | None = None
    refused_requests: list[RefusedRequest] = []  # any entry makes execution_error set


class CheckResult(Model):
    metric: CheckName
    verdict: Literal["pass", "fail", "inconclusive"]
    evidence: list[str] = []
    detail: str = ""


class Classification(Model):
    category: Category
    stage: str
    evidence: list[str]
    method: Literal["deterministic", "model"]
    confidence: Confidence


class Evaluation(Model):
    verdict: Verdict
    checks: list[CheckResult]
    classifications: list[Classification]


class Summary(Model):
    """`summary.json` of one `bolibench run`, derived only from the artifacts written in that run."""

    total: int
    counts: dict[Verdict, int]
    cases: dict[str, Verdict]
    adapters: list[AdapterInfo]  # distinct adapter infos across the run's artifacts
    config_id: str  # sha256 prefix of `adapters` (agent URL/script path, timeouts)


class Artifact(Model):
    """What `bolibench run` writes per case: the execution evidence and its judgement."""

    schema_version: Literal[1] = 1
    case_id: str
    run: RunRecord
    evaluation: Evaluation
