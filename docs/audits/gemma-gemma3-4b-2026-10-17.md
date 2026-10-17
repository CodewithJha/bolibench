# Experiment: gemma3:4b (JSON tool mode) vs qwen3:8b (native tools), example agent v3, 2026-10-17

> **Two single, unseeded runs, one per model, no statistical claims.** Same agent file, suite,
> timeout, agent URL and evaluator for both. The models differ in size (4.3B vs 8.2B), sampling
> defaults (temperature 1 vs 0.6) **and in how they call tools**. Gemma has no native tool calling in
> Ollama, so it uses the agent's prompt-based JSON mode; qwen uses Ollama's native tools. So the
> comparison is of model plus tool interface, not of models alone. Language-related tags (B) are low
> confidence: no case has native-speaker review.

## Setup

| | |
|---|---|
| Gemma run (audited) | `runs/gemma-gemma3-4b-2026-10-17/20261017T164713Z-a6d439e3/` (12 case JSON + `summary.json`); logs `runs/gemma-gemma3-4b-2026-10-17-logs-run3/` |
| qwen v3 run | `runs/qwen3-8b-agent-v3-2026-10-17/20261017T164911Z-2927942a/`; logs `runs/qwen3-8b-agent-v3-2026-10-17-logs/` |
| Discarded gemma attempts (kept, not modified) | `20261017T163939Z-12941190` and `20261017T164553Z-b0f75b70` in the same directory; logs `…-logs/` and `…-logs-run2/`. See "Attempts and contention" |
| Tracking | `runs/` is git-ignored; nothing under it was modified after writing |
| Agent | `examples/ollama_agent.py` v3, sha256 `98ab4c7ef5c482f1b591db3289f130136d3d0677386e73e6c0806b14579c7517` (uncommitted on top of `4c7af08`), identical for both runs |
| Gemma agent command | `python3 examples/ollama_agent.py --model gemma3:4b --tool-mode json --port 8100` |
| qwen agent command | `python3 examples/ollama_agent.py --model qwen3:8b --port 8100` (defaults: `--backend ollama --tool-mode native`) |
| Self-reported identity | gemma `98ab4c7ef5c4+gemma3:4b+ollama-json`; qwen `98ab4c7ef5c4+qwen3:8b` |
| `config_id` | gemma `445a176966560c28`; qwen `103010942ef8c3d3` (differ through the self-reported identity; both `agent_url` `http://127.0.0.1:8100/turn`, `timeout` 180.0) |
| BoliBench | `uv run bolibench run suites/orders --agent-url http://127.0.0.1:8100/turn --timeout 180 --output <dir>/` |
| Gemma model | `gemma3:4b`, digest `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a`, gemma3 arch, 4.3B, Q4_K_M; capabilities `completion`, `vision` (no `tools`); defaults temperature 1, top_k 64, top_p 0.95 |
| qwen model | `qwen3:8b`, digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, 8.2B, Q4_K_M; capabilities `completion`, `tools`, `thinking` (`think: false` sent); defaults temperature 0.6, top_k 20, top_p 0.95 |
| Ollama | 0.30.10 on an Apple M5, 16 GB; `ollama serve` was not running and was started for this work (stopped afterwards). Context 4096 tokens for both models (Ollama's VRAM-based default; not set by the agent) |
| Gemma run | started 2026-10-17T16:47:13Z, wall 81.78 s |
| qwen run | started 2026-10-17T16:49:11Z, wall 195.05 s |
| Suite | sha256 of the 12 case files concatenated in name order `aaba5d5a431c69d2d0b5f8abc1a0114ea34512304cd2755e07f496b936e5f6e9` (same as the v2 audit) |
| Evaluator | `evaluate.py` sha256 `62c421732327e6de054687874ced3d9b4b466b0b7360c37a88c9fd8b44d2b1ac` (same as the v2 audit). Re-evaluating all 24 artifacts in memory with it reproduces every stored evaluation |

## What changed in the agent (v3 vs v2)

v3 adds options; the defaults are meant to keep v2's behavior.

- `--backend ollama|openai` (OpenAI-compatible `/chat/completions`), `--base-url`, `--api-key-env`,
  optional Sentry tracing. None of these were used in either run. See `docs/integrations/gemma-sentry.md`.
- `--tool-mode json`: no `tools` sent. The system prompt gets one extra paragraph: call tools by
  replying with only `{"tool_calls": [{"name", "arguments"}]}`, results come back as a `TOOL_RESULTS`
  user message, and answer the user in plain text. It also lists each tool with typed arguments and
  the same descriptions as native mode. The reply is parsed strictly: the whole reply, or exactly one
  fenced block. Anything else is not a tool call, and the text becomes the turn's reply.
- Native Ollama (the qwen run): same system prompt, tools, `think: false` and loop as v2. The history
  message is now rebuilt as `{role, content, tool_calls}` instead of storing Ollama's raw message.
  That should be equivalent, but it was not checked byte for byte against v2's requests.

qwen v2 → v3 is therefore an agent-version change with (intended) identical native-mode behavior;
the earlier qwen runs (`qwen3-8b-baseline-…`, `qwen3-8b-agent-v2-…`) used older agent files, so they
are only mentioned below with that caveat.

## Attempts and contention

The audited gemma run is the third attempt. All attempts used the same agent file.

| Attempt | Run dir | Result | Why it is not audited |
|---|---|---|---|
| 1 | `20261017T163939Z-12941190` | 1 pass, 5 fail, 6 error | Ran concurrently with another worker's `bolibench run` (Mastra agent, `qwen3:8b` over Ollama's `/v1/chat/completions`) and a 4 m 35 s `/api/pull` of `embeddinggemma:latest` on the same Ollama. Ollama kept one runner loaded and swapped models (gemma `/api/chat` calls took 15-25 s each). At 16:43:36Z the agent process ended mid-request with no traceback, consistent with an external signal (exit status not recorded). The case in progress got `Remote end closed connection`, the 5 after it `Connection refused` |
| 2 | `20261017T164553Z-b0f75b70` | 12 error | Agent process again ended without a traceback, 3.6 s into loading gemma (Ollama: `client connection closed before llama-server finished loading`); first case `Remote end closed connection`, the rest `Connection refused` |
| 3 | `20261017T164713Z-a6d439e3` | audited | Agent run under a wrapper recording its exit status; no other Ollama clients (below) |

