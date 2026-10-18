# Sponsor evidence matrix (state on 2026-10-18, about 13:30 IST)

What is true in the repo today, per category, checked against the integration docs, the tests and
the recorded runs. Detail and commands for every claim: `docs/live-verification-report.md`.
"Live (local)" means the sponsor's real software on this laptop; "live (hosted)" means the sponsor's
hosted service with a real account. Fakes, stubs, in-memory transports and test servers are offline.
Category text: https://dev.to/challenges/hacktoberfest-week2-2026-10-12 (anchors
`#best-use-of-<name>` on https://dev.to/challenges/hf26).

Status values (one per provider):

- **PASS**: the real model or service was exercised and worked (local or hosted, as stated).
- **PARTIAL**: the real service was exercised; part of what the category needs is blocked.
- **LOCAL ONLY**: the sponsor's open-source software on this laptop, not the hosted product the
  category names.
- **MOCK ONLY**: fakes, stubs or in-memory transports only.
- **BLOCKED**: no credential, so nothing beyond offline tests is possible.
- **FAIL**: tried and did not work. No provider is in this state.

Test suite: `uv run pytest -q` → 387 passed, 4 skipped, the same on three consecutive runs; 392
passed, 4 skipped at about 13:35 IST, after the live-mode work added server tests (the 4 are
opt-in live tests; three passed against local MongoDB, TimescaleDB and Ollama with
`BOLIBENCH_LIVE=1`, and the ElevenLabs one passed live). `uv run bolibench validate suites/orders` →
12 cases ok.

## Summary counts (computed from the rows below)

| | Count | Which |
|---|---|---|
| Categories | 17 | |
| Entered or conditional on evidence | 10 | Gemma, Mastra, Temporal, Render, DigitalOcean, Sentry, ElevenLabs, MongoDB Atlas, Tiger Data, Backboard |
| Conditional | 1 | .tech: entered only if registered and serving the live demo |
| Not entered | 6 | Entire, GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino |
| PASS | 4 | Gemma (local + hosted Gemini API), ElevenLabs (hosted), Mastra (local framework), Render (deployed, live mode on) |
| PARTIAL | 1 | Backboard (billing) |
| LOCAL ONLY | 3 | Temporal, MongoDB (Atlas pending), Tiger Data (Tiger Cloud pending) |
| MOCK ONLY | 1 | Sentry (pending a DSN) |
| BLOCKED | 1 | DigitalOcean (no key) |
| FAIL | 0 | |
| Live (hosted) | 4 | Render, ElevenLabs, Gemma 4 on the Gemini API, Backboard (partial) |
| Deployed | 1 | Render: https://bolibench-demo-1b3o.onrender.com (token-gated live mode on, Gemma 4 on the Gemini API) |

## Matrix

