# Live verification report (HF26 Week 2: Side Hustle)

State on 2026-10-18 (IST), working tree on top of `master` @ `0fbd6e8`. Every row below comes from
recorded output: a log, an artifact, or a command rerun while writing this. Nothing is inferred.

Modes:

- **offline**: fakes, stubs, in-memory transports, dry runs, test servers. Proves our code against
  our reading of the sponsor's docs, not the sponsor's service.
- **live (local)**: the sponsor's real software on this laptop (Ollama models, MongoDB 7, TimescaleDB +
  pgvector, the Temporal dev server, a Mastra agent). Not the hosted product.
- **live (hosted)**: the sponsor's hosted service with a real account. Nothing is in this mode yet:
  there are no credentials on this machine (`.env` is absent).

Raw logs and run directories are in the git-ignored `runs/` (paths below). They stay local; this
report is the committed record. Worker timestamps in logs are UTC (`2026-10-17T18:35Z` =
2026-10-18 00:05 IST).

## 1. Challenge rules re-checked (2026-10-18 00:05 IST)

Pages fetched: the [launch post](https://dev.to/devteam/join-the-hacktoberfest-open-source-ai-challenge-side-hustle-2550-in-prizes-across-18-winners-55ba),
the [challenge page with FAQ](https://dev.to/challenges/hacktoberfest-week2-2026-10-12), the
[HF26 hub](https://dev.to/challenges/hf26) and the
[Week 2 contest rules](https://dev.to/page/hacktoberfest-week2-2026-10-12-contest-rules).

- **Deadline unchanged:** Oct 18 2026 11:59 PM PDT = **Mon Oct 19 2026 12:29 PM IST**. No extension.
- **No new requirements** since 2026-10-17: same 17 categories (6 featured at $200, 11 partner at
  $100), same category text, same judging.
- **Required elements:** a published DEV post from the template with `#hf26challenge`; a brand-new
  project built in the entry period with open-weight models / open-source AI at its core; the Side
  Hustle angle; **a link to a deployed project or a video demo**; a link to or embed of the repo;
  why open innovation matters. The user will provide both a Render deploy and a video.
- Partner categories: the project must "meaningfully incorporate that category's technology" and the
  post must name the category. One prize per participant; only the first entry is judged.
- New-project rule: first commit `1a91e20` is 2026-10-17 12:29 IST, inside the window. Commits after
  the deadline must be listed in the README.

## 2. Category decisions

| Category | Decision | Evidence in hand | Evidence still needed (user) |
|---|---|---|---|
| Gemma | entered | `gemma3:4b` full suite 2/12 (audited); 3-case rerun matched | none |
| Mastra | entered | full suite 6/12; 2-case rerun matched; `npm test` 5/5 | none |
| Temporal | entered, framed as a durable *evaluation* run (not a durable agent) | local dev server: summary identical to `bolibench run`, `kill -9` resume with activity attempt 2, same-id restart re-ran nothing | UI screenshots (local, no account) |
| Render | entered once deployed | image runs locally; Blueprint valid | deploy, URL, `/health`, live-mode result |
| DigitalOcean | entered once called | OpenAI-compatible path live (local) via Ollama `/v1` | model key, probe, one case / suite |
| Sentry Agent Tracing | entered once traced | spans and privacy tested offline | DSN, traced run, screenshots |
| ElevenLabs | entered once run | round-trip tested offline | key, voice id, live test, speech run |
| MongoDB Atlas | entered once on Atlas | exporter live (local) on MongoDB 7.0.45 | Atlas cluster, export, screenshot |
| Tiger Data | entered once on Tiger Cloud | exporter + hybrid search live (local) on TimescaleDB 2.30.2 + pgvector 0.8.7; this is a rehearsal, not the category evidence | Tiger Cloud service, export, `--similar`, screenshot |
| Backboard | entered once ≥2 models run | bridge tested against a stub of the documented API | key, ≥2 full-suite runs |
| .tech Domain | not entered, unless registered and serving the live demo | nothing registered | claim, CNAME, HTTPS |
| Entire | not entered | checkpoints local only (`push_sessions: false`) | — |
| GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino | not entered | — | — |

## 3. Verification log

### 3.1 Test suite and bundled runs

| Item | What | Command / procedure | Date | Mode | Result | Errors | Artifact | Remaining |
|---|---|---|---|---|---|---|---|---|
| Test suite | all unit and offline integration tests | `uv run pytest -q`; `uv run --all-extras pytest -q` | 2026-10-18 | offline | **335 passed, 4 skipped** (both). Was 307/4 at 00:05 IST, before the workers' fixes and tests | none | terminal | The 4 skipped are opt-in live tests: `test_live_ollama_embeddings`, `test_live_mongo`, `test_live_tiger`, `test_live_elevenlabs_round_trip`. The first three passed with `BOLIBENCH_LIVE=1` against local services (3.3) |
| Suite | schema check of the 12 cases | `uv run bolibench validate suites/orders` | 2026-10-18 | offline | `suites/orders: 12 cases ok` | none | terminal | — |
| qwen3:8b, example agent v1 | full suite | `docs/audits/qwen3-8b-baseline-2026-10-17.md` | 2026-10-17 | live (local), Ollama 0.30.10 | 3 pass / 9 fail / 0 error | none | `demo/runs/qwen3-8b-baseline-2026-10-17/` | — |
| qwen3:8b, v2 | full suite | `docs/audits/qwen3-8b-agent-v2-2026-10-17.md` | 2026-10-17 | live (local) | 6 / 6 / 0 | none | `demo/runs/qwen3-8b-agent-v2-2026-10-17/` | — |
| qwen3:8b, v3 (native tools) | full suite | `demo/runs/index.json` | 2026-10-17 | live (local) | 6 / 6 / 0 | none | `demo/runs/qwen3-8b-agent-v3-2026-10-17/` | — |
| gemma3:4b, v3, JSON tool mode | full suite | `docs/audits/gemma-gemma3-4b-2026-10-17.md` | 2026-10-17 | live (local) | 2 / 10 / 0 | two earlier attempts lost the agent process, not bundled | `demo/runs/gemma-gemma3-4b-2026-10-17/` | — |
| Mastra agent on qwen3:8b | full suite | `docs/integrations/mastra.md` | 2026-10-17 | live (local) | 6 / 6 / 0; per-case verdicts equal v2's | none | `demo/runs/mastra-qwen3-8b-2026-10-17/` | — |

### 3.2 Models and agents (local live)

| Integration | What | Command / procedure | Date | Mode | Result | Errors | Artifact | Remaining |
|---|---|---|---|---|---|---|---|---|
| Gemma 3 4B, 3-case rerun | Does the audited run reproduce? Same models (digests recorded) and the audited agent file (sha256 `98ab4c7e…`, the committed one) | `python3 examples/ollama_agent.py --model gemma3:4b --tool-mode json --port 8100`; `bolibench run` on `awadhi-cancel-yesterday`, `cancel-single-order`, `tool-failure-cancel` | 2026-10-18 00:17 IST | live (local), Ollama 0.30.10, `gemma3:4b` `a2af6cc3…` | 1 pass / 2 fail, same as the audited run. Per case, the verdict, the tool calls (tool, arguments, status) and the final state are identical to the audited artifacts; the reply wording differs in 2 of 3 cases. 12 s wall | none | `runs/gemma3-4b-repro-2026-10-18/20261017T184713Z-ee739838/`, logs in `runs/gemma3-4b-repro-2026-10-18-logs/` | none |
| OpenAI-compatible backend | `--backend openai` against a real OpenAI-compatible server (Ollama's `/v1`), with a dummy key, to exercise the code path DigitalOcean inference uses | `BB_DUMMY_KEY=<dummy> python3 examples/ollama_agent.py --backend openai --base-url http://127.0.0.1:11434/v1 --model qwen3:8b --api-key-env BB_DUMMY_KEY --port 8200`; `cancel-single-order`, `forbidden-bulk-cancel` | 2026-10-18 00:18 IST | live (local), qwen3:8b | 2 pass / 0 fail; agent identity `fc32f58d79e5+qwen3:8b+openai-native`; the dummy key is in no artifact or log (only the redacted placeholder in `pre-run.txt`). 50 s wall | none | `runs/openai-compat-ollama-qwen3-8b-2026-10-18/20261017T184802Z-00d1a8ea/`, `runs/openai-compat-ollama-qwen3-8b-2026-10-18-logs/` | Proves our client, not DigitalOcean: the hosted probe and run are user steps |
| Mastra agent | offline tests, typecheck, 2-case rerun, malformed HTTP requests | `npm test`, `npm run typecheck` in `examples/mastra-agent`; `bolibench run` on `similar-items-kurta-kurti`, `tool-failure-cancel`; curl negatives | 2026-10-18 00:19 IST | offline (tests) + live (local), qwen3:8b | `npm test` 5/5, `tsc` clean. Rerun: 1 pass / 1 fail, verdicts, tool calls and final states identical to the bundled run; reply wording differs. Negatives: bad JSON 400, schema-invalid 400, 70 kB and 5 MB bodies 413, `GET /turn` 404, unknown conversation 409; server healthy after | none | `runs/mastra-qwen3-8b-repro-2026-10-18/20261017T184921Z-2639fc2a/`, `runs/mastra-qwen3-8b-repro-2026-10-18-logs/http-negative-tests.txt`, `runs/live-verification-2026-10-18-logs/mastra-npm-test.log` | none |

### 3.3 Storage and orchestration (local live)

| Integration | What | Command / procedure | Date | Mode | Result | Errors | Artifact | Remaining |
|---|---|---|---|---|---|---|---|---|
| MongoDB export | export, idempotency, report, indexes, live test | `MONGODB_URI=mongodb://127.0.0.1:27017`, `MONGODB_DB=bolibench_verify_20261018`; `uv run --extra mongo bolibench export --to mongo <v3 run> --suite suites/orders` (twice), then the gemma and Mastra runs, then `--report`; `mongosh` index listing; `BOLIBENCH_LIVE=1 … pytest tests/test_export.py -k live_mongo` | 2026-10-18 00:11 IST | live (local), MongoDB 7.0.45 (`mongo:7` image) | first export `13 new`, re-export `0 new, 13 already present`; 3 runs / 36 case results; indexes on `case_results`: `case_id+started_at`, `run_id`, `verdict`; `--report` per-case pass rates (e.g. `cancel-single-order` 3/3, `similar-items-kurta-kurti` 0/3); `test_live_mongo` passed | none | `runs/live-verification-2026-10-18-logs/mongo.log` | **Atlas**: same commands with an Atlas `MONGODB_URI`, Data Explorer screenshot |
| Tiger Data export + similar-failure search | hypertable export, idempotency, report, embeddings, hybrid search, live tests | local `timescale/timescaledb-ha:pg16`; `uv run --extra tiger bolibench export --to tiger <runs>` (twice), `--report`, `--failures` (twice), `--similar … --k 5` on two failed artifacts; `psql` checks; `BOLIBENCH_LIVE=1 … -k "live_tiger or live_ollama"` | 2026-10-18 00:15 IST | live (local), TimescaleDB 2.30.2, PostgreSQL 16.15, pgvector 0.8.7; `embeddinggemma` via Ollama 0.30.10 | `bolibench_case_results` is a hypertable; 36 rows, re-export `0 inserted`; `--failures`: 22 failures indexed (768-dim), re-run `0 indexed`; indexes `bolibench_failures_tsv` (full text) and `bolibench_failures_embedding` (vector); `--similar` returns the same case from the other runs first (fused scores 0.032–0.033, then 0.029–0.031 for other cases). Those cases share mostly identical user text, so this shows the search works, not that it finds non-obvious matches; `test_live_tiger` and `test_live_ollama_embeddings` passed | none | `runs/live-verification-2026-10-18-logs/tiger.log` | **Tiger Cloud** (the category evidence): same commands with a Tiger Cloud `TIGER_DATABASE_URL`, console screenshot |
| Temporal: scripted parity | does a workflow run equal `bolibench run`? | `temporal server start-dev --db-filename …`; `uv run --extra temporal python -m bolibench.temporal_run worker`; `… start <3 cases> --scripts … --workflow-id bb-scripted-2026-10-18`; same cases with `bolibench run --scripts` | 2026-10-18 00:05 IST | live (local), Temporal CLI 1.9.1, Server 1.32.0 | 3 pass both ways; the two `summary.json` files are byte-identical (`cmp`); workflow COMPLETED, 3 `run_case` activities + summary, all attempt 1 | none | `runs/temporal-local-2026-10-18/`, `runs/live-verification-2026-10-18-logs/temporal-start-scripted.log`, `cli-run-scripted.log`, `temporal-history.txt` | — |
| Temporal: crash and resume | `kill -9` the worker mid-run, restart, let `start` finish | webhook run against a deliberately slow stub agent (`slow-stub`, not a model), workflow `bb-crash-resume-2-2026-10-18` | 2026-10-18 00:07 IST | live (local) | COMPLETED; the interrupted activity ran again as **attempt 2** after its timeout; one artifact per case + `summary.json`; 79 s wall. An earlier attempt (`bb-crash-resume-2026-10-18`) completed with every activity at attempt 1, i.e. no activity was interrupted | none | `runs/live-verification-2026-10-18-logs/temporal-start-crash-resume-2.log`, `temporal-history.txt` | — |
| Temporal: same workflow id again | resuming a finished run must not call the agent | `… start … --workflow-id bb-crash-resume-2-2026-10-18` again | 2026-10-18 | live (local) | every case printed `(already done)`; no agent call | none | `runs/live-verification-2026-10-18-logs/temporal-restart-same-id.log` | UI screenshots (http://localhost:8233): workflow list, Event History, the attempt-2 activity |
| Temporal: unreachable server | was a traceback | `TEMPORAL_ADDRESS=127.0.0.1:1 … worker` / `start` | 2026-10-18 | offline (test) | **bug fixed**: now `error: cannot connect to Temporal at <address>: …`, exit 2, nothing runs; test added | — | `tests/test_temporal_run.py::test_unreachable_server_is_an_error_line_not_a_traceback` | — |

### 3.4 Deploy readiness

| Item | What | Command / procedure | Date | Mode | Result | Errors | Artifact | Remaining |
|---|---|---|---|---|---|---|---|---|
| Docker image | build and run with no configuration | `docker build -t bolibench-demo .`; `docker run --read-only -p 10000:10000 -e PORT=10000 bolibench-demo`; the endpoint checks in `docs/deployment.md` "Verify a deployment" | 2026-10-18 | live (local) | about 218 MB unpacked (47 MB compressed); runs as `nobody` (uid 65534) on a read-only filesystem; live mode off; every endpoint answers | none | `docs/deployment.md` (procedure); local image `bolibench-demo:latest` | Render deploy |
| `render.yaml` | Blueprint schema | `render blueprints validate render.yaml` (Render CLI 2.28.0) | 2026-10-18, rerun after the tool-mode edit | offline | `"valid": true` | none | terminal | Deploy |
| `.do/app.yaml` | App Spec | checked by hand against the App Spec reference; YAML parses | 2026-10-18 | offline | no machine validation (`doctl` not installed) | — | — | `doctl apps spec validate .do/app.yaml` if DO hosting is used (optional) |
| Hosted tool mode | `AGENT_TOOL_MODE` default for `gemma-4-31B-it` | DigitalOcean's model table lists Chat Completions but **not tool calling** for `gemma-4-31B-it` (audit worker, docs URLs in `docs/integrations/gemma-sentry.md`) | 2026-10-18 | offline | both platform configs now set `AGENT_TOOL_MODE=json`; `native` only after the probe returns `tool_calls` | — | `render.yaml`, `.do/app.yaml`, `docs/deployment.md` | Probe with a real key |
| Demo page + integrations panel | page explains BoliBench, the 12 cases against the 5 bundled runs, and an integrations panel from `demo/integrations.json` (`GET /api/integrations`; unknown status values stop the server at startup) | `uv run pytest -q tests/test_server.py` | 2026-10-18 | offline | 60 passed, with this report's statuses | none | `src/bolibench/server.py`, `demo/integrations.json`, `tests/test_server.py` | — |

### 3.5 Code audit against the official docs (offline)

Each integration's request and response handling was compared with the provider's docs (URLs in
`docs/integrations/*.md`) and run end to end against a local stub of the documented API.

| Integration | Result | Bugs fixed (with tests) | Only a live call can confirm |
|---|---|---|---|
| Sentry agent tracing | span ops, names and `gen_ai.*` attributes conform | **Privacy:** with the SDK's default local-variable capture, an error event from a failed model call carried the utterance, the system prompt and the `Authorization: Bearer <key>` header (the SDK's scrubber only caught a top-level `api_key` variable). Now `include_local_variables=False`. Model and tool exceptions are now captured as Sentry issues and tag the failing span with `error.type` | ingestion, how the AI Agents views show the spans, cost display for a non-OpenAI provider |
| ElevenLabs | TTS and STT requests conform | 422 validation errors (a list under `detail`) are parsed into a readable reason; the temp file is removed if a cache write fails; a voice id `..` is rejected (no path segment) | multipart STT upload, `eleven_multilingual_v2` without `language_code`, error body shapes |
| Backboard | `/threads/messages` fields are a subset of the documented request schema; `/threads/tool-outputs` has exactly `thread_id` + `tool_outputs` | tests tightened to the documented schemas | `tool_calls[].function.arguments` as a JSON string, `status` on non-streaming replies |
| OpenAI-compatible (DigitalOcean) | request shape conforms; `--base-url` must be https for a remote host | — | that `gemma-4-31B-it` answers with the JSON tool format, cost per run |

### 3.6 Not testable here (no credentials)

Sentry (hosted), ElevenLabs, MongoDB Atlas, Tiger Cloud, Backboard, DigitalOcean inference and App
Platform, Render deploy, a .tech domain. Each stays out of "live (hosted)" until the user's step in
`docs/submission-checklist.md` has run and its output is added here.

### 3.7 Live (hosted) results

| Integration | Date | Command | Result | Artifact / screenshot |
|---|---|---|---|---|
| (none yet) | | | | |
