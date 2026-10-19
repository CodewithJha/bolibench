# Public demo deployment

One container, two processes, started by `deploy/start.sh`:

- `src/bolibench/server.py`: a small stdlib HTTP server (no web framework, no extra dependency) with
  the suite, bundled run artifacts, a scripted-harness evaluator, and live mode.
- Live mode only: `examples/ollama_agent.py` on 127.0.0.1, backed by an open-weight model on an
  OpenAI-compatible endpoint: Gemma 4 (`gemma-4-31b-it`) on Google's Gemini API in `render.yaml`,
  DigitalOcean serverless inference as the alternative. A token-authenticated request queues one suite
  case (202 at once); a background thread runs it through the agent with the regular webhook adapter:
  the agent's tool calls go through BoliBench's gateway into its sandbox, and the evaluator judges the
  recorded calls and final state. The caller polls `GET /api/live-runs/<run_id>`.

Why async: a hosted-model turn can take up to ~180 s (provider latency plus the agent's retries on
429/5xx), and Render's proxy cuts a request at about 100 s, so a synchronous request could not return
a slow run's result.

The demo is live on Render's free plan at https://bolibench-demo-1b3o.onrender.com (service
`srv-dbafue7btjjs73f13di0`, region Singapore, created on 2026-10-18 with Render's REST API
`POST /v1/services`, so `render.yaml` changes are not synced automatically) with token-gated live mode on
(Gemma 4 `gemma-4-31b-it` on the Gemini API); no domain is registered. Render added the `-1b3o` suffix
because `bolibench-demo.onrender.com` was taken. The earlier read-only service
(`srv-dba5nh5g1s2s73asmb5g`, https://bolibench-demo.onrender.com) is suspended on an old Render workspace
(billing) and no longer used. Render is the primary target.
The DigitalOcean App Platform spec is an optional alternative: maintaining both is not required.

Checked locally on 2026-10-18: `docker build` then `docker run --read-only -p 10000:10000 -e PORT=10000`
with no other configuration starts as `nobody` (uid 65534) with live mode off, and every endpoint below
answers; the image is about 218 MB unpacked (47 MB compressed). `render blueprints validate render.yaml`
(Render CLI 2.28) reports it valid.

## What it serves

| Endpoint | What |
|---|---|
| `GET /` | HTML page: what BoliBench evaluates, the cases (id, tags, first user turn) against the bundled runs (verdict + failure classifications, each linked to its artifact, pass totals per run), the integrations panel, a form that posts a script to `/api/evaluate`, and the live section (status, token form, recent live runs). No external JS or CSS |
| `GET /health` | `{"status": "ok", "cases": N, "runs": N, "live": bool}` |
| `GET /api/integrations` | `demo/integrations.json`, as validated at startup (see below) |
| `GET /api/cases` | Every suite case, whole: turns, context, `initial_state` and `expected`. The benchmark is open source, so the gold expectations are already public; a script author needs the order ids anyway |
| `GET /api/runs` | Bundled runs: label, source dir, date, model, agent identity/hash, note, plus `config_id`, `total`, `counts`, per-case verdicts and adapter infos from each run's `summary.json` |
| `GET /api/runs/<label>/<case_id>` | One artifact (`{schema_version, case_id, run, evaluation}`), as bundled |
| `POST /api/evaluate` | Body `{"case_id": ..., "script": [[step, ...], ...]}`; a script is the same one `bolibench run --scripts` takes. It replays against a fresh in-memory sandbox, then the real evaluator runs. Returns an artifact |
| `POST /api/live-run` | Live mode. Header `Authorization: Bearer <BOLIBENCH_DEMO_TOKEN>`, body `{"case_id": ...}`. Queues that case against the hosted agent and answers at once: `202 {"run_id": ..., "status": "queued"}` with a `Location: /api/live-runs/<run_id>` header. 401 bad token, 404 unknown case or live mode off, 503 (`Retry-After: 30`) while another run is in progress, 429 daily cap or rate limit |
| `GET /api/live-runs/<run_id>` | One live run: `{run_id, status, case_id, queued_at, started_at, finished_at}`. `status` is `queued`, `running`, `done` (plus `verdict`, `agent` = the agent's self-reported identity, i.e. file hash + model + backend + tool mode + reasoning effort, and the full `artifact`) or `error` (plus `error`, e.g. the run deadline was exceeded; no artifact). Public: it holds no secrets. 404 once the run is no longer kept |
| `GET /api/live-runs` | Live mode status (`enabled`, or the reason it is off), `busy`, `daily_cap`, `runs_today`, `turn_timeout_s`, `run_timeout_s`, and the last 20 live runs in any status (same shape as above), newest first |

Try it: `curl -s -X POST --data-binary @demo/example-request.json http://127.0.0.1:8080/api/evaluate`.

Every bundled GET body is built once at startup and served from memory by exact path, so no request
reads a file (path traversal has nothing to reach). If a bundled file is inconsistent (artifacts not
matching `summary.json`, a schema change) the server refuses to start. Absolute paths in bundled JSON
(a string value that is an absolute path, e.g. a scripted run's `config.script`) are replaced by
their file name in the response; the bundled files themselves are verbatim copies.

### `demo/integrations.json`

The integrations panel and `GET /api/integrations` come from this static file, hand-maintained:

```json
{"as_of": "2026-10-18", "integrations": [
  {"name": "Mastra agent", "category": "agent framework", "status": "local",
   "evidence": "demo/runs/mastra-qwen3-8b-2026-10-17, docs/integrations/mastra.md", "note": "..."}]}
```

`status` is the highest level actually reached, one of (`STATUSES` in `src/bolibench/server.py`, also
the page legend): `deployed` (exercised by this deployed app), `hosted-api` (a real hosted provider API,
called from a laptop; not in the deployed app), `local` (real software or models run on a laptop; not in
the deployed app), `partial` (real calls work, but the intended setup could not run in full), `offline`
(checked only against fakes, stubs or in-memory transports), `implemented` (code in the repo, not
exercised) or `blocked` (a credential or account is missing). Only `deployed` rows count as exercised
by the deployed app. Raise it only with evidence in the repo, name that evidence (repo-relative paths) in `evidence`, and bump
`as_of`. Any other status or a missing/extra field stops the server at startup;
`uv run pytest -q tests/test_server.py` checks the file.

Live results are honest: an agent that is down, times out or replies badly gives an `error` verdict,
a wrong action a `fail`; a run past the whole-run deadline ends as status `error` with no verdict;
every run is listed, whatever its outcome. Live mode off means the endpoint says so (404 with the
reason); nothing is simulated.

## Run locally

```sh
uv run bolibench serve                     # http://127.0.0.1:8080, run from the repo root (= python -m bolibench.server)
docker build -t bolibench-demo . && docker run --rm -p 8080:8080 bolibench-demo
```

Live mode locally, against the example agent on Ollama (`--backend ollama` is the agent's default):

```sh
python examples/ollama_agent.py --model qwen3:8b --port 8765 &
BOLIBENCH_DEMO_TOKEN=$(openssl rand -hex 24) BOLIBENCH_LIVE_AGENT_URL=http://127.0.0.1:8765/turn \
    uv run python -m bolibench.server
```

Or exactly what the container runs, against Gemma 4 on the Gemini API (`GEMINI_API_KEY` in the
git-ignored `.env`; a local-only throwaway token):

```sh
(set -a; . ./.env; set +a
 export AGENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai AGENT_MODEL=gemma-4-31b-it \
     AGENT_API_KEY_ENV=GEMINI_API_KEY AGENT_TOOL_MODE=native AGENT_REASONING_EFFORT=minimal \
     BOLIBENCH_DEMO_TOKEN=local-only-token-0123456789 PORT=8080 HOST=127.0.0.1
 uv run sh deploy/start.sh)
# another terminal: queue a run, then poll the Location it returns
curl -si -X POST -H "Authorization: Bearer local-only-token-0123456789" -d '{"case_id": "cancel-single-order"}' \
    http://127.0.0.1:8080/api/live-run
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | Listen port. Render sets `10000`; DigitalOcean sets it to `http_port` |
| `HOST` | `127.0.0.1`, or `0.0.0.0` when `PORT` is set | Bind address. The Docker image sets `0.0.0.0` |
| `BOLIBENCH_CLIENT_IP_HEADER` | unset (use the socket peer) | Header holding the real client IP, for the rate limiter. Render: `True-Client-IP`. DigitalOcean: `do-connecting-ip`. Do not set it when the server is reachable directly: clients could then pick their own rate-limit key |
| `BOLIBENCH_SUITE` | `suites/orders` | Suite directory, relative to the working directory |
| `BOLIBENCH_DEMO` | `demo` | Bundle directory (`runs/index.json`, `runs/<label>/`, `example-request.json`) |
| `AGENT_BASE_URL` | unset | Live: OpenAI-compatible base URL (the agent's `--base-url`). Gemini: `https://generativelanguage.googleapis.com/v1beta/openai`; DigitalOcean: `https://inference.do-ai.run/v1` |
| `AGENT_MODEL` | unset | Live: model id (`--model`). Gemini: `gemma-4-31b-it` (`render.yaml`); DigitalOcean: `gemma-4-31B-it` (`.do/app.yaml`) |
| `AGENT_API_KEY_ENV` | unset | Live: the *name* of the variable that holds the key (`--api-key-env`): `GEMINI_API_KEY` or `MODEL_ACCESS_KEY` |
| `GEMINI_API_KEY` / `MODEL_ACCESS_KEY` (the name above) | unset | Live, secret: the model key. Only the agent process sees it |
| `AGENT_TOOL_MODE` | `native` | Live: `--tool-mode`. Gemini: `native` (tool calls verified, see below). DigitalOcean: `json`, since its model table does not list tool calling for `gemma-4-31B-it`; set `native` only if the probe below returns `tool_calls` |
| `AGENT_REASONING_EFFORT` | unset (not passed) | Live: `--reasoning-effort`, sent as `reasoning_effort`. Gemini: `minimal`, otherwise Gemma 4 puts `<thought>...</thought>` into its reply. Leave unset for DigitalOcean |
| `BOLIBENCH_DEMO_TOKEN` | unset | Live, secret: bearer token for `POST /api/live-run`, at least 16 characters. Only the server process sees it |
| `BOLIBENCH_LIVE_DAILY_CAP` | `50` (`20` in both platform configs) | Live runs per UTC day, whole server |
| `BOLIBENCH_LIVE_TURN_TIMEOUT` | `240` | Seconds per turn (0-600), the webhook adapter's turn deadline. A hosted-model turn with the agent's retries can take ~180 s |
| `BOLIBENCH_LIVE_RUN_TIMEOUT` | `600` | Seconds per whole run (0-3600). Past it the run is reported as status `error`; the run slot stays busy until the abandoned turn hits its turn deadline |
| `BOLIBENCH_LIVE_AGENT_URL` | set by `start.sh` | Fixed agent URL, `http://127.0.0.1:8765/turn`; must be localhost. Never taken from a request |

Live mode is on only when `start.sh` started the agent (the three `AGENT_*` variables set and the key
non-empty) and `BOLIBENCH_DEMO_TOKEN` is set. Without them the demo runs read-only and says so.

Startup: an empty value counts as unset, so secrets left blank on the platform give a read-only demo.
A value that is set but invalid stops the server with `bolibench demo: invalid configuration: ...`
(exit 1, so the platform's deploy fails instead of serving a half-configured demo): a non-numeric or
non-positive `BOLIBENCH_LIVE_DAILY_CAP`, a `BOLIBENCH_LIVE_TURN_TIMEOUT` outside 0-600 s or
`BOLIBENCH_LIVE_RUN_TIMEOUT` outside 0-3600 s, a
`BOLIBENCH_DEMO_TOKEN` under 16 characters (even while live mode would be off), a non-local agent
URL, or an inconsistent `demo/` bundle. The server writes no files (the image runs with `--read-only`).

## Live mode: Gemma 4 on the Gemini API (Render's configuration)

Google's Gemini API hosts the open-weight Gemma 4 behind an OpenAI-compatible endpoint,
`https://generativelanguage.googleapis.com/v1beta/openai`, model `gemma-4-31b-it`, with native tool
calls. Settings (in `render.yaml`): `AGENT_BASE_URL` as above, `AGENT_MODEL=gemma-4-31b-it`,
`AGENT_TOOL_MODE=native`, `AGENT_REASONING_EFFORT=minimal`, `AGENT_API_KEY_ENV=GEMINI_API_KEY`, and the
secrets `GEMINI_API_KEY` (a Google AI Studio API key) and `BOLIBENCH_DEMO_TOKEN`.

Checked locally on 2026-10-18 with `deploy/start.sh` (server + agent as in the container) and a real
key: `POST /api/live-run` for `cancel-single-order` answered 202 in about 2 ms, a second POST while it
ran got 503 and a wrong token 401; polling reached `done` with verdict `pass` (one `cancel_order` on
`ORD-201`, all five checks pass) about 62 s after it started, including one provider HTTP 500 that the
agent retried. The key and the token appeared in no response, page or log. One run of one case, not
a benchmark result.

Cost: Gemma pricing on the Gemini API was not confirmed on Google's official pricing pages at the time
of writing (it may be free-tier only, rate limited, or billed); check your AI Studio project. Whatever
it is, `BOLIBENCH_LIVE_DAILY_CAP` (20 on Render) bounds how many runs a day the token holders can start,
and one run is one case of at most 2 turns. Provider rate limits (429) and 5xx errors are retried by
the agent at most twice per model call; a run that still fails is listed with an `error` verdict.

## Live mode: a DigitalOcean serverless inference model (alternative)

DigitalOcean's serverless inference serves open-weight models behind an OpenAI-compatible API at
`https://inference.do-ai.run/v1` (see DigitalOcean's "Serverless Inference API Endpoints" and
"Supported Models" docs).

1. Control Panel: Inference > Manage > Model Access Keys > create a key (optionally scoped to the model). Copy it once.
2. Pick an open-weight model with serverless inference. At the time of writing the docs list, among others:
   `openai-gpt-oss-120b`, `openai-gpt-oss-20b` (OpenAI open-weight), `gemma-4-31B-it` (Google),
   `llama-4-maverick` (Meta), `mistral-3-14B` (Mistral), `qwen3.5-397b-a17b` (Alibaba). Check the
   current list and ids:
   ```sh
   curl -s -H "Authorization: Bearer $MODEL_ACCESS_KEY" https://inference.do-ai.run/v1/models | python3 -m json.tool | grep '"id"'
   ```
3. Check that the model returns tool calls (the agent's default `native` tool mode needs them). The
   committed configs use `gemma-4-31B-it`, whose tool calling on this endpoint has not been verified yet:
   ```sh
   curl -s https://inference.do-ai.run/v1/chat/completions -H "Authorization: Bearer $MODEL_ACCESS_KEY" \
     -H "Content-Type: application/json" -d '{"model": "gemma-4-31B-it",
     "messages": [{"role": "user", "content": "List my orders."}],
     "tools": [{"type": "function", "function": {"name": "list_orders", "description": "List all orders.",
       "parameters": {"type": "object", "properties": {}, "required": []}}}]}' | python3 -m json.tool | grep -A3 tool_calls
   ```
   No `tool_calls` in the answer: keep the configs' `AGENT_TOOL_MODE=json` (or pick another model, e.g.
   `openai-gpt-oss-120b`). With `tool_calls`, `AGENT_TOOL_MODE=native` can be tried.
4. Set the variables on the platform (below): `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY_ENV=MODEL_ACCESS_KEY`,
   `AGENT_TOOL_MODE`, no `AGENT_REASONING_EFFORT`, and the secrets `MODEL_ACCESS_KEY` and
   `BOLIBENCH_DEMO_TOKEN` (`openssl rand -hex 24`). `.do/app.yaml` has these values; `render.yaml`
   lists them in a comment.

Each live run costs model tokens on your DigitalOcean account; `BOLIBENCH_LIVE_DAILY_CAP` bounds how
many runs a day the token holders can start.

## Render (primary)

`render.yaml` is a Blueprint: one Docker web service (`runtime: docker`, `./Dockerfile`) on the free
plan, region Singapore, branch `master`, health check `/health`, `autoDeployTrigger: commit`,
live-mode settings for `gemma-4-31b-it` on the Gemini API (DigitalOcean values in a comment), daily
cap 20, turn/run timeouts 240/600 s, and the two secrets as `sync: false`. Fields checked against
Render's Blueprint spec (https://render.com/docs/blueprint-spec) and `render blueprints validate`
(valid, 2026-10-18). Render sets `PORT=10000`; the image reads it.

Read-only demo first (no secrets needed):

1. The repo is on GitHub (`CodewithJha/bolibench`, branch `master`, with `render.yaml` at the root).
2. Render Dashboard: **New > Blueprint**, connect GitHub if asked, select `CodewithJha/bolibench`,
   give the Blueprint a name.
3. Render lists the `bolibench-demo` web service and prompts for the `sync: false` variables
   `GEMINI_API_KEY` and `BOLIBENCH_DEMO_TOKEN`. Leave both empty for the read-only demo.
4. **Apply** (Deploy Blueprint). Wait for the build and the `/health` check to pass, then open the
   `https://<service>.onrender.com` URL the service page shows (`bolibench-demo.onrender.com` if
   the name is free) and run the checks under "Verify a deployment".

Enable live mode later (Gemini). The running service was created with the REST API with all of these
variables already set (live mode on since its first deploy), so `render.yaml` is not applied to it;
to change its environment, set it directly:

1. Push the async live-mode code to `master` first (auto-deploy builds it), so live mode never starts
   on the old synchronous endpoint.
2. Set the variables on the service: `AGENT_BASE_URL`, `AGENT_MODEL=gemma-4-31b-it`,
   `AGENT_API_KEY_ENV=GEMINI_API_KEY`, `AGENT_TOOL_MODE=native`, `AGENT_REASONING_EFFORT=minimal`,
   `BOLIBENCH_LIVE_DAILY_CAP=20`, `BOLIBENCH_LIVE_TURN_TIMEOUT=240`, `BOLIBENCH_LIVE_RUN_TIMEOUT=600`,
   and the secrets `GEMINI_API_KEY` and `BOLIBENCH_DEMO_TOKEN` (`openssl rand -hex 24`; keep a copy in
   the git-ignored local `.env`). Either Dashboard > service > **Environment** (Save redeploys), or
   Render's REST API, `PUT https://api.render.com/v1/services/<service id>/env-vars/<KEY>` with body
   `{"value": "..."}` (the Render CLI 2.28 has no env-var command); API changes take effect on the
   next deploy: `render deploys create <service id> --confirm`.
3. `curl -s https://bolibench-demo-1b3o.onrender.com/health` shows `"live": true`; then trigger a run:

```sh
TOKEN=$(sed -n 's/^BOLIBENCH_DEMO_TOKEN=//p' .env)   # from the local .env; never echo it
BASE=https://bolibench-demo-1b3o.onrender.com
RUN=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
while sleep 5; do
  S=$(curl -s $BASE/api/live-runs/$RUN | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["status"], r.get("verdict") or r.get("error") or "")')
  echo "$S"; case "$S" in done*|error*) break;; esac
done
```

   Or open the page, pick a case, paste the token and press **Run live**: the page polls the run and
   shows its status, then the artifact.

The free plan spins the service down after about 15 minutes without inbound traffic; the first
request afterwards takes a while, and the in-memory daily cap and live runs reset. A run ends within its
600 s deadline (plus at most one turn timeout), well inside that idle window, but a result nobody
fetches before the next spin-down or redeploy is gone. To change the model: Environment > `AGENT_MODEL`.

Client IP for the rate limiter: Render puts Cloudflare in front and appends to a client-sent
`X-Forwarded-For`, so the Blueprint uses `True-Client-IP`, which Cloudflare sets and Render support
recommends but Render's docs do not list. If it ever disappears, the limiter falls back to the proxy
address (one shared bucket: stricter, not looser).

## DigitalOcean App Platform (optional, secondary)

Not needed if the Render service runs; use it only to host the demo on DigitalOcean too, at $5/month.
`.do/app.yaml` builds the same `Dockerfile`: one `apps-s-1vcpu-0.5gb` instance (the smallest,
single instance only), `http_port` 8080 (App Platform sets `PORT` to it), health check `/health`,
deploy on push to `master`, the client IP from `do-connecting-ip`, and the same non-secret live
settings. Fields checked against the App Spec reference
(https://docs.digitalocean.com/products/app-platform/reference/app-spec/); `doctl` was not available
to validate it. Secrets are not in the committed spec.

1. Edit `github.repo` in `.do/app.yaml` if the repo is not `CodewithJha/bolibench`.
2. `doctl apps create --spec .do/app.yaml` (after `doctl auth init`; `doctl apps spec validate .do/app.yaml` first), or Control Panel: Create App, pick the repo, then replace the generated spec with this one under Settings > App Spec.
3. Live mode only: App > Settings > web component > Environment Variables: add `MODEL_ACCESS_KEY` (or `GEMINI_API_KEY` with the Gemini values from the spec's comment) and `BOLIBENCH_DEMO_TOKEN`, tick Encrypt, save (redeploys).
4. Check the `*.ondigitalocean.app` URL the app shows, with the curls below.

## Custom `.tech` domain

Only after the domain is actually registered (e.g. `bolibench.tech`, or a subdomain like `demo.<name>.tech`):

- Render: service Settings > Custom Domains > add the hostname. At the registrar's DNS panel, add a
  `CNAME` from the subdomain (e.g. `demo`) to the service's `onrender.com` hostname. For a bare apex
  domain use the record Render shows (A or ALIAS/ANAME), since apex CNAMEs are not allowed. Render
  then verifies and issues TLS. Optionally uncomment `domains:` in `render.yaml`.
- DigitalOcean: app Settings > Domains > Add Domain, "You manage your domain", then add a `CNAME`
  from the subdomain to the app's `ondigitalocean.app` hostname. Optionally uncomment `domains:` in
  `.do/app.yaml`.

DNS changes can take minutes to hours. `dig +short CNAME demo.<name>.tech` shows what resolvers see.

## Verify a deployment

```sh
BASE=https://<service>.onrender.com   # or the DO / custom domain URL
curl -s $BASE/health                                  # {"status": "ok", "cases": 12, "runs": 5, "live": false}; true once live mode is configured
curl -s $BASE/api/cases | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'   # 12
curl -s $BASE/api/runs | python3 -m json.tool | head -30
curl -s $BASE/api/integrations | python3 -m json.tool | head -20
curl -s -o /dev/null -w '%{http_code}\n' $BASE/       # 200
curl -s $BASE/api/runs/qwen3-8b-agent-v2-2026-10-17/ambiguous-previous-order | python3 -m json.tool | head
curl -s -X POST --data-binary @demo/example-request.json $BASE/api/evaluate | python3 -c 'import json,sys; print(json.load(sys.stdin)["evaluation"]["verdict"])'   # pass
curl -s -o /dev/null -w '%{http_code}\n' --path-as-is $BASE/api/runs/../../pyproject.toml   # 404

# live mode
curl -s $BASE/api/live-runs | python3 -m json.tool | head            # enabled, busy, daily_cap, runs_today, timeouts
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run   # 401 without the token
curl -si -X POST -H "Authorization: Bearer $TOKEN" -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run   # 202, run_id, Location
curl -s $BASE/api/live-runs/<run_id> | python3 -c 'import json,sys; e=json.load(sys.stdin); print(e["status"], e.get("verdict"), e.get("agent"),
  [c["tool"] for c in e["artifact"]["run"]["tool_calls"]] if "artifact" in e else e.get("error"))'   # repeat until done or error
```

A `done` run with an `error` verdict and `agent request failed` in `artifact.run.execution_error`
means the agent process is not answering; `turn deadline exceeded` means a turn took longer than
`BOLIBENCH_LIVE_TURN_TIMEOUT`. The platform logs show the agent's output (bad key, unknown model id,
`model call: HTTP 429, retrying ...`).

## Refresh the bundled runs

Each bundle is a verbatim copy of one `bolibench run` directory (case JSONs + `summary.json`). For a
new run, e.g. a Gemma run in `runs/gemma-.../<timestamp>/`:

```sh
L=gemma3-4b-2026-10-18; mkdir -p demo/runs/$L && cp runs/$L/*/*.json demo/runs/$L/
```

Make sure `runs/$L/` holds exactly one timestamp directory (otherwise copy from the one you mean).
Then add an entry to `demo/runs/index.json` (`label` = the directory name, `source`, `date`,
`model`, `agent` with its hash, `note`, e.g. "single unseeded run") and run `uv run pytest -q
tests/test_server.py`. The server refuses to start if the copied artifacts do not match the
`summary.json`. Never edit anything under `runs/`.

## Security notes

Read endpoints and `POST /api/evaluate` have no authentication, on purpose; `POST /api/live-run` needs
the demo token.

- The GET endpoints are read-only and serve precomputed bytes (live runs from memory).
- `POST /api/evaluate` is public because it is bounded and side-effect free: it only replays the
  posted steps against a fresh in-memory sandbox, never makes an outbound request, and never writes a
  file. A request carrying `agent_url` is refused.
- `POST /api/live-run` spends model tokens, so it needs `Authorization: Bearer <BOLIBENCH_DEMO_TOKEN>`
  (constant-time comparison; 401 otherwise) and is limited to one run at a time (503 while one is
  queued or running, including an abandoned run that is still winding down) and
  `BOLIBENCH_LIVE_DAILY_CAP` runs per UTC day (429), counted when a run is accepted, errors included.
  `GET /api/live-runs/<run_id>` is public and unauthenticated: a run holds the case, the agent's
  replies and tool calls, and the evaluation, nothing secret. Run ids are random (64 bits) but not a
  secret either; `GET /api/live-runs` lists them.
  The agent URL is fixed at startup to 127.0.0.1 (checked like `bolibench run --agent-url`); a body
  with `agent_url` is refused and query strings are ignored. Without the token or the agent the
  endpoint answers 404 with the reason.
- Secrets: the model key is visible only to the agent process and the demo token only to the server
  process (`start.sh` removes each from the other's environment). Neither is echoed in responses or
  logs; access logs record the request line, not headers.
- Limits on both POSTs: body at most 32 KiB (413 above it, decided from `Content-Length` before
  reading); per-client token bucket of 10 requests burst and 10/minute sustained, shared by both (429
  with `Retry-After`), applied before the token check, so it also slows token guessing.
  `/api/evaluate` only: at most 64 steps across all turns (400), script turns must equal the case's
  turns, at most 4 evaluations at once (503). JSON nesting is capped by pydantic's parser.
- Time: each socket read times out after 10 s, which bounds slow clients. A scripted evaluation is
  pure in-memory work bounded by the size and step caps (milliseconds). A live run never holds a
  request open: the POST returns 202 at once. The run itself is bounded by the webhook adapter's
  per-turn deadline (`BOLIBENCH_LIVE_TURN_TIMEOUT`, 240 s) and the whole-run deadline
  (`BOLIBENCH_LIVE_RUN_TIMEOUT`, 600 s): past the latter it is reported as `error`, its late result is
  discarded, and the run slot frees once the abandoned turn hits its own deadline.
- Errors are JSON (`{"error": ...}`, validation `details` without the posted input); no stack traces
  or filesystem paths. An unexpected server bug drops the connection and is logged to stderr.

What is not protected:

- The rate limiter, the daily cap and the live runs are in memory and per process: a restart
  (including Render's free-plan spin-down and every redeploy) resets the cap and forgets every run,
  queued, running or finished, and several instances would each have their own. Both configs run one
  instance. A live run that matters should be saved from `GET /api/live-runs/<run_id>` by the caller.
- A run past its deadline is reported as `error`, but the agent may still finish its model call in
  the background (the provider bills it, if it bills); its tool calls are then refused by the gateway.
- Anyone holding the demo token can spend up to the daily cap of model tokens; rotate it by changing
  the variable.
- GET endpoints are not rate limited, and `ThreadingHTTPServer` starts one thread per connection, so a
  flood of slow connections can exhaust the instance. Render and DigitalOcean put Cloudflare-based
  proxies in front, which absorb some of this; nothing in the app does.
- The rate-limit key is only as trustworthy as `BOLIBENCH_CLIENT_IP_HEADER`'s source.
- If the agent process dies, the container keeps serving and live runs return `error` until a redeploy.
- Bundled and live artifacts include the agent URL (`http://127.0.0.1:...`), a local address, not a secret.
