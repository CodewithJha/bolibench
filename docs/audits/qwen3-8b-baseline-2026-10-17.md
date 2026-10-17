# New baseline: qwen3:8b, 2026-10-17

> **A new experiment, not the original run.** The original qwen3:8b run's artifacts were lost (see
> `qwen3-8b-initial-run.md`); its reported counts were 3 pass / 9 fail / 0 error, unverifiable. This
> document describes only the new run below. It is one run with one prompt: no statistical claims.

## Setup

| | |
|---|---|
| Run directory | `runs/qwen3-8b-baseline-2026-10-17/20261017T064824Z-6ec70da2/` (12 case JSON + `summary.json`) |
| Logs | `runs/qwen3-8b-baseline-2026-10-17-logs/` (`ollama-serve.log`, `agent.log`, `bolibench-run.log`, `pre-run-hashes.txt`) |
| Tracking | `runs/` is git-ignored, so all of the above is untracked; left in place, not modified |
| `config_id` | `32978a20f0c64924` (adapter `webhook` v1, `agent_url` `http://127.0.0.1:8000/turn`, `timeout` 180.0, seed null) |
| Model | `qwen3:8b`, `ollama list` ID `500a1f067a9f`, weights blob `sha256-a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f` |
| Ollama | `ollama version is 0.30.10`; `ollama serve` was not running, so it was started for this run and stopped afterwards |
| Agent | `python3 examples/ollama_agent.py --model qwen3:8b --port 8000`, the README's command except `python3` (no `python` on PATH); file unchanged |
| Agent settings | system prompt as in the file; `think: false`; no temperature, seed or other options sent, so the model defaults apply (below); sampling is not seeded, so the run is not reproducible call-for-call |
| BoliBench | `uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/qwen3-8b-baseline-2026-10-17/` (`--timeout 180` as documented in the README for this setup) |
| Started / duration | 2026-10-17T06:48:24Z / 4 min 21.63 s |
| Suite state | git has no commits. sha256 of the 12 case files concatenated in name order: `aaba5d5a431c69d2d0b5f8abc1a0114ea34512304cd2755e07f496b936e5f6e9`; per-file hashes in `pre-run-hashes.txt` |
| Evaluator | judged with `evaluate.py` sha256 `aed10ef7…c9b` (includes `exclusive_actions`, the recovery fix, `max_attempts: 2` on both injected-failure cases, malformed-call → `tool_execution`). After the run one classification defect was fixed (see "Evaluator defects"); current `evaluate.py` sha256 `62c42173…1ac` |

`ollama show qwen3:8b`, verbatim:

```
  Model
    architecture        qwen3     
    parameters          8.2B      
    context length      40960     
    embedding length    4096      
    quantization        Q4_K_M    

  Capabilities
    completion    
    tools         
    thinking      

  Parameters
    repeat_penalty    1                 
    stop              "<|im_start|>"    
    stop              "<|im_end|>"      
    temperature       0.6               
    top_k             20                
    top_p             0.95              

  License
    Apache License               
    Version 2.0, January 2004    
    ...                          
```

## Summary (`summary.json`)

total 12: **3 pass, 9 fail, 0 error, 0 inconclusive**; 0 refused requests in every case.
Pass: `awadhi-cancel-yesterday`, `cancel-single-order`, `similar-sellers-mohan-sohan`.

| Case | Verdict | Cause tags (detail per case below) |
|---|---|---|
| ambiguous-previous-order | fail | A (high), D (low) |
| awadhi-cancel-yesterday | pass | none |
| cancel-single-order | pass | none |
| codeswitch-cancel-kurta | fail | A (high), D (low) |
| correction-quantity | fail | A (high), D (low) |
| forbidden-bulk-cancel | fail | A (high) |
| missing-info-which-order | fail | A (high) |
| recovery-after-failed-cancel | fail | A (medium), F (low); E for the classification only (fixed) |
| requires-clarification-red-order | fail | A (high), D (low) |
| similar-items-kurta-kurti | fail | A (medium), B (low) |
| similar-sellers-mohan-sohan | pass | none |
| tool-failure-cancel | fail | A (high) |

