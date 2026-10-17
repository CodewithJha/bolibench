# Sponsor integration plan (HF26 Week 2: Side Hustle)

Researched 2026-10-17 from the official pages. Nothing here is a claim that any integration works;
the Status column says what is true today.

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

## Category status (2026-10-18, IST)

Rules re-checked 2026-10-18 00:05 IST: deadline and requirements unchanged. Decisions: a Render deploy
**and** a video demo; Temporal entered as a durable evaluation run; Tiger Data entered via Tiger Cloud.
Evidence per row: `docs/sponsor-evidence-matrix.md`; commands and results:
`docs/live-verification-report.md`; runbook: `docs/submission-checklist.md`.

| Sponsor | What exists | Status | Enter? |
|---|---|---|---|
| Gemma | JSON tool mode in the example agent; `gemma3:4b` full suite 2/12 (audited), 3-case rerun with the same actions; EmbeddingGemma in the Tiger exporter; hosted `gemma-4-31B-it` (DigitalOcean) in the deploy configs, JSON tool mode, not called yet | live-verified (local) | yes |
| Mastra | `examples/mastra-agent` on local `qwen3:8b`, full suite 6/12, 2-case rerun with the same actions | live-verified (local) | yes |
| Temporal | `python -m bolibench.temporal_run`; local dev server: parity with `bolibench run`, `kill -9` resume (attempt 2), no re-run on restart | live-verified (local); screenshots pending | yes, as a durable **evaluation** run |
| Render | `render.yaml` + demo page with integrations panel and token-gated live mode; image smoke-tested, Blueprint valid | deploy pending (user) | yes, once deployed |
| DigitalOcean | `--backend openai` (live (local) via Ollama `/v1`); `.do/app.yaml`; JSON tool mode by default | hosted call pending (user: key) | yes, once called |
| Sentry Agent Tracing | `gen_ai` agent/chat/tool spans; no local variables on error events | offline-tested; traces pending (user: DSN) | yes, once traced |
| ElevenLabs | `bolibench run --speech elevenlabs` | offline-tested; live run pending (user: key) | yes, once run |
| MongoDB Atlas | `bolibench export --to mongo`; live (local) on MongoDB 7.0.45 | Atlas export pending (user: cluster) | yes, once on Atlas |
| Tiger Data | `bolibench export --to tiger`, pgvector + full-text hybrid search; live (local) on TimescaleDB 2.30.2 + pgvector 0.8.7 | Tiger Cloud export pending (user: service) | yes, once on Tiger Cloud |
| Backboard | `examples/backboard_agent.py`, checked against the documented schemas | offline-tested; runs pending (user: key, ≥2 models) | yes, once ≥2 models run |
| .tech Domain | nothing registered | conditional | only if registered and serving the live demo |
| Entire | CLI enabled; checkpoints kept local, not pushed | not entered | no |
| GitHub Copilot | — | not used | no |
| Tinker | — | not planned | no |
| TabPFN | — | not relevant | no |
| SerpApi | — | not relevant | no |
| Arduino | — | not relevant | no |

Since only one prize is possible and writing counts most, lead with the overall story and list only
categories whose evidence is in the post at publishing time.
