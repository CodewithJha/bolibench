"""Deterministic checks over recorded tool calls and sandbox state.

Semantics:
- required_actions are satisfied only by a successful (status "ok") matching call.
- forbidden_actions are violated by any matching attempt, whatever its status: the agent decided to
  do it, and a sandbox rejection or injected failure does not undo that decision.
- A required action's `max_attempts` counts matching attempts of any status; every attempt past it
  is treated exactly like a forbidden attempt (forbidden_actions check, one classification).
- `exclusive_actions`: every cancel_order/update_quantity attempt (any status) matching no required
  spec is treated exactly like a forbidden attempt. Read-only tools are never restricted. Such an
  attempt that the sandbox rejected for bad arguments, on a tool a required action uses, still fails
  forbidden_actions but is classified tool_execution (malformed call), not as a policy violation.
  So is every attempt of a tool name the sandbox does not register (e.g. `cancel_all_orders`),
  classified tool_selection (certain).
- recovery_failure is only for an injected failure with no later successful call of the same tool
  and args.
- final_state is judged on its own; rejected and injected-failure calls never mutate state.
- ask_policy is about ordering: the first attempt of the tool (whatever its status) must be preceded
  by a successful ask_user of the right kind in an earlier turn. If the tool is never attempted the
  ordering holds; whether it should have been called is required_actions' job.
- Checks that need tool calls are inconclusive when the adapter does not expose them, and
  final_state is inconclusive when no state was observed. Missing evidence never passes.
"""

from collections.abc import Callable
from typing import Any, get_args

from bolibench.models import (
    ActionSpec,
    Category,
    CheckResult,
    Classification,
    Confidence,
    Evaluation,
    RunRecord,
    TestCase,
    Tool,
    ToolCall,
)
from bolibench.sandbox import BAD_ARGS

MISSING = object()
READ_ONLY = {"list_orders", "get_order", "ask_user"}
TOOLS = set(get_args(Tool))
CONSEQUENTIAL = TOOLS - READ_ONLY
AMBIGUITY_TAGS = {"ambiguous_reference", "missing_information"}
NO_CALLS = "adapter does not expose tool calls"
STAGE: dict[Category, str] = {
    "speech_recognition": "asr",
    "intent_interpretation": "understanding",
    "entity_resolution": "understanding",
    "ambiguity_handling": "dialogue",
    "tool_selection": "planning",
    "policy_violation": "planning",
    "tool_execution": "execution",
    "state_transition": "execution",
    "recovery_failure": "execution",
    "insufficient_evidence": "evaluation",
    "unclassified": "unknown",
}
RANK: dict[Confidence, int] = {"possible": 0, "likely": 1, "certain": 2}


def resolve(state: Any, path: str) -> Any:
    """Follow a dotted path like `orders.ORD-101.status`; list items are addressed by their "id"."""
    node = state
    for key in path.split("."):
        if isinstance(node, dict):
            node = node.get(key, MISSING)
        elif isinstance(node, list):
            node = next((x for x in node if isinstance(x, dict) and x.get("id") == key), MISSING)
        else:
            return MISSING
    return node


def _matches(spec: ActionSpec, call: ToolCall) -> bool:
    return call.tool == spec.tool and spec.args.items() <= call.args.items()


def _succeeded(run: RunRecord) -> list[tuple[int, ToolCall]]:
    return [(i, c) for i, c in enumerate(run.tool_calls) if c.status == "ok"]


def _unmet(case: TestCase, run: RunRecord) -> list[tuple[int, ActionSpec]]:
    done = _succeeded(run)
    return [(j, s) for j, s in enumerate(case.expected.required_actions) if not any(_matches(s, c) for _, c in done)]


def _forbidden_hits(case: TestCase, run: RunRecord) -> list[int]:
    calls, required = run.tool_calls, case.expected.required_actions
    hits = {i for i, c in enumerate(calls) if any(_matches(s, c) for s in case.expected.forbidden_actions)}
    if case.expected.exclusive_actions:
        hits.update(
            i
            for i, c in enumerate(calls)
            if c.tool not in TOOLS or (c.tool in CONSEQUENTIAL and not any(_matches(s, c) for s in required))
        )
    for spec in required:
        if spec.max_attempts is not None:
            hits.update([i for i, c in enumerate(calls) if _matches(spec, c)][spec.max_attempts :])
    return sorted(hits)


def _malformed(case: TestCase, call: ToolCall) -> bool:
    """An exclusive_actions-only hit the sandbox rejected for bad arguments, on a tool a required action uses."""
    e = case.expected
    return (
        call.status == "rejected"
        and (call.error or "").startswith(BAD_ARGS)
        and any(s.tool == call.tool for s in e.required_actions)
        and not any(_matches(s, call) for s in e.required_actions + e.forbidden_actions)
    )


def _refs(indexes: list[int]) -> list[str]:
    return [f"tool_calls[{i}]" for i in indexes]


