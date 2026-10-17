# Optional integrations

BoliBench's core (`validate`, `review-sheet`, `run --scripts`, `run --agent-url`) needs no service, no
key and no dependency beyond pydantic. Everything below is opt-in and runs only when invoked. The
evaluator is the same everywhere; no integration changes a verdict.

| Integration | Entry point | Install | Status | Doc |
|---|---|---|---|---|
| ElevenLabs speech round-trip | `bolibench run --speech elevenlabs [--speech-audio-dir DIR]` | none (stdlib) | offline-tested (fakes, local stub); no live call yet | [elevenlabs.md](integrations/elevenlabs.md) |
| Public demo + live runs | `bolibench serve`, `Dockerfile`, `render.yaml`, `.do/app.yaml` | none (stdlib) | offline-tested; not deployed | [deployment.md](deployment.md) |
| MongoDB Atlas export | `bolibench export --to mongo ...` | `--extra mongo` | offline-tested (dry run, fakes); live test opt-in, not run | [mongodb-atlas.md](integrations/mongodb-atlas.md) |
| Tiger Data export + similar failures | `bolibench export --to tiger ...` | `--extra tiger` (+ local Ollama for `--failures`/`--similar`) | offline-tested (dry run, fakes); live test opt-in, not run | [tiger-data.md](integrations/tiger-data.md) |
| Temporal durable runs | `python -m bolibench.temporal_run worker\|start` | `--extra temporal` | tested on temporalio's local test server; not on Temporal Cloud | [temporal.md](integrations/temporal.md) |
| OpenAI-compatible backend (DigitalOcean Gemma) + Sentry tracing | `examples/ollama_agent.py --backend openai`, `SENTRY_DSN` | `--extra sentry` (tracing only) | offline-tested (in-memory Sentry transport); no live DSN or hosted endpoint used | [gemma-sentry.md](integrations/gemma-sentry.md), [audit](audits/gemma-gemma3-4b-2026-10-17.md) |
| Mastra framework agent | `examples/mastra-agent` (`npm start`) | `npm install` | `npm test` offline; one real full-suite run on local `qwen3:8b` | [mastra.md](integrations/mastra.md) |
| Backboard bridge | `examples/backboard_agent.py` | none (stdlib) | offline stub only | [backboard.md](integrations/backboard.md) |

`uv sync --extra all` installs every Python extra. Without an extra, the matching command exits with
an error naming it; nothing else imports the drivers.

## Environment variables

Read from the environment only; BoliBench never reads `.env` files. `.env.example` has placeholders.
Secrets are never written to artifacts, logs or error messages.

| Variable | Provider | Required? | Where read |
|---|---|---|---|
| `ELEVENLABS_API_KEY` (secret) | ElevenLabs | for `--speech elevenlabs` | `speech.elevenlabs_from_env` |
| `ELEVENLABS_VOICE_ID` | ElevenLabs | for `--speech elevenlabs` | same |
| `ELEVENLABS_TTS_MODEL`, `ELEVENLABS_STT_MODEL`, `ELEVENLABS_STT_LANGUAGE`, `ELEVENLABS_BASE_URL` | ElevenLabs | no | same |
| `MONGODB_URI` (secret) | MongoDB Atlas | for a non-dry-run export | `export_mongo.main` |
| `MONGODB_DB` | MongoDB Atlas | no (`bolibench`) | same |
| `TIGER_DATABASE_URL` (secret) | Tiger Data | for a non-dry-run export | `export_tiger.main` |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE` | Temporal | no (`localhost:7233`, `default`) | temporalio `ClientConfig` in `temporal_run.connect` |
| `TEMPORAL_API_KEY` (secret) | Temporal Cloud | for Cloud | same |
| `TEMPORAL_TASK_QUEUE` | Temporal | no (`bolibench`) | `temporal_run.main` |
| `SENTRY_DSN` (secret) | Sentry | to enable tracing | `examples/ollama_agent.py` `init_sentry` |
| `SENTRY_TRACES_SAMPLE_RATE` | Sentry | no (`1.0`) | same |
| `BACKBOARD_API_KEY` (secret) | Backboard | for the bridge | `examples/backboard_agent.py` |
| `MODEL_ACCESS_KEY` (secret; any name, see `AGENT_API_KEY_ENV`) | DigitalOcean Gradient serverless inference | for live mode | the agent's `--api-key-env` (`examples/ollama_agent.py`) |
| `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY_ENV` | demo deploy | for live mode | `deploy/start.sh` |
| `AGENT_TOOL_MODE` | demo deploy | no (`native`) | `deploy/start.sh` |
| `BOLIBENCH_DEMO_TOKEN` (secret) | demo server | for live mode | `server.main` |
| `BOLIBENCH_LIVE_AGENT_URL` | demo server | set by `deploy/start.sh` | `server.main` |
| `BOLIBENCH_LIVE_DAILY_CAP`, `BOLIBENCH_LIVE_TURN_TIMEOUT` | demo server | no (`50`, `40`) | `server.main` |
| `BOLIBENCH_CLIENT_IP_HEADER` | demo server | only behind a proxy that sets it | `server.main` |
| `BOLIBENCH_SUITE`, `BOLIBENCH_DEMO`, `HOST`, `PORT` | demo server | no (`suites/orders`, `demo`, `127.0.0.1`, `8080`) | `server.main` |
| `MODEL`, `OLLAMA_BASE_URL`, `PORT`, `TURN_TIMEOUT_S` | Mastra example | no | `examples/mastra-agent/src/server.ts` |
| `BOLIBENCH_LIVE` | tests | no; `1` opts in to live tests (real calls, may cost money) | `tests/test_speech.py`, `tests/test_export.py` |

## How to verify each

- Offline, everything at once: `uv run pytest -q` (extras' tests skip), then
  `uv run --with 'sentry-sdk>=2.64' --with pymongo --with 'psycopg[binary]' --with temporalio pytest -q`.
- Speech: `BOLIBENCH_LIVE=1 uv run pytest -q -s tests/test_speech.py -k live`, then one CLI case with
  `--speech elevenlabs --speech-audio-dir audio-cache`; see "Live verification" in the doc.
- Exports: `bolibench export --to mongo --dry-run <run dir>` (no network), then the opt-in live tests
  `BOLIBENCH_LIVE=1 ... pytest tests/test_export.py -k live_mongo` / `-k live_tiger`.
- Temporal: `temporal server start-dev`, a worker, and `start --workflow-id demo-1`; its `summary.json`
  must equal `bolibench run`'s on the same inputs.
- Demo: `bolibench serve`, then `curl` `/health`, `/api/runs` and the checks in "Verify a deployment".
- Hosted model: the tool-calling probe in docs/deployment.md before enabling live mode (fall back to
  `AGENT_TOOL_MODE=json` if it returns no `tool_calls`).
- Mastra: `cd examples/mastra-agent && npm test`.
- Secrets: after any live run, `rg "$THE_KEY" runs/ audio-cache/` must find nothing.

## Rotating keys

Each provider's doc has the exact steps. In general: create the new key in the provider's dashboard,
replace the variable in your shell or the platform's secret store (Render/DigitalOcean redeploy on
save), then delete the old key. BoliBench never stores or caches keys (cached audio does not depend
on the key), so nothing else needs cleaning. If a key may have leaked, delete it first, and prefer
keys scoped to the needed endpoints with a spending quota.
