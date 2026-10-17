# Gemma, OpenAI-compatible backends and Sentry agent tracing (example agent)

All of this lives in `examples/ollama_agent.py`, the stdlib example agent behind `bolibench run
--agent-url`. BoliBench itself is unchanged: it still judges only the sandbox-observed tool calls and
final state. The backend, tool mode and tracing are agent-side choices.

Status: tested offline only (`tests/test_example_agent.py`: fakes, a local HTTP stub, and the real
`sentry-sdk` with an in-memory transport). **No live Sentry DSN and no DigitalOcean key were
available, so no event has been sent to Sentry and no hosted endpoint has been called.** See
"Manual verification".

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--model` | `qwen3:8b` | model name as the backend knows it |
| `--backend ollama\|openai` | `ollama` | `ollama`: native `/api/chat`. `openai`: any OpenAI-compatible `/chat/completions` |
| `--base-url URL` | `http://127.0.0.1:11434` for ollama; required for openai | must be `https://`, or `http://` only on `127.0.0.1`, `localhost`, `[::1]`; no credentials, query or fragment. For openai include `/v1` (the agent appends `/chat/completions`) |
| `--api-key-env NAME` | none | the API key is read from environment variable `NAME` and sent as `Authorization: Bearer`. Never a flag value, never printed or logged, not in `Config`'s repr, never sent to the tool gateway. Set but empty = exit with an error naming the variable |
| `--tool-mode native\|json` | `native` | `native`: the backend's tool calling. `json`: prompt-based tool calls for models without native tools (see below) |
| `--sentry-capture-content` | off | send prompts, replies and tool arguments/results to Sentry (see "Privacy"). Exits with an error if `SENTRY_DSN` is unset |
| `--port` | `8000` | port the agent listens on (`127.0.0.1` only) |

HTTP redirects are never followed (they would carry the Authorization header elsewhere), and no
proxy is used.

The agent's self-reported identity (`adapter.self_reported_agent` in artifacts, part of
`config_id`) is `<sha256[:12] of the file>+<model>`, plus `+<backend>-<tool_mode>` when either is not
the default. So a gemma json-mode run is `…+gemma3:4b+ollama-json`, and default qwen runs keep the v2
format. The base URL is not part of the identity: the same model name on two providers looks the same.

## Gemma on Ollama

```sh
ollama show gemma3:4b      # Ollama 0.30.10: Capabilities = completion, vision (no "tools")
```

`gemma3:4b` (ID `a2af6cc3eb7f`, Q4_K_M, 4.3B) does not advertise `tools` in Ollama, and Ollama rejects
a request with tools (`"... does not support tools"`). So use `--tool-mode json`:

```sh
ollama serve                                   # if not already running
python examples/ollama_agent.py --model gemma3:4b --tool-mode json --port 8000
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
```

If a Gemma model's `ollama show` lists `tools`, use `--tool-mode native` with it instead. The mode is
never chosen automatically.

One audited run (gemma3:4b, json mode): 2 pass, 10 fail, 0 error. In 7 cases the model wrote a JSON
tool call the strict parser rejected (trailing period, missing brace, or prose before it). See
`docs/audits/gemma-gemma3-4b-2026-10-17.md`; it is a single unseeded run, not a measurement.

JSON tool mode contract:

- No `tools` are sent. The system prompt lists the tools with their argument types and says: to call
  tools, the whole reply must be `{"tool_calls": [{"name": "<tool>", "arguments": {...}}]}` and
  nothing else; answer the user in plain text.
- Parsing is strict: the reply, stripped of surrounding whitespace, must be exactly that JSON, or
  exactly one fenced block (` ```json ` or ` ``` `) containing it. Exactly the keys `tool_calls` and,
  per call, `name` (string) and `arguments` (object). Anything else (text around it, a trailing
  period, a truncated object, extra keys) is **not a tool call**: the text is the turn's reply and no
  tool runs. Nothing is repaired or guessed.
