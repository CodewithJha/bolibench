# BoliBench

BoliBench is an open-source benchmark for evaluating conversational AI agents through task
correctness, tool-call behavior, and state-transition verification.

A transcript that looks right is not evidence the task succeeded. BoliBench runs agents against a
sandbox and judges the sandbox's final state and the tool calls it recorded, not the agent's reply.
The current suite uses Hindi-English code-switching, Awadhi-influenced Hindi, ambiguous references
and mid-utterance corrections in an order-management task.

What it is and is not:

- Transcript-level by default. Cases are text. An optional speech round-trip (`run --speech elevenlabs`)
  gives the agent the speech-to-text transcript of synthetic text-to-speech audio, not real speakers.
- Tool execution is observed by the sandbox, not taken from the agent's own account.
- The scripted fake adapter is a test harness, not an AI agent; its results say nothing about any AI system.
- Nothing in BoliBench understands Hindi or Awadhi. Case correctness rests on their human authors.
- Linguistic validation is pending: no case has been reviewed by a native speaker.

## Status

Data models, an in-memory order sandbox, deterministic checks with failure classification, a JSON
case loader, `bolibench validate`, `bolibench review-sheet`, `bolibench run` with per-case JSON
artifacts and a `summary.json`, a scripted fake adapter, and a localhost webhook adapter for external
agents. No reports or scores beyond verdict counts. Optional integrations (speech round-trip, demo
server, database export, durable runs) are listed under "Optional integrations".

## Setup

```sh
uv sync
uv run pytest
uv run bolibench validate suites/orders
uv run bolibench review-sheet suites/orders
```

## Architecture

- `models.py`: pydantic models for cases, tool calls, run records, evaluations and artifacts.
- `store.py`: loads a case file or a suite directory (`<id>.json`, id must equal the file stem).
- `sandbox.py`: `OrderSandbox`, an in-memory order store. Every tool call attempt is recorded with
  `status` `ok`, `rejected` or `injected_failure`; only `ok` calls change state.
- `adapters.py`: the `AgentAdapter` contract, `AdapterError`, and `FakeAgentAdapter`.
- `webhook.py`: `WebhookAgentAdapter` and its local tool gateway.
- `runner.py`: `run_case(case, adapter) -> RunRecord`, plus artifact writing.
- `evaluate.py`: `evaluate(case, run) -> Evaluation`, deterministic checks and classification.
- `cli.py`: `validate`, `review-sheet`, `run`, `export`, `serve`.
- Optional, see "Optional integrations": `speech.py` (TTS -> STT wrapper), `server.py` (public demo),
  `export.py`/`export_mongo.py`/`export_tiger.py` (database export), `temporal_run.py` (durable runs).

## Cases

A suite is a directory of `<id>.json` files (`suites/orders/`). Each case scripts the user turns,
optional agent-visible `context`, the initial sandbox state, and what must (and must not) happen.
Final-state expectations are dotted paths where list items are addressed by `id`, e.g.
`orders.ORD-101.status`.

A required action may set `max_attempts`: matching attempts are counted whatever their status
(failed and rejected ones included), and every attempt past the limit is treated exactly like a
forbidden attempt. It never makes a failed attempt count as success. Not allowed on forbidden
actions. The two injected-failure cases, `recovery-after-failed-cancel` and `tool-failure-cancel`,
use `max_attempts: 2` on their cancel (the injected failure plus one retry), so re-cancelling after
a successful retry fails the case. Elsewhere repeats are unconstrained; see
`docs/audits/qwen3-8b-initial-run.md` for the per-case reasoning.

