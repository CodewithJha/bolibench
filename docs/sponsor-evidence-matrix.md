# Sponsor evidence matrix (state on 2026-10-18, IST)

What is true in the repo today, per category, checked against the integration docs, the tests and
the recorded runs. Detail and commands for every claim: `docs/live-verification-report.md`.
"Live (local)" means the sponsor's real software on this laptop; "live (hosted)" means the sponsor's
hosted service with a real account. Fakes, stubs, in-memory transports and test servers are offline.
Category text: https://dev.to/challenges/hacktoberfest-week2-2026-10-12 (anchors
`#best-use-of-<name>` on https://dev.to/challenges/hf26).

Test suite: `uv run pytest -q` → 335 passed, 4 skipped (the 4 opt-in live tests; three of them
passed against local MongoDB, TimescaleDB and Ollama with `BOLIBENCH_LIVE=1`).
`uv run bolibench validate suites/orders` → 12 cases ok.

## Summary counts (computed from the rows below)

| | Count | Which |
|---|---|---|
| Categories | 17 | |
| Entered (named in the post once its evidence is in) | 10 | Gemma, Mastra, Temporal, Render, DigitalOcean, Sentry, ElevenLabs, MongoDB Atlas, Tiger Data, Backboard |
| Conditional | 1 | .tech: entered only if registered and serving the live demo |
| Not entered | 6 | Entire, GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino |
| Implemented (code or config in repo) | 10 | the 10 entered |
| Offline-tested | 10 | the 10 entered |
| Live (local) with the sponsor's software | 5 | Gemma, Mastra, Temporal (dev server), MongoDB (local 7.0.45, not Atlas), Tiger Data (local TimescaleDB + pgvector, not Tiger Cloud) |
| Live (hosted) | 0 | no credentials yet |
| Deployed | 0 | Render deploy is the user's first step |
| Category evidence complete today | 2 | Gemma, Mastra |
| Complete after local-only user steps (no account) | 1 | Temporal (UI screenshots) |
| Need an account, key or deploy from the user | 7 | Render, DigitalOcean, Sentry, ElevenLabs, MongoDB Atlas, Tiger Data, Backboard (+ .tech if pursued) |

## Matrix

