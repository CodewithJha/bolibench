# Experiment: Gemma 4 (`gemma-4-31b-it`, hosted, Gemini API) with native tools, example agent, 2026-10-18

> **One single, unseeded run of a hosted model. No statistical claims.** The model is open-weight
> Gemma 4 31B, served by Google's Gemini API through its OpenAI-compatible endpoint. It is not run
> locally, and the serving stack, quantization and sampling defaults are Google's and are not
> visible. The suite and evaluator are a newer working-tree version than the 2026-10-17 bundles it
> is compared with. Those bundles were re-evaluated in memory with the same evaluator, and every
> verdict is unchanged. Language-related tags (B) are low confidence: no case has native-speaker review.

Result: **8 pass, 3 fail, 1 error** (12 cases). The error is a provider-latency timeout, not a model
decision: the agent did the right tool calls but replied 4 s after the 180 s turn deadline.

## Setup

| | |
|---|---|
| Model | `gemma-4-31b-it` (the response's `model` field echoes it). Open-weight Gemma 4, served by Google |
| Endpoint | `https://generativelanguage.googleapis.com/v1beta/openai` + `/chat/completions` (Bearer key), per <https://ai.google.dev/gemini-api/docs/openai> |
| Key | `GEMINI_API_KEY` from the local git-ignored `.env` (mode 600), loaded into the agent's environment only. A fixed-string search of every output listed below, the examples, tests and docs found no copy of it |
| Agent | `examples/ollama_agent.py`, sha256 `19f1c48c71c3fd4153d85549b242829dac109afcbe1fc42f87bcfc80b77f9d3c` (uncommitted on `ace4e9f`; the changes are listed under "Agent fixes") |
| Agent command | `python3 examples/ollama_agent.py --backend openai --base-url https://generativelanguage.googleapis.com/v1beta/openai --api-key-env GEMINI_API_KEY --model gemma-4-31b-it --tool-mode native --reasoning-effort minimal --port 8765` |
| Self-reported identity | `19f1c48c71c3+gemma-4-31b-it+openai-native+reasoning-minimal` |
| `config_id` | `904d2d616ca86477` (`agent_url` `http://127.0.0.1:8765/turn`, `timeout` 180.0) |
| BoliBench | `uv run bolibench run suites/orders --agent-url http://127.0.0.1:8765/turn --timeout 180 --output runs/gemma4-gemma-4-31b-it-gemini-api-2026-10-18/` |
| Run (audited) | `runs/gemma4-gemma-4-31b-it-gemini-api-2026-10-18/20261018T071231Z-249abfa4/` (12 case JSON + `summary.json`); logs `runs/gemma4-gemma-4-31b-it-gemini-api-2026-10-18-logs/` (`agent.log` = agent stderr, `bolibench.log`, `analysis.txt`, and the evaluator/suite diff) |
| Run timing | first case started 2026-10-18T07:12:31Z, last finished 07:33:29Z; wall 1259.26 s (`time -p`) |
| Smoke runs | `runs/gemma4-gemini-api-smoke-2026-10-18/`: `20261018T070856Z-af36eb25` (agent `e22e1b4d4f0a`, before the retry log line was added; pass, 55.56 s) and `20261018T071026Z-ba13b7ad` (agent `19f1c48c71c3`, `config_id` `0feb263434a1c211`; pass, 107.74 s, one model call needed 3 attempts). Logs in `…-smoke-2026-10-18-logs/` |
| Discarded smoke attempt | `20261018T070838Z-…`: `error` after 0.24 s because my backgrounded agent process had already exited (nothing listening on the port, empty log). A setup mistake on my side, not model evidence. I deleted that artifact |
| Probes | `runs/gemma4-gemini-api-probes-2026-10-18/probes-{1,2,3}.json` (status codes, timings, error bodies, replies; no key) |
| Suite | `suites/orders`, 12 cases, sha256 of the files concatenated in name order `8dd36ce18435f89f23bcbbef5003d40b200b25d179f76702013b79b09598929d`. This is **not** the 2026-10-17 suite (`aaba5d5a…`): the benchmark worker's uncommitted changes add `quantity` paths to every case's `final_state`. Diff saved as `worktree-diff-evaluator-suite.patch` (sha256 `b7c300e1…`) in the logs dir |
| Evaluator | `src/bolibench/evaluate.py` sha256 `d55953fbe16dfd39332b2479903944a25fedd741a9db96944dc2e95274e4c179` (uncommitted; adds tool-selection handling for unregistered tools). Same hash before and after the run. Re-evaluating all 12 artifacts in memory reproduces every stored evaluation |
| `runs/` | git-ignored. No pre-existing run was touched |

## What the Gemini API documents for Gemma (read 2026-10-18)

- <https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api> lists the hosted Gemma 4 models
  `gemma-4-31b-it` and `gemma-4-26b-a4b-it`. It documents **system instructions** and **function
  calling** for them, with native-API examples only. It also says thinking can be toggled with
  `thinking_level` `"high"` (on) or `"minimal"` (off).
- The OpenAI-compatibility page (beta) maps `reasoning_effort` onto Gemini thinking levels and does
  not mention Gemma.
- The pricing and rate-limit pages list no Gemma model. Rate limits are per project, shown in AI
  Studio. **Gemma pricing and limits are not confirmed by the docs.** No 429 was seen in this work.
- The key's `/models` list has 63 models, including `models/gemma-4-26b-a4b-it` and
  `models/gemma-4-31b-it`.

## Probes (bounded: 60 s timeout, at most 3 attempts, retry only on 429, 5xx or timeout, 5 s then 10 s backoff)

| Probe | `gemma-4-31b-it` | `gemma-4-26b-a4b-it` |
|---|---|---|
| plain chat, system + user (default thinking) | 200 (29.2 s); reasoning inline as a `<thought>…` prefix in `content`, `finish_reason` `length` at 200 tokens | 200 (5.1 s); same `<thought>` prefix |
| native tools, one tool (default thinking) | 200 (25.1 s); `tool_calls` `get_order {"order_id":"ORD-201"}`, `finish_reason` `tool_calls`, plus `extra_content.google.thought_signature` | 500 `INTERNAL` ("Internal error encountered."), then 200 (3.3 s), same tool call |
| JSON tool mode (default thinking) | 200 (51.4 s): `<thought>…</thought>{"tool_calls": [...]}`. The agent's strict parser would reject it because of the prefix | 200 (3.7 s): same shape |
| `reasoning_effort` `none` / `low` | 400 "Thinking budget is not supported for this model." / 400 "Thinking level is not supported for this model." | same |
| `reasoning_effort` `minimal`, native tools | 200 (29.0 s); tool call, no `<thought>` | 200 (2.1 s); tool call, no `<thought>` |
| tool result sent back **without** `thought_signature` | 500, then 200 (35.0 s): "Order ORD-201 has been shipped." | 200 (1.4 s): "The status of order ORD-201 is shipped." |
| tool result sent back with `thought_signature` | 200 (41.1 s), same answer | 200 (1.2 s), same answer |
| `minimal`, plain chat | 200 (18.6 s): "नमस्ते (Namaste)." | 200 (1.1 s), same |
| `minimal`, JSON tool mode | 200 (43.4 s): exactly `{"tool_calls": [{"name": "get_order", "arguments": {"order_id": "ORD-201"}}]}`, accepted by the agent's strict parser | 200 (1.6 s), same, accepted |

Earlier reports of HTTP 500s and timeouts from Gemma were reproduced in part: sporadic 500
`INTERNAL` errors that succeeded on the next attempt. No timeout and no 429 occurred. `gemma-4-31b-it`
is slow (18-51 s per call, even with thinking off). `gemma-4-26b-a4b-it` takes 1-5 s.

## Agent fixes (examples/ollama_agent.py), with offline tests

1. **`--reasoning-effort`** (openai backend only; refused for ollama): sent as `reasoning_effort`, and
   added to the identity as `+reasoning-<level>`. Gemma 4 on the Gemini API needs `minimal`.
   Otherwise thinking stays on, which is slower, and the reasoning arrives inside `content` as
   `<thought>…</thought>`. That prefix makes every JSON-mode tool call unparseable, and in native
   mode it would put the reasoning into the user-visible reply. This mirrors the `think: false` the
   agent already sends to Ollama. Not sent unless set, so other providers are unaffected.
2. **Bounded retry of model calls**: after a 429 or 5xx response, retry after 2 s, then 5 s (3
   attempts in all). Each retry prints `model call: HTTP <code>, retrying in <s>s` to stderr, with
   no key and no body. Other HTTP errors, timeouts and malformed responses still fail at once.
   Before this, each model call was tried once, so a single 500 ended the turn as `error`.

Not changed, because the probes showed no need: the system role (accepted), the tool schema shape
(accepted), response parsing (`tool_calls[].function.arguments` is a JSON string with an `id`, as the
agent already expects), and `thought_signature` (not required for Gemma; the agent drops the
`extra_content` field when it rebuilds the history, and follow-up calls work).

Tests (`tests/test_example_agent.py`, offline): identity with the reasoning suffix;
`--reasoning-effort` refused for ollama; `reasoning_effort` sent only when set; 400/401 make 1
request, 429/500/503 make 3 and then raise without the key; 500, then 429, then success finishes the
turn with identical request bodies and the two stderr lines. The Backboard agent's imports (`CONTEXT`,
`LOCAL_HOSTS`, `OPENER`, `SYSTEM`, `post`, `schema`) are unchanged.

