# Live verification report (HF26 Week 2: Side Hustle)

State on 2026-10-18 (IST), working tree on top of `master` @ `0fbd6e8`; updated at about 13:30 IST on
top of `ace4e9f` (uncommitted: the benchmark audit, the hosted Gemma 4, Backboard and ElevenLabs work,
3.7 and 3.8). Every row below comes from recorded output: a log, an artifact, or a command rerun while
writing this. Nothing is inferred.

Modes:

- **offline**: fakes, stubs, in-memory transports, dry runs, test servers. Proves our code against
  our reading of the sponsor's docs, not the sponsor's service.
- **live (local)**: the sponsor's real software on this laptop (Ollama models, MongoDB 7, TimescaleDB +
  pgvector, the Temporal dev server, a Mastra agent). Not the hosted product.
- **live (hosted)**: the sponsor's hosted service with a real account. In this mode (3.7): the Render
  deployment, ElevenLabs, Gemma 4 on Google's Gemini API, and Backboard (partial). The ElevenLabs,
  Backboard and Gemini keys were reused from the owner's other project into a git-ignored local
  `.env` (`docs/credential-matrix.md`); there is no DigitalOcean, Sentry, Atlas or Tiger Cloud
  credential.

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
| Gemma | entered | `gemma3:4b` full suite 2/12 (audited); 3-case rerun matched; hosted `gemma-4-31b-it` on the Gemini API full suite 8 pass / 3 fail / 1 error (audited, 3.7) | none |
| Mastra | entered | full suite 6/12; 2-case rerun matched; `npm test` 5/5 | none |
| Temporal | entered, framed as a durable *evaluation* run (not a durable agent) | local dev server: summary identical to `bolibench run`, `kill -9` resume with activity attempt 2, same-id restart re-ran nothing | UI screenshots (local, no account) |
| Render | entered | redeployed on a new Render workspace at https://bolibench-demo-1b3o.onrender.com (`srv-dbafue7btjjs73f13di0`, free plan, commit `3440507`) with token-gated live mode on (Gemma 4 on the Gemini API); public checks passed and one hosted live run `cancel-single-order` passed (3.7). The first service (read-only, `ace4e9f`) is suspended on the old workspace and no longer used | dashboard screenshot |
| DigitalOcean | entered once called | OpenAI-compatible path live via Ollama `/v1` (local) and Google's Gemini API (hosted, not DigitalOcean) | model key, probe, one case / suite |
| Sentry Agent Tracing | entered once traced | spans and privacy tested offline | a dedicated BoliBench DSN, traced run, screenshots |
| ElevenLabs | entered | live TTS, STT, live test, CLI with cache, 3-case end-to-end run (3.7) | usage screenshot |
| MongoDB Atlas | entered once on Atlas | exporter live (local) on MongoDB 7.0.45 | Atlas cluster, export, screenshot |
| Tiger Data | entered once on Tiger Cloud | exporter + hybrid search live (local) on TimescaleDB 2.30.2 + pgvector 0.8.7; this is a rehearsal, not the category evidence | Tiger Cloud service, export, `--similar`, screenshot |
| Backboard | entered once ≥2 models run | bridge run against the real API (3.7): round trip and memory isolation pass; chosen open-weight model blocked by billing; a free preview model passed 3 of 4 cases | paid credit, ≥2 full-suite runs of open-weight models |
| .tech Domain | not entered, unless registered and serving the live demo | nothing registered | claim, CNAME, HTTPS |
| Entire | not entered | checkpoints local only (`push_sessions: false`) | — |
| GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino | not entered | — | — |

## 3. Verification log

### 3.1 Test suite and bundled runs

