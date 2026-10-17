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
2. **Repo must exist publicly.** `origin` is `github.com/CodewithJha/bolibench`, but nothing has
   been pushed yet. Push before posting.
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

## Category status (2026-10-17, 22:45 IST)

Detail, evidence gaps and user actions per row: `docs/sponsor-evidence-matrix.md`. Runbook:
`docs/submission-checklist.md`.

| Sponsor | What exists | Status | Enter? |
|---|---|---|---|
| Gemma | JSON tool mode in the example agent; `gemma3:4b` full suite run (2/12, audited); EmbeddingGemma in the Tiger exporter. Local Gemma evaluation = `gemma3:4b` only (2/12, JSON tool mode); Gemma 4 only as the hosted DigitalOcean `gemma-4-31B-it` in the deploy config, tool calling unverified | live-verified (local) | yes |
| Mastra | `examples/mastra-agent` on local `qwen3:8b`, full suite 6/12 | live-verified (local) | yes |
| Sentry Agent Tracing | `gen_ai` agent/chat/tool spans in the example agent | implemented-local; evidence pending (DSN, trace screenshots) | if screenshots |
| ElevenLabs | `bolibench run --speech elevenlabs` | implemented-local; evidence pending (key, one live run) | if live run |
| DigitalOcean | `--backend openai` for serverless inference; `.do/app.yaml` | implemented-local; evidence pending (key, tool probe, run or deploy) | if run or deploy |
| Render | `render.yaml` + demo server with live mode | implemented-local; evidence pending (deploy). Read-only demo alone: needs rule clarification | if deployed with live mode |
| .tech Domain | nothing registered | evidence pending (claim + DNS) | if live on Render/DO |
| MongoDB Atlas | `bolibench export --to mongo` | implemented-local; evidence pending (cluster, screenshot) | if exported |
| Tiger Data | `bolibench export --to tiger` with pgvector + full-text hybrid search | implemented-local (embeddings live, database not); evidence pending | if exported |
| Backboard | `examples/backboard_agent.py` | implemented-local; evidence pending (key, ≥2 models) | if ≥2 model runs |
| Temporal | `python -m bolibench.temporal_run` | implemented-local (test server); needs rule clarification (durable eval, not agent) | optional, label honestly |
| Entire | CLI enabled; checkpoints kept local, not pushed | not entered unless sessions are published | if a public link exists |
| GitHub Copilot | — | not relevant (not used) | no |
| Tinker | — | not relevant (not planned) | no |
| TabPFN | — | not relevant | no |
| SerpApi | — | not relevant | no |
| Arduino | — | not relevant | no |

Since only one prize is possible and writing counts most, lead with the overall story and list only
categories whose evidence is in the post at publishing time.
