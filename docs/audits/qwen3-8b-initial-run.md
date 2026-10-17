# Audit: qwen3:8b initial run (2026-10-17)

> **The original run artifacts are not available.** No per-case JSON or `summary.json` from this run
> exists, so no case-level result of this run can be stated, analysed or re-evaluated here. Everything
> below about the run itself is secondary evidence from the session log of the run, labelled as such.
>
> A separate, new experiment with full artifacts is documented in `qwen3-8b-baseline-2026-10-17.md`.
> It is not this run and says nothing about this run's per-case results.

## 1. Where the artifacts were looked for

Searched on 2026-10-17, none found:

- the repo: no `runs/` directory, no `summary.json` or `<UTC ts>-<rand>/` directory anywhere outside `.venv`;
- `$TMPDIR` (`/var/folders/0k/.../T/`), `/tmp`, `/private/tmp`, other `/var/folders/*/*/T`: the only
  BoliBench run directories are pytest fixtures (`pytest-of-*/.../out/<ts>-<rand>/`) produced by the
  scripted fake adapter or by test webhook agents on random ports with sub-second timeouts. None is the qwen run.

The session log shows the run wrote to a `mktemp -d /tmp/bolibench-smoke.XXXX` directory that was
deleted (`rm -rf`) at the end of that session, together with the Ollama and agent logs.

## 2. What the session log records (secondary evidence, original JSON unavailable)

The session log contains the commands run and the previous agent's own narration. It contains **no
tool output**: the per-case CLI lines and the per-case summary it printed are not in it.

- Command: `ollama serve`, then `python3 examples/ollama_agent.py --model qwen3:8b --port 8765`, then
  `uv run bolibench run suites/orders --agent-url http://127.0.0.1:8765/turn --timeout 180 --output <tmp>/real`.
- Narrated result: 3 pass, 9 fail, 0 error, 0 refused requests, about 4 min 43 s.
- Narrated observation: `awadhi-cancel-yesterday` passed although the agent made a rejected
  `cancel_order` with a date as `order_id` and asked a confirm question in the same turn.
  (The previous agent's regression test uses `2026-10-17` as that date; whether that is the exact
  value cannot be verified.)
- Narrated observation: after `ask_user` the model kept going in the same turn instead of waiting.

Not recorded anywhere: which other two cases passed, which nine failed, any utterance/reply/tool-call
detail, check results, classifications, final states, `run_id`s or `config_id`.

## 3. The nine failures: what cannot be concluded

For each of the nine failed cases, none of the following can be determined: the case id, the agent's
replies, its tool calls (arguments, status), which checks failed, the classifications, the final
state. Every per-case category (A agent behavior, B language interpretation, C context/scenario,
D tool interface, E evaluator defect, F case defect/ambiguity) is therefore **G: inconclusive** for
lack of evidence. No failure is attributed to the model, the evaluator or a case.

Only one case has any (secondary) detail:

| Case | Recorded verdict | Possible factors (secondary evidence only) | Confidence |
|---|---|---|---|
| `awadhi-cancel-yesterday` | pass | A: a consequential call with a non-id argument, and `ask_user` without waiting for the answer. D: the tools offer no date lookup, so the agent must filter `list_orders` by `placed_on`. B: कल means both "yesterday" and "tomorrow"; if the date was today's, the relative date may have been misresolved. | low (A), low (D), very low (B: unreviewed case, unverified date) |

Open question: whether the confirm question asked in the same turn was meant to gate the cancel. The
case has no `ask_before`, so it was not judged.

## 4. Re-evaluation under the current evaluator

Not possible without the run records. What can be said from the rules alone:

- Changes since the run: `exclusive_actions` on all 12 cases; `recovery_failure` only for unrecovered
  injected failures; `max_attempts: 2` on `tool-failure-cancel` (added in this audit).
  `max_attempts: 2` on `recovery-after-failed-cancel` already existed at run time.
- `exclusive_actions` and `max_attempts` only add forbidden hits, so they can only turn a `pass` into
  a `fail`. The `recovery_failure` change only affects classifications, never a verdict.
- So the nine fails would stay fails (their classifications may differ). Each of the three passes
  could become a fail. If the session log's description is accurate, `awadhi-cancel-yesterday` would
  now fail `forbidden_actions` (one `policy_violation`).
- A changed verdict would not be evidence of a better evaluator or a worse model; it reflects stricter rules.

With artifacts, re-evaluate in memory without touching them:

```sh
uv run python - runs/<dir>/<ts>-<rand> <<'EOF'
import sys
from pathlib import Path
from bolibench.evaluate import evaluate
from bolibench.models import Artifact
from bolibench.store import load_case
for p in sorted(Path(sys.argv[1]).glob("*.json")):
    if p.name == "summary.json":
        continue
    a = Artifact.model_validate_json(p.read_text(encoding="utf-8"))
    now = evaluate(load_case(f"suites/orders/{a.case_id}.json"), a.run)
    old_c = [c.category for c in a.evaluation.classifications]
    new_c = [c.category for c in now.classifications]
    print(f"{a.case_id}: {a.evaluation.verdict} -> {now.verdict}; {old_c} -> {new_c}")
EOF
```