`expected.exclusive_actions: true` (default `false`) means every `cancel_order` or `update_quantity`
attempt, of any status, that matches no required action is treated exactly like a forbidden attempt.
That includes made-up order ids, which no explicit forbidden spec can list. Retries of a required
action still match it (bounded only by `max_attempts`). `list_orders`, `get_order` and `ask_user`
are never restricted. All 12 `orders` cases set it, because each request names exactly the changes
it wants (or none). It also catches malformed attempts at the right action (e.g. `{"id": ...}`
instead of `order_id`, or a quantity sent as a string), since those match no required action either.
Those still fail `forbidden_actions` but are classified `tool_execution`, not `policy_violation`:
"malformed" means the sandbox rejected the call with `bad arguments for <tool>` and the tool is one
a required action uses. Well-formed stray attempts (valid arguments, wrong order or wrong tool) stay
`policy_violation` (or `entity_resolution`/`intent_interpretation` when a required action is unmet).

### Review status

Three separate things, never inferred from each other:

1. Schema validity: the case loads (`bolibench validate`). Not stored; checked every load.
2. `review.behavior`: internal review of the expected behavior (`unreviewed`, `reviewed`, `needs_changes`).
3. `review.linguistic`: native-speaker review of the utterances (`unreviewed`, `native_reviewed`, `needs_changes`).

`review` is optional (absent = both `unreviewed`) and may also hold `language_claim`, `notes` and
`reviewer`. `status: trusted` is only accepted with `behavior: reviewed` and `linguistic:
native_reviewed`; everything else stays `proposed`. Today every case is `proposed` and unreviewed.

`uv run bolibench review-sheet suites/orders > review.md` prints a Markdown sheet for a Hindi/Awadhi
speaker: per case the exact utterances, claimed language (or the tags, when no claim is set), the
context shown to the agent, any simulated tool failure, the expected behavior in plain words,
whether clarification is expected, current status, and blanks for naturalness, interpretation,
problems and verdict. It is a blank sheet, not a completed validation. It is generated from the JSON
each time so it cannot drift from the cases. Copy reviewers' answers back into each case's `review` by hand.

### Agent-visible context vs evaluator-only fields

An adapter sees exactly three things per turn: the turn index, the user utterance, and the case's
`context`, plus whatever the agent fetches through sandbox tools.

- `context` (optional, frozen): `today` (ISO date) and `policy` (text). Unset fields are `null`;
  BoliBench never invents a date. The same object is passed on every turn of a case.
- `initial_state` is sandbox state, reachable only through tools. Context never falls back to it.
- Evaluator-only, never sent to an adapter: `id`, `tags`, `expected` (final state, required and
  forbidden actions, `ask_before`), `inject_failures`, `checks`, `provenance`, `review`.

`awadhi-cancel-yesterday` (`today`) and `forbidden-bulk-cancel` (`policy`) used to keep these values
inside `initial_state`, where no tool exposed them; they were moved, not copied, to `context`.

## Validate

```sh
uv run bolibench validate suites/orders   # exit 0 ok, 1 invalid suite
```

## Run

```sh
# one case, one script file
uv run bolibench run suites/orders/ambiguous-previous-order.json \
  --scripts examples/scripts/ambiguous-previous-order.json --output runs/
# a suite: --scripts DIR must hold <case_id>.json for every case
uv run bolibench run suites/orders --scripts my-scripts/ --output runs/
# an external agent over the webhook adapter
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --output runs/
```

`--scripts` drives `FakeAgentAdapter`. A script is a JSON list with one list of steps per case turn;
a step is `{"tool": ..., "args": {...}}` (tool call), `{"text": ...}` (reply) or `{"reason": ...}`
(adapter failure). See `examples/scripts/`. Every script is loaded and checked (including turn
count) before anything runs; a missing or invalid script aborts the run with exit 2. A case is
never skipped or given a fabricated result.

One line per case is printed (`verdict case_id artifact_path`) and a final count. A failing or
erroring case does not stop the suite; an `AdapterError` becomes an `error` verdict; any other
exception is a bug and propagates.

### Artifacts

