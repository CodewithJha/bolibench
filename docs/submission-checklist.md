# Submission runbook (HF26 Week 2: Side Hustle)

**Hard deadline: Sun Oct 18 2026, 11:59 PM PDT = Mon Oct 19 2026, 12:29 PM IST.**
Target: publish by **Sun Oct 18, 11:00 PM IST**; Monday morning is buffer only.

Official pages: [challenge + template + FAQ](https://dev.to/challenges/hacktoberfest-week2-2026-10-12),
[contest rules](https://dev.to/page/hacktoberfest-week2-2026-10-12-contest-rules),
[credits](https://hacktoberfest.com/my/promos). State of every category:
`docs/sponsor-evidence-matrix.md`.

Ground rules for every step:

- One prize per person, one entry (only the first is judged). Writing quality is weighted most.
- A category goes in the post's Prize Categories section only when its evidence is in the post.
- Keys only in your shell (`read -rs NAME && export NAME`), never in files, flags, the post or
  screenshots. After every live run: `rg -F "$THE_KEY" runs/ audio-cache/` must print nothing.
- Each step has a time box. If a step overruns, drop that category and move on.
- Commits after the deadline must be listed in the README (FAQ rule).

## 0. Sat 22:45 – 23:45 IST: identity, commit, push (required)

The rules require a code link. `origin` is `https://github.com/CodewithJha/bolibench.git`; nothing is pushed.

1. Set a noreply email first (the local config has a personal address). GitHub > Settings > Emails
   shows your `<id>+<username>@users.noreply.github.com`:
   ```sh
   git config user.email "<id>+<username>@users.noreply.github.com"
   git config user.name "<name>"
   ```
   The two initial commits were rewritten to this noreply identity before the first push (now
   `1a91e20`, `4c7af08`); README and the audits cite the new hashes.
2. Entire stays enabled, but its checkpoints are kept local and not pushed: `push_sessions` is false
   in the gitignored `.entire/settings.local.json`, and the first push skips Entire's pre-push hook,
   so no agent session data goes to the public repo. Check `entire status` before any later push.
3. Review what gets committed. The editor's local hook directory, `runs/`, `.env`, `audio-cache/`
   and `*.mp3` are ignored. `demo/runs/` (bundled artifacts) must be committed. Commits are made
   from a normal terminal, not an editor's agent shell.
   ```sh
   git status --short
   uv run pytest -q && uv run bolibench validate suites/orders
   git add <paths> && git commit -m "..." && git push -u origin master
   ```
4. Open the GitHub page logged out: README renders, LICENSE (Apache-2.0) shows.

## 1. Sun 09:00 – 10:30 IST: credits, DigitalOcean key, tool probe, Render deploy

1. Claim credits and the .tech domain at https://hacktoberfest.com/my/promos (Render, Backboard,
   Tinker, .tech). Note what you got.
2. DigitalOcean model access key: Control Panel > Inference > Model Access Keys > create
   (https://cloud.digitalocean.com/model-studio/manage-keys).
   ```sh
   read -rs MODEL_ACCESS_KEY && export MODEL_ACCESS_KEY
   curl -s -H "Authorization: Bearer $MODEL_ACCESS_KEY" https://inference.do-ai.run/v1/models | python3 -m json.tool | grep '"id"'
   curl -s https://inference.do-ai.run/v1/chat/completions -H "Authorization: Bearer $MODEL_ACCESS_KEY" \
     -H "Content-Type: application/json" -d '{"model": "gemma-4-31B-it",
     "messages": [{"role": "user", "content": "List my orders."}],
     "tools": [{"type": "function", "function": {"name": "list_orders", "description": "List all orders.",
       "parameters": {"type": "object", "properties": {}, "required": []}}}]}' | python3 -m json.tool | grep -A3 tool_calls
   ```
   No `tool_calls`: use `AGENT_TOOL_MODE=json` or another model (e.g. `openai-gpt-oss-120b`). Save the
   probe output (without the key) as DigitalOcean evidence.
3. One case against DO from the laptop (DigitalOcean + Gemma 4 evidence):
   ```sh
   python3 examples/ollama_agent.py --backend openai --base-url https://inference.do-ai.run/v1 \
     --api-key-env MODEL_ACCESS_KEY --model gemma-4-31B-it --tool-mode native --port 8000
   uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8000/turn \
     --timeout 180 --output runs/do-gemma-4-31b-smoke-2026-10-18/
   ```
   If it works, run the full suite into its own directory.
4. Render: Dashboard > New > Blueprint > pick the repo. Enter `MODEL_ACCESS_KEY` and
   `BOLIBENCH_DEMO_TOKEN` (`openssl rand -hex 24`) when prompted. If step 2 said JSON mode, add
   `AGENT_TOOL_MODE=json`. Apply, wait for the deploy, then:
   ```sh
   BASE=https://<service>.onrender.com
   curl -s $BASE/health                                   # "live": true
   curl -s -X POST --data-binary @demo/example-request.json $BASE/api/evaluate | python3 -c 'import json,sys; print(json.load(sys.stdin)["evaluation"]["verdict"])'
   curl -s -X POST -H "Authorization: Bearer $BOLIBENCH_DEMO_TOKEN" -d '{"case_id": "cancel-single-order"}' $BASE/api/live-run \
     | python3 -c 'import json,sys; e=json.load(sys.stdin); print(e["verdict"], e["agent"], [c["tool"] for c in e["artifact"]["run"]["tool_calls"]])'
   ```
   Evidence: the URL, a dashboard screenshot, one live-run result. The free plan sleeps when idle;
   open the URL once before judges might. Optional: `doctl apps create --spec .do/app.yaml` (a $5/month
   instance) for a DigitalOcean-hosted copy.

## 2. Sun 10:30 – 12:30 IST: Sentry traced run, ElevenLabs speech run

Start the local agent once (`ollama serve` running, `qwen3:8b` pulled).

1. Sentry: create a Python project, copy the DSN (Project Settings > Client Keys).
   ```sh
   read -rs SENTRY_DSN && export SENTRY_DSN
   uv run --with 'sentry-sdk>=2.64' python examples/ollama_agent.py --model qwen3:8b --port 8000
   uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/sentry-qwen3-8b-2026-10-18/
   ```
   Screenshots (the category text asks for setup, latency, tokens, cost, findings, debugging):
   Explore > Traces, search `span.op:gen_ai.invoke_agent`; one trace with `chat` and `execute_tool`
   children and their durations; token counts on a `chat` span; the AI Agents page; the
   Conversations view for one case. Cost: local Ollama is $0; say so rather than showing a number.
   Write down one thing you found from a trace (e.g. which turn spent most time in model calls).
   Check that no span holds a Devanagari utterance (content capture is off by default).
2. ElevenLabs: create a key restricted to TTS + STT with a credit quota; pick a Hindi-capable voice.
   ```sh
   read -rs ELEVENLABS_API_KEY && export ELEVENLABS_API_KEY
   export ELEVENLABS_VOICE_ID=<voice id>
   BOLIBENCH_LIVE=1 uv run pytest -q -s tests/test_speech.py -k live
   uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 \
     --speech elevenlabs --speech-audio-dir audio-cache --output runs/speech-qwen3-8b-2026-10-18/
   rg -F "$ELEVENLABS_API_KEY" runs/ audio-cache/
   ```
   Evidence: one artifact excerpt with `user_input` vs `asr_text`, the counts, and any misheard words
   (listen to the Awadhi mp3s). The speech run is synthetic TTS audio, not real speakers; say so.

## 3. Sun 12:30 – 14:30 IST: MongoDB Atlas, Tiger Data, Backboard

1. Atlas: create an M0 cluster, a `readWrite` user, add your IP, copy the Python connection string.
   ```sh
   read -rs MONGODB_URI && export MONGODB_URI
   R=runs/qwen3-8b-agent-v3-2026-10-17/20261017T164911Z-2927942a
   uv run --with pymongo bolibench export --to mongo --dry-run $R
   uv run --with pymongo bolibench export --to mongo $R runs/gemma-gemma3-4b-2026-10-17/20261017T164713Z-a6d439e3 --suite suites/orders
   uv run --with pymongo bolibench export --to mongo --report
   ```
   Screenshot: Atlas Data Explorer, `bolibench.case_results`, one document expanded.
2. Tiger Data: create a Tiger Cloud service, save the credentials file.
   ```sh
   read -rs TIGER_DATABASE_URL && export TIGER_DATABASE_URL
   ollama pull embeddinggemma
   uv run --with 'psycopg[binary]' bolibench export --to tiger --failures \
     runs/qwen3-8b-baseline-2026-10-17/20261017T064824Z-6ec70da2 runs/qwen3-8b-agent-v2-2026-10-17/20261017T070131Z-317851a2
   uv run --with 'psycopg[binary]' bolibench export --to tiger --similar \
     runs/qwen3-8b-agent-v3-2026-10-17/20261017T164911Z-2927942a/similar-items-kurta-kurti.json --k 5
   uv run --with 'psycopg[binary]' bolibench export --to tiger --report
   ```
   Evidence: `SELECT * FROM timescaledb_information.hypertables;`, the `--similar` output, a console
   screenshot of `bolibench_failures`. This is the first time the pgvector SQL meets a real database;
   if it fails, record the error and drop the category.
3. Backboard: get the key from app.backboard.io (credits from step 1).
   ```sh
   read -rs BACKBOARD_API_KEY && export BACKBOARD_API_KEY
   curl -s "https://app.backboard.io/api/models?model_type=llm&supports_tools=true&provider=openrouter&limit=100" \
     -H "X-API-Key: $BACKBOARD_API_KEY" | python3 -m json.tool | less
   python3 examples/backboard_agent.py --provider openrouter --model <open-weight model> --port 8001
   uv run bolibench run suites/orders/cancel-single-order.json --agent-url http://127.0.0.1:8001/turn \
     --timeout 180 --output runs/backboard-<model>-smoke-2026-10-18/
   ```
   The category is about comparing open-weight models through one key: enter it only with full-suite
   runs of at least two models.

## 4. Sun 14:30 – 15:30 IST: Temporal screenshots, .tech domain

1. Temporal (category text is "make your agent durable"; describe it honestly as a durable
   evaluation run):
   ```sh
   temporal server start-dev --db-filename temporal.db          # UI http://localhost:8233
   uv run --extra temporal python -m bolibench.temporal_run worker
   uv run --extra temporal python -m bolibench.temporal_run start suites/orders \
     --agent-url http://127.0.0.1:8000/turn --timeout 180 --workflow-id demo-1 --output runs/temporal/
   ```
   After a few cases, `kill -9` the worker, restart it, let `start` finish. Screenshots: workflow list
   with `demo-1` Completed; Event History with one `bolibench.run_case` per case; the retried attempt.
   Check `runs/temporal/demo-1/` holds exactly 12 case files plus `summary.json`.
2. .tech: claim through Hacktoberfest (required by the category). Render service > Settings > Custom
   Domains > add `demo.<name>.tech`; at get.tech DNS add a `CNAME` `demo` → `<service>.onrender.com`.
   `dig +short CNAME demo.<name>.tech`, then load it over HTTPS.

## 5. Sun 15:30 – 16:30 IST: Entire, Gemma

1. Entire: checkpoints are kept local and not pushed, so the Entire category is not entered. Only if
   you later decide to publish sessions: read the session first, then `entire login`, then
   `entire repo create --help` and follow it to get a shareable entire.io page;
   `entire checkpoint list` should show the checkpoint.
2. Gemma: the local Gemma evaluation is `gemma3:4b` only (2/12, JSON tool mode). Gemma 4 is only
   used as the hosted DigitalOcean model `gemma-4-31B-it` in the deploy config; its tool calling is
   unverified. Check the post says exactly this.

## 6. Sun 16:30 – 19:30 IST: demo video and post

1. Video (2–3 min, the rules need a deployed link **or** a video; have both if you can):
   the problem in one sentence; `bolibench run` on the suite; open `similar-items-kurta-kurti` where
   the agent's fluent reply claims the Kurti but the sandbox shows the Kurta changed; the demo page on
   Render/.tech; one Sentry trace; the speech `asr_text`. Upload (YouTube unlisted or similar).
2. Post: open the template from the challenge page (front matter `tags: devchallenge, hf26challenge`).
   Paste `docs/dev-post-draft.md`, then replace every TODO with real results or delete it. Sections in
   template order: What I Built, Demo, Code, How I Built It, Why Does Open Innovation Matter?, My Agent
   Session (optional), My First User (only if real), Prize Categories.

## 7. Sun 19:30 – 23:00 IST: check and publish

- [ ] Repo link, demo link and/or video work logged out
- [ ] Every number matches an audit doc or `summary.json`
- [ ] Caveats stated: single unseeded runs, no native-speaker review, gemma3:4b used JSON tool mode
- [ ] No key, DSN, token or connection string in text, code blocks or screenshots
- [ ] No TODO left
- [ ] Prize Categories lists only categories with evidence in the post (see matrix)
- [ ] README lists any commit made after the deadline
- [ ] Publish, then reread the public page

Mon Oct 19 before 12:29 PM IST: fixes only. No new features.

## If time runs out, drop in this order

Backboard, Tiger Data, Temporal, MongoDB Atlas, Entire, .tech, DigitalOcean deploy, ElevenLabs,
Sentry, Render. Never drop: pushed repo, demo link or video, the post's writing.
