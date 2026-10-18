# Gemma, OpenAI-compatible backends and Sentry agent tracing (example agent)

All of this lives in `examples/ollama_agent.py`, the stdlib example agent behind `bolibench run
--agent-url`. BoliBench itself is unchanged: it still judges only the sandbox-observed tool calls and
final state. The backend, tool mode and tracing are agent-side choices.

Status: tested offline only (`tests/test_example_agent.py`: fakes, a local HTTP stub, and the real
`sentry-sdk` with an in-memory transport). On 2026-10-18 it was also run by hand as a process:
`bolibench run --agent-url` drove the agent with `--backend openai` against a local stub of the
Chat Completions API, with `SENTRY_DSN` pointing at a local envelope sink. `cancel-single-order`
passed. With a wrong key, the case was `error` and a Sentry error event was sent, and neither the key
nor the utterance appeared in any envelope. **No live Sentry DSN and no DigitalOcean key were
available, so no event has reached Sentry and DigitalOcean has not been called.** See "Manual
verification".

Hosted endpoint verified: on 2026-10-18 the `openai` backend ran the full suite against Gemma 4
(`gemma-4-31b-it`) on Google's Gemini API OpenAI-compatible endpoint, with native tool calls (8 pass,
3 fail, 1 error, single run). See "Gemma 4 on the Gemini API" and
`docs/audits/gemma4-gemini-api-2026-10-18.md`.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--model` | `qwen3:8b` | model name as the backend knows it |
| `--backend ollama\|openai` | `ollama` | `ollama`: native `/api/chat`. `openai`: any OpenAI-compatible `/chat/completions` |
| `--base-url URL` | `http://127.0.0.1:11434` for ollama; required for openai | must be `https://`, or `http://` only on `127.0.0.1`, `localhost`, `[::1]`; no credentials, query or fragment. For openai include `/v1` (the agent appends `/chat/completions`) |
| `--api-key-env NAME` | none | the API key is read from environment variable `NAME` and sent as `Authorization: Bearer`. Never a flag value, never printed or logged, not in `Config`'s repr, never sent to the tool gateway. Set but empty = exit with an error naming the variable |
| `--tool-mode native\|json` | `native` | `native`: the backend's tool calling. `json`: prompt-based tool calls for models without native tools (see below) |
| `--reasoning-effort none\|minimal\|low\|medium\|high` | not sent | openai backend only (exits with an error for ollama, whose thinking is always off): sent as `reasoning_effort`. Gemma 4 on the Gemini API needs `minimal` (see below). Part of the identity when set |
| `--sentry-capture-content` | off | send prompts, replies and tool arguments/results to Sentry (see "Privacy"). Exits with an error if `SENTRY_DSN` is unset |
| `--port` | `8000` | port the agent listens on (`127.0.0.1` only) |

HTTP redirects are never followed (they would carry the Authorization header elsewhere), and no
proxy is used.

The agent's self-reported identity (`adapter.self_reported_agent` in artifacts, part of
`config_id`) is `<sha256[:12] of the file>+<model>`, plus `+<backend>-<tool_mode>` when either is not
the default, plus `+reasoning-<level>` when `--reasoning-effort` is set. So a gemma json-mode run is
`…+gemma3:4b+ollama-json`, a Gemini API Gemma 4 run is `…+gemma-4-31b-it+openai-native+reasoning-minimal`,
and default qwen runs keep the v2 format. The base URL is not part of the identity: the same model
name on two providers looks the same.

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

Each model call has a 300 s timeout, and a turn makes at most 8 model calls. A 429 or 5xx response
is retried after 2 s and then 5 s (3 attempts in all), and each retry prints one line to stderr
(`model call: HTTP 500, retrying in 2s`; status code only). Any other HTTP error (401, 400, ...), a
timeout, a malformed response, or a third 429/5xx ends the turn. BoliBench then records the case as
`error` (`agent request failed: Remote end closed connection without response`), and the agent's
stderr holds the traceback (`urllib.error.HTTPError: HTTP Error 401: ...`). A traceback shows source
lines, not values, so the key is never printed. Tested: 400/401 make one request, 429/500/503 make
three, a 500 then 429 then success finishes the turn, and the key is not in the error. Retries add
at most 7 s of waiting per model call plus the extra requests' time, all inside BoliBench's
`--timeout` for the turn. The retry exists because the Gemini API returned sporadic HTTP 500s for
Gemma 4 that succeeded on the next attempt (below).

DigitalOcean serverless inference (base URL `https://inference.do-ai.run/v1`, Bearer auth):

