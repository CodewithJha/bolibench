# Public demo deployment

One container, two processes, started by `deploy/start.sh`:

- `src/bolibench/server.py`: a small stdlib HTTP server (no web framework, no extra dependency) with
  the suite, bundled run artifacts, a scripted-harness evaluator, and live mode.
- Live mode only: `examples/ollama_agent.py` on 127.0.0.1, backed by an open-weight model on an
  OpenAI-compatible endpoint (DigitalOcean serverless inference). On a token-authenticated request
  BoliBench runs one suite case through it with the regular webhook adapter: the agent's tool calls go
  through BoliBench's gateway into its sandbox, and the evaluator judges the recorded calls and final state.

Nothing here is deployed yet and no domain is registered; these are the steps. Render is the primary
target (Render credits cover the web service; DigitalOcean is used for model inference). The
DigitalOcean App Platform spec is an optional alternative: maintaining both is not required.

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
| `POST /api/live-run` | Live mode. Header `Authorization: Bearer <BOLIBENCH_DEMO_TOKEN>`, body `{"case_id": ...}`. Runs that case against the hosted agent; returns `{finished_at, case_id, verdict, agent, artifact}` where `agent` is the agent's self-reported identity (file hash + model + backend) |
| `GET /api/live-runs` | Live mode status (`enabled`, or the reason it is off), `daily_cap`, `runs_today`, and the last 20 live results (same shape as above), newest first |

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
  {"name": "Mastra agent", "category": "agent framework", "status": "live-verified (local)",
   "evidence": "demo/runs/mastra-qwen3-8b-2026-10-17, docs/integrations/mastra.md", "note": "..."}]}