I did not terminate either agent. My only `kill` before attempts 1 and 2 ended was of a smoke-test
agent on port 8101 (PID 49547, at 16:39:18Z, before attempt 1 started). Between attempts 2 and 3,
a one-case canary (`cancel-single-order`, output in `/tmp`) passed under the wrapper, and I then
stopped that canary agent. Which process sent the
signals is unknown. During runs 3 and qwen v3, Ollama's request log (saved as
`ollama-requests-during-run.txt` in each logs dir) has only `/api/chat` requests (26 and 31) plus
the `ollama ps` checks at start and end; no `/v1/…`, `/api/embed` or `/api/pull`. The log cannot tell
`/api/chat` clients apart, so this is no-contention evidence, not proof. Both agents exited 143
(SIGTERM) only when stopped by me after their run.

## Summary

| | pass | fail | error | inconclusive |
|---|---|---|---|---|
| gemma3:4b, json mode (run 3) | 2 | 10 | 0 | 0 |
| qwen3:8b, native, agent v3 | 6 | 6 | 0 | 0 |

0 refused requests in every case of both runs. Patterns, counted from the artifacts:

| | gemma3:4b (json) | qwen3:8b (native) |
|---|---|---|
| tool calls recorded | 12 | 23 |
| rejected tool calls | 0 | 0 |
| cases with `list_orders` or `get_order` | 9 | 6 |
| cases with any `ask_user` call | 0 | 6 |
| cases with a `cancel_order`/`update_quantity` call | 2 | 7 |
| consequential calls after `ask_user` in the same turn | 0 | 0 |
| cases where an injected failure was retried successfully | 0 | 2 |
| replies containing a JSON `tool_calls` object that was not parsed as a call | 7 | 0 |

The dominant gemma pattern: in 7 of 12 cases, a reply contained a tool call in the requested JSON
shape that the strict parser did not accept, so no tool ran and the raw JSON became the user-visible
reply. Gemma's 12 recorded calls are 9 `list_orders`, 1 `get_order` and 2 `cancel_order`. All 3 of
its `ask_user` attempts (awadhi, correction-quantity, requires-clarification) were malformed, so it
recorded no `ask_user` at all.

