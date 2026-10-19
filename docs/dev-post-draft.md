<!-- Final draft, 2026-10-19. Every number from docs/audits/, demo/runs/*/summary.json, docs/sponsor-evidence-matrix.md and docs/live-verification-report.md. Only categories with evidence in this post are listed. -->

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

## Demo

**Live demo:** https://bolibench-demo-1b3o.onrender.com

![BoliBench demo: the specimen ledger and a real case as a lab plate](https://raw.githubusercontent.com/CodewithJha/bolibench/master/docs/images/demo-home.png)

The page explains what BoliBench checks, then puts the 12 cases against five real runs side by side:
every verdict links to its full artifact (transcript, every tool call, final state, each check). An
integrations panel says, for each technology, how far it has actually been verified: deployed,
hosted, local, or only against stubs. Anyone can replay a scripted agent against the real evaluator
for free, and a token holder can run a case live against the hosted open-weight model (Gemma 4,
`gemma-4-31b-it`); one hosted live run of `cancel-single-order` passed in 35 seconds.

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

![Selecting a verdict shows the evidence: the request, the agent's recorded actions, and the checks that failed](https://raw.githubusercontent.com/CodewithJha/bolibench/master/docs/images/evidence-view.png)

## How I Built It

**The judge.** A Python sandbox holds the orders and exposes five tools (`list_orders`, `get_order`,
`cancel_order`, `update_quantity`, `ask_user`). Every attempt is logged as `ok`, `rejected` or
`injected_failure`, and only `ok` calls change state. Each case is judged by plain, deterministic
checks: the final state, required actions (need a successful call), forbidden actions (any attempt
fails, even a rejected one), ask-before-acting, and evidence present. Missing evidence is
`inconclusive`, never `pass`. The agent never sees the case id or the expected outcome.

Each case is scored by five deterministic checks:

| Check | What it asks |
|---|---|
| Final state | Did the sandbox end in exactly the expected state? |
| Required actions | Did every required tool call actually succeed? |
| Forbidden actions | Did the agent attempt anything it must not do — even a rejected attempt counts? |
| Ask policy | Did it ask the customer *before* the consequential action, in an earlier turn? |
| Evidence | Is there recorded evidence to judge at all? Missing evidence is `inconclusive`, never `pass`. |

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

The local Gemma evaluation is `gemma3:4b` (2/12, JSON tool mode). Gemma 4 (`gemma-4-31b-it`) also ran
hosted through Google's Gemini API (an OpenAI-compatible endpoint) with native tool calls: one
full-suite run scored 8 pass / 3 fail / 1 error, the error being provider latency past the turn
deadline. That hosted run is Gemma evidence; it is not a DigitalOcean run, and I don't claim it as one.

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
  stub agent so the kill would land mid-case.
- **ElevenLabs:** `bolibench run --speech elevenlabs` speaks each utterance with text-to-speech,
  transcribes it back with speech-to-text, and gives the agent only the transcript (stored as
  `asr_text`). Verified live on the free tier: on three cases run end to end with local `qwen3:8b`,
  the speech round-trip scored 1 pass / 2 fail against 0 / 3 for the same cases as plain text.
  Synthetic voices, not real speakers.
- **Render:** the live demo above is one Docker container on Render (free plan), running as `nobody`
  on a read-only filesystem. Live mode is on: the same container runs the example agent against the
  hosted Gemma 4 model, gated by a demo token, with a daily cap.

**Also genuinely used, with their limits stated plainly — documented here, but not entered as prize
categories, because the evidence below is local, partial, or offline rather than a verified hosted use:**

- **Backboard (real API, partial):** `examples/backboard_agent.py` bridges BoliBench to Backboard's
  API. Verified live against the real service: authentication, model listing, an assistant/thread
  round-trip, tool calls, and memory isolation between cases (two bridge bugs were found this way and
  fixed). What I could not do: run the open-weight models I wanted to compare, because the account's
  free credit does not pay for LLM chat. A zero-priced preview model ran 4 cases (3 pass / 1 fail).
  So: the bridge is real and tested; a multi-model comparison through one Backboard key is **not**
  claimed, because it never ran.
- **Sentry Agent Tracing (SDK, offline only):** the example agent emits `gen_ai.invoke_agent`,
  `gen_ai.chat` and `gen_ai.execute_tool` spans with token counts, grouped per case. This was tested
  with the real SDK against an in-memory transport; no DSN was ever configured, so no trace reached
  Sentry and I claim no hosted tracing. The offline work did catch a real leak: with the SDK's default
  local-variable capture, an error event carried the customer's utterance and an `Authorization`
  header; local variables are now off, and a test keeps them off.
- **MongoDB (local only, not Atlas):** `bolibench export --to mongo` exports run history with
  idempotent upserts and indexes. Verified against a local MongoDB 7 server, including the report
  command. No Atlas cluster or credentials were available, so this is a local MongoDB integration —
  not an Atlas deployment, and not entered as one.
- **Tiger Data technology (local only, not Tiger Cloud):** `bolibench export --to tiger` stores run
  history in a TimescaleDB hypertable and embeds every failure with EmbeddingGemma into pgvector for
  hybrid keyword + vector "have we seen this failure before?" search. Verified locally on
  TimescaleDB 2.30.2 + pgvector 0.8.7 (22 failures embedded; the top matches for a failure were the
  same case in other runs). No Tiger Cloud service or credentials were available, so no cloud use is
  claimed.
- **DigitalOcean (code and configuration only — never called):** an OpenAI-compatible backend option
  and an App Platform spec exist in the repo, and the same client code ran live against Ollama
  locally and Google's Gemini API hosted. DigitalOcean's own API was never called: no model access
  key was available. I list it here only to be explicit that it is implemented-but-unused, not an
  integration I ran.

No sponsor outreach is claimed anywhere in this post: there is no record of contact with any partner,
and appearing in this list means only that the code above exists and was exercised as described.

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

## What I Learned

**Fluent is not correct.** The single most dangerous agent failure I found was not a crash or a refusal — it was a polite, confident, completely wrong reply. If your evaluation reads the reply, you will ship that bug.

**Fixing behaviour moves failures around.** My v2 agent fixed five cases and broke two it used to pass, by becoming over-cautious. Without per-case evidence, I would have seen “6 is better than 3” and missed the regression entirely.

**A model can fail on format, not understanding.** Gemma's worst results came from almost-valid tool calls that a strict parser refused. In one case its rejected call was exactly right while another model's accepted call was wrong. Evaluating only final scores would have taught me the opposite lesson.

**Honesty is a feature.** Every integration in this project is labelled by how far it was really verified — deployed, hosted, local, or offline-only. That discipline started as bookkeeping and became the design principle of the whole demo.

## Limitations

- **No native-speaker review yet.** All 12 cases are synthetic and marked `proposed`. Nothing in
  BoliBench understands Hindi or Awadhi; case correctness rests on the people who wrote them.
- **Transcript-level** unless the ElevenLabs speech round-trip is used, and that uses synthetic voices.
- **12 cases, single unseeded runs.** The counts are not model measurements.
- **Integrations are verified only as far as stated.** Where a line above says local or stubs, the
  hosted service hasn't been exercised.
- The agent under test must run next to BoliBench (localhost only). That's a dev safeguard, not a
  security boundary.

## Prize Categories

- Best Use of Gemma: `gemma3:4b` locally (2/12, JSON tool mode) and `gemma-4-31b-it` hosted (8/3/1), both audited above, plus EmbeddingGemma for failure search.
- Best Use of Render: the live demo, with token-gated live mode running the agent in the container.
- Best Use of Mastra: the Mastra agent's full-suite run above.
- Best Use of ElevenLabs: the verified live speech round-trip above.
- Best Use of Temporal: the suite run as a durable workflow that resumed after `kill -9` (a durable evaluation run, stated as such).

Documented above but **not entered** as prize categories: Backboard (real API, billing-blocked comparison), Sentry Agent Tracing (SDK, offline only), MongoDB Atlas (local MongoDB only), Tiger Data (local TimescaleDB only), DigitalOcean (code/config only, never called). Not used at all: .tech Domain, Entire, GitHub Copilot, Tinker, TabPFN, SerpApi, Arduino.