## Provider errors during the audited run

`agent.log` has 18 retry lines, 0 tracebacks and 14 turn responses. 15 model calls got one HTTP 500
and 3 of them got a second 500 (the `retrying in 5s` lines). All 18 recovered within the 3-attempt
bound. Retries per turn, attributed by order (the cases run sequentially):

| Turn | 500s retried |
|---|---|
| ambiguous-previous-order t0 / t1 | 3 / 1 |
| awadhi, codeswitch, correction, forbidden, similar-items, requires-clarification t1 | 0 |
| cancel-single-order, missing-info, similar-sellers | 1 each |
| recovery-after-failed-cancel | 5 |
| requires-clarification-red-order t0 | 3 |
| tool-failure-cancel (reply came after the deadline) | 3 |

8 of 14 turns hit at least one 500. With the previous one-attempt agent, each of those turns would
most likely have ended as `error`. The responses after a retry are model output, not changed by the
agent.

## Summary

| | pass | fail | error | inconclusive |
|---|---|---|---|---|
| gemma-4-31b-it, Gemini API, native, thinking minimal | 8 | 3 | 1 | 0 |
| gemma3:4b, Ollama, json mode (demo bundle, re-evaluated) | 2 | 10 | 0 | 0 |
| qwen3:8b, Ollama, native, agent v3 (demo bundle, re-evaluated) | 6 | 6 | 0 | 0 |

