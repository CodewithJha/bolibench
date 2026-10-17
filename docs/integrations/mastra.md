# Mastra agent on an open-weight model (example)

`examples/mastra-agent/` is a BoliBench webhook agent built with the [Mastra](https://mastra.ai)
TypeScript framework (`@mastra/core` 1.78.0) and running `qwen3:8b` locally through Ollama. It shows
BoliBench judging a framework-built agent with the evaluator unchanged: Mastra decides which tools to
call, but every call goes through BoliBench's tool gateway, so the verdict rests on sandbox-observed
tool calls and final state, never on what the agent says it did.

## How it works

- Node `http` server, `POST /turn` only, request body capped at 64 KiB, turn request validated with zod
  (`tools_url` must be `http` on `127.0.0.1`, `localhost` or `[::1]`).
- Per turn, one Mastra `Agent` is built. Its tools are made with `createTool` from the turn's `tools`
  list (zod input schemas; `quantity` is an integer, everything else a string). Each tool's `execute`
  only POSTs `{"tool", "args"}` to the turn's `tools_url` and returns the gateway's reply to the model.
- `ask_user` ends the turn, as in `examples/ollama_agent.py`: tool calls run one at a time in model
  order (`toolCallConcurrency: 1`), a `stopWhen` condition stops the loop after `ask_user`, any call
  after it in the same step is answered "not sent" without touching the gateway, and the question is
  the reply.
- Bounded: `maxSteps: 8` model calls per turn (then the reply is "Sorry, I could not finish that.", as
  in the Python example), 30 s per tool call, `TURN_TIMEOUT_S` (default 170) for the whole turn.
- A gateway answer other than 200 (stale token, malformed request) fails the turn with HTTP 500, so
  BoliBench records the case as `error` instead of the model seeing a protocol problem as a tool result.
- Conversation history is kept in memory per BoliBench `conversation`, cleared on each turn 0 (BoliBench
  runs one case at a time). No Mastra memory or storage packages.
- Model: Mastra's built-in model router with a custom OpenAI-compatible URL,
  `model: { id: 'ollama/qwen3:8b', url: 'http://127.0.0.1:11434/v1' }`, the documented way to use a
  local model in Mastra ([Model Providers, "Use local models"](https://mastra.ai/models)). No extra
  provider package and no API key (a dummy value is sent; Ollama ignores it). Thinking is turned off
  with `providerOptions.openaiCompatible.reasoningEffort: 'none'`, which Ollama maps to `think: false`.
- Same system prompt and tool descriptions as `examples/ollama_agent.py`.
- Identity: `{"name": "bolibench-mastra-agent", "version": "<package.json version>+<model>"}`, e.g.
  `0.1.0+qwen3:8b`. Unlike the Python example the version is not a code hash, so bump `version` in
  `package.json` when the agent changes.

## Setup

Node 22.18 or newer (runs the `.ts` files directly through Node's type stripping, no build step).

```sh
ollama serve                                  # qwen3:8b already pulled
cd examples/mastra-agent
npm install
MODEL=qwen3:8b PORT=8000 npm start            # prints the /turn URL
```

Environment (all optional):

| Variable | Default |
|---|---|
| `MODEL` | `qwen3:8b` (any Ollama model with tool calling) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` (any OpenAI-compatible base URL) |
| `PORT` | `8000` (`0` = random) |
| `TURN_TIMEOUT_S` | `170`, keep it below BoliBench's `--timeout` |

Then, from the repository root:

```sh
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
```

Checks: `npm test` (offline: the real Mastra loop against a scripted OpenAI-compatible model and a stub
gateway; covers `ask_user` ending the turn, history across turns, gateway refusals, the localhost rule,
identity, 400 and 413) and `npm run typecheck`.

## Results (2026-10-17, qwen3:8b Q4_K_M via Ollama 0.30.10, Apple Silicon, 16 GB)

Single runs; another worker's `gemma3:4b` shared the Ollama server during the full run.

| Run | Verdicts | Artifacts |
|---|---|---|
| Smoke: `cancel-single-order`, `requires-clarification-red-order`, `tool-failure-cancel` | 3 pass | `runs/mastra-qwen3-8b-smoke-2026-10-17/` |
| Full `suites/orders` (12 cases, about 6.5 min) | 6 pass, 6 fail, 0 error | `runs/mastra-qwen3-8b-2026-10-17/` |

Full-run failures, from the evaluator's checks:

- `ambiguous-previous-order`: cancelled `ORD-101` without asking for confirmation first (`ambiguity_handling`).
- `missing-info-which-order`: asked `confirm` where a `clarify` was required (`ambiguity_handling`).
- `codeswitch-cancel-kurta`: asked `confirm` and ended the turn without cancelling `ORD-301`.
- `awadhi-cancel-yesterday`: listed orders, never cancelled `ORD-401`.
- `similar-items-kurta-kurti`: changed the quantity of the wrong order (`ORD-701` instead of `ORD-702`; `entity_resolution`).
- `similar-sellers-mohan-sohan`: asked `clarify` and never cancelled `ORD-602`.

The six passes include both injected-failure cases (retried once, then succeeded) and the
clarification case across two turns. The per-case verdicts happen to equal those of the Python
example's v2 run on the same model (`runs/qwen3-8b-agent-v2-2026-10-17/`); with one run each, that
says nothing about whether the two agents are equivalent.

The first smoke attempt ended as 3 `error` (connection refused) because the agent process had exited
before the run, a harness mistake; that artifact was deleted and the smoke re-run.

## Limitations

- An example, not part of the package; its tests are offline only and nothing in CI starts a model.
- Ollama's OpenAI-compatible endpoint uses the model's default context (4096 for this run); the
  native-API Python example has the same default.
- Invalid tool arguments (e.g. `quantity` as a string) are rejected by Mastra's input validation and
  never reach the gateway, so they are not recorded as attempts; the Python example sends them and the
  sandbox records them as `rejected`.
- Calls after `ask_user` stay in the Mastra history with a "not sent" result; the Python example drops
  them from its history.
- Conversation memory is per process and in memory; restart the agent between runs if in doubt.