1. Create a model access key: DigitalOcean control panel, Inference, **Model Access Keys**
   (<https://cloud.digitalocean.com/model-studio/manage-keys>), **Create model access key**, scope it
   to the models you need. The secret is shown once; copy it then.
2. Put it in an environment variable (the name is up to you; `MODEL_ACCESS_KEY` here):

   ```sh
   read -rs MODEL_ACCESS_KEY && export MODEL_ACCESS_KEY    # not in shell history
   ```

3. List the models the key can use and pick an id:

   ```sh
   curl -s -H "Authorization: Bearer $MODEL_ACCESS_KEY" https://inference.do-ai.run/v1/models | python3 -m json.tool | grep '"id"'
   ```

   DigitalOcean's model table (<https://docs.digitalocean.com/products/inference/details/models/>,
   read 2026-10-18) lists Gemma 4 as `gemma-4-31B-it` for serverless inference through "Chat
   Completions and Responses APIs" with prompt caching. Unlike for some other models in the same
   table, **tool calling is not listed for it**, and the features page only promises tool calling for
   the Anthropic and OpenAI models. So start Gemma with `--tool-mode json`. Try `native` only as a
   comparison, and believe it only if the artifacts show real `tool_calls`.

4. Run the agent and BoliBench:

   ```sh
   python examples/ollama_agent.py --backend openai --base-url https://inference.do-ai.run/v1 \
     --api-key-env MODEL_ACCESS_KEY --model gemma-4-31B-it --tool-mode json --port 8000
   uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
   ```

   Requests are billed per token at DigitalOcean's serverless inference prices (see the model
   catalog). A full suite run is 12 cases, about 14 turns and a few model calls per turn.

