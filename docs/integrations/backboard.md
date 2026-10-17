# Backboard bridge (example, not verified live)

`examples/backboard_agent.py` is a stdlib-only BoliBench webhook agent whose model runs on
[Backboard](https://backboard.io): one API key, many providers, including open-weight models through
`llm_provider: "openrouter"`. BoliBench and its evaluator are unchanged; every tool call Backboard asks
for is executed only through the turn's `tools_url`, so verdicts rest on sandbox-observed tool calls.

Status: tested offline against a local stub of the documented API only. On 2026-10-18 it was also run
by hand as a process behind `bolibench run --agent-url`, against a stub answering in the documented
shapes: `cancel-single-order` passed. No Backboard key was available, so it has **never been run
against the real API**. The field names below come from Backboard's docs and OpenAPI schema
(<https://docs.backboard.io/llms.txt>, read 2026-10-17 and rechecked 2026-10-18), not from observed
responses.

## How it maps

- Turn → `POST https://app.backboard.io/api/threads/messages` (JSON, header `X-API-Key`) with
  `content` (the utterance), `system_prompt` (the Python example's prompt plus `context`; Backboard does
  not persist it, so it is sent every turn), `tools` (OpenAI function schemas from the turn's tool list),
  `llm_provider`, `model_name`, `memory: "off"`, `stream: false`. Turn 0 omits `thread_id` (Backboard
  creates a thread); later turns pass the thread of that BoliBench conversation. Without
  `assistant_id`, Backboard attaches the new thread to the account's first assistant, creating one
  if needed. Documents attached to an assistant are available to all its threads, so use an account
  whose first assistant has no uploaded documents. Retrieval over unrelated files would be a
  confound.
- `status: "REQUIRES_ACTION"` with `tool_calls` → each call is POSTed to `tools_url`, and all outputs
  are submitted together to `POST /threads/tool-outputs` (`{thread_id, tool_outputs: [{tool_call_id,
  output}]}`, with `output` a string), as Backboard requires an output for every call of the round.
  The schema of that body has `additionalProperties: false`, so provider and model can't be resent
  there; the run keeps the ones given to `/threads/messages`. At most 8 rounds per turn.
- `status: "COMPLETED"` → `content` is the reply. Any other status (`FAILED`, `CANCELLED`,
  `IN_PROGRESS`, missing) or HTTP error (401, 429, 5xx, timeout after 150 s) fails the turn with HTTP
  500. BoliBench records `error`, and the agent prints one line to stderr, such as `turn failed:
  HTTPError: HTTP Error 401: Unauthorized`. Each request is tried once (tested for 401, 429 and 502).
- `ask_user` ends the turn: calls after it are answered "not sent" without reaching the gateway, and the
  question is the reply. Backboard has no way to submit outputs without another model call, so the
  bridge still submits them and answers any further tool calls "not sent" until the run completes; those
  extra model calls cost tokens but cannot touch the sandbox.
- Arguments that are not a JSON object are answered "not sent" to the model and are not recorded as
  attempts.
- Identity: `{"name": "bolibench-backboard-agent", "version": "<sha256[:12] of backboard_agent.py +
  ollama_agent.py>+<provider>/<model>"}`. The prompt and tool schemas are imported from
  `examples/ollama_agent.py`, so its hash is part of the version.
- `BACKBOARD_API_KEY` is read from the environment only, sent only as the `X-API-Key` header, kept out of
  `repr`, and never printed; redirects are not followed (they would carry the header elsewhere).

## Live verification (manual, needs a key)

Get a key at <https://app.backboard.io> under Settings > API Keys (it is shown once). Two terminals:
A runs the bridge, B runs BoliBench.

1. Terminal A, key and model list:

   ```sh
   read -rs BACKBOARD_API_KEY && export BACKBOARD_API_KEY
   curl -s "https://app.backboard.io/api/billing/balance" -H "X-API-Key: $BACKBOARD_API_KEY"
   curl -s "https://app.backboard.io/api/models?model_type=llm&supports_tools=true&provider=openrouter&limit=100" \
     -H "X-API-Key: $BACKBOARD_API_KEY" | python3 -c "import json,sys; [print(m['name']) for m in json.load(sys.stdin)['models']]"
   ```

   Expected: a JSON balance (a `401` means a bad key), then model names. Pick one, e.g. an
   open-weight Gemma or Qwen name from the list.

2. Terminal A, start the bridge:

   ```sh
   python examples/backboard_agent.py --provider openrouter --model <name> --port 8000 2> /tmp/bb-agent.log
   ```

   Expected: `bolibench-backboard-agent <sha>+openrouter/<name> on http://127.0.0.1:8000/turn`.

3. Terminal B, one case:

   ```sh
   uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8000/turn --timeout 180 --output /tmp/bb-backboard/
   python3 -c "import json,glob; d=json.load(open(glob.glob('/tmp/bb-backboard/*/cancel-single-order.json')[0])); print(d['evaluation']['verdict'], [(c['tool'], c['args']) for c in d['run']['tool_calls']])"
   ```

   Expected: `pass [('cancel_order', {'order_id': 'ORD-201'})]` (a `fail` is a model result). An
   `error` puts the reason in `/tmp/bb-agent.log` (`turn failed: ...`). A `422` there means a field
   was rejected, which would be a real mismatch with the docs; report it.

4. In terminal A: `rg -l --fixed-strings "$BACKBOARD_API_KEY" /tmp/bb-backboard /tmp/bb-agent.log ||
   echo "key not in outputs"` must print `key not in outputs`.
5. Then run the full suite once per model, each into its own output directory, and compare the
   `summary.json` counts.

Evidence to keep for the write-up: the terminal output of step 3, and a screenshot of the Backboard
dashboard's usage for that day (or the output of `GET /api/billing/usage/recent`). Don't screenshot
the API keys page. Cost: one case is a few model calls on the chosen model. Extra rounds after
`ask_user` (see above) cost tokens too.

Key rotation: create a new key under Settings > API Keys, export it, restart the bridge (the key is
read only at startup), rerun step 3, then revoke the old key.

What only a live run can confirm: that `tool_calls[].function.arguments` arrives as a JSON string
(as in every docs example; an object would fail the turn with `error`, not be guessed), and that a
non-streaming reply always carries `status`.

## Tests

`uv run pytest tests/test_backboard_agent.py`: a local stub serves `/threads/messages`,
`/threads/tool-outputs` and the BoliBench gateway. Covers request fields (a subset of the documented
JSON fields) and the key header; the tool-outputs body being exactly `{thread_id, tool_outputs}` with
string outputs; `ask_user` ending the turn (later calls not sent, every call still answered); thread
continuity across turns; a failed run, and HTTP 401, 429 and 502, failing the turn after one request;
and that the identity is accepted and the key stays out of `repr`.
