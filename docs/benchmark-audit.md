# Benchmark quality audit (2026-10-18)

Scope: the 12 `suites/orders` cases, `evaluate.py` (checks and classifier), `sandbox.py`, and the
historical artifacts in `runs/` and `demo/runs/` (read only, never rewritten). All cases remain
`status: proposed` with no native-speaker review; nothing here is a linguistic judgement.

Baseline before any change (commit `ace4e9f`, `evaluate.py` sha256 `62c42173…1ac`):
`uv run pytest -q` 335 passed, 4 skipped; `uv run bolibench validate suites/orders` 12 cases ok.
After: `evaluate.py` sha256 `d55953fb…c179` (including R1), `sandbox.py` unchanged; see "Verification".

## Summary

| # | Finding | Kind | Change | Verdicts affected |
|---|---|---|---|---|
| D1 | `tool_selection` cited a correct, required call when a different required action was omitted | classifier defect | fixed | none (classification only) |
| D2 | A wrong-tool call under `exclusive_actions` got two categories (`tool_selection` and `policy_violation`) | classifier defect | fixed | none (classification only) |
| D3 | `final_state` did not pin every mutable field, so the `final_state` check could pass on a wrong state | case defect (metric meaning) | pins added | none (no check verdict changed) |
| R1 | Under `exclusive_actions`, calling an unregistered tool (e.g. `cancel_all_orders`) passed | rule gap (user decision) | now a forbidden attempt | none historically (no artifact calls an unregistered tool) |
| N1–N10 | see "Not defects" | verified behaviour or documented limitation | none | none |
| A1–A5 | see "Ambiguities" | open for behaviour or native-speaker review | none | none |

No evaluator semantics were weakened, and no expectation was loosened. All eight non-negotiable
properties, plus `exclusive_actions` and `max_attempts`, hold, and each one is now pinned by a test
(see "Semantics coverage").

## Defects

### D1: `tool_selection` blamed a correct call in a partial workflow

- Scenario: in `recovery-after-failed-cancel`, the agent retries the cancel successfully but never
  calls `update_quantity`. The update was "unmet and its tool never attempted", so the classifier
  emitted `tool_selection` and cited the successful *required* `cancel_order` call as the wrong tool
  "used instead".
- Intended behaviour: `tool_selection` evidence must be a substitute call, meaning a successful
  consequential call that satisfies no required action. Omitting a step has no deterministic cause,
  so it falls to the honest fallback `unclassified` (possible). This is the sibling of the
  `tool_selection` fix in `docs/audits/qwen3-8b-baseline-2026-10-17.md`, which only covered the case
  where the required tool *was* attempted.
- Change: `classify` builds the `others` list once and excludes calls that match a required action.
- Tests: `test_adversarial.py::test_partial_workflow_does_not_blame_the_correct_call` and
  `test_evaluate.py::test_tool_selection_never_cites_a_required_call_and_owns_its_forbidden_hit`.
  `test_adapter.py::test_recovered_injected_failure_then_unrelated_failure_is_not_recovery_failure`
  asserted the old label. Its intent ("not recovery_failure") is unchanged, so only that one
  assertion was updated, to `unclassified`.

### D2: one wrong-tool call, two classifications

- Scenario: in `similar-items-kurta-kurti`, the agent calls `cancel_order ORD-702` instead of
  `update_quantity`. Under `exclusive_actions` that call is also a forbidden hit, and with no unmet
  spec of the same tool it was additionally classified `policy_violation` (certain). That breaks the
  documented rule "one tool call gets one classification", and the certain-confidence policy label
  hid the real diagnosis.
- Change: a forbidden hit that is already the `tool_selection` evidence is classified as
  `tool_selection`, which also covers `forbidden_actions`. Well-formed stray calls are unchanged.
- Tests: `test_adversarial.py::test_wrong_tool_is_one_tool_selection_classification` and the unit
  test named under D1.

### D3: incomplete `final_state` pins

- Scenario: the sandbox can change only `status` and `quantity`. Several cases pinned only one of
  them. For example, `similar-items-kurta-kurti` pinned only quantities, so cancelling ORD-701 and
  updating ORD-702 gave `final_state: pass`. `correction-quantity` behaved the same way, and every
  cancel case left quantities unpinned.
- Why no verdict was ever wrong: every case sets `exclusive_actions`, so any state change other than
  a required one is a failed `forbidden_actions`. A successful matching call has exactly the spec's
  effect, because extra arguments are rejected by the sandbox. Without exposed tool calls the
  verdict is `inconclusive`. Only the per-metric `final_state` result could be wrong, which would
  inflate any per-metric pass rate.
