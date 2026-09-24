# 001 — Conversation history grows unboundedly

**Status:** deferred
**Trigger:** any of —
- **answers get vague or self-contradictory in long conversations** (quality
  degradation, see "lost in the middle" below) — this is the realistic trigger,
  and it arrives long before the hard limit
- we move to a model with a smaller context window (paid models are often
  128K-200K, not 1M)
- we move to a paid provider (cost becomes real, and prompt caching becomes
  available)
- the benchmark (M3) starts running multi-turn cases
- a conversation fails with a context-length error (the hard wall — unlikely to
  be what we hit first)
**Milestone:** most likely G2 (orchestration/memory)
**Filed:** 2026-09-02
**Updated:** 2026-09-03 — measured against the running model; added the three
failure curves and revised which trigger fires first

---

## The problem

Chat APIs are **stateless**. The model has no memory between calls, so the
backend re-sends the entire conversation on every turn. That is not a design
choice — every provider (OpenAI, Anthropic, OpenRouter) works this way.

The consequence is that input tokens grow **quadratically** with turn count.
Measured with typical message sizes (system 100, user 60, assistant 400 tokens):

| Turn | Sent that turn | Cumulative |
|-----:|---------------:|-----------:|
| 1 | 160 | 160 |
| 2 | 620 | 780 |
| 5 | 2,000 | 5,400 |
| 10 | 4,300 | 22,300 |
| 20 | 8,900 | 90,600 |

After 20 turns: **90,600 input tokens sent** to deliver 3,200 tokens of actual
new content — a **28x** overhead. Turn 20 alone spends 8,900 tokens to ask a
60-token question.

### Cost, if we were paying

20-turn conversation, input tokens only:

| Model | No caching | With prompt caching |
|---|---|---|
| Haiku 4.5 | $0.0906 | $0.0172 |
| Sonnet 5 | $0.1812 | $0.0344 |
| Opus 5 | $0.4530 | $0.0861 |

Prompt caching cuts it ~5x because the conversation prefix is unchanged between
turns. **OpenRouter's free tier does not offer prompt caching**, which is a
concrete reason to move to a paid provider before running the benchmark
repeatedly.

### It fails in three ways, at three different points

Measured against `nvidia/nemotron-3.5-lightning:free` (1M context), which is
what the agent currently runs.

**1. Quality degrades gradually — "lost in the middle" (hits first)**

Everything is still in the input, but *present in the context* is not the same
as *reliably used*. Models attend best to the beginning and end of a long
context and worst to the middle. By turn 400, a fact stated at turn 180 sits in
the least-attended region.

There is no error. The assistant just gets vaguer, misses details, and
contradicts things it said earlier. Experienced as "it got dumber."

This is the same reason `rag_engine/context/` has an ordering responsibility:
strongest evidence first and last, never buried in the middle.

**2. Cost and latency grow quadratically**

| Turn | Sent that turn | Cumulative input |
|-----:|---------------:|-----------------:|
| 10 | 4,300 | 22,300 |
| 100 | 45,700 | 2,293,000 |
| 500 | 229,700 | 57,465,000 |
| 1,000 | 459,700 | **229,930,000** |

A 1,000-turn conversation pushes ~230M input tokens through the API. At Sonnet
5 rates that is roughly **$460 for one conversation** (far less with prompt
caching, but the shape of the curve does not change). Latency tracks it — a
460K-token request is meaningfully slower than a 4K one.

**3. The hard wall (hits last)**

| Context window | Conversation dies around |
|---|---|
| 1M — `nemotron-3.5-lightning` (current) | **~2,165 turns** |
| 262K — `gemma-4` | ~561 turns |
| 32K — older free tiers | ~62 turns |

(Assumes system 100, user 60, assistant 400 tokens per turn, and 4,096 reserved
for output — output shares the same window as input.)

The failure is worse than it sounds: **the conversation becomes permanently
unusable.** Every retry re-sends the same oversized payload and fails
identically. There is no recovery without discarding history, and the code has
no mechanism to do that.

