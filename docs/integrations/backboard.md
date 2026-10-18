# Backboard bridge (example, verified live 2026-10-18)

`examples/backboard_agent.py` is a stdlib-only BoliBench webhook agent whose model runs on
[Backboard](https://backboard.io): one API key, many providers, including open-weight models through
`llm_provider: "openrouter"`. BoliBench and its evaluator are unchanged; every tool call Backboard asks
for is executed only through the turn's `tools_url`, so verdicts rest on sandbox-observed tool calls.

Status: run against the real API on 2026-10-18 (audit: [`docs/audits/backboard-2026-10-18.md`](../audits/backboard-2026-10-18.md)).
Auth, model listing, assistants and threads, the tool-call round trip and memory isolation were checked
live. Two bridge bugs found that day are fixed and covered by offline tests that replay the real response
shapes. The free credit on the test account does not pay for LLM chat, so the open-weight model picked
(`openrouter` / `qwen/qwen3-235b-a22b-2507`) recorded `error`. With the zero-priced
`openrouter` / `dots-studio/dots-3-note-preview:free`, 4 cases gave 3 `pass` and 1 `fail` (a model
choice: it cancelled without confirming).

## How it maps

- Assistant: `--assistant-id` (required) names a dedicated assistant whose name must start with
  `bolibench-`. At startup the bridge `GET`s it and exits otherwise. Without `assistant_id`, Backboard
  attaches new threads to the account's *first* assistant, which may belong to another app and carry
  documents the model could retrieve. Create one with
  `curl -X POST https://app.backboard.io/api/assistants -H "X-API-Key: $BACKBOARD_API_KEY" -H "Content-Type: application/json" -d '{"name":"bolibench-agent"}'`
  and use the returned `assistant_id`.
- Turn → `POST https://app.backboard.io/api/threads/messages` (JSON, header `X-API-Key`) with
  `content` (the utterance), `system_prompt` (the Python example's prompt plus `context`; not persisted, so
  sent every turn), `tools` (OpenAI function schemas from the turn's tool list), `llm_provider`,
  `model_name`, `memory: "off"`, `stream: false`. Turn 0 sends `assistant_id` and no `thread_id`, so every
  case gets a new thread. Later turns send that conversation's `thread_id`.
- `status: "REQUIRES_ACTION"` with `tool_calls` → each new call is POSTed to `tools_url`, then all outputs
  go to `POST /threads/{thread_id}/runs/{run_id}/submit-tool-outputs` as `{tool_outputs: [{tool_call_id,
  output}], tools}`, with `output` a JSON string. The simpler `/threads/tool-outputs` can't carry `tools`.
  Its continuation ran without them, and the model then wrote later calls as plain text (seen live).
  A run's `tool_calls` list every call of the run so far. The bridge keeps each output by
  `tool_call_id`, resubmits repeated ids with their stored output, and never sends them to the gateway again.
  At most 8 rounds per turn.
- `status: "COMPLETED"` → `content`, stripped, is the reply. Any other status or an HTTP error (401, 429,
  5xx, timeout after 150 s) fails the turn with HTTP 500. BoliBench records `error`, and the agent prints
  one line to stderr. Backboard reports billing and upstream-provider failures as HTTP **200** with
  `status: "FAILED"` and the reason in `content`, for example `turn failed: RuntimeError: Backboard run
  FAILED: Your free credit is reserved for Memory & RAG, so it can't cover LLM chat. …`. Each request is
  tried once.
- `ask_user` ends the turn: calls after it are answered "not sent" without reaching the gateway, and the
  question is the reply. Backboard needs an output for every call before the run can end, so the bridge
  still submits them and answers further calls "not sent" until the run completes. Those extra model
  calls cost tokens but cannot touch the sandbox.
- Arguments that are not a JSON object are answered "not sent" to the model and are not recorded as
  attempts. They arrived as JSON strings in every live reply.
- Memory: Backboard memory belongs to an assistant and is shared by all its threads when a message
  sets `memory`/`memory_pro` to `Auto` or `Readonly`. With `"off"` nothing is stored or retrieved. A live
  check showed a fact from one thread unknown in the next with `off`, recalled with `Readonly` after
  `Auto` stored it, and invisible to another assistant. Keep it `off` so cases can't leak into each other.
- Identity: `{"name": "bolibench-backboard-agent", "version": "<sha256[:12] of backboard_agent.py +
  ollama_agent.py>+<provider>/<model>"}`. The prompt and tool schemas are imported from
  `examples/ollama_agent.py`, so its hash is part of the version.
- `BACKBOARD_API_KEY` is read from the environment only, sent only as the `X-API-Key` header, kept out of
  `repr`, and never printed. Redirects and proxies are not followed. The latter means the bridge needs
  direct network access.

## Billing

`GET /api/billing/balance` returns `balance_usd`, `paid_credit_usd`, `free_credit_usd`.
`GET /api/billing/usage/recent?start=YYYY-MM-DD` returns per-call events with `amount_deducted_usd`.
On 2026-10-18, free credit paid only for Memory and RAG: chat on `openrouter` and `cerebras` models came
back `FAILED`, except zero-priced `:free` models. A paid model needs paid credit or a subscription. The
model catalog shows rates under `billing.rates` (USD per 1M tokens).

## Live verification (manual, needs a key)

Two terminals: A runs the bridge, B runs BoliBench.

1. Terminal A, key, balance and tool-capable models:

   ```sh
   read -rs BACKBOARD_API_KEY && export BACKBOARD_API_KEY
   curl -s "https://app.backboard.io/api/billing/balance" -H "X-API-Key: $BACKBOARD_API_KEY"
   curl -s "https://app.backboard.io/api/models?model_type=llm&supports_tools=true&provider=openrouter&limit=500" \
     -H "X-API-Key: $BACKBOARD_API_KEY" | python3 -c "import json,sys; [print(m['name']) for m in json.load(sys.stdin)['models']]"
   ```

   Expected: a JSON balance (a `401` means a bad key), then model names (305 on 2026-10-18).

2. Terminal A, create a `bolibench-*` assistant (see above), then start the bridge:

   ```sh
   python3 -u examples/backboard_agent.py --assistant-id <uuid> --provider openrouter --model <name> --port 8000 2> /tmp/bb-agent.log
   ```

   Expected: `assistant <uuid> (bolibench-agent)`, then
   `bolibench-backboard-agent <sha>+openrouter/<name> on http://127.0.0.1:8000/turn`.

3. Terminal B, one case:

   ```sh
   uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8000/turn --timeout 180 --output /tmp/bb-backboard/
   python3 -c "import json,glob; d=json.load(open(glob.glob('/tmp/bb-backboard/*/cancel-single-order.json')[0])); print(d['evaluation']['verdict'], [(c['tool'], c['args']) for c in d['run']['tool_calls']])"
   ```

   Observed 2026-10-18 with `dots-studio/dots-3-note-preview:free`:
   `pass [('get_order', {'order_id': 'ORD-201'}), ('cancel_order', {'order_id': 'ORD-201'})]`.
   An `error` puts the reason in `/tmp/bb-agent.log` (`turn failed: ...`).

4. In terminal A: `rg -l --fixed-strings "$BACKBOARD_API_KEY" /tmp/bb-backboard /tmp/bb-agent.log ||
   echo "key not in outputs"` must print `key not in outputs`.

Clean-up: `DELETE /api/assistants/{id}` removes the assistant with its threads and documents. Delete
memories first with `DELETE /api/assistants/{id}/memories/{memory_id}` if any were stored.

## Tests

`uv run pytest tests/test_backboard_agent.py`: a local stub serves Backboard (`GET /assistants/{id}`,
`/threads/messages`, the run's `submit-tool-outputs`) and the BoliBench gateway. Some stub replies are
copied from real 2026-10-18 responses. Covers:

- request fields (a subset of the documented JSON fields), the key header, and `assistant_id` on turn 0
  only;
- the submit body being exactly `{tool_outputs, tools}`, with string outputs;
- a run's repeated `tool_calls` reaching the gateway once, and the reply being stripped;
- `ask_user` ending the turn (later calls not sent, every call still answered);
- thread continuity across turns;
- `FAILED` runs (including the real billing refusal) and HTTP 401, 429 and 502 failing the turn after one
  request;
- the `bolibench-*` assistant guard;
- the identity being accepted, and the key staying out of `repr`.