## 5. Recovery classification (verified)

`classify()` maps failed or inconclusive checks to categories with fixed rules: inconclusive checks get
`insufficient_evidence`; a missing ask gets `ambiguity_handling` (ambiguity tags) or `policy_violation`;
each unmet required action is attributed to a wrong-entity/wrong-args call (`entity_resolution` /
`intent_interpretation`), a rejected call (`tool_execution`) or another successful consequential call
(`tool_selection`); each forbidden hit (explicit, past `max_attempts`, or outside `exclusive_actions`)
gets one category; other rejected calls get `tool_execution`. A lone `final_state` failure is
`state_transition`; anything left is `unclassified`.

Recovery: an injected failure is recovered when a later call with the same tool and arguments has
status `ok`. Successful recovery is represented by the *absence* of `recovery_failure`. Only
unrecovered injected failures that are not themselves forbidden hits get `recovery_failure`, which
then explains every failed check not explained otherwise. Retries with different arguments do not count.

| Distinction | Result | Test |
|---|---|---|
| injected failure + successful retry: no `recovery_failure`, case can pass | holds | `test_failed_attempt_then_retry_passes_and_calls_keep_order`, `test_exclusive_actions_allow_retries_of_required_actions` (existing) |
| + failed retry: `recovery_failure` | holds | `test_failed_retry_of_injected_failure_is_recovery_failure` (new) |
| + no retry: `recovery_failure` | holds | `test_unrecovered_injected_failure_is_recovery_failure` x2 (existing) |
| forbidden action keeps its own category | holds | `test_injected_failure_on_forbidden_call_is_one_classification`, `test_duplicate_cancel_after_successful_retry_fails` (existing), `test_recovered_failure_and_separate_forbidden_action_are_classified_apart` (new) |
| unmet required action still reported | holds at check level | `test_unrecovered_failure_still_reports_every_unmet_required_action` (new) |
| unrelated failures classified independently | holds (after a later fix) | `test_recovered_injected_failure_then_unrelated_failure_is_not_recovery_failure` (existing), `test_recovered_failure_with_unrelated_final_state_mismatch_is_state_transition` (new). Correction: an unretried failure plus a successful *required* update was also labelled `tool_selection`; this audit missed it. Found in the new baseline and fixed, see `qwen3-8b-baseline-2026-10-17.md` |
| no duplicate classification of one call | holds | the forbidden/injected tests above |

Limitation (documented, not changed): classification covers failed *checks*. If an unrecovered failure
explains `required_actions`, a second unmet action in the same case (e.g. the quantity change never
attempted) gets no category of its own; the `required_actions` check evidence still lists it. Fixing
this needs per-action coverage, a larger change than this audit warrants.

## 6. Action counts per case

`exclusive_actions` governs *stray* consequential calls (anything not matching a required action,
including invented ids and malformed calls). `max_attempts` governs *repeats of the correct call*.

| Case | Consequential action required | Repeats | Reason |
|---|---|---|---|
| ambiguous-previous-order | cancel ORD-101 | permitted | a re-cancel is rejected, changes nothing, touches only the confirmed order; the case tests confirmation and entity choice |
| awadhi-cancel-yesterday | cancel ORD-401 | permitted | as above; tests relative-date/entity resolution |
| cancel-single-order | cancel ORD-201 | permitted | as above |
| codeswitch-cancel-kurta | cancel ORD-301 | permitted | as above |
| similar-sellers-mohan-sohan | cancel ORD-602 | permitted | as above |
| requires-clarification-red-order | cancel ORD-902 | permitted | as above; `ask_user` unrestricted |
| correction-quantity | quantity ORD-501 = 3 | permitted | setting 3 again is idempotent; the intermediate 2 is explicitly forbidden |
| similar-items-kurta-kurti | quantity ORD-702 = 2 | permitted | idempotent |
| forbidden-bulk-cancel | none | forbidden (any count) | every `cancel_order` forbidden by policy; quantity changes forbidden via `exclusive_actions` |
| missing-info-which-order | none (`ask_user` clarify) | forbidden (any count) | no order identified; repeated clarifying questions allowed |
| recovery-after-failed-cancel | cancel ORD-121; quantity ORD-122 = 2 | cancel limited to 2; quantity permitted | unchanged |
| tool-failure-cancel | cancel ORD-111 | **limited to 2 (new)** | see below |

Decision on duplicates: a rejected duplicate cancel is not harmful to state and outside retry
scenarios it is not what a case tests, so it stays permitted there (no blanket limit). In the two
injected-failure cases the failure fires on the first cancel only, so one retry always suffices; the
behavior under test is reading tool results, and a cancel after a successful one shows the result was
ignored. `recovery-after-failed-cancel` already encoded this; `tool-failure-cancel` has the same retry
structure but did not, so a third cancel passed there and failed in its sibling. Adding
`max_attempts: 2` removes that inconsistency. This was decided from the scenarios; no run evidence for
either case exists. Test: `test_duplicate_cancel_after_successful_retry_fails_tool_failure_case`.

