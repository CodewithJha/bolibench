# Submission runbook (HF26 Week 2: Side Hustle)

**Hard deadline: Sun Oct 18 2026, 11:59 PM PDT = Mon Oct 19 2026, 12:29 PM IST.**
Target: publish by **Sun Oct 18, 11:00 PM IST**; Monday morning is buffer for fixes only.

Official pages: [challenge + template + FAQ](https://dev.to/challenges/hacktoberfest-week2-2026-10-12),
[contest rules](https://dev.to/page/hacktoberfest-week2-2026-10-12-contest-rules),
[credits](https://hacktoberfest.com/my/promos). Re-checked 2026-10-18 00:05 IST: nothing changed.
Category state: `docs/sponsor-evidence-matrix.md`. What has been verified so far, with commands:
`docs/live-verification-report.md`.

Ground rules for every step:

- One prize per person, one entry (only the first is judged). Writing quality is weighted most.
- The rules require a deployed link **or** a video. We do both (step 1 and step 11).
- A category goes in the post's Prize Categories section only when its evidence is in the post.
- Keys only in the shell (`read -rs NAME && export NAME`), never in files, flags, the post or
  screenshots. After every live run: `rg -F "$THE_KEY" runs/ audio-cache/ /tmp/bb-*` must print nothing.
- Each step has a time box. If it overruns, drop that category and move on (order at the end).
- After each hosted step, add one row to section 3.7 of `docs/live-verification-report.md` (date,
  command, result, where the screenshot is) and update that row of the matrix. Commit before the deadline.
- Commits after the deadline must be listed in the README (FAQ rule).

Start one local agent for the steps that need it (Sentry, ElevenLabs, Temporal), in its own terminal:

```sh
ollama serve                                            # if not running; qwen3:8b already pulled
python3 examples/ollama_agent.py --model qwen3:8b --port 8000
```

## 0. Commit and push the verified work (15 min, required)

Done through `ace4e9f`. Later commits: from macOS Terminal (an editor's agent shell appends a
`Co-authored-by` trailer), stage only the named files, `git commit -m ...`, then `git push origin
master`, hooks left on. Entire's hooks may add an `Entire-Checkpoint:` trailer (and may ask to link
the commit to a session); with `push_sessions: false` in `.entire/settings.local.json` its pre-push
hook uploads no checkpoints (`entire status`: "Automatic checkpoint pushing: disabled"). Afterwards
open https://github.com/CodewithJha/bolibench logged out: README renders, LICENSE shows.

## 1. Render deploy, read-only first (30 min, required)

**Done 2026-10-18** with `render services create` (not a Blueprint, so `render.yaml` edits are not
synced): https://bolibench-demo.onrender.com, `srv-dba5nh5g1s2s73asmb5g`, free plan, deploy
`dep-dba5nhlg1s2s73asmd40` of `ace4e9f` status `live`; smoke tests in `docs/live-verification-report.md`
3.7. Auto-deploy is on, so pushing `master` redeploys. Cold start seen 12:11:38 IST: the first `GET /`
took 12.9 s and the logs show the instance starting at 12:11:42 IST; open the URL before recording or
judging. Still to do: step 4's screenshots. That service is now suspended on its old workspace
(billing). **Redeployed 2026-10-18 22:48 IST** on a new Render workspace with the REST API, live mode
on: https://bolibench-demo-1b3o.onrender.com, `srv-dbafue7btjjs73f13di0`, free plan, commit
`3440507`; one hosted live run passed (`docs/live-verification-report.md` 3.7). Use this URL below.
The original Blueprint procedure, for reference:

1. https://dashboard.render.com > **New > Blueprint**, connect GitHub if asked, pick
   `CodewithJha/bolibench`, branch `master`. Render reads `render.yaml`.
2. It prompts for `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN`: leave both **empty** for now.
3. **Apply**. Wait for the build and the `/health` check. Then:

   ```sh
   BASE=https://<service>.onrender.com
   curl -s $BASE/health                                    # {"status": "ok", "cases": 12, "runs": 5, "live": false}
   curl -s $BASE/api/integrations | python3 -m json.tool | head -20
   curl -s -X POST --data-binary @demo/example-request.json $BASE/api/evaluate \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["evaluation"]["verdict"])'   # pass
   ```

4. Open `$BASE` in a browser. Evidence: the URL, a screenshot of the page, a screenshot of the Render
   service page (no Environment tab). The free plan sleeps when idle: open it once before judging.

## 2. Claim credits (10 min)

https://hacktoberfest.com/my/promos: Render, Backboard, .tech (and Tinker, unused). Note what you got.

## 3. DigitalOcean inference, then Render live mode (60 min; DigitalOcean $200, makes Render $200 strong)

1. DigitalOcean Control Panel > Inference > Model Access Keys > create
   (https://cloud.digitalocean.com/model-studio/manage-keys).
2. Model list and tool-calling probe (`docs/deployment.md`, "Live mode"):

   ```sh
   read -rs MODEL_ACCESS_KEY && export MODEL_ACCESS_KEY
   curl -s -H "Authorization: Bearer $MODEL_ACCESS_KEY" https://inference.do-ai.run/v1/models | python3 -m json.tool | grep '"id"'
   curl -s https://inference.do-ai.run/v1/chat/completions -H "Authorization: Bearer $MODEL_ACCESS_KEY" \
     -H "Content-Type: application/json" -d '{"model": "gemma-4-31B-it",
     "messages": [{"role": "user", "content": "List my orders."}],
     "tools": [{"type": "function", "function": {"name": "list_orders", "description": "List all orders.",
       "parameters": {"type": "object", "properties": {}, "required": []}}}]}' | python3 -m json.tool | grep -A3 tool_calls
   ```

   DigitalOcean's model table lists no tool calling for `gemma-4-31B-it`, so the configs use
   `AGENT_TOOL_MODE=json`. Save the probe output (without the key) either way.
3. One case, then the suite, from the laptop (a second terminal; port 8001 so the local agent keeps 8000):

   ```sh
   python3 examples/ollama_agent.py --backend openai --base-url https://inference.do-ai.run/v1 \
     --api-key-env MODEL_ACCESS_KEY --model gemma-4-31B-it --tool-mode json --port 8001 2> /tmp/do-agent.log
   uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8001/turn \
     --timeout 180 --output runs/do-gemma-4-31b-smoke-2026-10-18/
   uv run bolibench run suites/orders --agent-url http://127.0.0.1:8001/turn \
     --timeout 180 --output runs/do-gemma-4-31b-2026-10-18/
   rg -F "$MODEL_ACCESS_KEY" runs/do-gemma-4-31b-* /tmp/do-agent.log || echo "key not in outputs"
   ```

   The agent version in the artifacts must end in `+gemma-4-31B-it+openai-json`. This is also the
   post's first Gemma 4 result; report the counts as they come, whatever they are.
4. Render > service > **Environment**: add `MODEL_ACCESS_KEY` and `BOLIBENCH_DEMO_TOKEN`
   (`openssl rand -hex 24`; keep it in your password manager). Save (redeploys). Then:

   ```sh
   read -rs BOLIBENCH_DEMO_TOKEN && export BOLIBENCH_DEMO_TOKEN
   curl -s $BASE/health                                                   # "live": true
   curl -s -X POST -H "Authorization: Bearer $BOLIBENCH_DEMO_TOKEN" -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run \
     | python3 -c 'import json,sys; e=json.load(sys.stdin); print(e["verdict"], e["agent"], [c["tool"] for c in e["artifact"]["run"]["tool_calls"]])'
   ```

   Evidence: that output and a screenshot of the page's live section. `error` with `agent request
   failed`: read the Render logs (bad key, unknown model id).

## 4. Sentry Agent Tracing (45 min, $100)

Procedure and expected spans: `docs/integrations/gemma-sentry.md`, "Manual verification".

1. Sentry (free) > new Python project > Project Settings > Client Keys (DSN).
2. Restart the local agent with tracing (stop the plain one first):

   ```sh
   read -rs SENTRY_DSN && export SENTRY_DSN
   uv run --extra sentry python examples/ollama_agent.py --model qwen3:8b --port 8000
   uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 \
     --output runs/sentry-qwen3-8b-2026-10-18/
   ```

3. Screenshots: Explore > Traces, `span.op:gen_ai.invoke_agent`, one trace waterfall with `chat` and
   `execute_tool` children and token counts; the AI Agents dashboard; one Conversation. Privacy: search
   the trace for `ORD-201` / `Please cancel` (must be absent).
4. Error event (needs step 3's DigitalOcean setup; skip otherwise): run step 3's agent command with
   `MODEL_ACCESS_KEY=wrong` and `SENTRY_DSN` set, via `uv run --extra sentry python …`, run one case,
   open the new `HTTP Error 401` issue: no local variables, no key.
5. Write down one finding from the traces (e.g. which turn or case spent most time in `chat`). Cost:
   the local model is $0; say so instead of showing a number.

## 5. ElevenLabs (45 min, $100)

**Engineering part done 2026-10-18** (free tier, reused key, voice Sarah): live TTS and STT, the live
test, the CLI with the audio cache on 3 cases, and those 3 cases end to end with local `qwen3:8b`
(speech 1 pass / 2 fail, text-only 0 / 3). Results: `docs/integrations/elevenlabs.md` "Verified
results"; row in `docs/live-verification-report.md` 3.7. A full-suite speech run was not done.
Procedure: `docs/integrations/elevenlabs.md`, "Live verification procedure".

```sh
read -rs ELEVENLABS_API_KEY && export ELEVENLABS_API_KEY        # key restricted to TTS + STT, with a quota
export ELEVENLABS_VOICE_ID=<Hindi-capable voice id from https://elevenlabs.io/app/voice-library>
BOLIBENCH_LIVE=1 uv run pytest -q -s tests/test_speech.py -k live
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 \
  --speech elevenlabs --speech-audio-dir audio-cache --output runs/speech-qwen3-8b-2026-10-18/
rg -F "$ELEVENLABS_API_KEY" runs/speech-qwen3-8b-2026-10-18/ audio-cache/ || echo "key not in outputs"
```

Evidence: the live test's three printed lines; one artifact's `user_input` next to `asr_text`; how
many turns ASR changed and whether any verdict moved versus the text run; the usage screenshot.
Listen to the Awadhi mp3s and note misheard words. Synthetic voices, not real speakers: say so.

## 6. MongoDB Atlas (30 min, $100)

Procedure: `docs/integrations/mongodb-atlas.md`, "Atlas setup, verification, cleanup". Already
rehearsed on a local MongoDB 7.0.45 with the same commands.

```sh
read -rs MONGODB_URI && export MONGODB_URI                     # M0 cluster, readWrite user, your IP allowed
uv run --extra mongo bolibench export --to mongo demo/runs/qwen3-8b-agent-v3-2026-10-17 \
  demo/runs/gemma-gemma3-4b-2026-10-17 demo/runs/mastra-qwen3-8b-2026-10-17 --suite suites/orders
uv run --extra mongo bolibench export --to mongo --report
BOLIBENCH_LIVE=1 uv run --extra mongo pytest -q tests/test_export.py -k live_mongo
```

Evidence: Atlas Data Explorer, `bolibench.case_results`, one document expanded; the `--report` output.

## 7. Tiger Data on Tiger Cloud (45 min, $100)

Procedure: `docs/integrations/tiger-data.md`, "Tiger Cloud setup, verification, cleanup". Rehearsed
locally on TimescaleDB 2.30.2 + pgvector 0.8.7; only the Tiger Cloud run counts.

```sh
read -rs TIGER_DATABASE_URL && export TIGER_DATABASE_URL
ollama pull embeddinggemma
uv run --extra tiger bolibench export --to tiger --failures demo/runs/qwen3-8b-baseline-2026-10-17 \
  demo/runs/qwen3-8b-agent-v2-2026-10-17 demo/runs/qwen3-8b-agent-v3-2026-10-17 \
  demo/runs/gemma-gemma3-4b-2026-10-17 demo/runs/mastra-qwen3-8b-2026-10-17
uv run --extra tiger bolibench export --to tiger --similar demo/runs/qwen3-8b-agent-v3-2026-10-17/similar-items-kurta-kurti.json --k 5
uv run --extra tiger bolibench export --to tiger --report
BOLIBENCH_LIVE=1 uv run --extra tiger pytest -q tests/test_export.py -k "live_tiger or live_ollama"
```

Evidence: console screenshot of `SELECT * FROM timescaledb_information.hypertables;` and of
`bolibench_failures`; the `--similar` output. Honest framing: the top hits are mostly the same case in
other runs (near-identical user text); say what it found, not more.

## 8. Temporal screenshots (20 min, $100, no account)

Procedure: `docs/integrations/temporal.md`, "Verify it yourself". Already run on the dev server
(`docs/live-verification-report.md` 3.3); this step is for the screenshots.

```sh
temporal server start-dev --db-filename /tmp/temporal.db                # UI http://localhost:8233
uv run --extra temporal python -m bolibench.temporal_run worker         # terminal 2
uv run --extra temporal python -m bolibench.temporal_run start suites/orders \
  --agent-url http://127.0.0.1:8000/turn --timeout 60 --workflow-id demo-1 --output runs/temporal/   # terminal 3
```

After 2–3 cases, `kill -9` the worker while a case is running (`pgrep -f "temporal_run worker"`),
restart it, let `start` finish. The killed case re-runs only after its activity timeout (turns ×
`--timeout` plus a margin), which is why this uses `--timeout 60` rather than 180. Screenshots: the list with `demo-1` Completed; Event History with one
`bolibench.run_case` per case and `bolibench.write_summary`; the activity with **Attempt 2**. Check
`runs/temporal/demo-1/` holds 12 case files plus `summary.json`. Post framing: a durable evaluation
run; the agent itself is not a Temporal workflow.

## 9. Backboard (1.5–2 h, $100; lowest value per hour)

Procedure: `docs/integrations/backboard.md`, "Live verification". The category is about comparing
open-weight models through one key, so enter it only with full-suite runs of **two or more** models.

**Partial on 2026-10-18** (`docs/audits/backboard-2026-10-18.md`): the bridge works against the real
API (tool-call round trip, memory isolation), but the account has free credit only, which Backboard
does not let pay for LLM chat, so the chosen open-weight model `qwen/qwen3-235b-a22b-2507` could not
run. A zero-priced preview model passed 3 of 4 cases. The steps below need paid credit first. The
bridge now requires `--assistant-id` of a dedicated assistant named `bolibench-*` (the audit kept
`bolibench-agent`).

```sh
read -rs BACKBOARD_API_KEY && export BACKBOARD_API_KEY
curl -s "https://app.backboard.io/api/models?model_type=llm&supports_tools=true&provider=openrouter&limit=100" \
  -H "X-API-Key: $BACKBOARD_API_KEY" | python3 -c "import json,sys; [print(m['name']) for m in json.load(sys.stdin)['models']]"
python3 examples/backboard_agent.py --assistant-id <bolibench-* assistant id> --provider openrouter \
  --model <open-weight model A> --port 8002 2> /tmp/bb-agent.log
uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8002/turn --timeout 180 --output runs/backboard-smoke-2026-10-18/
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8002/turn --timeout 180 --output runs/backboard-<model-a>-2026-10-18/
# restart the bridge with model B, then the same full-suite command into runs/backboard-<model-b>-2026-10-18/
```

Evidence: both `summary.json` counts side by side, the Backboard usage screenshot.

## 10. .tech domain (optional, 30 min + DNS wait)

Enter the category only if the domain is claimed through Hacktoberfest **and** serves the live demo.
Render service > Settings > Custom Domains > add `demo.<name>.tech`; at the registrar add a `CNAME`
`demo` → `<service>.onrender.com`; `dig +short CNAME demo.<name>.tech`; load it over HTTPS. Start
early: DNS and TLS can take hours.

## 11. Video demo (60 min, required as the backup to the link)

About 2.5 minutes, screen recording with voice-over, uploaded unlisted (YouTube or similar). Open
the Render URL a minute before recording (free-plan cold start). Every number below is from
`demo/runs/*/summary.json` or the artifact named; say nothing that is not on screen.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:15 | `similar-items-kurta-kurti` artifact (qwen3:8b v3) | "The customer says: कुर्ती वाले order की quantity 2 कर दो. The agent answers, in fluent Hindi, that the kurti order is updated. It reads perfectly. It's wrong." |
| 0:15–0:40 | README / demo page header | "BoliBench is an open-source benchmark for Hindi, Hinglish and Awadhi order-support agents. Twelve cases. The agent's tool calls go to a sandboxed order system, and deterministic checks judge the final state and the calls, never the wording of the reply." |
| 0:40–1:15 | Demo page grid on https://bolibench-demo-1b3o.onrender.com | "Five bundled runs, each a single unseeded run on a laptop: qwen3:8b v1 baseline 3 of 12, v2 6, v3 6, gemma3:4b 2, the Mastra agent on qwen3:8b 6. v2 fixed five cases but broke two the baseline passed, Awadhi 'yesterday' and Mohan/Sohan, by asking instead of acting. gemma3:4b in JSON tool mode lost most cases because in 7 of 12 it wrote a tool call the strict parser did not accept." |
| 1:15–1:50 | Click the kurta/kurti verdict; scroll `tool_calls` and `evaluation.checks` | "The record: `list_orders` returns ORD-701 Kurta and ORD-702 Kurti. Then `update_quantity` on ORD-701, quantity 2, status ok. The checks: final state fail, ORD-701 expected 1 got 2, ORD-702 expected 2 got 1; required action fail, no update on ORD-702; forbidden action fail. Classified entity resolution. Still, the reply calls ORD-701 the kurti. Every one of the five runs fails this case." |
| 1:50–2:20 | Integrations panel, then `docs/live-verification-report.md` 3.7 | "Each integration is labelled by what was verified. This demo is hosted on Render, read-only, smoke-tested publicly. Gemma, Mastra, Temporal, MongoDB and TimescaleDB ran against the real software on this laptop, not their clouds. Gemma 4 also ran hosted on Google's Gemini API, and ElevenLabs speech ran live; Backboard ran live but only partly, because of billing. DigitalOcean and Sentry are tested offline only." (Update this line only with steps actually finished, e.g. a DigitalOcean run or a Sentry trace.) |
| 2:20–2:30 | Repo page | "Open source, runs on a laptop with local models. Repo and demo are linked below." |

## 12. Final evidence checklist (tick before writing the post)

- [ ] Public demo screenshot: https://bolibench-demo-1b3o.onrender.com showing the grid and the
      Integrations panel (after the next deploy it should say Render `live-verified (hosted)`)
- [ ] Render: service page screenshot (name, `free`, region, URL, no Environment tab) and Events or
      Deploys screenshot with the deploy `live`; `curl -s $BASE/health` output
- [ ] Video, 2–3 min, plays logged out
- [ ] Reproducible benchmark comparison. Bundled record: `demo/runs/<label>/summary.json` and the
      per-case artifacts; provenance (model, agent sha256, source run dir) in `demo/runs/index.json`.
      Counts (pass/fail/error): `qwen3-8b-baseline-2026-10-17` 3/9/0, `qwen3-8b-agent-v2-2026-10-17`
      6/6/0, `qwen3-8b-agent-v3-2026-10-17` 6/6/0, `gemma-gemma3-4b-2026-10-17` 2/10/0,
      `mastra-qwen3-8b-2026-10-17` 6/6/0. Print them:

      ```sh
      for s in demo/runs/*/summary.json; do python3 -c "import json,sys; print(sys.argv[1].split('/')[2], json.load(open(sys.argv[1]))['counts'])" "$s"; done
      ```

      Rerun the same procedure (current `examples/ollama_agent.py`, whose sha256 differs from the
      bundled runs'; unseeded, so expect the same actions on most cases, not identical runs):

      ```sh
      uv run bolibench validate suites/orders                       # suites/orders: 12 cases ok
      python3 examples/ollama_agent.py --model qwen3:8b --port 8000                       # terminal 1
      uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 \
        --output runs/qwen3-8b-rerun/                                                     # terminal 2
      # gemma: restart the agent with --model gemma3:4b --tool-mode json; Mastra: docs/integrations/mastra.md
      ```

- [ ] One failure with evidence: `demo/runs/qwen3-8b-agent-v3-2026-10-17/similar-items-kurta-kurti.json`.
      Tool calls: `list_orders {}` (ok: ORD-701 Kurta, ORD-702 Kurti), `update_quantity {"order_id":
      "ORD-701", "quantity": 2}` (ok). Checks: `final_state` fail ("orders.ORD-701.quantity: expected 1,
      got 2; orders.ORD-702.quantity: expected 2, got 1"), `required_actions` fail ("no successful call
      for: update_quantity {'order_id': 'ORD-702', 'quantity': 2}"), `forbidden_actions` fail,
      `ask_policy` pass, `evidence` pass; classification `entity_resolution` (understanding, likely).
      The reply says कुर्ती वाले ऑर्डर (ORD-701). Verify:

      ```sh
      python3 -c "import json; a=json.load(open('demo/runs/qwen3-8b-agent-v3-2026-10-17/similar-items-kurta-kurti.json')); print([(t['tool'], t['args'], t['status']) for t in a['run']['tool_calls']]); print([(c['metric'], c['verdict']) for c in a['evaluation']['checks']])"
      ```

- [ ] Integrations panel screenshot (`GET /api/integrations`, 12 entries)
- [ ] Per-sponsor proof, only for categories kept in the post:
  - [ ] Gemma: `docs/audits/gemma-gemma3-4b-2026-10-17.md`, gemma run counts; hosted Gemma 4 on the Gemini API (`docs/audits/gemma4-gemini-api-2026-10-18.md`, 8/3/1); DO Gemma 4 result if step 3 done
  - [ ] Mastra: `npm test` 5/5, Mastra run counts
  - [ ] Temporal: list, Event History, Attempt 2 screenshots (step 8)
  - [ ] Render: the two screenshots above; live-run output if step 3 done
  - [ ] DigitalOcean: probe output (key removed), smoke + suite counts, agent version string
  - [ ] Sentry: trace waterfall, AI Agents view, conversation, error issue without locals, one finding
  - [ ] ElevenLabs: live test lines, `user_input` vs `asr_text`, changed-turn count, usage screenshot
  - [ ] Atlas: Data Explorer screenshot, `--report`
  - [ ] Tiger Cloud: hypertables query, `bolibench_failures`, `--similar` output
  - [ ] Backboard: two summary counts, usage screenshot
  - [ ] .tech URL over HTTPS (optional)
- [ ] Each done step has a row in `docs/live-verification-report.md` 3.7; committed and pushed

### Integration status (2026-10-18 about 13:30 IST; same facts as `docs/sponsor-evidence-matrix.md`)

"Eligible" reads the category text on https://dev.to/challenges/hf26. Status values are defined in
the matrix.

| Integration | Status | Implemented | Unit-tested | Local service | Real provider | Deployed | Eligible (per official text) |
|---|---|---|---|---|---|---|---|
| Gemma | PASS | yes | yes | yes: Ollama `gemma3:4b`, full suite | yes: `gemma-4-31b-it` on Google's Gemini API, full suite 8/3/1 (DigitalOcean not called) | n/a | yes: "run it locally" |
| Mastra | PASS (local framework) | yes | yes (`npm test` 5/5) | yes: full suite on `qwen3:8b` | n/a (open-source framework) | n/a | yes: "orchestrate an agent over open models" |
| Temporal | LOCAL ONLY | yes | yes (test server) | yes: dev server, crash + resume | no (no Temporal Cloud; not required) | n/a | with caveat: text says "make your agent durable"; ours makes the evaluation run durable |
| Render | PASS (read-only) | yes | yes (`tests/test_server.py`) | yes: Docker image | yes: Render hosting | yes, read-only, `ace4e9f`; live mode in progress | yes, weak read-only: text says "AI runtime" or "host an agent's front end"; strong once live mode runs the agent on Render |
| DigitalOcean | BLOCKED | yes | yes (stub) | OpenAI-compatible client live via Ollama `/v1` and the Gemini API (neither is DigitalOcean) | no (no key) | no (App Platform spec unvalidated) | not yet: needs a real call; text names hosting, GPU Droplets or the Gradient AI Platform |
| Sentry Agent Tracing | MOCK ONLY | yes | yes (real SDK, in-memory transport) | n/a | no (no dedicated DSN) | n/a | not yet: text asks for traces/screenshots, latency, tokens, cost, a finding |
| ElevenLabs | PASS | yes | yes (fakes, stub, live test) | n/a | yes: TTS + STT live, 3 cases end to end with local `qwen3:8b` | n/a | fits "transcribe audio for a local model" |
| MongoDB Atlas | LOCAL ONLY | yes | yes | local MongoDB 7.0.45 | no (no dedicated Atlas cluster) | n/a | not yet: text says "use Atlas" |
| Tiger Data | LOCAL ONLY | yes | yes | local TimescaleDB + pgvector | no (no dedicated Tiger Cloud service) | n/a | not yet (matrix: only Tiger Cloud counts) |
| Backboard | PARTIAL | yes | yes (stubs from real responses) | n/a | yes, partly: real API round trip and memory isolation; paid models blocked by billing; free preview model 3 of 4 cases | n/a | not yet: needs ≥2 open-weight models through one key |
| .tech domain | not started | no | n/a | n/a | no | no | no: needs a claimed domain serving the demo |

### Next two integrations before the deadline

Ranked by value per hour; both need only a free account, and secrets go in the shell
(`read -rs NAME && export NAME`) or Render's Environment tab, never in chat, files or screenshots.

1. **DigitalOcean (category $200; also upgrades Render to live mode and gives a hosted Gemma 4 result)**
   about 60 min. Key: Control Panel > Inference (Gradient AI) > Model Access Keys > Create
   (https://cloud.digitalocean.com/model-studio/manage-keys). Variable: `MODEL_ACCESS_KEY`. Commands:
   step 3 (model list, probe, then one case and the suite with `--model gemma-4-31B-it --tool-mode json`).
   Then Render dashboard > `bolibench-demo` > Environment: add `MODEL_ACCESS_KEY` and
   `BOLIBENCH_DEMO_TOKEN` (`openssl rand -hex 24`); `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_TOOL_MODE=json`
   and `AGENT_API_KEY_ENV=MODEL_ACCESS_KEY` must also be there, because the service was created with the
   CLI from `render.yaml`'s non-secret values; check before saving. Evidence: model list, probe output, smoke
   and suite `summary.json` counts, agent version ending `+gemma-4-31B-it+openai-json`, `/health`
   `"live": true`, one `/api/live-run` output, `rg -F "$MODEL_ACCESS_KEY" runs/ /tmp/do-agent.log` empty.
2. **Sentry Agent Tracing ($100)** about 45 min, local only (no Render change). Key: sentry.io > new
   Python project > Project Settings > Client Keys (DSN). Variables: `SENTRY_DSN`, optional
   `SENTRY_TRACES_SAMPLE_RATE=1.0`. Commands: step 4 (`uv run --extra sentry python
   examples/ollama_agent.py --model qwen3:8b --port 8000`, then the suite into
   `runs/sentry-qwen3-8b-2026-10-18/`). Evidence: trace waterfall with `gen_ai.invoke_agent` > `chat` /
   `execute_tool` and token counts, AI Agents dashboard, one conversation, one finding (latency or
   tokens), `ORD-201` / `Please cancel` absent from traces; error issue without locals if DO is done.

Why this order: DigitalOcean is a $200 category and its key also makes Render strong; Sentry needs no
deploy and is the next most direct evidence. ElevenLabs is third (key + voice id, about 45 min).

## 13. Write and publish the post (Sun 19:30 – 23:00 IST)

1. Open the template from the challenge page (front matter `tags: devchallenge, hf26challenge`).
   Paste `docs/dev-post-draft.md`. Replace every TODO with a recorded result or delete it.
2. Prize Categories: keep a category only if its evidence is in the post; delete the others.
3. Final checks:
   - [ ] Repo link, demo link and video work logged out
   - [ ] Every number matches an audit doc, `summary.json` or the verification report
   - [ ] Caveats stated: single unseeded runs, no native-speaker review, JSON tool mode for Gemma,
         local vs hosted for each integration, Temporal = durable evaluation run
   - [ ] No key, DSN, token or connection string in text, code blocks or screenshots
   - [ ] No TODO left
   - [ ] README lists any commit made after the deadline
4. Publish, then reread the public page.

Mon Oct 19 before 12:29 PM IST: fixes only. No new features.

## If time runs out, drop in this order

Backboard, .tech, Tiger Data, MongoDB Atlas, ElevenLabs, Temporal screenshots, Sentry, DigitalOcean.
Never drop: the pushed repo, the Render link or the video, the post's writing.