Note how much the model choice moved this: switching from a 32K free model to
the 1M one pushed the wall from ~62 turns to ~2,165. That is why failure mode 1,
not 3, is the realistic trigger.

---

## Why it is deferred

Three honest reasons:

1. **The cost today is $0.** Free tier. The quadratic curve is real but the
   multiplier is zero.
2. **The hard wall is ~2,165 turns away** on the current model, and
   conversations do not survive a backend restart anyway (in-memory dict), so
   in practice no conversation gets near it.
3. **Building it now would be building ahead of evidence** — the exact thing
   the project's central rule forbids. We do not yet know whether a sliding
   window or summarisation is right, because we have no benchmark showing which
   failure actually occurs.

What *would* change this: quality degradation (failure mode 1) is subjective
and has no error message, so it needs the benchmark's multi-turn cases to
detect reliably. That is the honest reason to wait for M3 rather than guess.

Deferring is the correct decision. It stops being correct the moment a trigger
fires.

---

## Options

Roughly in order of effort. These are not exclusive — production systems stack
several.

| Approach | What it does | Cost | Loses |
|---|---|---|---|
| **Prompt caching** | provider caches the unchanged prefix, ~10% price on re-reads | config only | nothing — do this first |
| **Sliding window** | keep the last N turns verbatim, drop older ones | ~10 lines | early context, silently |
| **Token counting + hard cap** | measure before sending; refuse or compact at the limit | small | nothing — this is a safety net |
| **Rolling summary** | summarise older turns, keep recent ones verbatim | moderate; costs an extra model call | detail in the summarised span |
| **Recursive summarisation** | summaries of summaries for very long threads | higher | more detail, compounding |
| **Semantic retrieval over history** | embed past turns, retrieve only relevant ones | high — it is RAG over the conversation | conversational flow |

**Likely first move when triggered:** prompt caching (free win) + token counting
with a hard cap (prevents the hard failure) + a sliding window. Summarisation
only if dropping old turns measurably hurts answers.

### Two traps

- **Never trim mid-turn.** Cutting between a user message and its assistant
  reply leaves the model reading a broken transcript. Trim on turn boundaries.
- **Never drop the system prompt.** It is the first message; a naive "keep the
  last N messages" slice will eat it.

---

## What to learn

This one item touches most of the memory topics in the design doc:

- **Why chat APIs are stateless**, and why that is a feature: any server can
  serve any request, retries are safe, and turns are exactly replayable.
- **Why it matters for RAG specifically** — RAG only works *because* we control
  the message array. Retrieved chunks get injected into it. If the provider held
  conversation state server-side, we could not put documents in front of the
  model at all. Statelessness is not a tax; it is the mechanism the whole plan
  depends on.
- **Prompt caching**: what invalidates a cached prefix (any byte change earlier
  in the request), and why volatile content must go last.
- **Short-term memory vs compaction vs summarisation** — three different things
  that get called "memory".
- **Token counting** — measuring before sending, rather than discovering the
  limit by hitting it.
- **Lost in the middle** — why a bigger context window does not straightforwardly
  mean better recall, and why ordering the prompt is a real design decision
  rather than cosmetic.

Related: design doc section 7.5 (Memory — all four kinds), which places this in
the wider map.

---

## Where it lives

Today the entire memory of the application is one dict:

- `backend/app/api/routes/chat.py` — `_conversations: dict[str, list[...]]`,
  appended to on every turn, never trimmed. Also dies on restart (a separate
  problem, solved by persistence in M1).
- `backend/app/services/agent_client.py` — sends `history` wholesale.
- `agent/app/providers/openrouter.py` — prepends the system prompt to whatever
  arrives.

When this is built, the window/compaction logic belongs in the agent
(`chat_orchestrator/memory/`), not the backend — it is a conversation concern,
and the backend is not allowed to know about prompts or tokens.
