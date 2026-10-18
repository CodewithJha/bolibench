# Credential matrix

Names and status only: no secret values appear here or anywhere in the repo. Values live in the
git-ignored local `.env` (mode 600) and, for live mode, in the platform's secret store.

Source checked: the owner's Render service `nivara` (`srv-db165qlg1s2s738ofgfg`, repo
`CodewithJha/nivara`), read-only, with the owner's authorization. Nivara has no linked environment
groups and no secret files. Nothing on Nivara or on the BoliBench Render service was changed.

Checked 2026-10-18; "Real feature verified?" updated about 13:30 IST from the live runs.

## Nivara env var names, classified

| Nivara name | Class | Used by BoliBench? |
| --- | --- | --- |
| `ELEVENLABS_API_KEY` | API credential (account-level, permission-scoped key) | yes, copied |
| `BACKBOARD_API_KEY` | API credential (account-level) | yes, copied |
| `GEMINI_API_KEY` | model provider key (Google Gemini API, OpenAI-compatible endpoint) | optional, copied |
| `SENTRY_DSN` | observability, project-specific | not copied, see risks |
| `MONGODB_URI` | DB connection string, data-bearing | not copied, see risks |
| `TIGER_DATABASE_URL` | DB connection string, data-bearing | not copied, see risks |
| `SERPAPI_API_KEY` | API credential | no (BoliBench has no SerpAPI use) |
| `MONGODB_DB` | public config (Nivara's database name) | no |
| `LLM_PROVIDER`, `FORECAST_MODE` | Nivara-specific app config | no |
| `LOG_LEVEL`, `NODE_ENV`, `NODE_VERSION` | public runtime config | no |

## Matrix

| Provider | BoliBench env var(s) | Nivara match | Reuse decision + reason | In BoliBench `.env`? | Auth smoke result | Real feature verified? | Needs user action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DigitalOcean Gradient serverless inference | `MODEL_ACCESS_KEY` (+ `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY_ENV`) | none | nothing to reuse | no | not run (no key) | no | **yes: create a Model Access Key** |
| ElevenLabs | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | `ELEVENLABS_API_KEY` | reused: account-level key, not tied to Nivara data | key yes; the voice id is a public premade id (Sarah, `EXAVITQu4vr4xnSDxMaL`), not a secret | `GET /v1/user/subscription` 200 (free tier, 2,272 / 10,000 characters used before the live run, 2,541 after); `GET /v1/voices` 200 (21 premade voices); `GET /v1/models` 401, because the key lacks the `models_read` permission (BoliBench doesn't use it) | **yes** (2026-10-18): TTS, STT, live test, CLI with cache, 3-case end-to-end run (`docs/integrations/elevenlabs.md`) | none |
| Backboard | `BACKBOARD_API_KEY` (+ `--assistant-id` of a `bolibench-*` assistant) | `BACKBOARD_API_KEY` | reused: account-level key. The account also holds 9 assistants of other apps; the bridge refuses any assistant not named `bolibench-*` | yes | `GET /api/assistants` 200; `GET /billing/balance` 200 (free credit only) | **partial** (2026-10-18, `docs/audits/backboard-2026-10-18.md`): round trip and memory isolation pass; chat on paid models refused because free credit is reserved for Memory & RAG | **yes, for paid chat**: add credit or a subscription |
| Google Gemini API (OpenAI-compatible, open-weight Gemma) | `GEMINI_API_KEY` as `AGENT_API_KEY_ENV`; `AGENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`; `AGENT_MODEL=gemma-4-31b-it`; `AGENT_REASONING_EFFORT=minimal` | `GEMINI_API_KEY` | reused as an open-weight backend: account-level key | yes | `GET /models` 200 (63 models; open-weight: `gemma-4-31b-it`, `gemma-4-26b-a4b-it`); early probes saw sporadic HTTP 500s, which succeed on retry | **yes** (2026-10-18): `gemma-4-31b-it` native tool calls with `reasoning_effort` `minimal`, full suite 8 pass / 3 fail / 1 error (`docs/audits/gemma4-gemini-api-2026-10-18.md`) | none. Not a sponsor backend: it is Gemma evidence, not DigitalOcean evidence |
| Sentry | `SENTRY_DSN` | `SENTRY_DSN` | **not reused**: a DSN is project-specific, so BoliBench events would land in Nivara's Sentry project | no | not run | no | **yes: create a BoliBench Sentry project and DSN** |
| MongoDB Atlas | `MONGODB_URI`, `MONGODB_DB` | `MONGODB_URI` | **not reused**: same cluster and credential as Nivara's data (risks below) | no | not run | no (local MongoDB only) | **yes: create a dedicated cluster or a user scoped to `bolibench`** |
| Tiger Data | `TIGER_DATABASE_URL` | `TIGER_DATABASE_URL` | **not reused**: same database as Nivara (risks below) | no | not run | no (local TimescaleDB only) | **yes: create a dedicated Tiger Cloud service** |
| Temporal | `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY` | none | nothing to reuse | no | not run | no | yes, if Temporal Cloud is wanted (local dev server needs no credential) |

`ELEVENLABS_API_KEY` matches ElevenLabs' documented key format. `GEMINI_API_KEY` does not match the
classic `AIza…` format but authenticates. Backboard publishes no key format.

## Risks of reusing Nivara's credentials (why these are not reused)

- **Sentry DSN.** Reusing Nivara's DSN mixes BoliBench errors and traces into Nivara's project,
  issue alerts, and quota. Recommended: a dedicated BoliBench Python project and DSN.
- **MongoDB URI.** BoliBench writes to database `MONGODB_DB` (default `bolibench`) via upserts, so
  it would not touch Nivara's database if `MONGODB_DB` is set correctly. But the credential has
  Nivara's rights: a wrong `MONGODB_DB` would write into Nivara's data. A free M0 cluster also shares
  one 512 MB storage limit. Acceptable only with `MONGODB_DB=bolibench` pinned; a dedicated database
  user restricted to the `bolibench` database is safer.
- **Tiger URL.** `bolibench export --to tiger` runs `CREATE EXTENSION IF NOT EXISTS vector`, which
  changes the whole database, and creates `bolibench_case_results` (a hypertable) and
  `bolibench_failures` in the default schema of Nivara's database. The names don't collide today,
  but the database is shared. Recommended: a separate Tiger service, or at minimum a separate
  role/schema.

## New credentials still needed: official dashboard steps

- **DigitalOcean (required for live mode).** cloud.digitalocean.com → Inference (Agent Platform /
  Serverless Inference) → Model Access Keys → Create key. Then set `MODEL_ACCESS_KEY`. Pay-per-token;
  the account needs a payment method. Next worker: `GET https://inference.do-ai.run/v1/models` to
  confirm the exact Gemma id (`.env.example` assumes `gemma-4-31B-it`) and probe native tool calls.
- **Sentry.** sentry.io → Projects → Create Project → Python → copy the DSN into `SENTRY_DSN`. The
  free Developer plan covers this.
- **ElevenLabs.** Not needed: the reused key did TTS and STT live on 2026-10-18. For a separate
  BoliBench key: elevenlabs.io → Profile / Developers → API Keys → create a key with Text to Speech,
  Speech to Text, and Voices read permissions. Free tier: 10,000 characters/month, premade voices
  only via the API.
- **MongoDB Atlas (if not sharing Nivara's).** cloud.mongodb.com → create a free M0 cluster →
  Database Access: add a user (scope it to the `bolibench` database) → Network Access: allow the
  deploy's egress IPs (Render free services have no static IP, so likely `0.0.0.0/0`) → Connect →
  Drivers → copy the `mongodb+srv` URI. M0 is free.
- **Tiger Cloud (if not sharing Nivara's).** console.cloud.timescale.com → Create service (free
  tier/trial) → copy the connection string into `TIGER_DATABASE_URL` (`sslmode=require`).
- **Backboard.** The reused key works, but the account's free credit cannot pay for LLM chat, so
  running a paid open-weight model needs credit or a subscription on app.backboard.io → Billing. If
  you want a separate key: app.backboard.io → API keys.
- **Temporal Cloud (optional).** cloud.temporal.io → Namespaces → Create (API-key auth) → Settings →
  API Keys → create. Set `TEMPORAL_ADDRESS` (the namespace's gRPC endpoint), `TEMPORAL_NAMESPACE`,
  and `TEMPORAL_API_KEY`. Trial credits first, paid afterward; the local `temporal server start-dev`
  needs no credential.