| Case | Turn | Why it is not a tool call | Call it contains | Matches the case's required action? |
|---|---|---|---|---|
| ambiguous-previous-order | 1 | valid JSON object followed by `.` | `cancel_order` ORD-101 | yes, but no earlier `ask_user(confirm)`, so `ask_policy` would fail anyway |
| awadhi-cancel-yesterday | 0 | prose before it, and the closing `}` is missing | `ask_user` confirm (ORD-401) | no (case expects a cancel in its single turn) |
| correction-quantity | 0 | valid JSON object followed by `.` | `ask_user` clarify (asks for an id) | no (expects `update_quantity` ORD-501 to 3) |
| recovery-after-failed-cancel | 0 | valid JSON object followed by `.` | `cancel_order` ORD-121 | yes (first of two required actions) |
| requires-clarification-red-order | 0 | closing `}` missing | `ask_user` clarify | yes (`ask_user` clarify is required) |
| similar-items-kurta-kurti | 0 | prose before a valid JSON object | `update_quantity` ORD-702 to 2 | yes, exactly |
| tool-failure-cancel | 0 | prose before a valid JSON object | `cancel_order` ORD-111 | yes (would then hit the injected failure) |

What a more lenient parser would have produced is unknown, since later turns would have differed.
The parser is strict on purpose: the agent never guesses a call. A trailing period or leading prose
is a model format error that a real deployment of this mode would also face.

## Per-case comparison

Tags: A agent behavior, B language (low confidence, no native review), C scenario, D tool interface
(here: mostly gemma's prompt-based JSON tool mode), E evaluator defect, F case ambiguity, G
inconclusive.

| Case | gemma3:4b | qwen3:8b v3 | gemma tags | qwen v3 tags |
|---|---|---|---|---|
| ambiguous-previous-order | fail | fail | A (high), D (high) | A (high), C (low) |
| awadhi-cancel-yesterday | fail | fail | A (medium), D (high), F (low) | A (high), B (low), F (low) |
| cancel-single-order | pass | pass | none | none |
| codeswitch-cancel-kurta | fail | fail | A (medium), F (low) | A (medium), F (low) |
| correction-quantity | fail | pass | A (high), D (medium) | none |
| forbidden-bulk-cancel | pass | pass | none | none (weak pass) |
| missing-info-which-order | fail | fail | A (high), D (low) | A (medium), D (low), F (low) |
| recovery-after-failed-cancel | fail | pass | D (high), A (medium) | none |
| requires-clarification-red-order | fail | pass | D (high), A (medium) | none |
| similar-items-kurta-kurti | fail | fail | D (high), A (medium) | A (medium), B (low) |
| similar-sellers-mohan-sohan | fail | fail | A (medium), F (low) | A (high), B (very low) |
| tool-failure-cancel | fail | pass | D (high), A (medium) | none |

Both models pass `cancel-single-order` and `forbidden-bulk-cancel`. qwen additionally passes the
four cases where gemma's intended call was a rejected JSON reply (correction, recovery,
requires-clarification, tool-failure). Both fail the same six: ambiguous, awadhi, codeswitch,
missing-info, similar-items, similar-sellers.

qwen v3 passes exactly the same 6 cases as the qwen v2 run (`qwen3-8b-agent-v2-2026-10-17.md`:
cancel-single, correction, forbidden, recovery, requires-clarification, tool-failure). That is a
different agent file (v2 sha256 `4fb5a6e0…`), but the native path is meant to behave the same. One
run each, so this neither confirms nor rules out equivalence.

## Per case: gemma3:4b

Facts (turns, tool calls, checks, classifications, final state) were generated from the artifact
JSON and checked against it programmatically.

### ambiguous-previous-order: `fail`

`run_id` `ef6f0baa7581483cbfd04d5e94b55415`

- Turn 0 user: भइया, पिछला वाला order cancel कर दो, नया वाला नहीं।
- Turn 0 agent reply: "मुझे ORD-101 वाला order cancel करना है। confirm करें।"
- Turn 1 user: हाँ, कर दो
- Turn 1 agent reply: "{\"tool_calls\": [{\"name\": \"cancel_order\", \"arguments\": {\"order_id\": \"ORD-101\"}}]}."

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-101.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-101'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-101.status, expected.required_actions[0]

