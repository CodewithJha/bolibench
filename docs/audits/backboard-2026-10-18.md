# Audit: Backboard bridge against the real API, 2026-10-18

> First run of `examples/backboard_agent.py` against the real Backboard API (`https://app.backboard.io/api`),
> 2026-10-18 07:01–07:14 UTC. Single, unseeded runs on 4 of 12 cases: verdicts describe this run only, no
> statistical claims. Two bridge bugs found live, fixed and covered by offline tests built from the observed
> responses. BoliBench's evaluator and suite were not changed by this work.

## Summary

| Layer | Result | Evidence |
|---|---|---|
| Auth (`X-API-Key`) | PASS | `GET /billing/balance` 200; `GET /assistants` 200 |
| Model listing | PASS | `GET /models?model_type=llm&supports_tools=true`: 13,438 tool-capable LLMs (12 providers); 305 on `openrouter` |
| Assistant + thread | PASS | `POST /assistants` created `bolibench-smoke` and `bolibench-agent`; threads auto-created under them by `POST /threads/messages` with `assistant_id` |
| Tool-call round trip | PASS (after fix) | `REQUIRES_ACTION` → tool output → `COMPLETED`; multi-round only works through the run endpoint with `tools` resent (bug 2) |
| Feature run, chosen open-weight model (`openrouter` / `qwen/qwen3-235b-a22b-2507`) | BLOCKED (billing) | 1 case, `error`: the account has free credit only, which Backboard reserves for Memory & RAG |
| Feature run, zero-priced model (`openrouter` / `dots-studio/dots-3-note-preview:free`) | PARTIAL: 3 pass, 1 fail of 4 | after fixes; before fix 2: 0 of 4 |
| Memory isolation | PASS | with `memory: "off"` nothing is stored or retrieved and a fact from thread A is unknown in thread B; positive control shows memory is assistant-wide when on |

Credits: balance $4.6761 → $4.6605 (free credit; no paid credit on the account). The $0.0156 spent was 4
`Memory` events from the memory positive control. The 46 LLM calls on `:free` models were billed $0
(`GET /billing/usage/recent?start=2026-10-18`).

## Account and safety constraints

- Key: `BACKBOARD_API_KEY` from the local git-ignored `.env` (mode 600), loaded inside each shell command;
  never printed. `rg --fixed-strings "$BACKBOARD_API_KEY"` over `runs/backboard-*`, `examples`, `tests`,
  `docs` and the scratch outputs: no match.
- The account already held 9 assistants of other apps (6 "Nivara business memory", 3 "ShadeLoop request
  memory"). None was modified, deleted or messaged. The only request touching one was a read-only
  `GET /assistants/{id}` by the bridge's new startup guard, which refused to start (below).
- Resources created: assistants `bolibench-smoke` (`0ae0bcca-…`, 14 threads, 1 test memory) and
  `bolibench-agent` (`dfab6025-f0db-427f-a8cf-38688886bf97`, 17 threads, 0 memories). After the checks the
  test memory and then `bolibench-smoke` were deleted (`DELETE /assistants/{id}` removes its threads and
  documents; `GET` then answers 404). `bolibench-agent` is **kept as evidence**: it holds the threads of
  every feature run and of the A/B check. Delete it with `DELETE /api/assistants/dfab6025-f0db-427f-a8cf-38688886bf97`.

## Docs vs. observed

Docs read 2026-10-18: <https://docs.backboard.io/llms.txt> and the linked pages (Send Message, Tool Calling,
Submit Tool Outputs and its legacy run endpoint, Memory, Billing, Models, Assistants, Threads).

| Topic | Docs | Observed |
|---|---|---|
| Thread without `assistant_id` | "Omit to use the user's first assistant (auto-created if needed)" | not exercised: on this account that would be another app's assistant (bug 1) |
| `tool_calls[].function.arguments` | JSON string | JSON string (`"{}"`, `"{\"order_id\": \"ORD-201\"}"`) |
| Non-streaming reply | `status` always present | present on every reply (COMPLETED, REQUIRES_ACTION, FAILED) |
| Failures | `FAILED` status | HTTP **200** with `status: "FAILED"`, the reason in `content`, no `error` field, token counts `null`. Seen for billing and for upstream errors (`LLM Error: … 404 No endpoints found`, `… 400 Provider returned error`) |
| `POST /threads/tool-outputs` | `{thread_id, tool_outputs}`, `additionalProperties: false`; "for per-run tool overrides, use the original endpoint" | works, but the continuation runs **without the message's `tools`** (bug 2) |
| `POST /threads/{thread_id}/runs/{run_id}/submit-tool-outputs` | `{tool_outputs, tools?, thinking?}` | with `tools` resent, later rounds come back as structured `tool_calls` |
| `tool_calls` across rounds | not documented | every reply of a run lists **all** calls of the run so far, answered ones included; `COMPLETED` replies still carry them. Submitting outputs for all listed ids, or only for the new ones, was accepted |
| Reply `content` | text | may start with blank lines (`"\n\nYou have 3 orders."`) |
| Memory | per assistant, cross-thread, `memory` default `"off"` | confirmed (below) |
| Billing | "New accounts include $5 in free credits" | free credit cannot pay for LLM chat on any provider (`openrouter`, `cerebras` tried); zero-priced `:free` models pass |