A local OpenAI-compatible server (vLLM, llama.cpp, Ollama's own `/v1`) works the same way with
`--base-url http://127.0.0.1:<port>/v1`, with or without `--api-key-env`.

## Gemma 4 on the Gemini API (verified 2026-10-18)

Google serves the open-weight Gemma 4 models `gemma-4-31b-it` and `gemma-4-26b-a4b-it` on the Gemini
API (<https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api>), which documents system
instructions and function calling for them. The OpenAI-compatible base URL is
`https://generativelanguage.googleapis.com/v1beta/openai` (<https://ai.google.dev/gemini-api/docs/openai>,
beta), with a Gemini API key from Google AI Studio as the Bearer token.

```sh
set -a; . ./.env; set +a          # a git-ignored file holding GEMINI_API_KEY=...; never cat it
python3 examples/ollama_agent.py --backend openai \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai \
  --api-key-env GEMINI_API_KEY --model gemma-4-31b-it --tool-mode native --reasoning-effort minimal --port 8765
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8765/turn --timeout 180 --output runs/
```

Found by bounded probes (details and status codes in the audit):

- **Native tools work** for both models: `choices[0].message.tool_calls` with a JSON-string
  `arguments` and an `id`, `finish_reason` `tool_calls`. The system role is accepted, so it does not
  need to be folded into the user message.
- **Use `--reasoning-effort minimal`.** Thinking is on by default, and the reasoning comes back
  inside `content` as a `<thought>…</thought>` prefix. In json mode that makes every tool call
  unparseable, and in native mode it would leak into the reply. `minimal` turns it off, as the Gemma
  docs describe. `none` and `low` are rejected with HTTP 400 ("Thinking budget/level is not
  supported for this model"). With `minimal`, json mode also works: replies were exactly the
  `{"tool_calls": …}` object.
- Tool calls carry `extra_content.google.thought_signature`. The agent does not send it back, and
  follow-up calls with tool results work without it.
- **Sporadic HTTP 500 `INTERNAL`** errors that succeed on the next attempt. In the audited run, 15
  model calls got a 500 (3 of them twice), and all recovered within the agent's 3-attempt retry. No
  429 and no timeout were seen.
- **Latency:** `gemma-4-31b-it` took 18-51 s per call (with thinking off, too), so a turn with 3
  model calls can approach a 180 s `--timeout`. One case of the audited run was `error` for that
  reason. `gemma-4-26b-a4b-it` took 1-5 s per call.
- Pricing and rate limits for Gemma are not listed on the Gemini API pricing and rate-limit pages
  (read 2026-10-18). Limits are per project and shown in AI Studio.

Audited run: `runs/gemma4-gemma-4-31b-it-gemini-api-2026-10-18/`, 8 pass, 3 fail, 1 error, single
unseeded run. See `docs/audits/gemma4-gemini-api-2026-10-18.md` for per-case causes and the
comparison with local gemma3:4b and qwen3:8b.

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

Errors: if a model call or a tool-gateway call raises (HTTP error, timeout, malformed response), the
open spans get the SDK's error status, and `error.type` is set to the exception class (e.g.
`HTTPError`) on the failed span and on `invoke_agent`. The exception is also sent as a Sentry error
event in the same trace, and then re-raised, so BoliBench still records the case as `error`. Tested
with the real SDK: the event has the exception type, message and stack (source lines only), and no
key, utterance or system prompt.

### Conformance with Sentry's docs (checked 2026-10-18)

Against the manual instrumentation page above and the agent tracing setup page
(<https://docs.sentry.io/platforms/python/tracing/instrumentation/custom-instrumentation/ai-agents-module/>):

- Span ops `gen_ai.invoke_agent`, `gen_ai.chat`, `gen_ai.execute_tool` ("MUST"), names `invoke_agent
  {agent}`, `chat {model}`, `execute_tool {tool}` ("SHOULD"), and the `gen_ai.operation.name` values
  `invoke_agent`, `chat`, `execute_tool` all match. So does the hierarchy, with chat and tool spans as
  siblings.
- Set at span start, as the docs ask: `gen_ai.operation.name`, `gen_ai.provider.name`,
  `gen_ai.request.model`, `gen_ai.agent.name` and `gen_ai.tool.name`.
- `gen_ai.response.model` (marked required on chat spans) is set from the backend's `model` field.
  Ollama and OpenAI-compatible APIs both return it.
- Token counts use `gen_ai.usage.input_tokens` and `output_tokens` (plus `total_tokens` when the
  backend gives it). There are no cache or reasoning subsets, so the docs' negative-cost pitfall
  cannot occur.
- Failed tools get status `internal_error` and `error.type`, which feeds the "Tool Errors" widget.
- Conversations: `sentry_sdk.ai.set_conversation_id()` is called per request, inside an isolation
  scope. The docs say gen_ai spans stream as standalone items from SDK 2.64.0, which Conversations
  needs; hence `sentry-sdk>=2.64`.
- Content attributes, when opted in, are JSON strings, as required. Messages use the OpenAI `{role,
  content}` shape, which the docs accept as legacy. The preferred `{role, parts}` shape is not used,
  so assistant tool calls inside `gen_ai.input.messages` may show only as raw JSON in Sentry's
  conversation view.
- Not sent (all optional): `gen_ai.tool.definitions`, `gen_ai.response.id`,
  `gen_ai.response.finish_reasons`, request parameters (temperature and so on), and `set_user`.

What this gives Sentry's AI Agents views, and what it doesn't: agent runs, model calls (count,
latency, tokens, model), tool calls (count, latency, errors), grouping by conversation, and errors
linked to the trace. Costs need Sentry to know the model name's price. Gemma, qwen3 and other
open-weight names may have none, so cost can show as empty. The trace is the agent's side only:
BoliBench sends no trace headers, so the benchmark run and the agent are separate traces, linked by
the conversation id.

### Privacy

By default no content is sent: no utterance, reply, system prompt, tool argument or tool result
(tested against the real SDK). The SDK's own PII defaults are left conservative; no
`send_default_pii` is set. Note that `send_default_pii` does not filter attributes set by hand: the
SDK sends whatever `set_data` is given (the tests show this), so `--sentry-capture-content` is the
only gate. `include_local_variables=False` is set because error events would otherwise carry each
stack frame's local variables. A test showed that, without it, a failed model call sent the utterance,
the system prompt and `post()`'s `headers` dict with `Authorization: Bearer <key>`. The SDK's scrubber
replaced only the top-level `api_key` variable. `--sentry-capture-content` adds `gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.call.arguments` and
`gen_ai.tool.call.result`. BoliBench cases are synthetic, but an agent pointed at real users would
send their messages. Turn it on only on purpose.

What is still sent without the flag: model and tool names, token counts, timings, the conversation
id, and the SDK's default integrations' data. Notably, the stdlib `http.client` integration records
outgoing request URLs (the model endpoint, and the tool gateway URL with its per-turn token, which
is revoked when the turn ends) but no headers or bodies. Trace propagation headers are disabled
(`trace_propagation_targets=[]`), so the model provider and the gateway receive no Sentry headers.

## Manual verification (not yet done)

Two terminals: A runs the agent, B runs BoliBench. All output goes to `/tmp`.

DigitalOcean (cost: a few cents of tokens for one case, then one full suite):

1. Terminal A:

   ```sh
   read -rs MODEL_ACCESS_KEY && export MODEL_ACCESS_KEY
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $MODEL_ACCESS_KEY" https://inference.do-ai.run/v1/models
   python examples/ollama_agent.py --backend openai --base-url https://inference.do-ai.run/v1 \
     --api-key-env MODEL_ACCESS_KEY --model gemma-4-31B-it --tool-mode json --port 8000 2> /tmp/do-agent.log
   ```

   Expected: `200` from curl (a `401` means a wrong key or a key without access to that model). The
   agent prints nothing while it waits.

2. Terminal B:

   ```sh
   uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8000/turn --timeout 180 --output /tmp/bb-do/
   ```

   Expected: one line `pass` (or `fail`, which is a model result, not a setup problem) and the
   artifact path. `error` with `Remote end closed connection` means the model call failed; the reason
   is at the end of `/tmp/do-agent.log`. Check:

   ```sh
   python3 -c "import json,glob; d=json.load(open(glob.glob('/tmp/bb-do/*/cancel-single-order.json')[0])); print(d['run']['adapter']['self_reported_agent']['version'], d['evaluation']['verdict'], [c['tool'] for c in d['run']['tool_calls']])"
   rg -l --fixed-strings "$MODEL_ACCESS_KEY" /tmp/bb-do /tmp/do-agent.log || echo "key not in outputs"
   ```

   The version must end in `+gemma-4-31B-it+openai-json`, and the `rg` must print `key not in outputs`
   (run it in terminal A, where the variable is set).

3. Optional, to measure whether native tools work: restart terminal A with `--tool-mode native`,
   rerun step 2, and compare the tool calls.
4. `python examples/ollama_agent.py --backend openai --base-url http://inference.do-ai.run/v1 --model m`
   must exit at once (code 1) with the `--base-url must be https://` message (checked offline).

Sentry (free tier is enough):

1. Create a Python project in Sentry and copy its DSN (Project Settings > Client Keys (DSN)).
2. Terminal A: `export SENTRY_DSN='<dsn>'`, then start the agent as in DigitalOcean step 1, but with
   `uv run --extra sentry python examples/ollama_agent.py ...`. A local Ollama model works too.
3. Terminal B: run `cancel-single-order` as in DigitalOcean step 2.
4. In Sentry > Explore > Traces, search `span.op:gen_ai.invoke_agent` and open the newest trace.
   Expected: transaction `POST /turn` with tags `model`, `agent.version`, `backend`, `tool_mode`;
   under it `invoke_agent bolibench-example-ollama-agent`, with children `chat gemma-4-31B-it`
   (with `gen_ai.usage.input_tokens`/`output_tokens` and `gen_ai.response.model`) and
   `execute_tool cancel_order`. Then open Sentry's AI Agents dashboard and its Conversations view
   (under Insights), and find the case's conversation id (`gen_ai.conversation.id` on any span).
5. Privacy: search the trace for `ORD-201` and `Please cancel`. Both must be absent. Restart the agent
   with `--sentry-capture-content`, rerun, and check that `gen_ai.input.messages` and
   `gen_ai.tool.call.arguments` now appear.
6. Errors: restart the agent with a wrong key (`MODEL_ACCESS_KEY=wrong`) and rerun. Expected: BoliBench
   prints `error`, and Sentry > Issues shows a new `HTTPError: HTTP Error 401` issue. Open its event
   and check that the stack frames show no local variables and the key is nowhere.
7. With `SENTRY_DSN` set and `sentry-sdk` not installed (`python3 examples/ollama_agent.py`), the agent
   must exit with "SENTRY_DSN is set but sentry-sdk is not installed".

Evidence to keep for the write-up: screenshots of the trace waterfall from step 4 (the span tree with
token counts visible), the AI Agents dashboard, the conversation, and the error issue from step 6.
Add the terminal output of DigitalOcean step 2. Don't screenshot the DSN or the key pages.

## Rotation

- DigitalOcean model access key: Model Access Keys page, `…`, **Regenerate** (the old secret stops
  working at once), or delete it and create a new one. Update the environment variable and restart
  the agent; the key is read only at startup.
- Sentry DSN: Project Settings, Client Keys (DSN): create a new key, switch `SENTRY_DSN`, restart the
  agent, then disable or revoke the old key.

## Limitations

- No live Sentry ingestion has been exercised. The only hosted endpoint exercised is the Gemini API
  (above); DigitalOcean has not been called.
- JSON tool mode depends on the model following a text format. A reply that is almost a tool call
  is treated as text by design; how often that happens is a property of the model and prompt, and
  shows in the artifacts as a JSON-looking `agent_reply` with no tool call.
- `gen_ai.provider.name` for `--backend openai` is the base URL's host (e.g. `inference.do-ai.run`),
  not a canonical provider id. Sentry derives cost from the model name and token counts, so cost
  depends on whether Sentry knows the model's price, not on this field.
- No streaming; model calls are retried only after a 429 or 5xx (3 attempts in all, fixed 2 s/5 s
  waits, `Retry-After` ignored); one conversation history per process (never evicted).
- Model-call errors (HTTP errors after the bounded retry, timeouts, malformed responses) end the turn with an HTTP connection
  close, which BoliBench records as an `error` verdict with no detail. The detail is in the agent's
  stderr and, with Sentry on, in the error event.
- The base URL is not part of the agent identity or `config_id`.