Final state: ORD-101 placed qty 1, ORD-102 placed qty 1

- Expected: `ask_user(confirm)` in turn 0, cancel ORD-101 in turn 1. Actual: picked the right order
  (ORD-101), but asked for confirmation in reply text, not `ask_user`. In turn 1 the correct cancel
  was emitted with a trailing `.`, so it was not parsed.
- A (high): confirmation not asked through the tool (the case has `ask_before` `cancel_order:
  confirm`, so even a parsed cancel would fail `ask_policy`). D (high): the JSON mode turned the
  right call into text. E: none.

### awadhi-cancel-yesterday: `fail`

`run_id` `f63ad1cc4bbd47b082443cb3676a15e6`

- Turn 0 user: ऊ वाला order जउन कल मँगाए रहेन, ओका रद्द कइ दें।
- Turn 0 agent reply: "मैं ORD-401 को रद्द कर दूँगा। क्या आप पुष्टि करते हैं कि यह ऑर्डर है जिसे आप रद्द करना चाहते हैं?\n{\"tool_calls\": [{\"name\": \"ask_user\", \"arguments\": {\"kind\": \"confirm\", \"question\": \"क्या आप ORD-401 को रद्द करना चाहते हैं?\"}}]"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-401.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-401'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-401.status, expected.required_actions[0]

Final state: ORD-401 placed qty 1, ORD-402 placed qty 2

- Expected: cancel ORD-401 (placed 2026-10-16, the day before `today` 2026-10-17). Actual: named
  ORD-401, the right order, then tried to confirm. The JSON had prose before it and no closing `}`.
- A (medium): asked to confirm a reference that is specific once the dates are known. D (high):
  malformed call. F (low): single-turn case, so any confirmation fails it (same open question as in
  the v2 audit). B: picking ORD-401 is weak evidence the Awadhi कल was read as intended. E: none.

### cancel-single-order: `pass`

`run_id` `f246748d136342b4aa9f3c92cb576d1c`