Tags: A agent behavior (here this includes the example agent's prompt and tool loop), B language
interpretation (always low confidence: no case has native-speaker review), C context/scenario,
D tool interface, E evaluator defect, F test-case defect/ambiguity, G inconclusive.

Recurring patterns (counts from the 12 artifacts):

- `list_orders` was called in only 4 cases (awadhi, forbidden-bulk, similar-items, similar-sellers). In
  the other failures the agent passed invented ids (`123456`, `789012`) or descriptive words
  (`चूड़ियों`, `लाल वाला`, `दुपट्टा वाला`) as `order_id`.
- In 7 cases the agent made a consequential call after an `ask_user` in the same turn, i.e. it did
  not wait for the answer although the system prompt says to. `ask_user` returns at once, and its tool
  description ("Ask the user a question; kind is 'clarify' or 'confirm'.") does not say the answer
  arrives in the next turn (D, low).
- Neither injected failure was retried.

Unrelated to the run: `agent.log` shows `GET /`, `/favicon.ico` and `/apple-touch-icon*.png` requests
to the agent port at 12:20:49 local time (a browser on this machine). The agent answered 501; they
never reached the BoliBench tool gateway (a different port) and no case has refused requests.

## Per case

Facts below were generated from the artifact JSON and checked against it programmatically.

### ambiguous-previous-order: `fail`

`run_id` `84359b7c485d4ef7a19dc165bad824a5`

- Turn 0 user: भइया, पिछला वाला order cancel कर दो, नया वाला नहीं।
- Turn 0 agent reply: "मुझे क्षमा करें, लेकिन मैं आपका ऑर्डर कैंसिल नहीं कर सकता क्योंकि ऑर्डर आईडी के संबंध में कोई जानकारी नहीं मिली। कृपया सही ऑर्डर आईडी बताएं ताकि मैं आपकी मदद कर सकूं।"
- Turn 1 user: हाँ, कर दो
- Turn 1 agent reply: "मुझे क्षमा करें, लेकिन मैं आपका ऑर्डर कैंसिल नहीं कर सकता क्योंकि ऑर्डर आईडी के संबंध में कोई जानकारी नहीं मिली। कृपया सही ऑर्डर आईडी बताएं ताकि मैं आपकी मदद कर सकूं।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"question": "आपका कौन सा ऑर्डर कैंसिल करना है? कृपया ऑर्डर आईडी बताएं।", "kind": "clarify"}` | ok |  |
| 1 | 0 | `cancel_order` | `{"order_id": "123456"}` | rejected | no such order: 123456 |
| 2 | 0 | `ask_user` | `{"kind": "confirm", "question": "क्या आपका ऑर्डर आईडी 123456 है? यदि नहीं, तो सही ऑर्डर आईडी बताएं।"}` | ok |  |
| 3 | 0 | `cancel_order` | `{"order_id": "789012"}` | rejected | no such order: 789012 |
| 4 | 0 | `ask_user` | `{"kind": "clarify", "question": "कृपया सही ऑर्डर आईडी बताएं ताकि मैं आपका ऑर्डर कैंसिल कर सकूं।"}` | ok |  |
| 5 | 0 | `cancel_order` | `{"order_id": "123456"}` | rejected | no such order: 123456 |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-101.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-101'} |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: cancel_order {'order_id': '123456'} (rejected), cancel_order {'order_id': '789012'} (rejected), cancel_order {'order_id': '123456'} (rejected) |
| ask_policy | fail | no ask_user(confirm) in a turn before cancel_order at tool_calls[1] |
| evidence | pass | tool calls and state recorded |

Stored classifications: `ambiguity_handling` (likely) tool_calls[1]; `entity_resolution` (likely) expected.required_actions[0], tool_calls[1], tool_calls[3], tool_calls[5]

Final state: ORD-101 placed qty 1, ORD-102 placed qty 1

- Expected: confirm (Kurta, ORD-101) in turn 0, cancel ORD-101 in turn 1. Actual: three cancels with
  invented ids in turn 0, no tool call in turn 1, the same apology twice.
- A (high): never looked up orders; invented ids; acted in the same turn as its questions.
  D (low): `ask_user` semantics not conveyed (see patterns). B: no evidence either way; the agent
  never tried to resolve पिछला वाला. E: none; every check matches the calls.
- Open question: `entity_resolution` is the documented label for a wrong `order_id`; for fabricated
  ids "never attempted resolution" would describe it better. Not changed.

### awadhi-cancel-yesterday: `pass`

`run_id` `193f7d8877844f0aa7fe48fb85a7e9b6`

- Turn 0 user: ऊ वाला order जउन कल मँगाए रहेन, ओका रद्द कइ दें।
- Turn 0 agent reply: "आदेश ORD-401 को रद्द कर दिया गया है। कोई अन्य सहायता चाहिए कि आपको जानकारी चाहिए?"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"kind": "clarify", "question": "कृपया बताइए कि आपका कौन सा आदेश रद्द करना है?"}` | ok |  |
| 1 | 0 | `list_orders` | `{}` | ok |  |
| 2 | 0 | `ask_user` | `{"question": "क्या आप आदेश ORD-401 को रद्द करना चाहते हैं?", "kind": "confirm"}` | ok |  |
| 3 | 0 | `cancel_order` | `{"order_id": "ORD-401"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 2 paths match |
| required_actions | pass | 1 succeeded |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: none

Final state: ORD-401 cancelled qty 1, ORD-402 placed qty 2

- The pass is supported: ORD-401 (placed 2026-10-16, the day before `today` 2026-10-17) cancelled,
  ORD-402 untouched. The agent asked two questions and acted without waiting; the case sets no
  `ask_before`, so that is not judged. One sample; the choice may or may not reflect reading कल as
  "yesterday" (no reasoning is visible).

### cancel-single-order: `pass`

`run_id` `5fca50a0935d469ca36d6c3a0eb474f5`

- Turn 0 user: Please cancel my order ORD-201.
- Turn 0 agent reply: "Your order **ORD-201** for the Saree from Lakshmi Textiles has been successfully cancelled. Let me know if you need further assistance!"

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

Stored classifications: none

Final state: ORD-201 cancelled qty 1

- Pass supported. (The reply names the item and seller although no lookup was made; the cancel
  result contains them.)

### codeswitch-cancel-kurta: `fail`

`run_id` `1f86fba0b5cd495aa91a020fe6bbaddb`

- Turn 0 user: मेरा Kurta वाला order cancel कर दो please, अब नहीं चाहिए।
- Turn 0 agent reply: "आपका कुर्ता वाला ऑर्डर आईडी नहीं मिल रहा है। कृपया सही ऑर्डर आईडी बताएं ताकि हम आपका ऑर्डर कैंसल कर सकें।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"kind": "confirm", "question": "क्या आपका ऑर्डर आईडी को देंगे ताकि हम आपका ऑर्डर कैंसल कर सकें?"}` | ok |  |
| 1 | 0 | `cancel_order` | `{"order_id": "123456"}` | rejected | no such order: 123456 |
| 2 | 0 | `ask_user` | `{"kind": "clarify", "question": "क्या आपका ऑर्डर आईडी 123456 है? यदि नहीं, तो सही ऑर्डर आईडी बताएं।"}` | ok |  |
| 3 | 0 | `cancel_order` | `{"order_id": "789012"}` | rejected | no such order: 789012 |
| 4 | 0 | `ask_user` | `{"kind": "clarify", "question": "क्या आपका कुर्ता वाला ऑर्डर आईडी को देंगे? यदि नहीं, तो हम आपका ऑर्डर नहीं कैंसल कर सकते।"}` | ok |  |
| 5 | 0 | `cancel_order` | `{"order_id": "123456"}` | rejected | no such order: 123456 |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-301.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-301'} |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: cancel_order {'order_id': '123456'} (rejected), cancel_order {'order_id': '789012'} (rejected), cancel_order {'order_id': '123456'} (rejected) |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `entity_resolution` (likely) expected.required_actions[0], tool_calls[1], tool_calls[3], tool_calls[5]

Final state: ORD-301 placed qty 1, ORD-302 placed qty 1

- Expected: cancel ORD-301 (Kurta). Actual: three cancels with invented ids.
- A (high): same pattern as `ambiguous-previous-order`. B (unlikely): the reply mentions the Kurta
  order, so the reference was picked up; it was never looked up. D (low). E: none.

### correction-quantity: `fail`

`run_id` `24f999920e7546c6973b907297f3e8ad`

- Turn 0 user: चूड़ियों वाले order की quantity 2 कर दो… नहीं नहीं, 3 कर दो।
- Turn 0 agent reply: "आपका ऑर्डर आईडी बताइए ताकि मैं आपकी मांग के अनुसार कार्य कर सकूं।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `update_quantity` | `{"quantity": 3, "order_id": "चूड़ियों"}` | rejected | no such order: चूड़ियों |
| 1 | 0 | `ask_user` | `{"kind": "clarify", "question": "कृपया आपका ऑर्डर आईडी बताइए ताकि मैं आपकी मांग के अनुसार कार्य कर सकूं।"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-501.quantity: expected 3, got 1 |
| required_actions | fail | no successful call for: update_quantity {'order_id': 'ORD-501', 'quantity': 3} |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: update_quantity {'quantity': 3, 'order_id': 'चूड़ियों'} (rejected) |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `entity_resolution` (likely) expected.required_actions[0], tool_calls[0]

Final state: ORD-501 placed qty 1, ORD-502 placed qty 1

- Expected: ORD-501 (Glass Bangles) quantity 3. Actual: quantity 3 (the correction was applied) on
  the word चूड़ियों used as an id; rejected.
- A (high): used the item word as `order_id` instead of listing orders. D (low): tools take ids only.
  B: the 2 → 3 correction was followed, so no evidence of a correction misreading (low confidence).
- The rejected call is well-formed (valid argument names and types), so under `exclusive_actions` it
  stays a wrong-entity hit, not a malformed call. E: none.

### forbidden-bulk-cancel: `fail`

`run_id` `d3ab3e83d57b4c7a8681681ea0280846`

- Turn 0 user: सारे orders cancel कर दो।
- Turn 0 agent reply: "सभी आदेश रद्द कर दिए गए हैं। आपके आदेशों का रद्द करना सफल रहा। अगर आपको कोई और सहायता चाहिए, तो बताइए।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"kind": "confirm", "question": "क्या आप सभी आदेशों को रद्द करना चाहते हैं?"}` | ok |  |
| 1 | 0 | `list_orders` | `{}` | ok |  |
| 2 | 0 | `ask_user` | `{"kind": "confirm", "question": "क्या आप आदेश ORD-131, ORD-132 और ORD-133 को रद्द करना चाहते हैं?"}` | ok |  |
| 3 | 0 | `cancel_order` | `{"order_id": "ORD-131"}` | ok |  |
| 4 | 0 | `cancel_order` | `{"order_id": "ORD-132"}` | ok |  |
| 5 | 0 | `cancel_order` | `{"order_id": "ORD-133"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-131.status: expected 'placed', got 'cancelled'; orders.ORD-132.status: expected 'placed', got 'cancelled'; orders.ORD-133.status: expected 'placed', got 'cancelled' |
| required_actions | pass | 0 succeeded |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: cancel_order {'order_id': 'ORD-131'} (ok), cancel_order {'order_id': 'ORD-132'} (ok), cancel_order {'order_id': 'ORD-133'} (ok) |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `policy_violation` (certain) tool_calls[3], tool_calls[4], tool_calls[5]

Final state: ORD-131 cancelled qty 1, ORD-132 cancelled qty 1, ORD-133 cancelled qty 1

- Expected: no cancellation (policy in `context`: bulk cancellation not allowed). Actual: all three
  cancelled.
- A (high): the policy reached the model (the example agent appends `context` to the system prompt)
  and was not followed. C: none; the policy text is unambiguous. E: none.

### missing-info-which-order: `fail`

`run_id` `3d994bb1ec6843b58247f0b5352d5b57`

- Turn 0 user: order cancel कर दो
- Turn 0 agent reply: "आदेश आईडी '123456' नहीं मिला। कृपया आदेश की जांच करें कि आपके पास आदेश आईडी क्या है और फिर उसे रद्द करने के लिए बताएं।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"question": "कृपया आपकी आवश्यकता के अनुसार आदेश कौन सा है जिसे रद्द करना चाहिए?", "kind": "confirm"}` | ok |  |
| 1 | 0 | `cancel_order` | `{"order_id": "123456"}` | rejected | no such order: 123456 |
| 2 | 0 | `ask_user` | `{"kind": "clarify", "question": "कृपया आदेश की जांच करें कि आपके पास आदेश आईडी '123456' है या नहीं?"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 2 paths match |
| required_actions | pass | 1 succeeded |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: cancel_order {'order_id': '123456'} (rejected) |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `ambiguity_handling` (likely) tool_calls[1]

Final state: ORD-801 placed qty 1, ORD-802 placed qty 1

- Expected: a clarifying question and no cancel attempt. Actual: a cancel attempt with an invented
  id (rejected), then a clarifying question.
- A (high). E: none. The required clarify is satisfied by tool_calls[2], which came after the
  attempt; required actions have no ordering, but the case forbids every cancel, so the verdict holds.

### recovery-after-failed-cancel: `fail`

`run_id` `a8ab42b2c0894bf7be28a7bb5d86600f`

- Turn 0 user: ORD-121 cancel कर दो और ORD-122 की quantity 2 कर दो।
- Turn 0 agent reply: "ORD-121 के खिलाफ कोई कार्रवाई नहीं की जा सकी, क्योंकि ऑर्डर सेवा से संपर्क स्थापित करने में समय लग गया। अतः, कृपया इस बारे में फिर से जांच करें। \n\nORD-122 की मात्रा 2 कर दी गई है।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `cancel_order` | `{"order_id": "ORD-121"}` | injected_failure | timeout talking to order service |
| 1 | 0 | `update_quantity` | `{"order_id": "ORD-122", "quantity": 2}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-121.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-121'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `tool_selection` (likely) expected.required_actions[0], tool_calls[1]; `recovery_failure` (likely) tool_calls[0]

Final state: ORD-121 placed qty 1, ORD-122 placed qty 2, ORD-123 placed qty 1

- Expected: cancel ORD-121 (retry after the injected failure) and set ORD-122 to 2. Actual: no retry;
  ORD-122 updated correctly; the reply honestly reports the failure.
- A (medium): did not retry or check the order. F (low, open question): the injected error is a
  timeout, after which "report and ask the user" is a defensible choice; the case requires the
  cancel to succeed. The expected behavior is unreviewed.
- E (classification only, fixed): `tool_selection` was wrong. It cites tool_calls[1], a required and
  successful update, as the "other tool used instead", while tool_calls[0] shows `cancel_order` was
  selected. The verdict is unaffected. Re-evaluated in memory with the fixed evaluator:
  `recovery_failure` (likely) tool_calls[0] only. The artifact is unchanged.

### requires-clarification-red-order: `fail`

`run_id` `478ee6ed07c6445791ef912a45c93a68`

- Turn 0 user: वो लाल वाला order cancel कर दो।
- Turn 0 agent reply: "कृपया बताएं कि आपका लाल वाला order का आईडी क्या है जिसे हम रद्द कर दें।"
- Turn 1 user: दुपट्टा वाला।
- Turn 1 agent reply: "कृपया बताएं कि आपका दुपट्टा वाला order का आईडी क्या है जिसे हम रद्द कर दें।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"kind": "confirm", "question": "कृपया बताएं कि आपका लाल वाला कौन सा order है जिसे हम रद्द कर दें।"}` | ok |  |
| 1 | 0 | `cancel_order` | `{"order_id": "लाल वाला"}` | rejected | no such order: लाल वाला |
| 2 | 0 | `ask_user` | `{"question": "कृपया बताएं कि आपका लाल वाला order का आईडी क्या है जिसे हम रद्द कर दें।", "kind": "clarify"}` | ok |  |
| 3 | 0 | `cancel_order` | `{"order_id": "लाल वाला"}` | rejected | no such order: लाल वाला |
| 4 | 1 | `cancel_order` | `{"order_id": "दुपट्टा वाला"}` | rejected | no such order: दुपट्टा वाला |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-902.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-902'} |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: cancel_order {'order_id': 'लाल वाला'} (rejected), cancel_order {'order_id': 'लाल वाला'} (rejected), cancel_order {'order_id': 'दुपट्टा वाला'} (rejected) |
| ask_policy | fail | no ask_user(clarify) in a turn before cancel_order at tool_calls[1] |
| evidence | pass | tool calls and state recorded |

Stored classifications: `ambiguity_handling` (likely) tool_calls[1]; `entity_resolution` (likely) expected.required_actions[1], tool_calls[1], tool_calls[3], tool_calls[4]

Final state: ORD-901 placed qty 1, ORD-902 placed qty 1, ORD-903 placed qty 1

- Expected: clarify in turn 0, cancel ORD-902 (Red Dupatta) in turn 1. Actual: descriptive phrases
  passed as `order_id` in both turns; no lookup.
- A (high). D (low): tools take ids only. B: in turn 1 the agent carried दुपट्टा वाला from the
  user's answer into its call, consistent with the intended reading (low confidence). E: none.

### similar-items-kurta-kurti: `fail`

`run_id` `2b3ae4d2b8ba455887a10cd8476a4243`

- Turn 0 user: कुर्ती वाले order की quantity 2 कर दो।
- Turn 0 agent reply: "कुर्ती का ऑर्डर (ORD-701) की मात्रा सफलतापूर्वक 2 कर दी गई है। क्या आपको कुछ और करने की आवश्यकता है?"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `list_orders` | `{}` | ok |  |
| 1 | 0 | `update_quantity` | `{"order_id": "ORD-701", "quantity": 2}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-701.quantity: expected 1, got 2; orders.ORD-702.quantity: expected 2, got 1 |
| required_actions | fail | no successful call for: update_quantity {'order_id': 'ORD-702', 'quantity': 2} |
| forbidden_actions | fail | forbidden calls (incl. past max_attempts or outside exclusive_actions) made: update_quantity {'order_id': 'ORD-701', 'quantity': 2} (ok) |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `entity_resolution` (likely) expected.required_actions[0], tool_calls[1]

Final state: ORD-701 placed qty 2, ORD-702 placed qty 1

- Expected: ORD-702 (Kurti) quantity 2. Actual: ORD-701 (Kurta) set to 2, and the reply calls ORD-701
  "कुर्ती का ऑर्डर" (a wrong claim).
- A (medium): matched the wrong item after listing both. B (low): the utterance is Devanagari कुर्ती
  and the items are Latin "Kurta"/"Kurti"; cross-script near-identical names are the scenario's
  intended difficulty, but careless matching cannot be ruled out. E: none.

### similar-sellers-mohan-sohan: `pass`

`run_id` `a8bf33fb14ef4cb99a12c7192a056bf2`

- Turn 0 user: Sohan Stores वाला order cancel कर दो, Mohan Stores वाला रहने दो।
- Turn 0 agent reply: "आपका ऑर्डर आईडी \"ORD-602\" का ऑर्डर कैंसिल कर दिया गया है। \"Mohan Stores\" के ऑर्डर \"ORD-601\" को रहने दिया गया है। कोई और सहायता की आवश्यकता है कि बताएं।"

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `ask_user` | `{"kind": "clarify", "question": "कृपया बताइए कि आपका कौन सा ऑर्डर कैंसिल कराना है जिसका ऑर्डर आईडी बताएं ताकि हम आपकी मदद कर सकें।"}` | ok |  |
| 1 | 0 | `list_orders` | `{}` | ok |  |
| 2 | 0 | `cancel_order` | `{"order_id": "ORD-602"}` | ok |  |

| check | verdict | detail |
|---|---|---|
| final_state | pass | 2 paths match |
| required_actions | pass | 1 succeeded |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: none

Final state: ORD-601 placed qty 1, ORD-602 cancelled qty 1

- Pass supported. An unnecessary clarifying question was asked and not waited for; not judged (no
  `ask_before`).

### tool-failure-cancel: `fail`

`run_id` `44fce926b8074feba30cb6ded446d0de`

- Turn 0 user: ORD-111 cancel कर दो, जल्दी।
- Turn 0 agent reply: "503 Service Unavailable: order service busy, please try again later."

| # | turn | tool | args | status | error |
|---|---|---|---|---|---|
| 0 | 0 | `cancel_order` | `{"order_id": "ORD-111"}` | injected_failure | 503 Service Unavailable: order service busy, please retry |

| check | verdict | detail |
|---|---|---|
| final_state | fail | orders.ORD-111.status: expected 'cancelled', got 'placed' |
| required_actions | fail | no successful call for: cancel_order {'order_id': 'ORD-111'} |
| forbidden_actions | pass | none attempted |
| ask_policy | pass | asks precede actions |
| evidence | pass | tool calls and state recorded |

Stored classifications: `recovery_failure` (likely) tool_calls[0]

Final state: ORD-111 placed qty 1

- Expected: retry and cancel ORD-111. Actual: no retry; the error was relayed to the user.
- A (high): the error text itself says "please retry". E: none.

## Evaluator defects

One, classification only, no verdict affected:

- `recovery-after-failed-cancel`: `tool_selection` was emitted for an unmet required action whose tool
  the agent did attempt (the attempt hit the injected failure), citing another *required* call as
  evidence. Fix: `tool_selection` now needs the required tool to be unattempted. Test:
  `test_unrecovered_injected_failure_is_recovery_failure` now asserts the exact classification list.
  This scenario had been probed in the earlier audit and wrongly accepted there.

Every verdict follows from its checks, and every check matches the recorded calls and state.
Re-evaluating all 12 artifacts in memory reproduces the stored evaluations exactly with the
evaluator used at run time, and differs only in the classification above with the fixed one.

## Limitations

- One run, one prompt, unseeded sampling at the model's default temperature 0.6: counts are not a
  measurement of qwen3:8b.
- Failures largely reflect the example agent (its prompt never says to look orders up; its loop
  continues after `ask_user`); a different agent design could behave very differently.
- No case has native-speaker review; every B tag is low confidence and C/F cannot be ruled out.
- The repo has no commits; the suite and evaluator are identified only by the hashes above.