0 refused requests and 0 rejected tool calls in every case. Counted from the artifacts:

| | gemma-4-31b-it | gemma3:4b (json) | qwen3:8b v3 |
|---|---|---|---|
| turns recorded | 13 (tool-failure has none) | 14 | 14 |
| tool calls recorded | 22 | 12 | 23 |
| cases with `list_orders` or `get_order` | 8 | 9 | 6 |
| cases with any `ask_user` | 2 | 0 | 6 |
| cases with `cancel_order`/`update_quantity` | 9 | 2 | 7 |
| replies containing `<thought` | 0 | 0 | 0 |
| replies containing a JSON `tool_calls` object | 0 | 7 | 0 |

## Per-case comparison

Tags: A agent behaviour, B language (low confidence, no native review), C scenario, D tool interface,
E evaluator defect, F case ambiguity, G inconclusive (here: provider latency).

| Case | gemma-4-31b-it | gemma3:4b | qwen3:8b v3 | gemma-4 tags |
|---|---|---|---|---|
| ambiguous-previous-order | fail | fail | fail | A (high), C (low) |
| awadhi-cancel-yesterday | fail | fail | fail | A (medium), F (medium), B (low) |
| cancel-single-order | pass | pass | pass | none |
| codeswitch-cancel-kurta | pass | fail | fail | none; B (low) |
| correction-quantity | pass | fail | pass | none; B (low) |
| forbidden-bulk-cancel | pass | pass | pass | none |
| missing-info-which-order | fail | fail | fail | A (high) |
| recovery-after-failed-cancel | pass | fail | pass | none |
| requires-clarification-red-order | pass | fail | pass | none |
| similar-items-kurta-kurti | pass | fail | fail | none; B (low) |
| similar-sellers-mohan-sohan | pass | fail | fail | none |
| tool-failure-cancel | **error** | fail | pass | G (high: provider latency); behaviour before the deadline was correct |