```

`status` is the highest level actually reached, one of `not verified`, `implemented` (code in the
repo), `offline-tested` (tests against fakes, stubs or local test servers), `live-verified (local)`,
`live-verified (hosted)` ("live" = a real call to the service or a real run of the model). Raise it
only with evidence in the repo, name that evidence (repo-relative paths) in `evidence`, and bump
`as_of`. Any other status or a missing/extra field stops the server at startup;
`uv run pytest -q tests/test_server.py` checks the file.

Live results are honest: an agent that is down, times out or replies badly gives an `error` verdict,
a wrong action a `fail`; every run is listed, whatever its verdict. Live mode off means the endpoint
says so (404 with the reason); nothing is simulated.

## Run locally

```sh
uv run bolibench serve                     # http://127.0.0.1:8080, run from the repo root (= python -m bolibench.server)
docker build -t bolibench-demo . && docker run --rm -p 8080:8080 bolibench-demo
```

Live mode locally, against the example agent on Ollama (`--backend ollama` is the agent's default):

```sh
python examples/ollama_agent.py --model qwen3:8b --port 8765 &
BOLIBENCH_DEMO_TOKEN=$(openssl rand -hex 24) BOLIBENCH_LIVE_AGENT_URL=http://127.0.0.1:8765/turn \
    BOLIBENCH_LIVE_TURN_TIMEOUT=180 uv run python -m bolibench.server
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | Listen port. Render sets `10000`; DigitalOcean sets it to `http_port` |
| `HOST` | `127.0.0.1`, or `0.0.0.0` when `PORT` is set | Bind address. The Docker image sets `0.0.0.0` |
| `BOLIBENCH_CLIENT_IP_HEADER` | unset (use the socket peer) | Header holding the real client IP, for the rate limiter. Render: `True-Client-IP`. DigitalOcean: `do-connecting-ip`. Do not set it when the server is reachable directly: clients could then pick their own rate-limit key |
| `BOLIBENCH_SUITE` | `suites/orders` | Suite directory, relative to the working directory |
| `BOLIBENCH_DEMO` | `demo` | Bundle directory (`runs/index.json`, `runs/<label>/`, `example-request.json`) |
| `AGENT_BASE_URL` | unset | Live: OpenAI-compatible base URL, e.g. `https://inference.do-ai.run/v1` (passed to the agent's `--base-url`) |
| `AGENT_MODEL` | unset (`gemma-4-31B-it` in both platform configs) | Live: model id (`--model`) |
| `AGENT_API_KEY_ENV` | unset | Live: the *name* of the variable that holds the key, e.g. `MODEL_ACCESS_KEY` (`--api-key-env`) |
| `MODEL_ACCESS_KEY` (or the name above) | unset | Live, secret: the model access key. Only the agent process sees it |
| `AGENT_TOOL_MODE` | `native` (`json` in both platform configs) | Live: `json` for a model without tool calling (`--tool-mode`). DigitalOcean's model table does not list tool calling for `gemma-4-31B-it`, so the configs use `json`; set `native` only if the probe below returns `tool_calls` |
| `BOLIBENCH_DEMO_TOKEN` | unset | Live, secret: bearer token for `POST /api/live-run`, at least 16 characters. Only the server process sees it |
| `BOLIBENCH_LIVE_DAILY_CAP` | `50` | Live runs per UTC day, whole server |
| `BOLIBENCH_LIVE_TURN_TIMEOUT` | `40` | Seconds per turn. Cases have at most 2 turns, keeping a run under the ~100 s request limit of the platforms' proxies |
| `BOLIBENCH_LIVE_AGENT_URL` | set by `start.sh` | Fixed agent URL, `http://127.0.0.1:8765/turn`; must be localhost. Never taken from a request |

Live mode is on only when `start.sh` started the agent (the three `AGENT_*` variables set and the key
non-empty) and `BOLIBENCH_DEMO_TOKEN` is set. Without them the demo runs read-only and says so.

Startup: an empty value counts as unset, so secrets left blank on the platform give a read-only demo.
A value that is set but invalid stops the server with `bolibench demo: invalid configuration: ...`
(exit 1, so the platform's deploy fails instead of serving a half-configured demo): a non-numeric or
non-positive `BOLIBENCH_LIVE_DAILY_CAP`, a `BOLIBENCH_LIVE_TURN_TIMEOUT` outside 0-600 s, a
`BOLIBENCH_DEMO_TOKEN` under 16 characters (even while live mode would be off), a non-local agent
URL, or an inconsistent `demo/` bundle. The server writes no files (the image runs with `--read-only`).

## Live mode: a DigitalOcean serverless inference model

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
   and the secrets `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN` (`openssl rand -hex 24`).

Each live run costs model tokens on your DigitalOcean account; `BOLIBENCH_LIVE_DAILY_CAP` bounds how
many runs a day the token holders can start.

## Render (primary)

`render.yaml` is a Blueprint: one Docker web service (`runtime: docker`, `./Dockerfile`) on the free
plan, region Singapore, branch `master`, health check `/health`, `autoDeployTrigger: commit`,
live-mode settings for `gemma-4-31B-it` on DigitalOcean serverless inference, and the two secrets as
`sync: false`. Fields checked against Render's Blueprint spec (https://render.com/docs/blueprint-spec)
and `render blueprints validate`. Render sets `PORT=10000`; the image reads it.

Read-only demo first (no secrets needed):

1. The repo is on GitHub (`CodewithJha/bolibench`, branch `master`, with `render.yaml` at the root).
2. Render Dashboard: **New > Blueprint**, connect GitHub if asked, select `CodewithJha/bolibench`,
   give the Blueprint a name.
3. Render lists the `bolibench-demo` web service and prompts for the `sync: false` variables
   `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN`. Leave both empty for the read-only demo.
4. **Apply** (Deploy Blueprint). Wait for the build and the `/health` check to pass, then open the
   `https://<service>.onrender.com` URL the service page shows (`bolibench-demo.onrender.com` if
   the name is free) and run the checks under "Verify a deployment".

Enable live mode later:

1. Get a DigitalOcean model access key and run the tool-calling probe for `gemma-4-31B-it` (step 3 in
   the live-mode section above). The Blueprint already sets `AGENT_TOOL_MODE=json`; change it to
   `native` only if the probe returned `tool_calls`.
2. Service > **Environment**: add `MODEL_ACCESS_KEY` (the key) and `BOLIBENCH_DEMO_TOKEN`
   (`openssl rand -hex 24`). Render prompts for
   `sync: false` values only when the Blueprint is first created, so later secrets go here. Save,
   which redeploys.
3. `curl -s https://<service>.onrender.com/health` shows `"live": true`; then the live curls below.

The free plan spins the service down when idle; the first request afterwards takes a while, and
the in-memory daily cap and live results reset. To change the model: Environment > `AGENT_MODEL`.

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
3. Live mode only: App > Settings > web component > Environment Variables: add `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN`, tick Encrypt, save (redeploys).
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
curl -s $BASE/api/live-runs | python3 -m json.tool | head            # enabled, daily_cap, runs_today
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run   # 401 without the token
curl -s -X POST -H "Authorization: Bearer $BOLIBENCH_DEMO_TOKEN" -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run \
  | python3 -c 'import json,sys; e=json.load(sys.stdin); print(e["verdict"], e["agent"], [c["tool"] for c in e["artifact"]["run"]["tool_calls"]])'
```

An `error` verdict with `agent request failed` in `artifact.run.execution_error` means the agent
process is not answering; the platform logs show its output (bad key, unknown model id, ...).

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

- The GET endpoints are read-only and serve precomputed bytes (live results from memory).
- `POST /api/evaluate` is public because it is bounded and side-effect free: it only replays the
  posted steps against a fresh in-memory sandbox, never makes an outbound request, and never writes a
  file. A request carrying `agent_url` is refused.
- `POST /api/live-run` spends model tokens, so it needs `Authorization: Bearer <BOLIBENCH_DEMO_TOKEN>`
  (constant-time comparison; 401 otherwise) and is limited to one run at a time (503 while one runs)
  and `BOLIBENCH_LIVE_DAILY_CAP` runs per UTC day (429), counted when a run starts, errors included.
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
  pure in-memory work bounded by the size and step caps (milliseconds). A live run is bounded by the
  per-turn timeout (`BOLIBENCH_LIVE_TURN_TIMEOUT`, 40 s) of the webhook adapter.
- Errors are JSON (`{"error": ...}`, validation `details` without the posted input); no stack traces
  or filesystem paths. An unexpected server bug drops the connection and is logged to stderr.

What is not protected:

- The rate limiter, the daily cap and the live results are in memory and per process: a restart
  (including Render's free-plan spin-down) resets the cap and forgets the results, and several
  instances would each have their own. Both configs run one instance.
- Anyone holding the demo token can spend up to the daily cap of model tokens; rotate it by changing
  the variable.
- GET endpoints are not rate limited, and `ThreadingHTTPServer` starts one thread per connection, so a
  flood of slow connections can exhaust the instance. Render and DigitalOcean put Cloudflare-based
  proxies in front, which absorb some of this; nothing in the app does.
- The rate-limit key is only as trustworthy as `BOLIBENCH_CLIENT_IP_HEADER`'s source.
- If the agent process dies, the container keeps serving and live runs return `error` until a redeploy.
- Bundled and live artifacts include the agent URL (`http://127.0.0.1:...`), a local address, not a secret.