| Item | What | Command / procedure | Date | Mode | Result | Errors | Artifact | Remaining |
|---|---|---|---|---|---|---|---|---|
| Test suite | all unit and offline integration tests | `uv run pytest -q`, three times in a row (13:1x IST) | 2026-10-18 | offline | **387 passed, 4 skipped**, identical all three times (no flakes); 392/4 at about 13:35 IST after the live-mode work added server tests. Was 335/4 at `ace4e9f`, 307/4 at 00:05 IST | none | terminal | The 4 skipped are opt-in live tests: `test_live_ollama_embeddings`, `test_live_mongo`, `test_live_tiger`, `test_live_elevenlabs_round_trip`. The first three passed with `BOLIBENCH_LIVE=1` against local services (3.3); the ElevenLabs one passed live (3.7) |
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
| Docker image | build and run with no configuration | `docker build -t bolibench-demo .`; `docker run --read-only -p 10000:10000 -e PORT=10000 bolibench-demo`; the endpoint checks in `docs/deployment.md` "Verify a deployment" | 2026-10-18 | live (local) | about 218 MB unpacked (47 MB compressed); runs as `nobody` (uid 65534) on a read-only filesystem; live mode off; every endpoint answers. Rebuilt from `ace4e9f` at 11:08 IST before the Render deploy: `/health` 200, `{"cases": 12, "runs": 5, "live": false}` | none | `docs/deployment.md` (procedure); local image `bolibench-demo:latest` | — (deployed, 3.7) |
| `render.yaml` | Blueprint schema | `render blueprints validate render.yaml` (Render CLI 2.28.0) | 2026-10-18, rerun after the tool-mode edit and before the deploy | offline | `"valid": true` | none | terminal | — (deployed, 3.7) |
| `.do/app.yaml` | App Spec | checked by hand against the App Spec reference; YAML parses | 2026-10-18 | offline | no machine validation (`doctl` not installed) | — | — | `doctl apps spec validate .do/app.yaml` if DO hosting is used (optional) |
| Hosted tool mode | `AGENT_TOOL_MODE` default for `gemma-4-31B-it` | DigitalOcean's model table lists Chat Completions but **not tool calling** for `gemma-4-31B-it` (audit worker, docs URLs in `docs/integrations/gemma-sentry.md`) | 2026-10-18 | offline | at `ace4e9f` both platform configs set `AGENT_TOOL_MODE=json`. Superseded in the working tree by the live-mode work: `render.yaml` now targets `gemma-4-31b-it` on the Gemini API with `AGENT_TOOL_MODE=native` and `AGENT_REASONING_EFFORT=minimal` (native tool calls verified there, 3.7); the DigitalOcean alternative keeps JSON mode | — | `render.yaml`, `.do/app.yaml`, `docs/deployment.md` | DigitalOcean: probe with a real key |
| Demo page + integrations panel | page explains BoliBench, the 12 cases against the 5 bundled runs, and an integrations panel from `demo/integrations.json` (`GET /api/integrations`; unknown status values stop the server at startup) | `uv run pytest -q tests/test_server.py` | 2026-10-18 | offline | 60 passed, with this report's statuses; 65 passed at 13:3x IST after the statuses were updated for 3.7 (13 entries) | none | `src/bolibench/server.py`, `demo/integrations.json`, `tests/test_server.py` | — |

### 3.5 Code audit against the official docs (offline)

Each integration's request and response handling was compared with the provider's docs (URLs in
`docs/integrations/*.md`) and run end to end against a local stub of the documented API.

| Integration | Result | Bugs fixed (with tests) | Only a live call can confirm |
|---|---|---|---|
| Sentry agent tracing | span ops, names and `gen_ai.*` attributes conform | **Privacy:** with the SDK's default local-variable capture, an error event from a failed model call carried the utterance, the system prompt and the `Authorization: Bearer <key>` header (the SDK's scrubber only caught a top-level `api_key` variable). Now `include_local_variables=False`. Model and tool exceptions are now captured as Sentry issues and tag the failing span with `error.type` | ingestion, how the AI Agents views show the spans, cost display for a non-OpenAI provider |
| ElevenLabs | TTS and STT requests conform | 422 validation errors (a list under `detail`) are parsed into a readable reason; the temp file is removed if a cache write fails; a voice id `..` is rejected (no path segment) | all three confirmed live on 2026-10-18 (3.7) |
| Backboard | `/threads/messages` fields are a subset of the documented request schema | tests tightened to the documented schemas; live (3.7): `--assistant-id` required and checked, tool outputs go to the run endpoint with `tools` resent, repeated call ids are not re-executed | confirmed live: `arguments` is a JSON string, `status` is on every non-streaming reply; `/threads/tool-outputs` drops the message's tools |
| OpenAI-compatible (DigitalOcean) | request shape conforms; `--base-url` must be https for a remote host | live on the Gemini API (3.7): `--reasoning-effort`, bounded retry on 429/5xx | DigitalOcean itself: that `gemma-4-31B-it` answers with the JSON tool format, cost per run |

