# Sponsor integration plan (HF26 Week 2: Side Hustle)

Researched 2026-10-17 from the official pages. Nothing here is a claim that any integration works;
the Status column says what is true as of its date.

Sources (all fetched 2026-10-17):

- Launch post: https://dev.to/devteam/join-the-hacktoberfest-open-source-ai-challenge-side-hustle-2550-in-prizes-across-18-winners-55ba
- Challenge page (theme, categories, template, FAQ): https://dev.to/challenges/hacktoberfest-week2-2026-10-12
- Hub (same category text): https://dev.to/challenges/hf26 (anchors `#best-use-of-<sponsor>`)
- Week 2 contest rules: https://dev.to/page/hacktoberfest-week2-2026-10-12-contest-rules
- General rules: https://dev.to/page/official-hackathon-rules
- Credits: https://hacktoberfest.com/my/promos (login required; not inspected)

## Rules that change strategy

1. **Required elements** (contest rules): published DEV post using the template and `#hf26challenge`;
   a brand-new project built during the Entry Period (Oct 12 12:00 PM PDT to Oct 18 11:59 PM PDT);
   open-weight models / open-source AI as a core part; a Side Hustle angle (something a real person
   or business would plausibly pay for); **a link to a deployed project or a video demo**; **a link
   to or embed of the code repository**; an explanation of why open innovation matters.
2. **Repo must exist publicly.** `origin` is `github.com/CodewithJha/bolibench`; `master` was pushed
   at `0fbd6e8` on 2026-10-17. Push the remaining work before posting.
3. **New-project rule** (FAQ): "all submissions and their respective repositories must be started
   and completed within the challenge window. Commits made after the submission deadline must be
   noted in the project's readme." First commit `1a91e20` is 2026-10-17 12:29 IST (= Oct 16 23:59
   PDT), inside the window. The user must be able to say truthfully that no work predates Oct 12.
4. **Partner categories** (rules): an entry must "meaningfully incorporate that category's
   technology and identify the Prize Category in the submission post". Max **one prize per
   participant** per contest. One entry only; if more are submitted, only the first is judged.
5. **Writing quality is weighted most heavily**; "A great project with a thin write-up won't win."
   Ties go to the post with more positive reactions.
6. **English only** for prize eligibility. 18+. Teams up to four, list DEV handles.
7. **Webhook constraint (BoliBench's own):** `--agent-url` must be `http://127.0.0.1|localhost|[::1]`.
   Any agent evaluated by BoliBench must run next to it; it may call a remote model API. The demo
   container solves this for hosting: its live mode runs the agent on 127.0.0.1 inside the same
   container (`deploy/start.sh`).
8. Credits named officially: Tinker, Render, Backboard, and a free first-year .tech domain
   (renews at $29.99/yr). No other sponsor credits are stated on the official pages.
9. Optional: DevRelay agent-session embed (https://devrelay.com) is encouraged for all entries; it is
   not a partner category. Entire is the partner category for agent sessions.

## Category status (2026-10-18, about 13:30 IST)

Rules re-checked 2026-10-18 00:05 IST: deadline and requirements unchanged. Decisions: a Render deploy
**and** a video demo; Temporal entered as a durable evaluation run; Tiger Data entered via Tiger Cloud.
Evidence per row: `docs/sponsor-evidence-matrix.md` (which defines the status values); commands and
results: `docs/live-verification-report.md`; runbook: `docs/submission-checklist.md`.

| Sponsor | What exists | Status | Enter? |
|---|---|---|---|
| Gemma | JSON tool mode and `--reasoning-effort` in the example agent; `gemma3:4b` full suite 2/12 (audited), 3-case rerun with the same actions; EmbeddingGemma in the Tiger exporter; hosted `gemma-4-31b-it` on Google's Gemini API, full suite 8 pass / 3 fail / 1 error (audited) | **PASS** (local + hosted Gemini API) | yes |
| Mastra | `examples/mastra-agent` on local `qwen3:8b`, full suite 6/12, 2-case rerun with the same actions | **PASS** (local framework) | yes |
| Temporal | `python -m bolibench.temporal_run`; local dev server: parity with `bolibench run`, `kill -9` resume (attempt 2), no re-run on restart | **LOCAL ONLY**; screenshots pending | yes, as a durable **evaluation** run |
| Render | `render.yaml` + demo page with integrations panel and token-gated live mode; deployed read-only at https://bolibench-demo.onrender.com (`ace4e9f`), smoke-tested | **PASS** (deployed, read-only; live mode in progress) | yes |
| DigitalOcean | `--backend openai` (the same client ran live against Ollama `/v1` and the Gemini API, neither DigitalOcean); `.do/app.yaml`; JSON tool mode by default | **BLOCKED** (no key) | yes, once called |
| Sentry Agent Tracing | `gen_ai` agent/chat/tool spans; no local variables on error events | **MOCK ONLY** (pending a dedicated DSN) | yes, once traced |
| ElevenLabs | `bolibench run --speech elevenlabs`; live TTS, STT, live test, CLI with cache, 3 cases end to end with local `qwen3:8b` | **PASS** (hosted) | yes |
| MongoDB Atlas | `bolibench export --to mongo`; live (local) on MongoDB 7.0.45 | **LOCAL ONLY** (Atlas pending user-created credentials) | yes, once on Atlas |
| Tiger Data | `bolibench export --to tiger`, pgvector + full-text hybrid search; live (local) on TimescaleDB 2.30.2 + pgvector 0.8.7 | **LOCAL ONLY** (Tiger Cloud pending a user-created service) | yes, once on Tiger Cloud |
| Backboard | `examples/backboard_agent.py` run against the real API: round trip and memory isolation pass; chosen open-weight model blocked by billing; free preview model 3 of 4 cases | **PARTIAL** (billing) | yes, once ≥2 models run |
| .tech Domain | nothing registered | conditional | only if registered and serving the live demo |
| Entire | CLI enabled; checkpoints kept local, not pushed | not entered | no |
| GitHub Copilot | — | not used | no |
| Tinker | — | not planned | no |
| TabPFN | — | not relevant | no |
| SerpApi | — | not relevant | no |
| Arduino | — | not relevant | no |

Since only one prize is possible and writing counts most, lead with the overall story and list only
categories whose evidence is in the post at publishing time.