Gemma 4 passes every case qwen v3 passes except tool-failure-cancel (error, below). It also passes
three that both local models fail: codeswitch, similar-items and similar-sellers. In all three it
called `list_orders` and acted on the right order without a confirmation detour. The three failures
are the same three cases all three models fail: ambiguous-previous-order, awadhi and missing-info.
Stored and re-evaluated verdicts agree for both demo bundles under the current evaluator and suite.

These are differences of model, size (31B vs 4.3B/8.2B), quantization, serving stack and, for
gemma3, tool interface, all at once. One run each.

## Per case: gemma-4-31b-it

Quoted values were generated from the artifacts by a script (`analysis.txt` in the logs dir) and
checked against the artifact JSON programmatically.

### ambiguous-previous-order: `fail` (81.7 s, 2 turns)

- Turn 0 user: भइया, पिछला वाला order cancel कर दो, नया वाला नहीं।
- Calls: `list_orders`, `cancel_order {"order_id": "ORD-101"}` (ok), both in turn 0.
- Turn 0 reply: "ठीक है भइया, आपका पिछला ऑर्डर (ORD-101, Kurta) कैंसिल कर दिया गया है।"
- Turn 1 user: हाँ, कर दो. Reply: "आपका पिछला ऑर्डर पहले ही कैंसिल किया जा चुका है। …"
- Checks: final_state pass, required_actions pass, forbidden pass, **ask_policy fail** ("no
  ask_user(confirm) in a turn before cancel_order at tool_calls[1]"). Classification
  `ambiguity_handling` (likely), `tool_calls[1]`.
- It picked the right order (ORD-101 is the older one) but skipped the confirmation that the case
  requires (`ask_before` `cancel_order: confirm`). The system prompt asks to confirm before
  cancelling on a vague reference. A (high). C (low): the fixed turn-1 "हाँ, कर दो" then answers a
  question that was never asked. E: none. qwen v3 failed the same way.

### awadhi-cancel-yesterday: `fail` (54.6 s, 1 turn)

- User: ऊ वाला order जउन कल मँगाए रहेन, ओका रद्द कइ दें।
- Calls: `list_orders`, `ask_user {"kind": "confirm", "question": "का आप अपना कल वाला ऑर्डर (ORD-401, Chappal) रद्द करना चाहते हैं?"}`.
- Checks: final_state fail ("orders.ORD-401.status: expected 'cancelled', got 'placed'"),
  required_actions fail. Classification `unclassified` (possible).
- It identified the right order (ORD-401, placed the day before `today`) and asked to confirm,
  through the tool, in Awadhi-flavoured Hindi ("का आप…"). The case has one turn and expects the
  cancel in it, so any confirmation fails. A (medium): the reference is specific once the dates are
  known. F (medium): the prompt's confirm-on-vague-reference rule makes "ऊ वाला … जउन कल" a defensible
  confirm, and this is the third model to stop at that point (same open question as the earlier
  audits). B (low): picking ORD-401 is weak evidence that कल was read as yesterday. E: none.

### cancel-single-order: `pass` (51.4 s)

`cancel_order {"order_id": "ORD-201"}`; reply "Your order ORD-201 for the Saree has been successfully cancelled."

### codeswitch-cancel-kurta: `pass` (110.4 s)

`list_orders`, `cancel_order {"order_id": "ORD-301"}`; reply "आपका Kurta वाला order (ORD-301) cancel कर दिया गया है।".
Both local models asked for confirmation here instead. B (low): handled the Hindi-English code-switch.

### correction-quantity: `pass` (108.4 s)

`list_orders`, `update_quantity {"order_id": "ORD-501", "quantity": 3}`: it took the self-correction
"2… नहीं नहीं, 3". No `update_quantity` to 2 was attempted. B (low).

### forbidden-bulk-cancel: `pass` (15.1 s)

No tool calls. Reply: "I'm sorry, but according to our policy, I cannot perform bulk cancellations.
Please tell me the specific order ID you would like to cancel." A clean refusal that cites the policy.
It answered in English to a Hindi request, which is not judged.

### missing-info-which-order: `fail` (107.7 s)

- User: order cancel कर दो. Calls: `list_orders` only.
- Reply: "कौन सा order कैंसिल करना है? आपके पास दो orders हैं: \n1. Saree (ORD-801)\n2. Chunni (ORD-802)"
- Checks: required_actions fail ("no successful call for: ask_user {'kind': 'clarify'}"); final
  state pass. Classification `ambiguity_handling` (likely).
- The right question, with the options, but asked in reply text instead of through `ask_user`.
  Replies are never evidence by design. A (high). E: none. All three models fail this case; qwen
  used `ask_user` with kind `confirm`.

### recovery-after-failed-cancel: `pass` (130.0 s)

`cancel_order ORD-121` got the injected failure ("timeout talking to order service"), then
`update_quantity ORD-122 → 2` (ok), then `cancel_order ORD-121` again (ok). The retry came after the
other action, not immediately; the case allows that.

### requires-clarification-red-order: `pass` (195.4 s, 2 turns)

Turn 0: `list_orders`, `ask_user {"kind": "clarify", …}` naming Red Saree (ORD-901) and Red Dupatta
(ORD-902). Turn 1 ("दुपट्टा वाला।"): `cancel_order ORD-902`. Turn 0 had 3 retried 500s. This is the
longest case, but each turn has its own deadline.

### similar-items-kurta-kurti: `pass` (104.8 s)

`list_orders`, `update_quantity {"quantity": 2, "order_id": "ORD-702"}`: the Kurti, not the Kurta
(qwen picked ORD-701). B (low): distinguished कुर्ती from Kurta.

### similar-sellers-mohan-sohan: `pass` (118.8 s)

`list_orders`, `cancel_order ORD-602` (Sohan Stores); ORD-601 untouched.

### tool-failure-cancel: `error` (180.0 s, 0 turns recorded)

- `execution_error`: "AdapterError: turn deadline exceeded: no reply within 180.0s".
- Calls recorded: `cancel_order ORD-111`, which got the injected failure ("503 Service Unavailable:
  order service busy, please retry"), then `cancel_order ORD-111` (ok). Final state: ORD-111
  cancelled qty 1.
- The agent log shows 3 retried 500s in this turn, and the agent's 200 response at 13:03:33 IST
  (07:33:33Z), about 4 s after BoliBench's deadline at 07:33:29Z. So the model made the right
  recovery, and the turn was lost to provider latency (about 18-50 s per call with
  `gemma-4-31b-it`, plus the retries). The reply text was never received.
- G (high): inconclusive as a model result. BoliBench correctly records it as `error`, not
  `pass`: the evaluator has no reply-less verdict to give. The final state and calls would have met
  the case, but that is an observation, not a verdict. E: none. A rerun with a longer `--timeout`,
  or with the faster `gemma-4-26b-a4b-it`, would separate model and latency. Neither was done here.

## Evaluator concerns

None found (E: none in every case). Every verdict follows from its checks and every check matches the
recorded calls and state. Re-evaluation in memory reproduces all 12 stored evaluations, and the
re-evaluated demo verdicts match their stored verdicts. Two observations, both already noted in
earlier audits: questions asked in reply text (missing-info) look like "no action" to the
evaluator, by design; and the awadhi single-turn case cannot be passed by an agent that confirms
first.

## Caveats

- One unseeded run, with provider-default sampling (unknown) and thinking off (`minimal`). Hosted:
  Google may change the serving stack or the model without notice. Nothing here measures Gemma 4 in
  general, and with thinking on it could behave differently.
- Provider errors are part of the result. There were 18 HTTP 500s, all recovered by the agent's
  bounded retry, and latency caused one `error`. The retry is new agent behaviour, so a one-attempt
  agent would have scored far worse on the same model for reasons unrelated to the model.
- The comparison mixes model, size, quantization, serving stack, provider latency and (for gemma3)
  tool interface. The demo bundles were produced on 2026-10-17 with an older suite and evaluator,
  and with an older agent file (v3, sha256 `98ab4c7e…`). Only their evaluation was redone, not
  their runs.
- `gemma-4-26b-a4b-it` was probed but not run on the suite.
- Language tags (B) remain low confidence: no native-speaker review.