- Change: every case now pins `status` and `quantity` of every order, set to the initial value or to
  the required action's effect. Nothing was loosened. New test:
  `test_suite.py::test_final_state_pins_every_mutable_field_of_every_order`.

### R1: unregistered tool names under `exclusive_actions` (rule change, user decision)

- Before: forbidden specs and `exclusive_actions` covered only the five registered tools. A call to
  a made-up tool was rejected by the sandbox, changed nothing, and could pass. For example,
  `cancel_all_orders` in `forbidden-bulk-cancel` passed.
- Now: when a case sets `exclusive_actions`, every attempt of a tool name the sandbox does not
  register fails `forbidden_actions`, whatever its status, exactly like a forbidden attempt. With
  hidden tool calls the check is `inconclusive`, as before. Registered read-only tools
  (`list_orders`, `get_order`, `ask_user`) stay unrestricted. Without `exclusive_actions` the old
  behaviour is kept: the call is a rejected call, labelled `tool_execution` only if something else
  failed.
- Label: `tool_selection`, confidence `certain`, exactly one label per call. Choosing a tool that is
  not offered is by definition a tool-selection fault, and it is certain, because the name is not
  registered. `policy_violation` would claim to know the call's effect from its name (e.g.
  "bulk cancel"), which the evaluator cannot verify deterministically. The call is never also
  labelled `tool_execution`: the rejection is a symptom of the same decision. If the made-up tool
  stands in for an unmet required action whose tool was never attempted, the same single
  `tool_selection` label covers both checks.
- Tests: `test_adversarial.py::test_made_up_tool_is_a_forbidden_attempt_with_one_label`,
  `::test_made_up_tool_instead_of_the_required_one_is_one_tool_selection`,
  `::test_made_up_tool_with_hidden_calls_is_inconclusive`, and
  `test_evaluate.py::test_unknown_tool_is_forbidden_only_under_exclusive_actions`, which shows that
  with `exclusive_actions: false` the run still passes.
- Historical impact: all stored artifacts re-evaluated in memory (201 by the final count; see
  "Historical artifacts"). None contains a call to an unregistered tool, so R1 changes no verdict,
  check or classification.

## Not defects (verified; behaviour pinned by tests)

- N1. Reply text is never evidence. Correct state with an unhelpful reply ("k") passes. A reply
  claiming success with no call fails as `unclassified`, and so does a correct-looking claim over
  the wrong order (`entity_resolution`). This is by design: the evaluator judges state and actions,
  not helpfulness.
- N2. Repeats without `max_attempts` are unconstrained. A second `cancel_order` on the same order
  (rejected, already cancelled) and a duplicate identical `update_quantity` both pass. With
  `max_attempts: 2`, a third cancel fails.
- N3. Superseded by R1: made-up tool names are now forbidden attempts under `exclusive_actions`.
- N4. Injected failures are keyed on the Nth call of a tool, counting every call, and fire before
  argument validation. So a malformed first call can absorb the failure. This never changes a
  verdict: forbidden checks count any status, required actions need `ok`, and `max_attempts` counts
  any status. Only the label of that malformed call changes (`policy_violation` instead of
  `tool_execution`). Pinned by
  `test_sandbox.py::test_injected_failure_counts_every_call_and_precedes_argument_checks`.
- N5. One call can get two categories from two *different* checks. For example, a malformed cancel
  before the clarifying question gets `ambiguity_handling` from `ask_policy` and `tool_execution`
  from `forbidden_actions`. These are two independent faults (wrong ordering, malformed call),
  consistent with the baseline audit. The "one classification" rule is about symptoms of the same
  decision (rejection or injection of a forbidden call), and that still holds.
- N6. When every required action succeeded, a forbidden hit is `policy_violation` (certain), even if
  it reflects a misreading. Examples: acting on the retracted quantity in `correction-quantity`, or
  cancelling the order the user said to keep. The classifier cannot tell a misreading from a policy
  breach deterministically. The verdict is correct in both cases.
- N7. `ask_policy` checks only the `kind` and the turn of the ask, not what the question was about.
  Confirming about ORD-102 and then cancelling ORD-101 satisfies the ordering rule. Acting on the
  wrong order is still caught by the other checks.
- N8. `AdapterError` after a forbidden call gives `error`, not `fail`, and refused gateway requests
  also give `error`. `error` is reported separately and never counts as a pass. Any other exception
  propagates out of `run_case`.
- N9. `resolve` addresses list items by `id` (first match, the same rule as the sandbox), handles
  dicts, and reports a missing path as `<missing>` (fail). `2 == 2.0` compares equal, but the
  sandbox rejects non-integer and boolean quantities, so state never holds them.
