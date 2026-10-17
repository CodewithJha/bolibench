# Sponsor evidence matrix (state on 2026-10-17, 22:45 IST)

What is true in the repo today, per category, checked against the integration docs, the tests and
`runs/`. "Live" means a real call to the sponsor's service or a real run of the sponsor's model; tests
against fakes, stubs or in-memory transports count as offline only. Category text:
https://dev.to/challenges/hacktoberfest-week2-2026-10-12 (anchors `#best-use-of-<name>` on
https://dev.to/challenges/hf26).

Test suite: `uv run pytest -q --co` collects 311 tests (reported: 300 passed, 11 skipped; with every
extra 307 passed, 4 skipped, the 4 being opt-in live tests: `test_live_elevenlabs_round_trip`,
`test_live_mongo`, `test_live_tiger`, `test_live_ollama_embeddings`).

## Summary counts (computed from the rows below)

| | Count | Which |
|---|---|---|
| Categories | 17 | |
| Targeted | 12 | Gemma, Sentry, DigitalOcean, Render, .tech, ElevenLabs, Mastra, Backboard, MongoDB Atlas, Tiger Data, Temporal, Entire |
| Not entered | 5 | GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino |
| Implemented (code or config in repo) | 10 | all targeted except .tech (nothing registered) and Entire (a CLI install, no repo code) |
| Offline/unit-tested | 10 | the same 10 |
| Live-verified with the sponsor's tech | 2 | Gemma (local `gemma3:4b` suite run), Mastra (local full-suite run) |
| Partially live | 2 | Tiger Data (real EmbeddingGemma calls; no real Tiger database yet), Temporal (real workflows on temporalio's test server; dev-server crash test reported by a worker but not recorded in the repo) |
| Deployed | 0 | |
| Awaiting user action (account, key, deploy or screenshot) | 10 | Sentry, DigitalOcean, Render, .tech, ElevenLabs, Backboard, MongoDB Atlas, Tiger Data, Temporal, Entire |
| Ready to list in the post today without user action | 2 | Gemma, Mastra |

## Matrix

| Category | Implemented | Unit/offline-tested | Live-tested (where/how) | Deployed | Eligibility per official text | Evidence still missing | User action needed |
|---|---|---|---|---|---|---|---|
| Gemma ($200) | Yes: `examples/ollama_agent.py --tool-mode json` for models without native tools; EmbeddingGemma used by the Tiger exporter; deploy configs default to `gemma-4-31B-it` | Yes (`tests/test_example_agent.py`) | **Yes, locally.** `gemma3:4b` (Ollama 0.30.10, digest `a2af6cc3…`), full suite, 2 pass / 10 fail / 0 error, audited in `docs/audits/gemma-gemma3-4b-2026-10-17.md`, bundled in `demo/runs/`. Real `embeddinggemma` calls via local Ollama. Local Gemma evaluation = `gemma3:4b` only (2/12, JSON tool mode); Gemma 4 is only used as the hosted DigitalOcean model `gemma-4-31B-it` in the deploy config, tool calling unverified | No | Verified ("run it locally") | Post paragraph on the JSON-tool-mode caveat | None required. Optional: DO `gemma-4-31B-it` probe |
| Sentry Agent Tracing ($100) | Yes: `gen_ai.invoke_agent` / `gen_ai.chat` / `gen_ai.execute_tool` spans per turn, `gen_ai.conversation.id`, token counts; content capture opt-in (`--sentry-capture-content`) | Yes, real `sentry-sdk` with an in-memory transport | No (no DSN) | n/a | Verified, but the text asks for "how it's set up, how it performs (latency, tokens, cost), what you found, and how you debugged it. Include traces or screenshots" | Screenshot of one trace (invoke_agent with chat + execute_tool children), span durations, token counts; cost (local Ollama = $0; Sentry may not compute cost for `ollama` or a DO host); one finding debugged from a trace | Create Sentry Python project, export `SENTRY_DSN`, one traced suite run, screenshots |
| DigitalOcean ($200) | Yes: `--backend openai` for Gradient serverless inference (`https://inference.do-ai.run/v1`); `.do/app.yaml` App Platform spec (default `AGENT_MODEL=gemma-4-31B-it`) | Yes, against a local OpenAI-compatible stub | No (no model access key). Tool calling of `gemma-4-31B-it` on DO is unverified | No | Verified ("host your app or agent", "Gradient AI Platform") | `/v1/models` list, tool-call probe output, one case (ideally the suite) against a DO model, and/or the live `*.ondigitalocean.app` URL | DO account, model access key, probe, optionally `doctl apps create --spec .do/app.yaml` ($5/month instance) |
| Render ($200) | Yes: `render.yaml` Docker Blueprint; `bolibench serve` demo (read-only results, bounded scripted `POST /api/evaluate`) plus token-gated live mode that runs the example agent inside the container against an open-weight model | Yes (`tests/test_server.py`, incl. live mode end to end with a local agent) | No | No | Verified **if live mode is on** (the container then hosts an agent: "AI runtime"). Read-only demo alone: needs clarification | Live `onrender.com` URL; `/health` showing `"live": true`; one `POST /api/live-run` result; dashboard screenshot | Push repo, Render Blueprint, enter `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN` |
| .tech Domain ($100) | No (deploy docs describe the CNAME only) | n/a | No | No domain registered | Verified **only if** claimed through Hacktoberfest and serving the project | The .tech URL serving the demo over HTTPS | Claim at hacktoberfest.com/my/promos, add custom domain on Render, CNAME at get.tech |
| ElevenLabs ($100) | Yes: `bolibench run --speech elevenlabs [--speech-audio-dir DIR]`, TTS → STT, `asr_text` + per-turn `speech` evidence (audio sha256, language, timings) | Yes, fakes and a local HTTP stub | No (no key) | n/a | Verified ("transcribe audio for a local model") | One live run: artifact with `asr_text` vs `user_input`, cached mp3s, note of any misheard words | API key (TTS + STT scopes, quota), `ELEVENLABS_VOICE_ID`, live test, one speech run |
| Mastra ($100) | Yes: `examples/mastra-agent` (`@mastra/core` 1.78.0) speaking the webhook protocol on local `qwen3:8b` | Yes, `npm test` (offline) | **Yes, locally.** Full suite 6 pass / 6 fail / 0 error (`runs/mastra-qwen3-8b-2026-10-17/`, bundled in `demo/runs/`); per-case verdicts equal the Python v2 run. Ollama was shared with another worker's gemma run during it | No | Verified ("orchestrate an agent over open models") | None beyond the post | None |
| Backboard ($100) | Yes: `examples/backboard_agent.py` bridge (`/threads/messages`, `/threads/tool-outputs`) | Yes, local stub of the documented API | No (no key); field names from docs, never observed | n/a | Verified ("compare open-weight models through a single Backboard API key"), which needs **at least two** models run | One case, then suite runs for ≥2 open-weight models via one key, `summary.json` counts | Claim Backboard credits, `BACKBOARD_API_KEY`, pick tool-capable open models, run |
| MongoDB Atlas ($100) | Yes: `bolibench export --to mongo` (full artifacts as documents, report aggregation) | Yes, dry run and fakes | No (`test_live_mongo` opt-in, not run) | n/a | Verified ("the database behind an app built on an open-weight model") | Atlas Data Explorer screenshot of `bolibench.case_results` from a real run; `--report` output | M0 cluster, DB user, IP allowlist, `MONGODB_URI`, export one run |
| Tiger Data ($100) | Yes: `bolibench export --to tiger` hypertable + pgvector/tsvector hybrid similar-failure search, EmbeddingGemma embeddings | Yes, dry run and fakes | Partial: real local `embeddinggemma` calls; **pgvector SQL never run on a real database** (`test_live_tiger` not run) | n/a | Verified ("store embeddings with pgvector, run hybrid keyword and vector search") | Console/query output: `timescaledb_information.hypertables`, `bolibench_failures` rows, one `--similar` result | Tiger Cloud service, `TIGER_DATABASE_URL`, export with `--failures`, run `--similar` |
| Temporal ($100) | Yes: `python -m bolibench.temporal_run worker|start`, one activity per case, resume, infra-only retries | Yes, real workflows on temporalio's time-skipping test server (`test_workflow_matches_bolibench_run_and_resumes_without_rerunning`) | Partial: a worker reports a local dev-server run with `kill -9` resume; no run directory or note of it exists in the repo | n/a | **Needs clarification**: the text is "Make your agent durable"; this makes the evaluation run durable, not the agent | Temporal UI screenshots (workflow Completed, one `bolibench.run_case` per case, the retried attempt after `kill -9`) | `temporal server start-dev --db-filename temporal.db`, worker, `start`, kill/restart, screenshots |
| Entire ($100) | Entire CLI 0.11.5 installed and enabled, checkpoints `git-refs`, kept local (`push_sessions: false` in the gitignored `.entire/settings.local.json`) | n/a | No: checkpoints are not pushed, so no public session exists | n/a | Verified ("share the agent sessions behind your project in the write-up") | A public entire.io session/checkpoint link tied to a real commit | Not entered unless sessions are published later: review what a session contains, then publish it deliberately and share the link |
| GitHub Copilot ($100) | No | — | — | — | Not entered (GitHub Copilot was not used, so that category is not entered) | — | — |
| Tinker ($200) | No | — | — | — | Not entered (needs a fine-tune with a clear improvement; not credible on 12 unreviewed cases) | — | — |
| TabPFN ($200) | No | — | — | — | Not entered (no tabular prediction problem) | — | — |
| SerpApi ($100) | No | — | — | — | Not entered (agent has no need for web search) | — | — |
| Arduino ($200) | No | — | — | — | Not entered (no UNO Q hardware) | — | — |

## Inconsistencies found while checking

- `docs/integrations.md` says the Tiger exporter's "live test opt-in, not run", while
  `docs/integrations/tiger-data.md` reports real EmbeddingGemma similarities (0.90–0.93). Both can
  be true (embeddings live, database not); the matrix records it as partial.
- Temporal: README and `docs/integrations.md` say "tested on temporalio's local test server". The
  dev-server `kill -9` resume reported by a worker is not recorded anywhere in the repo. Do not
  claim it in the post until it is rerun and screenshotted.
- Entire checkpoints are kept local: `push_sessions` is false in the gitignored
  `.entire/settings.local.json`, so pushes to the public GitHub repo carry no session data (prompts,
  tool calls). If sessions are published later, review them first: Entire redacts secrets, but
  personal paths and the git author email can still appear.
- The two initial commits are rewritten to the noreply identity before the first push; commits are
  made from a normal terminal. The editor's local hook directory is git-ignored and not committed.