- Tool results go back as one user message starting `TOOL_RESULTS ` with a JSON list of
  `{"name", "result"}` (Gemma's template has no tool role).
- The same `ask_user` rule as native mode: calls after the first `ask_user` in a reply are dropped.

## OpenAI-compatible backends (DigitalOcean serverless inference and others)

`--backend openai` speaks `POST {base}/chat/completions` with `model`, `messages`, `stream: false`
and (native mode) `tools`. Tool calls are read from `choices[0].message.tool_calls`; a call whose
`arguments` string is not a JSON object, or that has no `id`, is dropped (not guessed). Tool results
go back as `{"role": "tool", "tool_call_id": ..., "content": ...}`. Token usage
(`usage.prompt_tokens`, `completion_tokens`, `total_tokens`) is recorded in Sentry when present.

DigitalOcean serverless inference (base URL `https://inference.do-ai.run/v1`, Bearer auth):

1. Create a model access key: DigitalOcean control panel, Inference, **Model Access Keys**
   (<https://cloud.digitalocean.com/model-studio/manage-keys>), **Create model access key**, scope it
   to the models you need. The secret is shown once; copy it then.
2. Put it in an environment variable (the name is up to you; `MODEL_ACCESS_KEY` here):

   ```sh
   read -rs MODEL_ACCESS_KEY && export MODEL_ACCESS_KEY    # not in shell history
   ```

3. List the models the key can use and pick an id (which open-weight models are offered, and whether
   they support tool calling, is DigitalOcean's catalog, not checked here):

   ```sh
   curl -s -H "Authorization: Bearer $MODEL_ACCESS_KEY" https://inference.do-ai.run/v1/models
   ```

4. Run the agent and BoliBench:

   ```sh
   python examples/ollama_agent.py --backend openai --base-url https://inference.do-ai.run/v1 \
     --api-key-env MODEL_ACCESS_KEY --model <model-id> --tool-mode native --port 8000
   uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
   ```

   Use `--tool-mode json` if the model returns no `tool_calls`. Requests are billed per DigitalOcean's
   usage pricing.

A local OpenAI-compatible server (vLLM, llama.cpp, Ollama's own `/v1`) works the same way with
`--base-url http://127.0.0.1:<port>/v1`, with or without `--api-key-env`.

## Sentry AI agent tracing

Off unless `SENTRY_DSN` is set. Without it, `sentry_sdk` is never imported (tested). With it, the
agent needs `sentry-sdk` (tested with 2.72.0); if it is missing, the agent exits with an error
instead of running untraced.

```sh
export SENTRY_DSN='https://<key>@o<org>.ingest.sentry.io/<project>'
export SENTRY_TRACES_SAMPLE_RATE=1.0          # optional, 0..1, default 1.0; anything else exits
uv run --with 'sentry-sdk>=2.64' python examples/ollama_agent.py --model gemma3:4b --tool-mode json --port 8000
```

(`>=2.64` because that is where the SDK starts streaming `gen_ai` spans as standalone items, which
Sentry's Conversations view needs. `SENTRY_ENVIRONMENT` and `SENTRY_RELEASE` are read by the SDK
itself.)

What is sent, following Sentry's manual AI agent instrumentation
(<https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation/ai-agents-module/manual-instrumentation/>):

| Span | op / name | Attributes |
|---|---|---|
| transaction per turn request | `http.server` / `POST /turn` | tags `model`, `agent.version` (identity version), `backend`, `tool_mode` |
| one per turn | `gen_ai.invoke_agent` / `invoke_agent bolibench-example-ollama-agent` | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name` |
| one per model call | `gen_ai.chat` / `chat <model>` | `gen_ai.operation.name=chat`, `gen_ai.request.model`, `gen_ai.provider.name` (`ollama`, or the base URL's host), `gen_ai.agent.name`, `gen_ai.response.model` (if returned), `gen_ai.usage.input_tokens`/`output_tokens` (Ollama `prompt_eval_count`/`eval_count`; OpenAI `usage`, plus `total_tokens`) |
| one per tool call | `gen_ai.execute_tool` / `execute_tool <tool>` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`, `gen_ai.tool.description`, `gen_ai.agent.name`; when the gateway answers `ok: false`: status `internal_error`, `error.type=tool_error` |

Chat and tool spans are siblings under `invoke_agent`; a chat span ends before its tools run. Every
`gen_ai` span carries `gen_ai.conversation.id` = BoliBench's random per-case `conversation` value
(not user data), so a case's turns group into one Sentry Conversation. A transaction wraps each
turn because the SDK sends no spans without one.

### Privacy

By default no content is sent: no utterance, reply, system prompt, tool argument or tool result
(tested against the real SDK). The SDK's own PII defaults are left conservative; no
`send_default_pii` is set. `--sentry-capture-content` adds `gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.call.arguments` and
`gen_ai.tool.call.result`. BoliBench cases are synthetic, but an agent pointed at real users would
send their messages. Turn it on only on purpose.

What is still sent without the flag: model and tool names, token counts, timings, the conversation
id, and the SDK's default integrations' data. Notably, the stdlib `http.client` integration records
outgoing request URLs (the model endpoint, and the tool gateway URL with its per-turn token, which
is revoked when the turn ends) but no headers or bodies. Trace propagation headers are disabled
(`trace_propagation_targets=[]`), so the model provider and the gateway receive no Sentry headers.

## Manual verification (not yet done)

Sentry:

1. Create a Python project in Sentry; copy its DSN (Project Settings, Client Keys (DSN)).
2. `export SENTRY_DSN=...` and start the agent with `uv run --with 'sentry-sdk>=2.64' python examples/ollama_agent.py ...`.
3. Run one case: `uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8000/turn --timeout 180 --output /tmp/bb/`.
4. In Sentry, open Explore, Traces and search `span.op:gen_ai.invoke_agent`; open the trace and check
   the `invoke_agent` span has `chat` and `execute_tool` children with the attributes above, token
   counts on `chat`, and tags `model`/`agent.version` on the `POST /turn` transaction. Check the AI
   Agents insights page and the Conversations view for the case's conversation id.
5. Check that no span holds the case utterance (search the trace for a Devanagari word from the case).
   Then restart with `--sentry-capture-content` and check that `gen_ai.input.messages` now appears.
6. With `SENTRY_DSN` set and `sentry-sdk` not installed (`python3 examples/ollama_agent.py`), the agent
   must exit with "SENTRY_DSN is set but sentry-sdk is not installed".

DigitalOcean:

1. Steps 1-4 of the DigitalOcean section with one case first; check the case artifact's
   `adapter.self_reported_agent.version` ends in `+<model-id>+openai-native` (or `-json`).
2. Check the agent's stdout/stderr and the artifact do not contain the key
   (`grep -r "$MODEL_ACCESS_KEY" <run dir> agent.log` finds nothing).
3. `--base-url http://inference.do-ai.run/v1` must be refused before anything is sent.

## Rotation

- DigitalOcean model access key: Model Access Keys page, `…`, **Regenerate** (the old secret stops
  working at once), or delete it and create a new one. Update the environment variable and restart
  the agent; the key is read only at startup.
- Sentry DSN: Project Settings, Client Keys (DSN): create a new key, switch `SENTRY_DSN`, restart the
  agent, then disable or revoke the old key.

## Limitations

- Offline-tested only; no live Sentry ingestion or hosted endpoint has been exercised.
- JSON tool mode depends on the model following a text format. A reply that is almost a tool call
  is treated as text by design; how often that happens is a property of the model and prompt, and
  shows in the artifacts as a JSON-looking `agent_reply` with no tool call.
- `gen_ai.provider.name` for `--backend openai` is the base URL's host (e.g. `inference.do-ai.run`),
  not a canonical provider id, so Sentry may not resolve model costs for it.
- No streaming, no retries of model calls, one conversation history per process (never evicted).
- Model-call errors (HTTP errors, timeouts, malformed responses) end the turn with an HTTP connection
  close, which BoliBench records as an `error` verdict. They are not sent to Sentry as error events.
  The open spans end with an error status.
- The base URL is not part of the agent identity or `config_id`.