def _inconclusive(metric: str, missing: str, detail: str) -> CheckResult:
    return CheckResult(metric=metric, verdict="inconclusive", evidence=[missing], detail=detail)


def check_final_state(case: TestCase, run: RunRecord) -> CheckResult:
    if run.final_state is None:
        return _inconclusive("final_state", "final_state", "run has no final_state")
    expected = case.expected.final_state
    wrong = [(p, want, got) for p, want in expected.items() if (got := resolve(run.final_state, p)) != want]
    if wrong:
        return CheckResult(
            metric="final_state",
            verdict="fail",
            evidence=[f"final_state.{p}" for p, _, _ in wrong],
            detail="; ".join(f"{p}: expected {w!r}, got {'<missing>' if g is MISSING else repr(g)}" for p, w, g in wrong),
        )
    return CheckResult(
        metric="final_state",
        verdict="pass",
        evidence=[f"final_state.{p}" for p in expected],
        detail=f"{len(expected)} paths match",
    )


def check_required_actions(case: TestCase, run: RunRecord) -> CheckResult:
    if not run.exposes_tool_calls:
        return _inconclusive("required_actions", "tool_calls", NO_CALLS)
    if unmet := _unmet(case, run):
        return CheckResult(
            metric="required_actions",
            verdict="fail",
            evidence=[f"expected.required_actions[{j}]" for j, _ in unmet],
            detail="no successful call for: " + ", ".join(f"{s.tool} {s.args}" for _, s in unmet),
        )
    done = _succeeded(run)
    hits = [next(i for i, c in done if _matches(s, c)) for s in case.expected.required_actions]
    return CheckResult(metric="required_actions", verdict="pass", evidence=_refs(hits), detail=f"{len(hits)} succeeded")


def check_forbidden_actions(case: TestCase, run: RunRecord) -> CheckResult:
    if not run.exposes_tool_calls:
        return _inconclusive("forbidden_actions", "tool_calls", NO_CALLS)
    if hits := _forbidden_hits(case, run):
        calls = [run.tool_calls[i] for i in hits]
        detail = "forbidden calls (incl. past max_attempts or outside exclusive_actions) made: " + ", ".join(f"{c.tool} {c.args} ({c.status})" for c in calls)
        return CheckResult(metric="forbidden_actions", verdict="fail", evidence=_refs(hits), detail=detail)
    return CheckResult(metric="forbidden_actions", verdict="pass", evidence=["tool_calls"], detail="none attempted")


def check_ask_policy(case: TestCase, run: RunRecord) -> CheckResult:
    if not run.exposes_tool_calls:
        return _inconclusive("ask_policy", "tool_calls", NO_CALLS)
    calls = run.tool_calls
    evidence: list[str] = []
    violations: list[int] = []
    problems: list[str] = []
    for tool, kind in case.expected.ask_before.items():
        first = next((i for i, c in enumerate(calls) if c.tool == tool), None)
        if first is None:
            continue
        # the ask must be in an earlier turn: asking and acting in the same turn ignores the answer
        ask = next(
            (
                i
                for i, c in enumerate(calls[:first])
                if c.tool == "ask_user" and c.status == "ok" and c.args.get("kind") == kind and c.turn < calls[first].turn
            ),
            None,
        )
        if ask is None:
            violations.append(first)
            problems.append(f"no ask_user({kind}) in a turn before {tool} at tool_calls[{first}]")
        else:
            evidence += _refs([ask, first])
    if violations:
        return CheckResult(metric="ask_policy", verdict="fail", evidence=_refs(violations), detail="; ".join(problems))
    return CheckResult(metric="ask_policy", verdict="pass", evidence=evidence, detail="asks precede actions")


def check_evidence(case: TestCase, run: RunRecord) -> CheckResult:
    missing = [name for name, ok in (("tool_calls", run.exposes_tool_calls), ("final_state", run.final_state is not None)) if not ok]
    if missing:
        return CheckResult(metric="evidence", verdict="inconclusive", evidence=missing, detail="missing: " + ", ".join(missing))
    return CheckResult(metric="evidence", verdict="pass", evidence=["tool_calls", "final_state"], detail="tool calls and state recorded")


CHECKS: dict[str, Callable[[TestCase, RunRecord], CheckResult]] = {
    "final_state": check_final_state,
    "required_actions": check_required_actions,
    "forbidden_actions": check_forbidden_actions,
    "ask_policy": check_ask_policy,
    "evidence": check_evidence,
}


def evaluate(case: TestCase, run: RunRecord) -> Evaluation:
    if run.case_id != case.id:
        raise ValueError(f"run {run.run_id} is for case {run.case_id!r}, not {case.id!r}")
    if run.execution_error is not None:
        return Evaluation(verdict="error", checks=[], classifications=[])
    checks = [CHECKS[name](case, run) for name in case.checks or CHECKS]
    verdicts = {c.verdict for c in checks}
    verdict = "fail" if "fail" in verdicts else "inconclusive" if "inconclusive" in verdicts else "pass"
    return Evaluation(verdict=verdict, checks=checks, classifications=classify(case, run, checks))