## Bugs found and fixed (`examples/backboard_agent.py`)

1. **Threads would land on another app's assistant.** The bridge sent no `assistant_id`, so every case
   would have opened a thread on the account's first assistant (here a ShadeLoop or Nivara assistant), with
   its documents available to the model. Fix: required `--assistant-id`; turn 0 sends it; at startup the
   bridge `GET`s the assistant and exits unless its name starts with `bolibench-`. Checked live: pointed at
   the first assistant it printed `assistant <id> is named 'ShadeLoop request memory': use a dedicated
   assistant named bolibench-*` and exited 1. Tests: `test_ask_user_ends_the_turn_and_later_calls_are_not_sent`
   (asserts `assistant_id`), `test_later_turns_continue_the_thread` (not resent on later turns),
   `test_a_bolibench_assistant_is_accepted`, `test_another_apps_assistant_is_refused`.
2. **Every tool call after the first in a turn was lost.** `/threads/tool-outputs` cannot carry `tools`, and
   the continuation ran without them: the model then wrote its next call as plain text
   (`<dots_function_call><invoke name="cancel_order">…`) which became the reply, and the case failed with no
   `cancel_order` call. A/B on the same prompt (`runs/backboard-api-checks-2026-10-18/ab.txt`): simplified
   endpoint 2 of 2 text, run endpoint with `tools` 2 of 2 structured. Fix: submit to
   `/threads/{thread_id}/runs/{run_id}/submit-tool-outputs` with `{tool_outputs, tools}`.
   Because a run's `tool_calls` repeat earlier calls, the bridge now keeps the outputs of the turn by
   `tool_call_id`: a repeated id is resubmitted with its stored output and never sent to the tool gateway
   again (otherwise BoliBench would record duplicate tool calls). Test:
   `test_observed_shapes_run_each_call_once_and_strip_the_reply` (stub replies copied from the real ones).
3. Minor: the reply is stripped of the leading blank lines. Same test.

The billing `FAILED` (HTTP 200, reason in `content`) already failed the turn correctly; it is now a test case
in `test_a_failed_run_fails_the_turn`.

## Model choice

`GET /models` lists only `anthropic, aws-bedrock, cerebras, cohere, elevenlabs, featherless, google, openai,
openrouter, speechmatics, typesafe, xai`; open weights come through `openrouter` (and `cerebras`, 4 models,
`featherless`). Chosen: **`openrouter` / `qwen/qwen3-235b-a22b-2507`** (Apache-2.0 Qwen3 instruct, tools,
no thinking mode, 262,144 context, catalog rate $0.0875 / $0.35 per 1M input/output tokens). Every chat
request to it, and to `cerebras` / `openai/gpt-oss-120b`, came back `FAILED`: "Your free credit is reserved
for Memory & RAG, so it can't cover LLM chat. Add credits or start a subscription on the Billing page to
continue". Adding credit was not authorised, so this layer is BLOCKED.

Fallback used for the remaining layers: the zero-priced tool-capable models in the catalog.
`inclusionai/ling-3.0-flash-sante:free` had no live endpoint (404). **`dots-studio/dots-3-note-preview:free`**
worked (OpenRouter upstream observed in errors: AtlasCloud; 512,000 context). It is a free *preview*; its
open-weight status was not verified. `cohere/north-mini-code:free` was used for one memory step only.

## Feature runs

Command (bridge in one shell, BoliBench in another; `--timeout 180`):

```sh
python3 -u examples/backboard_agent.py --assistant-id dfab6025-f0db-427f-a8cf-38688886bf97 \
  --provider openrouter --model <model> --port <port> > runs/<dir>-logs/agent.log 2>&1
uv run bolibench run suites/orders/<case>.json --agent-url http://127.0.0.1:<port>/turn --timeout 180 --output runs/<dir>/
```