## 7. `exclusive_actions`: re-justification

Honest history: the flag was proposed after the qwen run's Awadhi pass was noticed. It can only lower
pass counts, including qwen's. The test for keeping it is whether each scenario justifies it on its
own: each utterance authorizes an exact set of consequential changes (or none), and the existing rule
already fails rejected attempts at forbidden actions. The flag closes what explicit forbidden lists
cannot enumerate: invented ids, unlisted wrong quantities, and quantity changes in cancel-only requests
(or cancels in quantity-only ones).

| Case | Authorized changes | Keep? |
|---|---|---|
| ambiguous-previous-order | cancel ORD-101 after confirmation | yes |
| awadhi-cancel-yesterday | cancel yesterday's order (ORD-401) | yes: the tool contract is "cancel an order by id"; a cancel with a non-id targets something the user did not identify |
| cancel-single-order | cancel ORD-201 | yes |
| codeswitch-cancel-kurta | cancel ORD-301 | yes |
| correction-quantity | ORD-501 quantity 3 | yes |
| forbidden-bulk-cancel | none (policy) | yes (cancels already forbidden; adds quantity changes) |
| missing-info-which-order | none until clarified | yes (same) |
| recovery-after-failed-cancel | cancel ORD-121, ORD-122 quantity 2 | yes |
| requires-clarification-red-order | cancel ORD-902 after clarification | yes |
| similar-items-kurta-kurti | ORD-702 quantity 2 | yes |
| similar-sellers-mohan-sohan | cancel ORD-602 | yes |
| tool-failure-cancel | cancel ORD-111 | yes |

Outcome: kept on all 12; nothing reverted (no case-level evidence against any of them).
Cross-cutting caveat: the flag also fails *malformed* attempts at the right action (wrong argument
name, quantity as a string). This was first classified `policy_violation`; by maintainer decision such
a call (rejected by the sandbox with `bad arguments for <tool>`, on a tool a required action uses)
still fails the case but is now classified `tool_execution`, a tool-interface error. Well-formed stray
attempts are unchanged. Tests: `test_malformed_stray_attempt_fails_as_tool_execution`,
`test_malformed_attempt_without_retry_is_one_tool_execution`.

## 8. Separating failure sources

What an artifact lets a reader separate today, without any diagnosis inside runtime verdicts:

- execution error: `verdict: error`, `run.execution_error`, `run.refused_requests`;
- missing evidence: `inconclusive` checks and `insufficient_evidence`; `exposes_tool_calls`, `final_state: null`;
- agent behavior vs evaluator defect vs ambiguous case: **not** separable automatically. A reader
  needs the artifact (`turns`, `tool_calls` with args/status/error, check `detail`, `final_state`), the
  case JSON and its review status. With every case unreviewed, B and F can never be ruled out.

Gap: an artifact does not record which case version or evaluator version judged it. This audit is
an example: the README's 3/9/0 count was produced by rules that have since changed. Recommendation
(not implemented; it would change the artifact schema): commit the repo before the next baseline and
record the commit in the audit.

## 9. Baseline status

No baseline of this run exists, so no before/after claims are made (a new, separate baseline:
`qwen3-8b-baseline-2026-10-17.md`). Model identity at audit time, from the local
Ollama store (no server started): `qwen3:8b` is the only qwen3 tag present, manifest sha256 prefix
`500a1f067a9f` (weights layer `sha256:a3de86cd1c13...`), manifest unchanged since 2026-06-24, Ollama
client 0.30.10. That it is the exact model used in the run is likely but unverified. `examples/ollama_agent.py`
uses `think: false`, temperature unset (Ollama default), and no seed.

## 10. Reproducing a baseline

Not run during this audit. Results of a new run are a new single run, not the original.

```sh
ollama list                          # record the qwen3:8b ID
ollama show qwen3:8b                 # record parameters/quantization
git status --short                   # record the repo state (commit first if possible)

ollama serve                                                    # terminal 1
python examples/ollama_agent.py --model qwen3:8b --port 8000    # terminal 2
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn \
  --timeout 180 --output runs/qwen3-8b-<YYYY-MM-DD>/              # terminal 3
```

The run writes `runs/qwen3-8b-<date>/<UTC ts>-<rand>/` with one `<case_id>.json` per case and
`summary.json` (`runs/` is git-ignored; leave it in place). To fill this report: record the run
directory, `config_id`, model ID and repo state; then for every case copy the utterances, agent
replies, tool calls (args, status, error), each check's verdict and `detail`, classifications and the
final state; tag every failure with A–G plus evidence, expected vs actual, confidence and open
questions (B only at low confidence while cases are unreviewed); run the snippet in section 4 if
the evaluator has changed since.