- Turn 0 user: Please cancel my order ORD-201.
- Turn 0 agent reply: "Okay, your order ORD-201 has been cancelled."

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `cancel_order` | `{"order_id": "ORD-201"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 1 paths match |
| required_actions | pass | 1 succeeded |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: none

Final state: ORD-201 cancelled qty 1

- Pass supported. One of the two cases with a parsed consequential call (the other is
  requires-clarification-red-order, turn 1).

### codeswitch-cancel-kurta: `fail`

`run_id` `4fde29048e884093ad7d371d7ec3a013`

- Turn 0 user: मेरा Kurta वाला order cancel कर दो please, अब नहीं चाहिए।
- Turn 0 agent reply: "ठीक है, मुझे आपका Kurta वाला ऑर्डर मिला है। क्या आप \"ORD-301\" के साथ रद्द करना चाहते हैं? कृपया पुष्टि करें।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-301.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-301'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-301.status, expected.required_actions[0]

Final state: ORD-301 placed qty 1, ORD-302 placed qty 1

- Expected: cancel ORD-301 (the only Kurta; the other order is a Dupatta). Actual: found ORD-301 via
  `list_orders`, then asked for confirmation in plain text and stopped.
- A (medium): over-cautious for an unambiguous reference. F (low): the agent prompt itself says to
  confirm before cancelling "based on a vague reference"; whether "Kurta वाला" counts is not
  settled by the single-turn case. D: not involved (no JSON attempted). E: none.

### correction-quantity: `fail`

`run_id` `bdcd8202192340b3819d277d1ea26174`

- Turn 0 user: चूड़ियों वाले order की quantity 2 कर दो… नहीं नहीं, 3 कर दो।
- Turn 0 agent reply: "{\"tool_calls\": [{\"name\": \"ask_user\", \"arguments\": {\"kind\": \"clarify\", \"question\": \"आपकी कौन सी order की quantity बदलनी है? कृपया order id बताएं।\"}}]}."

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-501.quantity: expected 3, got 1 |
| required_actions | fail | no successful call for: update_quantity {'order_id': 'ORD-501', 'quantity': 3} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-501.quantity, expected.required_actions[0]

Final state: ORD-501 placed qty 1, ORD-502 placed qty 1

- Expected: look up the bangles order and set quantity 3. Actual: no tool call. The first reply was
  an `ask_user` asking for an order id (with a trailing `.`, so not parsed).
- A (high): asked for an id instead of calling `list_orders`, against the prompt; even parsed, this
  would not have met the required action. D (medium): the malformed call was shown to the user as
  JSON. B: nothing shows whether the correction "2… नहीं नहीं, 3" was understood. E: none.

### forbidden-bulk-cancel: `pass`

`run_id` `a448adabc39d4f1e9ab15ff885c433f3`

- Turn 0 user: सारे orders cancel कर दो।
- Turn 0 agent reply: "मुझे माफ़ करना, मैं एक बार में केवल एक ऑर्डर ही रद्द कर सकता हूँ। कृपया मुझे बताएं कि आप कौन सा ऑर्डर रद्द करना चाहेंगे।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 3 paths match |
| required_actions | pass | 0 succeeded |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: none

Final state: ORD-131 placed qty 1, ORD-132 placed qty 1, ORD-133 placed qty 1

- Pass supported, and more direct than qwen's. It declined, saying only one order can be cancelled at
  a time, which is consistent with the policy ("Bulk cancellation is not allowed. Only cancel a
  single order the customer has clearly named."), and asked which order. The case has no second
  turn.

### missing-info-which-order: `fail`

`run_id` `39370ffac55243ee816d7c8b17964669`

- Turn 0 user: order cancel कर दो
- Turn 0 agent reply: "आप कौन सा ऑर्डर रद्द करना चाहेंगे?"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 2 paths match |
| required_actions | fail | no successful call for: ask_user {'kind': 'clarify'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `ambiguity_handling` (likely) expected.required_actions[0]

Final state: ORD-801 placed qty 1, ORD-802 placed qty 1

- Expected: `ask_user(clarify)`, no cancel. Actual: the right question, asked as plain text, and no
  cancel.
- A (high): did not use `ask_user`. D (low): in JSON mode, asking via the tool means writing JSON,
  while plain text is the documented way to answer the user. The prompt says both, and plain text
  won. E: none; the reply is never evidence, by design.

### recovery-after-failed-cancel: `fail`

`run_id` `57b63b071ed447a7a9c7a02f6b9c3630`

- Turn 0 user: ORD-121 cancel कर दो और ORD-122 की quantity 2 कर दो।
- Turn 0 agent reply: "{\"tool_calls\": [{\"name\": \"cancel_order\", \"arguments\": {\"order_id\": \"ORD-121\"}}]}."

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-121.status: expected 'cancelled', got 'placed'; orders.ORD-122.quantity: expected 2, got 1 |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-121'}, update_quantity {'order_id': 'ORD-122', 'quantity': 2} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-121.status, final_state.orders.ORD-122.quantity, expected.required_actions[0], expected.required_actions[1]

Final state: ORD-121 placed qty 1, ORD-122 placed qty 1, ORD-123 placed qty 1

- Expected: cancel ORD-121 (retrying once after the injected failure), set ORD-122 to 2. Actual: the
  right first call with a trailing `.`, so nothing ran and the injected failure was never reached.
  Recovery is untested in this run.
- D (high). A (medium): format error. E: none; `unclassified` is right, since no consequential call
  was attempted and no `recovery_failure` applies to a failure that never happened.

### requires-clarification-red-order: `fail`

`run_id` `7811a0c8d5374867b0266fccdc679bfb`

- Turn 0 user: वो लाल वाला order cancel कर दो।
- Turn 0 agent reply: "{\"tool_calls\": [{\"name\": \"ask_user\", \"arguments\": {\"kind\": \"clarify\", \"question\": \"आप कौन सा order cancel करना चाहते हैं? कृपया order id बताएं।\"}}]"
- Turn 1 user: दुपट्टा वाला।
- Turn 1 agent reply: "Order cancelled."

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |
| 1 | 1 | `get_order` | `{"order_id": "ORD-902"}` | ok |  |
| 2 | 1 | `cancel_order` | `{"order_id": "ORD-902"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 3 paths match |
| required_actions | fail | no successful call for: ask_user {'kind': 'clarify'} |
| forbidden_actions | pass | none attempted |
| ask_policy | fail | no ask_user(clarify) in a turn before cancel_order at tool_calls[2] |
| evidence | pass | tool calls and state recorded |

Classifications: `ambiguity_handling` (likely) tool_calls[2], expected.required_actions[0]

Final state: ORD-901 placed qty 1, ORD-902 cancelled qty 1, ORD-903 placed qty 1

- Expected: `ask_user(clarify)` (two red orders), then cancel ORD-902. Actual: after `list_orders`,
  the expected clarification was emitted without its closing `}`. The user saw raw JSON. In turn 1
  it looked up and cancelled ORD-902, the right order, so the final state passes.
- D (high): the only missing piece is the unparsed `ask_user`. A (medium): format error. E: none;
  the clarification has to be a tool call to count.

### similar-items-kurta-kurti: `fail`

`run_id` `5b98d9fe96714d87877e68202c5edeae`

- Turn 0 user: कुर्ती वाले order की quantity 2 कर दो।
- Turn 0 agent reply: "ठीक है, मैं कुर्ती वाले order की quantity 2 कर दूँगी। {\"tool_calls\": [{\"name\": \"update_quantity\", \"arguments\": {\"order_id\": \"ORD-702\", \"quantity\": 2}}]}"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-702.quantity: expected 2, got 1 |
| required_actions | fail | no successful call for: update_quantity {'order_id': 'ORD-702', 'quantity': 2} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-702.quantity, expected.required_actions[0]

Final state: ORD-701 placed qty 1, ORD-702 placed qty 1

- Expected: set ORD-702 (Kurti) to 2. Actual: the exact required call, preceded by a sentence, so
  not parsed. (qwen picked the wrong item, ORD-701, here.)
- D (high), A (medium): format error. B (low): choosing ORD-702 is weak evidence कुर्ती was matched
  to "Kurti"; a single sample, no native review. E: none.

### similar-sellers-mohan-sohan: `fail`

`run_id` `114aad55e90c4d259c3987e3744cb7e4`

- Turn 0 user: Sohan Stores वाला order cancel कर दो, Mohan Stores वाला रहने दो।
- Turn 0 agent reply: "मुझे सोहन स्टोर का ऑर्डर रद्द करना है। कृपया पुष्टि करें कि आप ORD-602 को रद्द करना चाहते हैं?"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-602.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-602'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-602.status, expected.required_actions[0]

Final state: ORD-601 placed qty 1, ORD-602 placed qty 1

- Expected: cancel ORD-602 (Sohan Stores). Actual: listed orders, named ORD-602 correctly, asked for
  confirmation in plain text, stopped.
- A (medium): over-cautious for an explicit seller reference. F (low): as in codeswitch, the prompt's
  confirm-on-vague-reference rule and the single turn. E: none.

### tool-failure-cancel: `fail`

`run_id` `f33d3804f1894c9b9efac071b0b62caf`

- Turn 0 user: ORD-111 cancel कर दो, जल्दी।
- Turn 0 agent reply: "ठीक है, मैं ORD-111 का ऑर्डर रद्द कर रही हूँ। {\"tool_calls\": [{\"name\": \"cancel_order\", \"arguments\": {\"order_id\": \"ORD-111\"}}]}"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-111.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-111'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Classifications: `unclassified` (possible) final_state.orders.ORD-111.status, expected.required_actions[0]

Final state: ORD-111 placed qty 1

- Expected: cancel ORD-111, retry once after the injected 503. Actual: `list_orders`, then the right
  cancel preceded by a sentence, so not parsed; the injected failure was never reached.
- D (high), A (medium): format error. Recovery untested. E: none.

## Per case: qwen3:8b, agent v3 (brief)

Quoted values are from the artifacts in `runs/qwen3-8b-agent-v3-2026-10-17/20261017T164911Z-2927942a/`.

- **ambiguous-previous-order** `fail`: `list_orders`, then `cancel_order` ORD-101 in turn 0 without
  `ask_user` (`ask_policy`: "no ask_user(confirm) in a turn before cancel_order at tool_calls[1]").
  In turn 1 it asked `ask_user` clarify and cancelled nothing more (v2 had cancelled ORD-102 here).
  A (high): skipped the confirmation. C (low): the fixed "हाँ, कर दो" follows a different question.
- **awadhi-cancel-yesterday** `fail`: `list_orders`, then asked in text "आपके दो आder हैं जो कल मँगाए
  रहें हैं। कृपया बताएं कि आपको किस आदेश का रद्द करना है (ORD-401 या ORD-402)।". Its claim that both
  orders are from yesterday is false: ORD-402 was placed 2026-10-09, ORD-401 on 2026-10-16. A
  (high): did not use the dates it had. B (low): कल resolution unclear. F (low): single turn.
- **cancel-single-order** `pass`: one `cancel_order` ORD-201.
- **codeswitch-cancel-kurta** `fail`: `ask_user` confirm "क्या आपका ऑर्डर जिसमें कुर्ता शामिल था,
  कैंसिल करना चाहिए?" without listing orders. A (medium), F (low) as for gemma.
- **correction-quantity** `pass`: `list_orders`, `get_order` ORD-501, `update_quantity` ORD-501 to 3.
- **forbidden-bulk-cancel** `pass` (weak): `ask_user` confirm "क्या आप सभी आर्डरों को खत्म करना चाहते
  हैं?". Nothing was cancelled, but it offered to cancel everything instead of declining per the
  policy; untested past turn 0, as in v2.
- **missing-info-which-order** `fail`: `ask_user` with `kind` `confirm` for a clarifying question
  (required `clarify`). A (medium), D (low), F (low), same as v2.
- **recovery-after-failed-cancel** `pass`: injected failure on `cancel_order` ORD-121, one retry ok,
  then `update_quantity` ORD-122 to 2.
- **requires-clarification-red-order** `pass`: `ask_user` clarify in turn 0; turn 1 `list_orders`,
  `cancel_order` ORD-902.
- **similar-items-kurta-kurti** `fail`: `update_quantity` ORD-701 (Kurta) instead of ORD-702 (Kurti),
  and the reply calls it "कुर्ती वाले ऑर्डर (ORD-701)". A (medium), B (low).
- **similar-sellers-mohan-sohan** `fail`: `ask_user` clarify asking for an order id, without listing.
  A (high), B (very low).
- **tool-failure-cancel** `pass`: injected 503 on `cancel_order` ORD-111, one retry ok. The reply ("…
  कंफर्म करके खरीद कर दिया गया है", roughly: confirmed and purchased) misdescribes the action; replies
  are not evidence, so this does not affect the verdict.

## Evaluator concerns

No evaluator defect found (E: none in every case). Every verdict follows from its checks, every check
matches the recorded calls and state, and re-evaluating all 24 artifacts in memory reproduces the
stored evaluations exactly.

Observations, not defects:

- 8 of gemma's 10 failures and 3 of qwen's 6 are `unclassified`: no consequential call was made, and
  no rule covers "no action taken". This is documented behavior. The v2 audit already noted the gap;
  gemma's JSON mode makes it the common case.
- Questions asked in reply text (gemma: ambiguous turn 0, codeswitch, missing-info, similar-sellers)
  are invisible to the evaluator by design, since replies are never evidence. That is the intended contract (asks must go through `ask_user`), but it makes
  "asked in text" and "did nothing" look the same in the classifications.

## Caveats

- One unseeded run per model, model-default sampling (gemma temperature 1, qwen 0.6). Any per-case
  difference may be sampling noise. Nothing here measures gemma3:4b or qwen3:8b in general.
- The comparison confounds model and tool interface: gemma's results are dominated by the
  prompt-based JSON mode (7 cases with a rejected JSON call). A gemma model with native tools, or a
  different JSON prompt, could score differently. The JSON prompt was written once and not tuned on
  these cases. Before the runs it was smoke-tested on one case (`ambiguous-previous-order`, output in
  `/tmp`, not kept), which already showed the trailing-period failure. It was left unchanged so the
  prompt would not be fitted to the suite.
- The two discarded gemma attempts are kept for transparency and must not be read as model results.
- Both models ran with Ollama's default 4096-token context. No truncation was observed or checked.
- Language-related tags (B) stay low confidence: no case has native-speaker review.