`<output>/<UTC timestamp>-<random>/<case_id>.json`, plus `summary.json` for the whole run. The run
directory must not exist and files are created exclusively, so nothing is ever overwritten. Each file is UTF-8 JSON (Devanagari not
escaped), produced by pydantic's `model_dump_json(indent=2)`:

```json
{
  "schema_version": 1,
  "case_id": "...",
  "run": {"run_id", "case_id", "adapter": {name, version, config, seed, self_reported_agent?},
          "started_at", "finished_at",
          "turns": [{user_input, asr_text, agent_reply, speech?}],
          "tool_calls": [{turn, tool, args, status, result, error}],
          "final_state", "exposes_tool_calls", "execution_error",
          "refused_requests": [{status, reason, tool, token_turn, token_age_s}]},
  "evaluation": {"verdict", "checks": [{metric, verdict, evidence, detail}],
                 "classifications": [{category, stage, evidence, method, confidence}]}
}
```

`summary.json` is computed from the artifacts just written: `total`, `counts` per verdict (`pass`,
`fail`, `error`, `inconclusive`), `cases` (id to verdict), the distinct `adapters` infos, and
`config_id`, a sha256 prefix of those infos: adapter name and version, config (agent URL or script
path, timeout), seed, and the agent's self-reported identity when present. Counts only; no scores or
statistics. The case id `summary` is reserved.

`asr_text` is `null` unless the run used `--speech`; then it is the transcript the agent acted on, and
`speech` holds that turn's round-trip evidence (transcript, detected language, audio size and sha256,
TTS/STT durations). `speech` is omitted when absent, so text-only artifacts are unchanged.

`adapter.self_reported_agent` (`{name, version}`) is only present when a webhook agent reported an
identity (see "Turn response"). It is the agent's own claim, not verified, and never used by the
evaluator. The key is omitted when absent, so artifacts and `config_id` of runs without it are
unchanged; `schema_version` stays 1 (an older BoliBench rejects the extra key rather than misreading
it). So two runs of different agent code behind the same URL share a `config_id` unless the agent
reports its version.

### Exit codes

- `0`: every case passed.
- `1`: at least one case was `fail`, `error` or `inconclusive`.
- `2`: input error (bad case file, missing or invalid script, bad `--agent-url`, existing output
  directory); nothing was run.

## Adapters

`bolibench.adapters.AgentAdapter` is the contract an agent integration implements: one
`respond(turn, utterance, context, sandbox) -> reply` per user turn, calling tools through
`sandbox.call(tool, turn, **args)`. An adapter declares `info` (name, version, config, seed) and
`exposes_tool_calls`: `False` means some tool use may bypass the sandbox, so the call log is not
recorded and tool-dependent checks are `inconclusive`. An adapter reports failure only by raising
`AdapterError`, which yields an `error` verdict (distinct from `fail`); any other exception is a bug
and propagates.

