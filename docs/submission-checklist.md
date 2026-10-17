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

From a normal terminal (not an editor's agent shell):

```sh
bash /tmp/bolibench-commit.v3.sh
```

It checks the branch, `origin/master`, your noreply email and the remote; makes the grouped commits;
scans each staged diff for secrets; runs the tests and `validate`; shows the commit list; asks y/N;
then pushes `master` (skipping Entire's pre-push hook, so no checkpoint data is uploaded). Afterwards
open https://github.com/CodewithJha/bolibench logged out: README renders, LICENSE shows.

## 1. Render deploy, read-only first (30 min, required)

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

Procedure: `docs/integrations/elevenlabs.md`, "Live verification".

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

```sh
read -rs BACKBOARD_API_KEY && export BACKBOARD_API_KEY
curl -s "https://app.backboard.io/api/models?model_type=llm&supports_tools=true&provider=openrouter&limit=100" \
  -H "X-API-Key: $BACKBOARD_API_KEY" | python3 -c "import json,sys; [print(m['name']) for m in json.load(sys.stdin)['models']]"
python3 examples/backboard_agent.py --provider openrouter --model <open-weight model A> --port 8002 2> /tmp/bb-agent.log
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

2–3 minutes, screen recording with voice-over, uploaded unlisted (YouTube or similar). Outline:

1. **0:00–0:20 The problem.** Show the `similar-items-kurta-kurti` case: the customer asks to change
   the *kurti* order; the agent replies in fluent Hindi that it did. Say: "It reads perfectly. It's wrong."
2. **0:20–0:45 What BoliBench is.** Twelve Hindi/Hinglish/Awadhi order-support cases; the agent's tool
   calls go into a sandbox; checks judge the final state, never the reply.
3. **0:45–1:15 The live demo page** (Render URL): the case-by-run grid, five bundled runs, pass
   totals per run, click one verdict to open its artifact.
4. **1:15–1:45 A run comparison.** v1 3/12 → v2 6/12, and the two cases v2 broke by over-asking;
   gemma3:4b 2/12 because its tool calls were almost-JSON.
5. **1:45–2:15 One failure with evidence.** In the artifact: `update_quantity` on `ORD-701` (the
   kurta) with status `ok`, the failed final-state check, the reply claiming the kurti.
6. **2:15–2:40 Integrations panel.** What is verified and how (local vs hosted), plus whichever hosted
   evidence exists by then: one live run on Render, a Sentry trace, a speech transcript.
7. **2:40–2:50 Close.** Repo link, "open source, runs on a laptop".

## 12. Evidence capture list (tick before writing the post)

- [ ] Render URL, page screenshot, `/health` output; live-run output (if step 3 done)
- [ ] DigitalOcean probe output, smoke + suite counts, agent version string
- [ ] Sentry: trace waterfall, AI Agents view, conversation, error issue without locals, one finding
- [ ] ElevenLabs: live test lines, `user_input` vs `asr_text`, changed-turn count, usage screenshot
- [ ] Atlas: Data Explorer screenshot, `--report`
- [ ] Tiger Cloud: hypertables query, `bolibench_failures`, `--similar` output
- [ ] Temporal: list, Event History, Attempt 2
- [ ] Backboard: two summary counts, usage screenshot
- [ ] .tech URL over HTTPS (optional)
- [ ] Video URL, plays logged out
- [ ] Each done step has a row in `docs/live-verification-report.md` 3.7; committed and pushed

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