### 3.6 Not testable here (no credentials)

Sentry (hosted; Nivara's DSN is deliberately not reused), MongoDB Atlas and Tiger Cloud (Nivara's
connection strings are deliberately not reused), DigitalOcean inference and App Platform (no key), a
paid Backboard model (free credit only), a .tech domain. Each stays out of "live (hosted)" until a
dedicated credential exists, the step in `docs/submission-checklist.md` has run, and its output is
added here. Credentials: `docs/credential-matrix.md`.

### 3.7 Live (hosted) results

| Integration | Date | Command | Result | Artifact / screenshot |
|---|---|---|---|---|
| Render deployment | 2026-10-18, created 11:10:22 IST, live 11:11:07 IST, smoke tests 11:11:56–11:12:06 IST | `render services create --type web_service --runtime docker --repo https://github.com/CodewithJha/bolibench --branch master --plan free --region singapore --health-check-path /health` plus the non-secret `envVars` of `render.yaml` (Render CLI 2.28.0); then the smoke tests below | URL https://bolibench-demo.onrender.com, service `srv-dba5nh5g1s2s73asmb5g`, plan **free**, region Singapore, commit **`ace4e9f`** (deploy `dep-dba5nhlg1s2s73asmd40`, build + deploy 45 s). `/health` 200 `{"status": "ok", "cases": 12, "runs": 5, "live": false}`. Every smoke test passed (below). Cold start not observed: after 28 minutes without public requests (11:12–11:40 IST) the instance had not spun down (Render's own `/health` checks kept arriving every ~5 s), and `/health` at 11:40:40 IST answered 200 in 0.65 s. Render documents that free instances spin down after 15 minutes idle; the first request after that is slow | Render logs (`render logs -r srv-dba5nh5g1s2s73asmb5g`): clean; this table. **Superseded**: this service is suspended on the old Render workspace (billing) and no longer used; see the next row |
| Render deployment, new workspace, live mode on: **PASS** | 2026-10-18, created 22:47:44 IST, live 22:48:36 IST, public checks 22:49:09–22:49:10 IST, live run 22:49:21–22:49:56 IST | Render REST API `POST /v1/services` (web service, runtime docker, `./Dockerfile`, plan free, region singapore, health check `/health`, auto-deploy on) with the non-secret `envVars` of `render.yaml`, `BOLIBENCH_CLIENT_IP_HEADER=True-Client-IP`, and the secrets `GEMINI_API_KEY` and `BOLIBENCH_DEMO_TOKEN` from the local `.env`; then the public checks and one `POST /api/live-run {"case_id": "cancel-single-order"}` with the demo token | URL https://bolibench-demo-1b3o.onrender.com (the bare `bolibench-demo` subdomain was taken), service `srv-dbafue7btjjs73f13di0`, plan **free**, region Singapore, commit **`3440507`** (deploy `dep-dbafuevbtjjs73f13gv0`, build + deploy 50 s). `/health` 200 `{"status": "ok", "cases": 12, "runs": 5, "live": true}`. Live run `f809fcb36f15f10e`: 202 then `done` after 35 s, verdict **pass** (all checks pass), agent `bolibench-example-ollama-agent` `19f1c48c71c3+gemma-4-31b-it+openai-native+reasoning-minimal`, 1 turn, 1 tool call `cancel_order {"order_id": "ORD-201"}` → `ok`, reply "Order ORD-201 has been successfully cancelled." | Render logs (REST `GET /v1/logs`): `live mode: on, agent http://127.0.0.1:8765/turn, daily cap 20, turn/run timeout 240/600s`; `POST /api/live-run` 202 at 17:19:21Z, the agent's `POST /turn` 200 at 17:19:56Z; no secret value, error or traceback in the logs; this table |
| ElevenLabs speech round-trip: **PASS** | 2026-10-18; run directories 07:00:49Z–07:03:03Z | `BOLIBENCH_LIVE=1 uv run pytest -q -s tests/test_speech.py -k live`; `bolibench run` on `awadhi-cancel-yesterday`, `codeswitch-cancel-kurta`, `similar-items-kurta-kurti` with `--scripts --speech elevenlabs --speech-audio-dir` (twice), then with the local `qwen3:8b` example agent with speech and without | Free tier, voice Sarah (verified `hi-IN`), `eleven_multilingual_v2` TTS, `scribe_v2` STT. Live test `1 passed`. Scripted 3/3 pass on both runs; the rerun had `tts_s: null` (cache hit) and identical transcripts. Local agent: speech 1 pass / 2 fail, text-only 0 / 3; the fails are the agent's, not speech's (doc). 239 TTS characters. QA re-check: 3 mp3s in the cache; every speech turn's `audio_sha256` and `audio_bytes` match a cached file, and `asr_text` equals `speech.transcript.text` | `docs/integrations/elevenlabs.md` "Verified results"; `runs/elevenlabs-{audio,scripted,qwen3-8b,qwen3-8b-text-baseline}-2026-10-18/` |
| Gemma 4 (`gemma-4-31b-it`) on Google's Gemini API: **PASS** | 2026-10-18, 07:12:31–07:33:29Z | `examples/ollama_agent.py --backend openai --base-url https://generativelanguage.googleapis.com/v1beta/openai --api-key-env GEMINI_API_KEY --model gemma-4-31b-it --tool-mode native --reasoning-effort minimal`; `bolibench run suites/orders --timeout 180` | One unseeded full-suite run: **8 pass / 3 fail / 1 error**, agent `19f1c48c71c3+gemma-4-31b-it+openai-native+reasoning-minimal`. The error is `tool-failure-cancel`: correct calls (injected failure, then a successful retry), reply 4 s after the 180 s deadline. `agent.log`: 18 HTTP 500s, all recovered by the bounded retry, 0 tracebacks. QA re-check: `summary.json` matches the 12 artifacts; 13 turns, 22 tool calls, 0 rejected, 0 refused, no `<thought` in any turn; re-evaluating with the current evaluator reproduces every verdict. Hosted by Google, not DigitalOcean | `docs/audits/gemma4-gemini-api-2026-10-18.md`; `runs/gemma4-gemma-4-31b-it-gemini-api-2026-10-18/20261018T071231Z-249abfa4/` |
| Backboard bridge: **PARTIAL** | 2026-10-18, 07:01–07:14Z | `examples/backboard_agent.py --assistant-id <bolibench-agent> --provider openrouter --model <model>`; `bolibench run` on single cases | Auth, model list, assistant and thread, tool-call round trip (after two live-found bridge fixes) and memory isolation: pass. Chosen open-weight `qwen/qwen3-235b-a22b-2507`: **blocked**, the free credit does not pay for LLM chat (1 case, `error`). Free preview `dots-studio/dots-3-note-preview:free`, fixed bridge: 3 pass / 1 fail of 4 cases (`cancel-single-order`, `tool-failure-cancel`, `codeswitch-cancel-kurta` pass; `ambiguous-previous-order` fail on `ask_policy`); before the fix, 0 / 4 (later calls arrived as text). QA re-check: every verdict and tool-call list matches the audit, and `ab.txt` shows 2 of 2 text-only vs 2 of 2 structured | `docs/audits/backboard-2026-10-18.md`; `runs/backboard-*-2026-10-18/` |