| Category | Status | Implemented | Offline-tested | Live (local) | Live (hosted) / deployed | Decision | Evidence still missing | User action |
|---|---|---|---|---|---|---|---|---|
| Gemma ($200) | **PASS** (local + hosted) | `examples/ollama_agent.py` (`--tool-mode json`, `--reasoning-effort`); EmbeddingGemma in the Tiger exporter | Yes | **Yes.** `gemma3:4b` full suite 2/10/0, audited (`docs/audits/gemma-gemma3-4b-2026-10-17.md`); 3-case rerun on 2026-10-18: same verdicts, tool calls and final states; `embeddinggemma` embedded 22 failures | **Yes, on Google's Gemini API** (not DigitalOcean): `gemma-4-31b-it`, native tools, reasoning `minimal`, one full-suite run 8 pass / 3 fail / 1 error (the error is provider latency past the 180 s turn deadline; 18 HTTP 500s recovered by bounded retry), audited (`docs/audits/gemma4-gemini-api-2026-10-18.md`) | Entered | none | none |
| Mastra ($100) | **PASS** (local framework) | `examples/mastra-agent` (`@mastra/core` 1.78.0) | `npm test` 5/5, `tsc` clean | **Yes.** Full suite 6/6/0 on `qwen3:8b`; 2-case rerun matched; malformed requests get 400/413/404/409 | n/a | Entered | none | none |
| Temporal ($100) | **LOCAL ONLY** | `python -m bolibench.temporal_run worker\|start` | Yes (temporalio test server) | **Yes.** Dev server (CLI 1.9.1 / Server 1.32.0): summary byte-identical to `bolibench run`; `kill -9` of the worker, interrupted activity re-ran as attempt 2, run completed; same workflow id again re-ran nothing. The crash test's agent was a slow stub | not on Temporal Cloud (no credential; not required) | Entered, framed as a durable **evaluation** run: the suite run survives worker crashes and resumes, the agent itself is not a workflow | UI screenshots | Rerun locally, screenshot http://localhost:8233 |
| Render ($200) | **PASS** (deployed, live mode on) | `render.yaml` Docker Blueprint; demo page + integrations panel; token-gated live mode running the agent in the container | Yes (`tests/test_server.py`) | Docker image runs locally as `nobody`, read-only FS, all endpoints OK | **Deployed** 2026-10-18 22:48 IST at https://bolibench-demo-1b3o.onrender.com (`srv-dbafue7btjjs73f13di0`, new Render workspace, free plan, Singapore, commit `3440507`): `/health` `"live": true`, every public check passed (live-run without or with a wrong token: 401), logs clean. Hosted live run `f809fcb36f15f10e` on `cancel-single-order`: **pass** in 35 s, agent `gemma-4-31b-it+openai-native`, one `cancel_order` call. The first service (`srv-dba5nh5g1s2s73asmb5g`, read-only) is suspended on the old workspace (billing) and no longer used | Entered; Render hosts the agent runtime | dashboard screenshot | screenshot the service page |
| DigitalOcean ($200) | **BLOCKED** (no key) | `--backend openai` for serverless inference; `.do/app.yaml` | Yes (stub) | The same OpenAI-compatible client ran against Ollama `/v1` (local) and Google's Gemini API (hosted); neither is DigitalOcean | Not called, not deployed. DO's model table lists no tool calling for `gemma-4-31B-it`, so the DO configs use JSON tool mode | Entered once called | model list + probe output, one case (ideally the suite) against DO, or the live demo using DO inference | DO account, model access key |
| Sentry Agent Tracing ($100) | **MOCK ONLY** (pending DSN) | `gen_ai.invoke_agent` / `chat` / `execute_tool` spans, conversation id, tokens; content opt-in; no local variables on error events; exceptions captured | Yes (real SDK, in-memory transport) | n/a (needs Sentry) | No DSN: Nivara's exists but is project-specific and deliberately not reused | Entered once traced | trace waterfall, AI Agents view, conversation, one error issue without locals, one finding | create a BoliBench Sentry project and DSN |
| ElevenLabs ($100) | **PASS** (hosted) | `bolibench run --speech elevenlabs [--speech-audio-dir]` | Yes (fakes, stub); audited against the API docs | n/a | **Yes**, 2026-10-18, free tier: live TTS and STT, live test passed, CLI with the audio cache (rerun reused the audio), 3 cases end to end with local `qwen3:8b` acting on the transcripts (speech 1/2/0, text-only 0/3/0). Synthetic voice, one run per case | Entered (the "once run" condition is met) | usage screenshot | none for the engineering evidence |
| MongoDB Atlas ($100) | **LOCAL ONLY** (Atlas pending user credentials) | `bolibench export --to mongo` | Yes | Local MongoDB 7.0.45: export, idempotent, indexes, report, live test | No Atlas cluster: Nivara's connection string is deliberately not reused | Entered once on Atlas (a local MongoDB is not Atlas) | Data Explorer screenshot, `--report` output from Atlas | create a dedicated M0 cluster or user, set `MONGODB_URI` |
| Tiger Data ($100) | **LOCAL ONLY** (Tiger Cloud pending) | `bolibench export --to tiger`, pgvector + full-text hybrid search over EmbeddingGemma embeddings | Yes | Local TimescaleDB 2.30.2 + pgvector 0.8.7: hypertable, idempotent, report, 22 failures embedded, `--similar` works (top hits are the same case in other runs) | No Tiger Cloud service: Nivara's database is deliberately not reused | Entered once on Tiger Cloud (local run is the rehearsal) | hypertable query, `--similar` output, console screenshot, all on Tiger Cloud | create a dedicated Tiger Cloud service, set `TIGER_DATABASE_URL` |
| Backboard ($100) | **PARTIAL** (billing) | `examples/backboard_agent.py` bridge (`--assistant-id` of a `bolibench-*` assistant required) | Yes, including stubs built from the real responses | n/a | **Yes**, 2026-10-18 (`docs/audits/backboard-2026-10-18.md`): auth, model list, assistant/thread, tool-call round trip (two bridge bugs found live and fixed) and memory isolation pass. Chosen open-weight `qwen/qwen3-235b-a22b-2507` blocked: the free credit does not pay for LLM chat. Zero-priced preview `dots-studio/dots-3-note-preview:free` (licence unverified): 3 pass / 1 fail of 4 cases | Entered once ≥2 models run (the category is "compare open-weight models through a single Backboard API key") | ≥2 full-suite `summary.json` counts of open-weight models via one key, usage screenshot | add paid credit (or a subscription), then two full-suite runs |
| .tech Domain ($100) | not started | No (deploy docs describe the CNAME) | n/a | n/a | Nothing registered | Conditional: only if claimed through Hacktoberfest and serving the live demo | the .tech URL over HTTPS | Claim, Render custom domain, CNAME |
| Entire ($100) | not entered | CLI enabled, checkpoints kept local (`push_sessions: false`) | n/a | n/a | No public session | Not entered | — | — |
| GitHub Copilot ($100) | not entered | No | — | — | — | Not entered (not used) | — | — |
| Tinker ($200) | not entered | No | — | — | — | Not entered | — | — |
| TabPFN ($200) | not entered | No | — | — | — | Not entered | — | — |
| SerpApi ($100) | not entered | No | — | — | — | Not entered | — | — |
| Arduino ($200) | not entered | No | — | — | — | Not entered | — | — |

## Notes

- Reproducibility: the Gemma and Mastra reruns matched the bundled runs on verdict, tool calls and
  final state, but not on reply wording. Say "the same actions", not "identical runs". Every hosted
  result above is one unseeded run.
- Hosted Gemma 4 ran on Google's Gemini API, not on DigitalOcean. It is Gemma evidence, not
  DigitalOcean evidence.
- Local MongoDB and local TimescaleDB are the sponsors' open-source databases, but the categories
  name Atlas and Tiger; only the hosted runs go in the post as category evidence.
- Temporal's crash test used a slow stub agent so the kill landed mid-case; it shows the evaluation
  harness's durability, which is how the post must describe it.
- The bundled demo runs keep the classifications they were judged with. Under the current evaluator
  every verdict and check is unchanged; one classification differs (the baseline
  `recovery-after-failed-cancel` no longer gets `tool_selection`). See `docs/live-verification-report.md` 3.8.
- Entire checkpoints stay local: `push_sessions: false` turns off checkpoint pushing in Entire's
  pre-push hook (`entire status`: "Automatic checkpoint pushing: disabled"), and no session data is public.