| Run directory (`runs/…`) | Agent version | Case | Verdict | Tool calls |
|---|---|---|---|---|
| `backboard-qwen3-235b-a22b-2507-2026-10-18/20261018T070514Z-9e501769` | before fix 2 | cancel-single-order | error | none: billing `FAILED` (in `-logs/agent.log`) |
| `backboard-dots-3-note-preview-free-prefix-2026-10-18/` (4 dirs) | `492c05bc04d2` (before fix 2) | the 4 below | 4 fail | the first call of each turn only; the next one arrived as text |
| `backboard-dots-3-note-preview-free-2026-10-18/20261018T070955Z-cac4a73e` | `72b6de06f9c2` | cancel-single-order | **pass** | `get_order(ORD-201)`, `cancel_order(ORD-201)` |
| `…/20261018T071007Z-abc8aa95` | `72b6de06f9c2` | ambiguous-previous-order | **fail** | `list_orders`, `cancel_order(ORD-101)` in turn 0 with no `ask_user(confirm)`; `ask_policy` failed (the model's choice, not the bridge) |
| `…/20261018T071026Z-fe5fddc5` | `72b6de06f9c2` | tool-failure-cancel | **pass** | `cancel_order(ORD-111)` injected failure, retried once, ok |
| `…/20261018T071051Z-ddc0ad80` | `72b6de06f9c2` | codeswitch-cancel-kurta | **pass** | `list_orders`, `cancel_order(ORD-301)` |

Agent version = sha256[:12] of `backboard_agent.py` + `ollama_agent.py` as imported at bridge start.
`ollama_agent.py` (owned by another worker) changed at 12:40:00 local, after the fixed bridge started at
about 12:39:45: the runs used the earlier bytes. The change only adds a `post_model` helper; `SYSTEM`,
`CONTEXT`, `schema`, `post`, `OPENER` and `LOCAL_HOSTS`, which the bridge imports, are unchanged. The case
files were last modified at 12:32 local, before every run (sha256[:16]: cancel-single-order
`66e401b053cabe60`, ambiguous-previous-order `72d0cf3bcc5d84b7`, tool-failure-cancel `b89cac4e9da0cb07`,
codeswitch-cancel-kurta `587efc65a7fd285e`; uncommitted on top of `ace4e9f`, owned by the benchmark worker).
`evaluate.py` sha256[:16] `d55953fbe16dfd39`, also another worker's uncommitted change. Bridge file as left
by this work: `ecd6f9cd0a0e0adb`.

## Memory isolation

Backboard memory belongs to an **assistant** and is shared by all its threads. `memory` (Lite) or
`memory_pro` is chosen per message; the default is `"off"`. The bridge sends `memory: "off"` on every message
and opens a new thread per case (turn 0 omits `thread_id`; BoliBench gives each case a random conversation
id), so cases share neither history nor memory. Check on our own assistants (script and output in
`runs/backboard-api-checks-2026-10-18/bb_mem.py`, `mem*.txt`):

| Step | Assistant / thread | Memory | Result |
|---|---|---|---|
| A: "For my deliveries, the code word is PAPAYA-4417." | smoke, new thread | off | COMPLETED; no memory stored (count stays as before) |
| B: "What is my … code word? … or UNKNOWN" | smoke, another new thread | off | `UNKNOWN` |
| C: "… my secret delivery code word is GUAVA-8823." | smoke, new thread | Auto | memory op COMPLETED; 1 memory: "User's secret delivery code word is GUAVA-8823" (the chat reply itself failed upstream, 400) |
| D: same question | smoke, new thread | Readonly | `GUAVA-8823`, with the memory in `retrieved_memories` (positive control: memory crosses threads when on) |
| E: same question | smoke, new thread | off | `UNKNOWN`: `off` does not retrieve existing memories either |
| F: same question | bolibench-agent, new thread | Readonly | `UNKNOWN`, nothing retrieved: memory does not cross assistants |

`bolibench-agent` had 0 memories before and after all feature runs. Caveat: with `dots-3-note-preview:free`,
upstream AtlasCloud answered `400 bad request` whenever a retrieved memory was injected (D, 3 tries) and to
one phrasing of A ("Please remember this: my secret …"); D was then answered with
`cohere/north-mini-code:free`, A with a neutral phrasing. These are provider errors, not memory results.

## Limitations

- The chosen open-weight paid model was never run: the free credit does not cover chat. All verdicts are from
  a free preview model of unverified licence, on 4 cases, once each.
- Free `:free` endpoints are flaky (404 no endpoint, 400 from the upstream); a BoliBench run on them can
  record `error` for provider reasons.
- Only `stream: false` was exercised. `memory_pro`, documents, web search and thinking were not.
- `bolibench run` exits 1 when any case is not `pass`; the bridge is an example, not part of the package.