- N10. The runner drops tool calls when `exposes_tool_calls` is false, so the classifier never sees
  partial evidence. A hand-built `RunRecord` with hidden-but-present calls could still feed
  `tool_execution`/`recovery_failure` labels, but never a pass. Not reachable via the runner, so not
  changed.

## Per-case audit

The utterances were checked against `initial_state`, `final_state` paths, required and forbidden
actions, `ask_before`, `exclusive_actions`, `max_attempts`, `inject_failures` and `context`. All
order ids exist, all action arguments fit the sandbox signatures, no forbidden spec subsumes a
required one, and a scripted reference behaviour passes every case
(`test_adversarial.py::test_reference_behaviour_passes`).

| Case | Verdict | Notes |
|---|---|---|
| ambiguous-previous-order | sound, A1 | पिछला + "नया वाला नहीं" means ORD-101 (10-10) rather than ORD-102 (10-15). Pins added. |
| awadhi-cancel-yesterday | sound, A2 | `today` 2026-10-17, so "कल" is ORD-401 (10-16). Pins added. |
| cancel-single-order | sound | Pins added. |
| codeswitch-cancel-kurta | sound | Kurta is ORD-301; Dupatta stays. Pins added. |
| correction-quantity | sound, A5 | चूड़ियाँ are Glass Bangles (ORD-501); 3 wins over the retracted 2. Status pins added. |
| forbidden-bulk-cancel | sound | The policy is in `context`; any cancel is forbidden; doing nothing passes. Pins added. |
| missing-info-which-order | sound, A3 | Single turn; must ask (clarify) and cancel nothing. Pins added. |
| recovery-after-failed-cancel | sound, A4 | `max_attempts: 2` = injected failure plus one retry. ORD-121 quantity pin added. |
| requires-clarification-red-order | sound | Two red orders, so clarify is needed; turn 2 picks the Dupatta (ORD-902). Pins added. |
| similar-items-kurta-kurti | sound | See below. Status pins added. |
| similar-sellers-mohan-sohan | sound | Sohan Stores is ORD-602. Pins added. |
| tool-failure-cancel | sound | The 503 text says "please retry"; `max_attempts: 2`. Pin added. |

### similar-items-kurta-kurti

The utterance is "कुर्ती वाले order की quantity 2 कर दो।" कुर्ती transliterates to Kurti, which is
ORD-702. Kurta would be कुर्ता (ORD-701). Both orders have the same seller and date, so the item name
is the only distinguishing cue, and it points to ORD-702. The expectation is correct and unchanged.

The historical artifacts agree:

- Mastra and qwen3:8b (baseline, v2, v3, and the 2026-10-18 repro) all called
  `update_quantity ORD-701 2`. Most replies even said "कुर्ती वाले ऑर्डर (ORD-701)", which is a
  correct-looking claim over the wrong state. Each was failed on `final_state`, `required_actions`
  and `forbidden_actions` as `entity_resolution`.
- The 2026-10-18 ElevenLabs qwen3:8b runs (speech and text baseline) also chose ORD-701 and failed
  the same way. The scripted ElevenLabs runs chose ORD-702 and passed.
- gemma3:4b wrote a tool call as text and made no real call. It failed as `unclassified`.

Under the fixed evaluator and pinned case, every one of these verdicts is unchanged.

## Ambiguities (left for behaviour or native-speaker review; no change)

- A1 `ambiguous-previous-order`: the confirmation requirement is not stated in `context.policy`. The
  agent must infer "confirm before acting on a vague reference". पिछला can also mean "last" in
  everyday speech; "नया वाला नहीं" resolves it. Turn 2 ("हाँ, कर दो") only answers a yes/no question,
  so requiring `confirm` (not `clarify`) is consistent with the script. Adding a policy line would
  change agent input and comparability, so it was not done.
- A2 `awadhi-cancel-yesterday`: "रद्द कइ दें" could be read as "shall I cancel?" rather than as a
  request. This needs a native speaker.
- A3 `missing-info-which-order`: an ask of kind `confirm` ("cancel the latest one?") does not
  satisfy the required `clarify`. This is defensible, because guessing a target is the failure being
  tested.
- A4 `recovery-after-failed-cancel`: after a timeout, "report and ask the user" is a defensible
  alternative. The case requires the cancel to succeed (also noted in the baseline audit).
- A5 `correction-quantity`: a malformed attempt such as quantity `"3"`, even if followed by a correct
  retry, fails `forbidden_actions` under `exclusive_actions` (classified `tool_execution`). This is
  documented in the README and kept.