`run_case(case, adapter)` builds a fresh sandbox (with the case's injected failures), drives the
turns, and returns a `RunRecord`. `evaluate(case, run)` judges it.

### Fake adapter

`FakeAgentAdapter` is a deterministic scripted test harness, not an AI agent. It never reads the
user's words or the context; it replays fixed steps per turn against the real sandbox, which still
validates and executes every call.

### Webhook adapter

`WebhookAgentAdapter(agent_url, timeout)` (library, and `run --agent-url ... --timeout S`) lets an agent running as
a separate local process take part. It is a context manager; it starts a tool gateway on
`127.0.0.1` on a random port.

Turn request: for each turn, BoliBench POSTs JSON to `agent_url`:

```json
{"conversation": "<random per case>", "turn": 0, "utterance": "...",
 "context": {"today": "2026-10-17", "policy": null},
 "tools_url": "http://127.0.0.1:<port>/runs/<token>/tools",
 "tools": {"list_orders": [], "get_order": ["order_id"], "cancel_order": ["order_id"],
           "update_quantity": ["order_id", "quantity"], "ask_user": ["kind", "question"]}}
```

`turn` 0 starts a new conversation. Case id, tags and expectations are never sent.

Tool calls: during the turn the agent POSTs `{"tool": "...", "args": {...}}` to `tools_url` and gets
`{"ok": bool, "result": ..., "error": ...}`. Rejected calls and injected failures look the same to
the agent. Calls are serialized under a lock and recorded in arrival order. The token is random and
new for every turn; it only scopes calls to the active turn.

Turn response: the agent answers the turn POST with `{"reply": "..."}` and optionally
`"agent": {"name": "...", "version": "..."}` (printable ASCII; name at most 64 and version at most
128 characters; no other keys). The reply is stored as the transcript and never used as evidence; any
claims in it about tools are ignored. The identity reported on turn 0 is recorded as the case's
`adapter.self_reported_agent` and enters `config_id`. A malformed identity is a bad reply, and an
identity that differs on a later turn of the same case (including appearing or disappearing) is an
`AdapterError`; both make the case `error`, since the case could not be attributed to one agent.
Different cases of one run may report different identities; `summary.json` lists each.

Lifecycle and attribution:

- A tool call is executed only if its token is the active turn's. The check and the execution
  happen under one lock, so every accepted call belongs to exactly one case and turn, and
  concurrent calls are serialized and recorded in arrival order.
- The token is revoked under that lock before the turn returns, fails, or hits its deadline. Each
  case gets a fresh sandbox, and the sandbox is closed when the case ends; a closed sandbox refuses
  any further call.
- Turn deadline: `timeout` (CLI `--timeout`, default 30 s) bounds the whole turn: the turn request,
  every tool call, and the reply. At the deadline the token is revoked first, then the case ends as
  `error` with `execution_error` `AdapterError: turn deadline exceeded: no reply within <S>s`. The
  abandoned request is left to finish on a background thread and its reply is discarded. There are
  no retries, since a retried turn could repeat tool calls. The suite continues with the next case.

Refused requests are never tool-call attempts: they never reach the sandbox and the evaluator never
sees them. They are kept as `RefusedRequest` diagnostics (HTTP status, reason, tool name, which turn
the token was issued for, token age; never the arguments):

- On the run record (`refused_requests`) when the token belongs to a case that is still running. This
  covers malformed requests in the turn (400/411/413) and stale tokens from an earlier turn of the
  same case, including calls between turns (409). Any such entry makes the case `error`.
- In `adapter.stray_calls` (and a warning on stderr from `bolibench run`) when no running case owns
  the token: unknown tokens, calls after the case ended or after its deadline, and calls from an
  earlier case arriving during a later one (409). These do not touch the later case.

Validation and failure handling:

- A well-formed request with the active token is always recorded. The sandbox rejects unknown tool
  names and arguments that do not fit the tool (recorded as `rejected`); only the five registered
  tools can execute. Payloads are data: there is no eval, shell, filesystem or URL access.
- Malformed requests (bad JSON, wrong shape, extra fields, bodies over 64 KiB, no `Content-Length`)
  get HTTP 400/411/413 and are refused as above.
- Connection failure, non-2xx status, redirects (never followed), a bad or oversized reply:
  `AdapterError`, so the case verdict is `error`. Calls already made in a failed turn stay in the
  sandbox log.
- An unexpected exception inside the gateway is re-raised from `respond()` on the runner thread.

`exposes_tool_calls` is `True` because the sandbox lives in the BoliBench process and the gateway is
the only way to reach it.

Security limitations: the agent URL must be plain `http` on `127.0.0.1`, `localhost` or `[::1]`
without credentials, and the gateway binds only `127.0.0.1`. That is a development safeguard, not a
security boundary: any local process can reach the gateway, and there is no authentication or TLS.
Only run agents you trust.

### Example local agent (Ollama)

`examples/ollama_agent.py` is a stdlib-only example agent that answers each turn with a local
Ollama model using Ollama's tool calling, and executes tools only through `tools_url`. It is not
part of the package; only its offline turn-ending logic is tested. Since the baseline it is v2:
`ask_user` ends the turn (later tool calls in that model message are dropped), the prompt says to
look orders up instead of guessing ids and to retry a temporary failure once, and `context` is
stated in full sentences. The baseline's v1 is the file at commit `1a91e20` (sha256 `4b68d382…`);
a single v2 run is audited in `docs/audits/qwen3-8b-agent-v2-2026-10-17.md`. The agent now reports
`{"name": "bolibench-example-ollama-agent", "version": "<sha256[:12] of its file>+<model>"}`.

```sh
ollama serve                                         # model already pulled, e.g. qwen3:8b
python examples/ollama_agent.py --model qwen3:8b --port 8000
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
```

One run of this setup (qwen3:8b, `think` off, 2026-10-17) gave 3 pass, 9 fail, 0 error. It is a
single run of a basic example prompt, not a measurement of the model. Its artifacts were not kept,
and it was judged before `exclusive_actions` and the `recovery_failure` fix existed; see
`docs/audits/qwen3-8b-initial-run.md` for what can and cannot be concluded from it. A new, separate
single run with full artifacts and a per-case audit is in `docs/audits/qwen3-8b-baseline-2026-10-17.md`.

## Attempted vs successful actions

- `required_actions` are satisfied only by a successful matching call.
- `forbidden_actions` fail on any matching attempt, including ones the sandbox rejected or that hit
  an injected failure.
- `final_state` is judged on its own; rejected and failed calls never change state.
- `max_attempts` on a required action counts attempts of any status; attempts past it fail
  `forbidden_actions` like any forbidden attempt. So does, with `exclusive_actions`, any
  consequential attempt that matches no required action, and any attempt of a tool name the sandbox
  does not register (e.g. `cancel_all_orders`; classified `tool_selection`, certain).
- `recovery_failure` is only given for an injected failure that no later successful call with the
  same tool and arguments followed. A recovered failure is never blamed for an unrelated failure.
- `ask_before` needs the matching `ask_user` in an earlier turn than the first attempt of the tool
  (failed attempts count); asking in the same turn does not count.
- Missing tool-call evidence or final state is `inconclusive`, never `pass`.
- One tool call gets one classification: a forbidden attempt that was rejected or hit an injected
  failure is classified as the forbidden action, not also as `tool_execution`/`recovery_failure`.

## Optional integrations

None is needed for the benchmark itself; the core install depends on pydantic only. Each is explicit
(nothing runs unless you invoke it) and documented, with its status, in its own file. Index and the
full environment-variable inventory: `docs/integrations.md`; placeholders in `.env.example`.

```sh
uv sync --extra sentry      # or mongo, tiger, temporal, all
# speech round-trip: synthetic audio via ElevenLabs TTS -> STT; the agent hears the transcript
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn \
  --speech elevenlabs --speech-audio-dir audio-cache
uv run bolibench export --to mongo --dry-run runs/<run dir>   # or --to tiger; `--to mongo --help`
uv run bolibench serve                                       # public demo on http://127.0.0.1:8080
```

Status as of 2026-10-18. "Live" means a real call to the service or a real run of the model; every
claim is backed by `docs/live-verification-report.md` or the linked audit.

- ElevenLabs speech round-trip (`run --speech elevenlabs`, stdlib only): **live-verified** on the free
  tier (TTS, STT, the opt-in live test, the CLI with the audio cache, and 3 cases end to end with a
  local `qwen3:8b` agent acting on the transcripts). Synthetic voice, one run per case.
  `docs/integrations/elevenlabs.md`
- Example agent on OpenAI-compatible endpoints: **live-verified (hosted)** with Gemma 4
  (`gemma-4-31b-it`) on Google's Gemini API, native tool calls, `--reasoning-effort minimal`: one
  full-suite run, 8 pass / 3 fail / 1 error (the error is a turn deadline missed through provider
  latency). `docs/audits/gemma4-gemini-api-2026-10-18.md`. DigitalOcean inference: not called (no
  key). Local `gemma3:4b` run: `docs/audits/gemma-gemma3-4b-2026-10-17.md`.
  `docs/integrations/gemma-sentry.md`
- Sentry tracing (extra `sentry`): offline only (real SDK, in-memory transport); no DSN yet.
  `docs/integrations/gemma-sentry.md`
- Backboard bridge (`examples/backboard_agent.py`, `--assistant-id` required): **partial**. The real API
  works end to end (tool-call round trip, memory isolation); the chosen open-weight model is blocked
  because the account's free credit does not pay for chat, and a free preview model passed 3 of 4
  cases. `docs/audits/backboard-2026-10-18.md`, `docs/integrations/backboard.md`
- Mastra framework agent (`examples/mastra-agent`, TypeScript): offline `npm test`, plus one real
  full-suite run with local `qwen3:8b` (6 pass, 6 fail). `docs/integrations/mastra.md`
- Temporal durable runs (`python -m bolibench.temporal_run`, extra `temporal`): local only (temporalio
  test server and the local dev server, including a worker crash and resume); not on Temporal Cloud.
  `docs/integrations/temporal.md`
- MongoDB export (`export --to mongo`, extra `mongo`): local only (MongoDB 7.0.45); Atlas not run.
  `docs/integrations/mongodb-atlas.md`
- Tiger Data export with similar-failure search (`export --to tiger`, extra `tiger`): local only
  (TimescaleDB + pgvector); Tiger Cloud not run. `docs/integrations/tiger-data.md`
- Public demo and token-gated live runs (`bolibench serve`, Docker, Render, DigitalOcean App
  Platform): read-only demo deployed on Render (https://bolibench-demo.onrender.com); live mode off
  there for now; DigitalOcean App Platform not deployed (no key). `docs/deployment.md`

## Benchmark audit

`docs/benchmark-audit.md` (2026-10-18) reviewed all 12 cases, the evaluator and the sandbox. Two
classifier defects were fixed (a correct call blamed as `tool_selection`, and a wrong-tool call given
two categories); every case now pins `status` and `quantity` of every order; and under
`exclusive_actions` a call to a tool name the sandbox does not register is now a forbidden attempt.
Re-evaluating every stored artifact with the current evaluator changes no verdict and no check; two
copies of one case's classifications lose a `tool_selection` label. Adversarial tests:
`tests/test_adversarial.py`. Test suite at that point: `uv run pytest -q` 387 passed, 4 skipped (the
opt-in live tests).

## Known limitations

- Transcript-level by default. The optional speech round-trip uses synthetic TTS audio (no real
  speakers, noise or phone codecs), and there is no speech-recognition failure classification yet.
- No built-in adapter for a hosted model or voice platform; the webhook adapter needs you to run the
  agent locally (it may call a hosted model API, as the example agents do). The fake adapter is a scripted harness and says nothing about any AI system.
- Only the two injected-failure cases set `max_attempts`, so elsewhere a repeated attempt of the
  required action itself (e.g. cancelling the right order twice) does not fail a case.
- Classification covers failed checks, not each unmet action: when an unrecovered injected failure
  explains `required_actions`, another unmet action in the same case gets no category of its own
  (the `required_actions` check still lists every unmet action).
- Rejected read-only calls (e.g. `get_order` on a made-up id) are classified `tool_execution` but
  fail no check, by design.
- Classification is a fixed rule set and can be wrong; confidence is `certain` only when a check
  directly proves the category. A retry with different arguments (even if equivalent) does not count
  as recovering from an injected failure.
- Refused requests that arrive after `bolibench run` has printed its warnings are not seen at all.
- Cases are hand-written synthetic data and have not had native-speaker review.

## License

Apache-2.0
