<!--
DRAFT for the DEV post, following the official Side Hustle template
(https://dev.to/challenges/hacktoberfest-week2-2026-10-12).
Every number below comes from docs/audits/, docs/integrations/mastra.md, demo/runs/*/summary.json or
docs/live-verification-report.md. Replace or delete every TODO before publishing; never fill one with
an estimate. Category state: docs/sponsor-evidence-matrix.md. Runbook: docs/submission-checklist.md.
-->

---
title: "Your Hindi support bot said \"done\". Did it cancel the right order?"
published: false
tags: devchallenge, hf26challenge, opensource, ai
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

## What I Built

A customer types: **"कुर्ती वाले order की quantity 2 कर दो।"** ("Make the kurti order quantity 2.")

The agent answers in fluent Hindi: *"कुर्ती वाले ऑर्डर (ORD-701) की क्वांटिटी सफलतापूर्वक 2 कर दी गई है।"*
("The kurti order (ORD-701) has been updated to 2.")

It reads perfectly, and it's wrong. ORD-701 is the customer's **kurta**. The kurti is ORD-702, and
nobody touched it. Grade that conversation by reading it, or by asking another LLM whether the reply
sounds right, and it passes. The customer gets two kurtas.

**BoliBench** is an open-source benchmark that doesn't believe the reply. It runs your agent against
a sandboxed order system, records every tool call the agent actually makes, and judges the
sandbox's **final state**: which order got cancelled, which quantity changed, whether the agent asked
before acting, whether it retried a flaky tool, whether it broke store policy. What the agent says it
did is stored, and never used as evidence.

The suite is 12 hand-written order-management cases in the language people actually use in north
India: Hindi-English code-switching (*"मेरा Kurta वाला order cancel कर दो please"*), Awadhi-influenced
Hindi (*"ऊ वाला order जउन कल मँगाए रहेन, ओका रद्द कइ दें"*), vague references (*"वो लाल वाला"*),
mid-sentence corrections (*"2 कर दो… नहीं नहीं, 3 कर दो"*), look-alike items (Kurta and Kurti) and sellers
(Mohan Stores and Sohan Stores), a forbidden bulk cancel, and injected tool failures.

### Who would pay for this

- **Teams shipping Hindi, Hinglish or Awadhi support and voice agents** for Indian commerce, D2C
  brands and small sellers. Their question isn't "is the reply fluent?" It's "did the agent cancel the
  right order, and only that one?" A wrong cancellation costs a refund, a sale and an angry call.
- **Voice-agent builders and agencies** who swap models and prompts every week and need a regression
  run that says which behavior broke, case by case, before customers find out.

What they'd pay for isn't the 12 public cases. It's private suites built from their own order flows,
native-speaker review of those cases, and the same regression run wired into their CI.

TODO (only if true): first user, what they said, whether they'd pay. Otherwise delete this line.

## Demo

**Live demo:** TODO Render URL (and the .tech domain only if claimed and serving it).

The page explains what BoliBench checks, then puts the 12 cases against five real runs side by side:
every verdict links to its full artifact (transcript, every tool call, final state, each check). An
integrations panel says, for each sponsor technology, how far it has actually been verified: local,
hosted, or only against stubs. Anyone can post a scripted agent to the real evaluator, and a token
holder can run a case live against an open-weight model hosted on DigitalOcean (TODO: keep only if
live mode is on, with one result).

**Video (2–3 min):** TODO link. The kurta/kurti failure, the demo page, a run comparison, one artifact
explained, the integrations panel.

## Code

{% github CodewithJha/bolibench %}

Apache-2.0.

```sh
uv sync
uv run bolibench validate suites/orders        # schema-check the cases
uv run bolibench review-sheet suites/orders    # a blank sheet for a native speaker to review the cases
uv run bolibench run suites/orders --agent-url http://127.0.0.1:8000/turn --timeout 180 --output runs/
```

Any agent can take part: BoliBench POSTs each user turn to your agent, hands it a per-turn tool URL,
and records whatever it calls there. Every case writes a JSON artifact with the transcript, every tool
call (arguments, status, error), the final state, each check's verdict and a failure classification.

## How I Built It

**The judge.** A Python sandbox holds the orders and exposes five tools (`list_orders`, `get_order`,
`cancel_order`, `update_quantity`, `ask_user`). Every attempt is logged as `ok`, `rejected` or
`injected_failure`, and only `ok` calls change state. Each case is judged by plain, deterministic
checks: the final state, required actions (need a successful call), forbidden actions (any attempt
fails, even a rejected one), ask-before-acting, and evidence present. Missing evidence is
`inconclusive`, never `pass`. The agent never sees the case id or the expected outcome.

**The agents, all on open-weight models running locally through Ollama:**

- `examples/ollama_agent.py`, a small stdlib agent using Ollama's tool calling.
- The same agent with a **JSON tool mode**, for models that have no native tool calling in Ollama.
  That's how Gemma runs: `gemma3:4b` doesn't advertise `tools` in Ollama, so the agent describes the
  tools in the prompt and accepts a call only if the whole reply is exactly
  `{"tool_calls": [...]}`. Nothing is repaired or guessed.
- A **Mastra** TypeScript agent (`examples/mastra-agent`) on `qwen3:8b`, to check that BoliBench judges
  a framework-built agent the same way.

**What the runs showed.** Every row is one unseeded run of the same 12 cases; caveats follow.

| Run | Pass / fail / error (of 12) |
|---|---|
| qwen3:8b, example agent v1 | 3 / 9 / 0 |
| qwen3:8b, example agent v2 (prompt + loop fixes) | 6 / 6 / 0 |
| qwen3:8b, example agent v3 (native tools) | 6 / 6 / 0 |
| gemma3:4b, same v3 agent file, JSON tool mode | 2 / 10 / 0 |
| qwen3:8b, Mastra agent | 6 / 6 / 0 |

*The v1 agent mostly failed on behavior, not language.* It invented order ids (`123456`, `789012`)
or passed words like `लाल वाला` ("the red one") as an id, asked the customer a question and then acted
without waiting for the answer, and passed an injected "503 … please retry" error straight to the
customer. In the bulk-cancel case it said *"सभी आदेश रद्द कर दिए गए हैं"* ("all orders have been
cancelled") and did exactly that, against a store policy it had been given.

*v2 changed only the agent:* look orders up instead of guessing, a question ends the turn, retry a
temporary failure once. Rejected tool calls went from 11 to 0, and both injected failures were
retried. But two cases that passed before now failed: the agent became over-cautious and asked
"which order?" when the Awadhi and Mohan/Sohan requests were already specific. BoliBench flagged the
regression as plainly as the improvement, which is the whole point.

*Gemma's 2/12 is mostly a tool-format result, not a language result.* In 7 of its 12 cases Gemma
wrote a tool call in the right shape that the strict parser refused: a trailing full stop, a missing
closing brace, or a sentence before the JSON. No tool ran, and the raw JSON became the reply. In the
kurta/kurti case its rejected call was *exactly* right (ORD-702, quantity 2), where qwen picked the
wrong order. In the bulk-cancel case Gemma declined outright, which follows the policy more directly
than qwen's "do you want to cancel all of them?". So this run compares model *plus* tool interface,
and the parser stays strict on purpose: in production, an almost-JSON call does nothing.

*Mastra:* the framework agent's per-case verdicts matched the Python v2 run exactly. With one run
each, that's a coincidence worth noting, not proof the two behave the same.

The local Gemma evaluation is `gemma3:4b` (2/12, JSON tool mode). Gemma 4 (`gemma-4-31B-it`) is the
hosted model behind the demo's live mode on DigitalOcean. DigitalOcean doesn't list tool calling for
it, so it runs in the same JSON tool mode. TODO: its smoke and suite counts, or delete these two
sentences.

**Can the runs be repeated?** A day later I reran three of Gemma's cases and two of Mastra's, with
the same model digests and agent files. Every verdict, every tool call (tool, arguments, status) and
every final state came out the same as in the bundled runs; only the wording of the replies changed.
That's five cases, not a reproducibility study, but it means the bundled artifacts are what these
agents actually do, not a lucky draw.

Full per-case audits are in the repo:
[v1 baseline](https://github.com/CodewithJha/bolibench/blob/master/docs/audits/qwen3-8b-baseline-2026-10-17.md),
[v2](https://github.com/CodewithJha/bolibench/blob/master/docs/audits/qwen3-8b-agent-v2-2026-10-17.md),
[Gemma](https://github.com/CodewithJha/bolibench/blob/master/docs/audits/gemma-gemma3-4b-2026-10-17.md),
[Mastra](https://github.com/CodewithJha/bolibench/blob/master/docs/integrations/mastra.md), and every
integration check, with commands and results, in the
[verification report](https://github.com/CodewithJha/bolibench/blob/master/docs/live-verification-report.md).

**Caveats, from the audits**

- Single unseeded runs at each model's default temperature (qwen 0.6, Gemma 1). Per-case differences
  may be sampling noise. None of this measures qwen3:8b or Gemma in general.
- The v2 fixes were written after seeing v1 fail on the same 12 cases, so v2's score is not an
  unbiased estimate even for that agent.
- Gemma ran in prompt-based JSON tool mode and qwen in native mode. The JSON prompt was written once
  and deliberately not tuned on the suite.
- No case has been reviewed by a native speaker yet, so every language-related diagnosis is low
  confidence.

**Sponsor integrations, and how far each is verified.** I held the integrations to the same rule as
the agents: a claim needs a recorded run. Each one below says whether it ran against the real hosted
service, against the sponsor's software on my laptop, or only against stubs.

- **Mastra:** `examples/mastra-agent`, a TypeScript agent built on `@mastra/core`, orchestrates
  `qwen3:8b` through BoliBench's tool gateway. Full suite above; it also rejects malformed requests
  (400, 413, 404, 409) without falling over.
- **Temporal:** `python -m bolibench.temporal_run` runs a suite as a Temporal workflow, one activity
  per case. On the local dev server, its summary was byte-identical to a plain `bolibench run`. I
  `kill -9`'d the worker in the middle of a case and restarted it: Temporal re-ran that case (attempt
  2) and the run completed. Starting the same workflow again re-ran nothing. This makes the
  *evaluation* durable. The agent itself isn't a workflow, and the crash test used a deliberately slow
  stub agent so the kill would land mid-case. TODO: UI screenshots.
- TODO **Sentry Agent Tracing:** the agent emits `gen_ai.invoke_agent`, `gen_ai.chat` and
  `gen_ai.execute_tool` spans with token counts, grouped per case as a Sentry Conversation. Prompts
  and replies go to Sentry only if you opt in. While checking this against Sentry's docs, a test
  caught a real leak: with the SDK's default local-variable capture, an error event from a failed
  model call carried the customer's utterance and the `Authorization: Bearer` header with the API key.
  The SDK's scrubber caught only a variable literally named `api_key`. The agent now turns local
  variables off, and a test keeps them off. Trace screenshot, latency and tokens per turn, cost ($0:
  the model is local), and one thing a trace helped debug.
- TODO **ElevenLabs:** `bolibench run --speech elevenlabs` speaks each utterance with TTS, transcribes
  it with STT, and gives the agent only the transcript (stored as `asr_text`). Real numbers: how many
  turns ASR changed, whether any verdict moved. Synthetic voices, not real speakers.
- TODO **Render + DigitalOcean:** the demo is one Docker container on Render. The image is 47 MB
  compressed, runs as `nobody` on a read-only filesystem, and starts read-only with no configuration.
  With a DigitalOcean key and a demo token, the same container also runs the example agent on an
  open-weight model served by DigitalOcean's serverless inference, so a case can run live from the
  page. URL, one live result, the DigitalOcean suite counts.
- TODO **MongoDB Atlas / Tiger Data:** `bolibench export` sends run history to Atlas, or to Tiger as a
  hypertable. Tiger also stores EmbeddingGemma embeddings of every failure in pgvector for a keyword +
  vector "have we seen this failure before?" search. Rehearsed on local MongoDB 7 and TimescaleDB +
  pgvector (22 failures indexed; the top matches for a failure were the same case in other runs).
  Atlas and Tiger Cloud screenshots.
- TODO **Backboard:** the same suite on two or more open-weight models through one Backboard key,
  counts side by side.

## Why Does Open Innovation Matter?

**Because the data is the customer's.** Order histories, names, addresses and complaints are exactly
what a support team can't paste into someone else's API. With an open-weight model in Ollama, the
agent under test, the sandbox and every artifact stay on one laptop.

**Because regression runs have to be cheap enough to run every time.** A team tuning prompts wants
the suite after every change. Locally, the Gemma run took 82 seconds and the qwen v3 run 3 minutes 15,
on a 16 GB laptop, with no bill. Metered runs get run less often, and the regressions slip through.

**Because the judge has to be inspectable.** A benchmark that tells you "your agent cancelled the
wrong order" must be something you can read, rerun and argue with. BoliBench's checks are plain
deterministic code, with no hidden LLM grader. When we found a bug in our own failure classifier, the
fix and the reasoning went into a public audit.

**Because pinned weights make results attributable.** Each audit records the exact model digest and
the agent file's hash. When the score moved from 3/12 to 6/12, the weights were byte-for-byte the
same, so the change comes from the agent code (or, with one run each, from sampling), never from a
provider quietly updating the model behind an API.

**Because we control the whole stack.** With the weights on our own machine we could put Gemma
behind a different tool interface than qwen, run both on the same agent file, and read every raw
reply. That's how we learned Gemma's failures were mostly formatting, not understanding: in the
kurta/kurti case its rejected call was right where the other model's accepted call was wrong.

**Because these languages need their speakers.** Awadhi and everyday Hinglish are where generic tools
are weakest. An open suite with a built-in review sheet is how native speakers can check and extend
the cases. That review hasn't happened yet, and it's the next thing BoliBench needs.

## Limitations

- **No native-speaker review yet.** All 12 cases are synthetic and marked `proposed`. Nothing in
  BoliBench understands Hindi or Awadhi; case correctness rests on the people who wrote them.
- **Transcript-level** unless the ElevenLabs speech round-trip is used, and that uses synthetic voices
  (TODO: keep this line only if the speech run happened).
- **12 cases, single unseeded runs.** The counts are not model measurements.
- **Integrations are verified only as far as stated.** Where a line above says local or stubs, the
  hosted service hasn't been exercised.
- The agent under test must run next to BoliBench (localhost only). That's a dev safeguard, not a
  security boundary.

## My Agent Session

TODO (optional): a DevRelay embed, only if captured and reviewed. Otherwise delete this section.
(Entire checkpoints are kept private, so no Entire link.)

## My First User

TODO: delete this section unless a real person used it. Don't invent one.

## Prize Categories

<!-- List only categories whose evidence is in this post at publishing time. Delete every line
whose "needs" step hasn't produced its evidence, and remove the "needs" notes from the rest. -->

- Best Use of Gemma: `gemma3:4b` run audited above (2/12, JSON tool mode), plus EmbeddingGemma for
  failure search. Ready.
- Best Use of Mastra: the Mastra agent's full-suite run above. Ready.
- Best Use of Temporal: the suite run as a durable workflow that resumed after `kill -9` (a durable
  evaluation run). Needs: UI screenshots.
- Best Use of Render: the live demo. Needs: the deploy, ideally with live mode on.
- Best Use of DigitalOcean: the suite and the live demo on DigitalOcean serverless inference. Needs:
  model access key, runs.
- Best Use of Sentry Agent Tracing: traces above. Needs: DSN, traced run, screenshots.
- Best Use of ElevenLabs: the speech round-trip run above. Needs: API key, speech run.
- Best Use of MongoDB Atlas: run history in Atlas. Needs: Atlas cluster, export, screenshot.
- Best Use of Tiger Data: pgvector failure search on Tiger Cloud. Needs: Tiger Cloud service,
  export, screenshot.
- Best Use of Backboard: two or more open-weight models through one key. Needs: key, two full runs.
- Best Use of a .tech Domain: only if claimed through Hacktoberfest and serving the live demo.

Not entered: Entire, GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino.

<!-- Team Submissions: credit teammates' DEV usernames here if any. -->
