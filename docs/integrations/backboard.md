# Backboard bridge (example, not verified live)

`examples/backboard_agent.py` is a stdlib-only BoliBench webhook agent whose model runs on
[Backboard](https://backboard.io): one API key, many providers, including open-weight models through
`llm_provider: "openrouter"`. BoliBench and its evaluator are unchanged; every tool call Backboard asks
for is executed only through the turn's `tools_url`, so verdicts rest on sandbox-observed tool calls.

Status: tested offline against a local stub of the documented API only. No Backboard key was
available, so it has **never been run against the real API**; the field names below come from
Backboard's docs (`docs.backboard.io`, read 2026-10-17), not from observed responses.

## How it maps

- Turn → `POST https://app.backboard.io/api/threads/messages` (JSON, header `X-API-Key`) with
  `content` (the utterance), `system_prompt` (the Python example's prompt plus `context`; Backboard does
  not persist it, so it is sent every turn), `tools` (OpenAI function schemas from the turn's tool list),
  `llm_provider`, `model_name`, `memory: "off"`, `stream: false`. Turn 0 omits `thread_id` (Backboard
  creates a thread); later turns pass the thread of that BoliBench conversation.
- `status: "REQUIRES_ACTION"` with `tool_calls` → each call is POSTed to `tools_url`, and all outputs
  are submitted together to `POST /threads/tool-outputs` (`{thread_id, tool_outputs: [{tool_call_id,
  output}]}`), as Backboard requires an output for every call of the round. At most 8 rounds per turn.
- `status: "COMPLETED"` → `content` is the reply. Any other status (`FAILED`, ...) or HTTP error fails the
  turn with HTTP 500, so BoliBench records `error`.
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

```sh
export BACKBOARD_API_KEY=...
# pick open-weight models that support tools
curl -s "https://app.backboard.io/api/models?model_type=llm&supports_tools=true&provider=openrouter&limit=100" \
  -H "X-API-Key: $BACKBOARD_API_KEY" | python3 -m json.tool | less
python examples/backboard_agent.py --provider openrouter --model <model name from the list> --port 8000
uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8000/turn \
  --timeout 180 --output runs/backboard-<model>-smoke-<date>/
```

Then the full suite once per model into its own `runs/` directory, and compare `summary.json` counts.
Check first that one case passes and that its artifact's `tool_calls` are the calls the model made.

Things the docs leave open, to confirm on the first live run: whether `/threads/tool-outputs` needs
`llm_provider`/`model_name` again, and how `tool_calls[].function.arguments` arrives (the bridge
expects a JSON string, as in the docs' examples).

## Tests

`uv run pytest tests/test_backboard_agent.py`: a local stub serves `/threads/messages`,
`/threads/tool-outputs` and the BoliBench gateway. Covers request fields and the key header,
`ask_user` ending the turn (later calls not sent, every call still answered), thread continuity across
turns, a failed run failing the turn, and that the identity is accepted and the key stays out of `repr`.