def _misread(spec: ActionSpec, call: ToolCall) -> Category:
    if "order_id" in spec.args and call.args.get("order_id") != spec.args["order_id"]:
        return "entity_resolution"
    return "intent_interpretation"


def classify(case: TestCase, run: RunRecord, checks: list[CheckResult]) -> list[Classification]:
    """Fixed rules mapping failed/inconclusive checks to failure categories. ASR rules are not applied yet."""
    found: dict[str, Classification] = {}
    covered: set[str] = set()

    def add(category: Category, evidence: list[str], confidence: Confidence, *covers: str) -> None:
        covered.update(covers)
        if (c := found.get(category)) is None:
            found[category] = Classification(
                category=category, stage=STAGE[category], evidence=evidence, method="deterministic", confidence=confidence
            )
            return
        c.evidence += [e for e in evidence if e not in c.evidence]
        if RANK[confidence] > RANK[c.confidence]:
            c.confidence = confidence

    by_metric = {c.metric: c for c in checks}
    failed = {m for m, c in by_metric.items() if c.verdict == "fail"}
    for c in checks:
        if c.verdict == "inconclusive":
            add("insufficient_evidence", c.evidence, "certain")
    if not failed:
        return list(found.values())

    calls = run.tool_calls
    done = _succeeded(run)
    ambiguous = bool(AMBIGUITY_TAGS & set(case.tags))
    ask_category: Category = "ambiguity_handling" if ambiguous else "policy_violation"
    unmet = _unmet(case, run) if "required_actions" in failed else []
    # A forbidden attempt is explained by its forbidden-action category; its rejection or injected
    # failure is a symptom of the same decision, not a separate tool_execution/recovery failure.
    forbidden = _forbidden_hits(case, run) if "forbidden_actions" in failed else []
    malformed = [i for i in forbidden if _malformed(case, calls[i])]
    unknown = [i for i in forbidden if calls[i].tool not in TOOLS]
    # successful consequential calls that satisfy no required action, and attempts of unregistered
    # tools: what a wrong tool choice looks like
    others = sorted(unknown + [i for i, c in done if c.tool in CONSEQUENTIAL and not any(_matches(s, c) for s in case.expected.required_actions)])
    substitutes: set[int] = set()

    if "ask_policy" in failed:
        add(ask_category, by_metric["ask_policy"].evidence, "likely" if ambiguous else "certain", "ask_policy")

    for j, spec in unmet:
        ref = f"expected.required_actions[{j}]"
        same = [i for i, c in enumerate(calls) if c.tool == spec.tool and (c.status == "ok" or i in forbidden) and i not in malformed]
        errored = [i for i, c in enumerate(calls) if c.tool == spec.tool and c.status == "rejected" and (i not in forbidden or i in malformed)]
        if spec.tool == "ask_user":
            add(ask_category, [ref], "likely", "required_actions")
        elif same:
            for i in same:
                add(_misread(spec, calls[i]), [ref, *_refs([i])], "likely", "required_actions")
        elif errored:
            add("tool_execution", [ref, *_refs(errored)], "likely", "required_actions")
        elif others and not any(c.tool == spec.tool for c in calls):  # an attempted tool was selected
            substitutes.update(others)
            add("tool_selection", [ref, *_refs(others)], "likely", "required_actions")

    for i in forbidden:
        spec = next((s for _, s in unmet if s.tool == calls[i].tool), None)
        if i in malformed:
            add("tool_execution", _refs([i]), "likely", "forbidden_actions")
        elif i in unknown:
            add("tool_selection", _refs([i]), "certain", "forbidden_actions")
        elif i in substitutes:
            add("tool_selection", _refs([i]), "likely", "forbidden_actions")
        elif spec is not None:
            add(_misread(spec, calls[i]), _refs([i]), "likely", "forbidden_actions")
        elif ambiguous:
            add("ambiguity_handling", _refs([i]), "likely", "forbidden_actions")
        else:
            add("policy_violation", _refs([i]), "certain", "forbidden_actions")

    if rejected := [i for i, c in enumerate(calls) if c.status == "rejected" and i not in forbidden]:
        add("tool_execution", _refs(rejected), "likely")

    # recovered = a later call with the same tool and args succeeded
    injected = [
        i
        for i, c in enumerate(calls)
        if c.status == "injected_failure"
        and i not in forbidden
        and not any(d.status == "ok" and d.tool == c.tool and d.args == c.args for d in calls[i + 1 :])
    ]
    if case.inject_failures and injected:
        add("recovery_failure", _refs(injected), "likely", *failed)

    if "final_state" in failed and "final_state" not in covered:
        if failed == {"final_state"}:
            add("state_transition", by_metric["final_state"].evidence, "likely", "final_state")
        elif covered:
            covered.add("final_state")  # downstream of an already-classified failure

    for metric in sorted(failed - covered):
        add("unclassified", by_metric[metric].evidence, "possible", metric)
    return list(found.values())