| Category | Implemented | Offline-tested | Live (local) | Live (hosted) / deployed | Decision | Evidence still missing | User action |
|---|---|---|---|---|---|---|---|
| Gemma ($200) | `examples/ollama_agent.py --tool-mode json`; EmbeddingGemma in the Tiger exporter; deploy configs default to `gemma-4-31B-it` in JSON tool mode | Yes | **Yes.** `gemma3:4b` full suite 2/10/0, audited (`docs/audits/gemma-gemma3-4b-2026-10-17.md`); 3-case rerun on 2026-10-18: same verdicts, tool calls and final states; `embeddinggemma` embedded 22 failures | `gemma-4-31B-it` on DigitalOcean not called | Entered | none (hosted Gemma 4 is optional, via the DigitalOcean step) | none |
| Mastra ($100) | `examples/mastra-agent` (`@mastra/core` 1.78.0) | `npm test` 5/5, `tsc` clean | **Yes.** Full suite 6/6/0 on `qwen3:8b`; 2-case rerun matched; malformed requests get 400/413/404/409 | n/a | Entered | none | none |
| Temporal ($100) | `python -m bolibench.temporal_run worker\|start` | Yes (temporalio test server) | **Yes.** Dev server (CLI 1.9.1 / Server 1.32.0): summary byte-identical to `bolibench run`; `kill -9` of the worker, interrupted activity re-ran as attempt 2, run completed; same workflow id again re-ran nothing. The crash test's agent was a slow stub | n/a | Entered, framed as a durable **evaluation** run: the suite run survives worker crashes and resumes, the agent itself is not a workflow | UI screenshots | Rerun locally, screenshot http://localhost:8233 |
| Render ($200) | `render.yaml` Docker Blueprint; demo page + integrations panel; token-gated live mode running the agent in the container | Yes (`tests/test_server.py`) | Docker image runs locally as `nobody`, read-only FS, all endpoints OK | Blueprint valid (`render blueprints validate`); **not deployed** | Entered once deployed; strongest with live mode on (Render then hosts the agent runtime) | URL, `/health`, dashboard screenshot, one `/api/live-run` result | Render account, Blueprint deploy; add DO key + demo token for live mode |
| DigitalOcean ($200) | `--backend openai` for serverless inference; `.do/app.yaml` | Yes (stub) | OpenAI-compatible path: 2/2 pass via Ollama `/v1`, dummy key in no output | Not called. DO's model table lists no tool calling for `gemma-4-31B-it`, so configs use JSON tool mode | Entered once called | model list + probe output, one case (ideally the suite) against DO, or the live demo using DO inference | DO account, model access key |
| Sentry Agent Tracing ($100) | `gen_ai.invoke_agent` / `chat` / `execute_tool` spans, conversation id, tokens; content opt-in; no local variables on error events; exceptions captured | Yes (real SDK, in-memory transport) | n/a (needs Sentry) | No DSN | Entered once traced | trace waterfall, AI Agents view, conversation, one error issue without locals, one finding | Sentry project, DSN, traced run, screenshots |
| ElevenLabs ($100) | `bolibench run --speech elevenlabs [--speech-audio-dir]` | Yes (fakes, stub); audited against the API docs | n/a | No key | Entered once run | live test output, one artifact `user_input` vs `asr_text`, usage screenshot | Key (TTS + STT), voice id, live test, speech run |
| MongoDB Atlas ($100) | `bolibench export --to mongo` | Yes | Local MongoDB 7.0.45: export, idempotent, indexes, report, live test | No Atlas cluster | Entered once on Atlas (a local MongoDB is not Atlas) | Data Explorer screenshot, `--report` output from Atlas | M0 cluster, user, IP allowlist, `MONGODB_URI` |
| Tiger Data ($100) | `bolibench export --to tiger`, pgvector + full-text hybrid search over EmbeddingGemma embeddings | Yes | Local TimescaleDB 2.30.2 + pgvector 0.8.7: hypertable, idempotent, report, 22 failures embedded, `--similar` works (top hits are the same case in other runs) | No Tiger Cloud service | Entered once on Tiger Cloud (local run is the rehearsal) | hypertable query, `--similar` output, console screenshot, all on Tiger Cloud | Tiger Cloud service, `TIGER_DATABASE_URL` |
| Backboard ($100) | `examples/backboard_agent.py` bridge | Yes; requests checked against the documented schemas | n/a | No key | Entered once ≥2 models run (the category is "compare open-weight models through a single Backboard API key") | ≥2 full-suite `summary.json` counts via one key, usage screenshot | Claim credits, key, pick tool-capable open models |
| .tech Domain ($100) | No (deploy docs describe the CNAME) | n/a | n/a | Nothing registered | Conditional: only if claimed through Hacktoberfest and serving the live demo | the .tech URL over HTTPS | Claim, Render custom domain, CNAME |
| Entire ($100) | CLI enabled, checkpoints kept local (`push_sessions: false`) | n/a | n/a | No public session | Not entered | — | — |
| GitHub Copilot ($100) | No | — | — | — | Not entered (not used) | — | — |
| Tinker ($200) | No | — | — | — | Not entered | — | — |
| TabPFN ($200) | No | — | — | — | Not entered | — | — |
| SerpApi ($100) | No | — | — | — | Not entered | — | — |
| Arduino ($200) | No | — | — | — | Not entered | — | — |

## Notes

- Reproducibility: the Gemma and Mastra reruns matched the bundled runs on verdict, tool calls and
  final state, but not on reply wording. Say "the same actions", not "identical runs".
- Local MongoDB and local TimescaleDB are the sponsors' open-source databases, but the categories
  name Atlas and Tiger; only the hosted runs go in the post as category evidence.
- Temporal's crash test used a slow stub agent so the kill landed mid-case; it shows the evaluation
  harness's durability, which is how the post must describe it.
- Entire checkpoints stay local: pushes skip Entire's pre-push hook, and no session data is public.