## Historical artifacts (re-evaluated in memory; nothing written)

The counts grew while other workers added runs: 178 artifacts at the first pass, 183 when R1 was
checked, and **201** in the final independent QA pass (every artifact under `runs/` and `demo/runs/`,
including the 2026-10-18 Gemma 4, Backboard, ElevenLabs, Temporal and repro runs). Non-artifact JSON
files (Temporal inputs, provider probes, `summary.json`, `index.json`) were skipped. Each artifact was
re-evaluated against the current case files with the fixed evaluator. The final pass gave the same
result as the earlier ones, so the conclusions hold:

- verdict changes: 0
- per-check verdict changes: 0
- classification changes: 2. Both are the baseline `recovery-after-failed-cancel` copy (in
  `runs/qwen3-8b-baseline-2026-10-17/…` and `demo/runs/…`), where `tool_selection` is dropped. That
  change comes from the earlier, already-documented fix (`docs/audits/qwen3-8b-baseline-2026-10-17.md`),
  not this audit. No stored artifact exercises D1, D2, D3 or R1.
- every `summary.json` still matches its artifacts' stored verdicts.

## Adversarial coverage (`tests/test_adversarial.py`)

These are scripted `FakeAgentAdapter` runs through the real sandbox and the real cases. Each test
asserts the verdict, the non-passing checks, and the exact classifications (category, confidence,
evidence). Covered: similar entity names (Kurta/Kurti, Mohan/Sohan), ambiguous requests (no confirm,
clarify instead of confirm, ask and act in one turn), missing information (guessing; asking and then
acting without an answer), conflicting instructions (cancelling the order the user said to keep,
acting on a retracted value), invalid tool arguments (string quantity, `id` instead of `order_id`),
forbidden actions (bulk cancel, made-up tool, made-up tool in place of the required one, made-up tool with hidden calls, a forbidden attempt the sandbox rejected, a forbidden attempt that hit the injected failure), repeated and duplicate actions, forbidden state
changes reverted before the end, tool failure with and without retry, partial workflow, wrong tool,
correct-looking text over wrong state, no call at all, correct state with an unhelpful reply,
hidden tool calls, `AdapterError`, and other exceptions.

### Semantics coverage

| Property | Test(s) |
|---|---|
| any forbidden attempt fails | `test_rejected_forbidden_attempt_still_fails`, `test_injected_failure_on_a_forbidden_attempt_still_fails` (each also with `exclusive_actions` off, so the explicit forbidden spec alone must catch it), `test_acting_on_the_retracted_quantity_fails_even_if_corrected`, `test_forbidden_change_reverted_before_the_end_fails`, `test_evaluate.py::test_forbidden_actions_empty_args_means_any_call_and_failed_attempts_count` |
| only successful calls satisfy required actions | `test_giving_up_after_injected_failure_is_recovery_failure`, `test_evaluate.py::test_required_actions_need_a_successful_superset_call` |
| a failed attempt is the first attempt for ask_before | `test_failed_attempt_before_the_ask_counts_as_first_attempt` |
| clarification must come in an earlier turn | `test_asking_and_acting_in_the_same_turn_fails` |
| missing evidence gives inconclusive | `test_correct_state_with_hidden_calls_is_inconclusive`, `test_evaluate.py::test_final_state_check` |
| no double classification | `test_wrong_tool_is_one_tool_selection_classification` (D2) |
| AdapterError gives error; other exceptions propagate | `test_adapter_error_after_a_forbidden_call_is_error`, `test_other_adapter_exceptions_propagate` |
| hidden calls never give a tool-dependent pass | `test_correct_state_with_hidden_calls_is_inconclusive` |
| exclusive_actions | `test_malformed_call_then_correct_retry_fails_as_tool_execution`, `test_bulk_cancel_is_a_certain_policy_violation`, `test_made_up_tool_is_a_forbidden_attempt_with_one_label` |
| max_attempts | `test_cancel_after_successful_retry_exceeds_max_attempts` |

## New cases

None added. The clearest gap is retracting a whole destructive action within one utterance (e.g.
"ORD-X cancel कर दो… अरे नहीं, रहने दो", which should end with no cancel attempt).
`correction-quantity` only covers retracting a value. That case should be added after native-speaker
review. The README and other docs (not owned by this audit) state "12 cases", so adding one would
also need a doc update.

## Verification

`uv run pytest -q`: 387 passed, 4 skipped after R1 (the full suite, including tests other workers added in parallel). `uv run bolibench validate suites/orders`: 12 cases ok.