Render deployment details:

- Created with the CLI, not as a Blueprint instance (the CLI has no Blueprint-launch command), so
  `render.yaml` is not synced to the service: later Blueprint edits must be mirrored in the
  dashboard. Auto-deploy on commit is on. `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN` are not set,
  so the demo is read-only and live mode reports itself off.
- Startup log: `live mode: no hosted agent ...`, `bolibench demo on http://0.0.0.0:10000 (12 cases)`,
  `live mode: off (...)`, then `==> Your service is live`. No errors or tracebacks; Render's health
  checks on `/health` return 200.
- Smoke tests (`BASE=https://bolibench-demo.onrender.com`, one request each):

| Request | Status | Body (excerpt) |
|---|---|---|
| `GET /` | 200 | HTML: the 5 run labels as columns, the 12 cases as rows with linked verdicts, per-run pass totals, the Integrations panel, the evaluator form; the live section says it needs the demo owner's token. Columns are labelled "bundled runs", "single unseeded run", "judged when the run was made". Headers: `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'`, `X-Content-Type-Options: nosniff` |
| `GET /health` | 200 | `{"status": "ok", "cases": 12, "runs": 5, "live": false}` |
| `GET /api/cases` | 200 | 12 cases |
| `GET /api/runs` | 200 | 5 bundles; counts equal each `demo/runs/*/summary.json`: baseline 3/9/0, v2 6/6/0, v3 6/6/0, gemma3:4b 2/10/0, Mastra 6/6/0 (pass/fail/error) |
| `GET /api/runs/qwen3-8b-agent-v2-2026-10-17/ambiguous-previous-order` | 200 | the bundled artifact, verdict `fail` |
| `GET /api/integrations` | 200 | 12 integrations, `as_of` 2026-10-18 (as deployed from `ace4e9f`, i.e. before this row) |
| `GET /api/live-runs` | 200 | `{"enabled": false, "reason": "live mode is disabled on this deployment: ...", "runs": []}` |
| `POST /api/evaluate`, `demo/example-request.json` | 200 | verdict `pass`, no classifications |
| `POST /api/evaluate`, same script cancelling `ORD-102` (the newer order) | 200 | verdict `fail`, `entity_resolution` |
| `POST /api/evaluate`, truncated JSON | 400 | `{"error": "invalid request", "details": [{"loc": [], "msg": "Invalid JSON: EOF while parsing a value ..."}]}` |
| `POST /api/evaluate`, 40 000-byte body | 413 | `{"error": "body exceeds 32768 bytes"}` |
| `POST /api/evaluate` with `agent_url` | 400 | `{"error": "agent_url is refused: ..."}` |
| `GET --path-as-is /api/runs/../../pyproject.toml` | 404 | `{"error": "not found"}` |
| `GET --path-as-is /api/runs/%2e%2e/%2e%2e/etc/passwd` | 404 | `{"error": "not found"}` |
| `GET /nope` | 404 | `{"error": "not found"}` |
| `POST /api/live-run`, no token | 404 | `{"error": "live mode is disabled on this deployment: no hosted agent or no demo token is configured"}` |

  No response body or header contains `/Users/`, `/home/`, `/app/`, `Traceback`, `KEY`, `TOKEN` or a
  bearer value; the only addresses are the bundled runs' local agent URLs (`http://127.0.0.1:...`).
  Response time warm: 0.26–2.3 s from India.
- Re-checked about 13:25 IST: `/health` `{"status": "ok", "cases": 12, "runs": 5, "live": false}`,
  `/api/live-runs` `enabled: false`. Hosted live mode is still in progress. The deployed
  `/api/integrations` is still the `ace4e9f` copy, so it shows ElevenLabs and Backboard as
  `offline-tested` until the next deploy.

Render deployment on the new workspace (2026-10-18, IST):

- The first service above was suspended on its Render workspace (billing). A new Render account
  (workspace `tea-dbafs16i0phs739rdj1g`) got GitHub access to the repo, and the service was created
  there with the REST API (not as a Blueprint instance, so `render.yaml` is not synced). Free plan;
  no payment was requested.
- Startup log: `bolibench demo on http://0.0.0.0:10000 (12 cases)`, `live mode: on, agent
  http://127.0.0.1:8765/turn, daily cap 20, turn/run timeout 240/600s`, `==> Your service is live`.
  Two `HEAD /` probes during startup (one 501 before the server was ready, then 200) are Render's.
- Public checks (`BASE=https://bolibench-demo-1b3o.onrender.com`, one request each, warm, 0.2–0.4 s):

| Request | Status | Body (excerpt) |
|---|---|---|
| `GET /health` | 200 | `{"status": "ok", "cases": 12, "runs": 5, "live": true}` |
| `GET /` | 200 | HTML demo page (26.6 kB) |
| `GET /api/integrations` | 200 | 13 integrations, `as_of` 2026-10-18 |
| `GET /api/cases` | 200 | 12 cases |
| `GET /api/runs` | 200 | 5 bundles |
| `POST /api/evaluate`, `demo/example-request.json` | 200 | verdict `pass` |
| `POST /api/live-run`, no token | 401 | `{"error": "a valid Authorization: Bearer <demo token> header is required"}` |
| `POST /api/live-run`, wrong token | 401 | same |
| `POST /api/live-run` `cancel-single-order`, demo token | 202 | `{"run_id": "f809fcb36f15f10e", "status": "queued"}`; polled `GET /api/live-runs/f809fcb36f15f10e` every 5 s: `running` ×6, then `done`, verdict `pass` |
| `GET /api/live-runs` after the run | 200 | `enabled: true`, `daily_cap: 20`, `runs_today: 1` |

  No response body or log line contains a value from the local `.env`, `/Users/`, `/home/`, `/app/`,
  `Traceback`, or a key prefix. The server does not log the agent's outbound call to the Gemini API;
  the evidence of a real provider call is the agent's self-reported `gemma-4-31b-it+openai-native`
  identity, the 35 s turn (the agent's `POST /turn` in the logs), and a natural-language reply with the
  correct tool call. One live run was made.

### 3.8 Benchmark audit and independent QA (offline)

| Item | What | Command / procedure | Date | Mode | Result | Artifact |
|---|---|---|---|---|---|---|
| Benchmark audit | cases, evaluator, sandbox | `docs/benchmark-audit.md` | 2026-10-18 | offline | Fixed 2 classifier defects (D1: a correct required call blamed as `tool_selection`; D2: a wrong-tool call given 2 categories); every case now pins `status` and `quantity` of every order (D3); rule change R1: under `exclusive_actions`, calling a tool name the sandbox does not register is a forbidden attempt (`tool_selection`, certain). No expectation was loosened | `docs/benchmark-audit.md`, `tests/test_adversarial.py` |
| Mutation checks | do the tests catch evaluator regressions? | 10 mutations applied one at a time to a scratch copy under `/tmp` (the repo was not edited), then `pytest` on the evaluator, adversarial, suite and adapter tests | 2026-10-18 | offline | **10 of 10 caught.** Reverting R1, D1 or D2; forbidden matches counted only when `ok`; required actions satisfied by any status; same-turn asks allowed; hidden calls passing `required_actions`; `max_attempts` off by one; `exclusive_actions` ignoring rejected calls; and a wrong Kurti expectation each failed 1–9 tests. The "forbidden at any status" rule is caught by one unit test only, not by an adversarial test | QA scratch, not kept |
| Historical re-evaluation | do stored verdicts still hold under the current evaluator and suite? | every artifact in `runs/` and `demo/runs/` loaded and re-evaluated in memory; nothing written | 2026-10-18 | offline | **201 artifacts: 0 verdict changes, 0 check changes, 2 classification changes**: `qwen3-8b-baseline-2026-10-17` `recovery-after-failed-cancel` (the `runs/` copy and the `demo/runs/` copy) loses a `tool_selection` label (it cited the correct cancel). Every `summary.json` matches its artifacts. The demo page shows the stored classification, labelled "judged when the run was made" | — |
| Suite pins | spot check | `correction-quantity`, `recovery-after-failed-cancel`, `similar-sellers-mohan-sohan`, `ambiguous-previous-order` pins read against the utterances and the sandbox's effects | 2026-10-18 | offline | all correct | — |
| Secrets | repo scan | `.env` is git-ignored and untracked; a pattern scan (API key, token, DSN and connection-string shapes) of tracked and untracked files outside `.venv`, `node_modules` and `runs` | 2026-10-18 | offline | only placeholders (`<password>`, `<secret>`) and test fixtures; no key value in any doc | — |
