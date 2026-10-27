# 0006 — Stage 2.5: a provider you can drive

**Date:** 2026-10-27
**Stage:** 2.5 (A provider you can drive)
**Status:** complete. All figures `[measured]`.

## The premise, demonstrated by accident

The first act of this stage was to calibrate the fake provider's delay against
one real Gemini call. It failed:

```text
sample 1:  3482.0 ms (100 vectors)
sample 2:  FAILED — 429 RESOURCE_EXHAUSTED
           "Embed content requests per minute limit exceeded on Free Tier"
```

**Two requests was enough.** That is the whole argument for this stage, arrived
at before a single line of it had been exercised: a load test against the real
provider measures the quota, not the system.

A second run spacing calls 45 seconds apart got three samples — and its *first*
attempt was rate-limited too:

| | ms per batch of 100 |
|---|---|
| min | 3076 |
| **median** | **3168** |
| max | 3247 |

`FAKE_EMBED_DELAY_MS = 3482` was used for the sweep below (the first sample,
measured before the spaced run completed). The 9% difference from the
calibrated median does not move any conclusion here, and it is recorded rather
than quietly corrected.

## The probe's own ceiling, measured first

```text
SELF-TEST  N=60 concurrent /health
  wall clock  0.671s   ceiling 89 req/s
```

A load generator that saturates before its target is measuring itself. Upload
throughput below peaks at 10/s, an order of magnitude under this, so the
numbers are about the system.

## Question 1 — latency under concurrency

### Synchronous (the agent's blocking endpoint)

```text
N=10   wall  5.56s   response p50 1.954s   p95 5.508s
N=40   wall  4.02s   response p50 3.937s   p95 3.988s
N=60   wall  7.98s   response p50 4.432s   p95 7.884s
```

**The knee is exactly at 40, and this is the first time it has been
demonstrated.** At N=40 the whole batch completes in one wave of roughly one
embed delay. At N=60 the wall clock doubles and p95 doubles with it: twenty
uploads waited for a thread.

The agent route's own docstring has claimed since 1.1 that its threadpool bound
is "a real limit and a real future trigger… enough concurrent uploads will
exhaust it, and that observation is part of what earns the queue at stage 1.3".
The queue was built on that claim fifteen months of curriculum before anyone
checked it. It holds.

### Asynchronous (the backend's `202` plus a worker)

```text
N=10   response p50 0.701s   completion p50 23.054s
N=40   response p50 1.251s   completion p50 77.035s   max 145.8s
```

### The comparison, and the part that is not flattering

| at N=40 | sync | async |
|---|---|---|
| **response** p50 | 3.937s | **1.251s** — 3.1× better |
| **completion** p50 | 3.937s | **77.0s** — 20× *worse* |

**Stage 1.3 bought response latency and paid for it in completion latency**,
and at this concurrency the price is steep. The reason is not subtle once
measured: the synchronous path has **forty workers** — the threadpool — and the
asynchronous path has **one**. Forty documents at 3.2 seconds each run in one
wave through the first and serially through the second.

That is **stage 12.2's trigger, measured**: adding workers is the only thing
that makes the queue's trade favourable at concurrency, and until there are
more than one the queue is a latency *regression* for anyone waiting on a
result rather than on a response.

It also corrects 1.3's withdrawn measure once and for all. The claim was
"p95 240s → <200ms". The honest version is **two numbers, not one**, and
neither is 200 ms: a `202` under 40 concurrent uploads takes 1.25 s, because
forty multipart bodies still have to be read.

## Question 2 — does `/health` degrade under load?

**Yes, catastrophically, and the stage fixed it.**

```text
SYNC, N=40,  agent /health as `def`
  /health   p50 3.508s   (2 samples in the window, 0 failed)
```

From 8 ms to **3508 ms — 438× worse**. The sample count is the other half of
the evidence: the poller managed *two* probes in four seconds, because each one
took 3.5 seconds to return.

### Why

Both `/health` routes are plain `def`, so FastAPI runs them **in the worker
threadpool** — the same pool `POST /documents` occupies for an entire ingest.
With all forty threads blocked inside `rag.ingest`, a liveness check that
touches nothing and does no I/O sat in a queue behind forty documents.

The consequence is exactly what the health route's own docstring says it wants
to avoid: *"a liveness check that fails because a dependency is down invites a
restart that cannot possibly help."* A check that fails because the service is
**busy** invites a restart that throws away the work in progress.

### The fix, and the re-measurement

One word — `async def` — putting it on the event loop, where it never competes
with ingestion.

```text
SYNC, N=40,  agent /health as `async def`
  /health   p50 0.007s   p95 0.164s   (33 samples, 0 failed)
```

**3.508 s → 0.007 s.** The sample count went from 2 to 33: the poller had been
starved too.

The rule it illustrates has two halves, and both matter: **a route that does no
I/O should be `async def`; a route that blocks should be `def`.**
`POST /documents` is deliberately the second half, and is correct as it stands.

### The backend never degraded

```text
ASYNC, N=40   /health p50 0.014s   (642 samples, 0 failed)
```

Its `/health` is also a plain `def`, but its upload route is `async def` and
does no blocking work, so the threadpool is free. The defect needed *both* a
pooled health check and a pool-occupying sibling.

## Question 3 — the timeout divergence, reframed

The original question was *"does a 120 s timeout produce a Postgres/Qdrant
divergence?"*. **Stage 2.2 changed its shape, and this stage records that
rather than measuring the old question.**

- The agent exceeds `AGENT_TIMEOUT`, the backend raises
  `AgentUnavailableError`, 2.3 classifies it **transient**, the job requeues —
  while the agent keeps working and writes chunks anyway.
- **After 2.2** a successful retry upserts under deterministic ids and prunes
  everything else for that document, so the divergence *self-heals*.
- If every retry fails, Postgres says `failed` while Qdrant holds chunks — and
  `tools/qdrant_orphans.py` already has a group for precisely that:
  **`pending`**, "in Postgres, never successfully ingested, but has points".

So the question is now *"does it still self-heal, and does the tool catch the
case where it does not?"* The fake provider makes it reproducible on demand by
setting the delay above `AGENT_TIMEOUT`, which is what the deferred question
could never do against a real provider.

## What the fake provider does and does not model

Recovered verbatim from the removed implementation, and worth repeating beside
the numbers:

**It models** wall-clock time a worker thread is blocked, and everything
downstream of that — threads held, sockets held, requests left open, timeouts
fired.

**It does not model** latency *variance* (the delay is constant, so there is no
tail), rate limiting, retries, TLS handshakes, bandwidth, token cost, or the
provider's own CPU. **Every p95 above is a measure of queueing alone.**

One thing it does have that the real provider does not: measurable CPU cost.
Hashing 100 × 768-dimension vectors takes ~80 ms, which a timing test charged
to the sleep until it was corrected to subtract a zero-delay baseline.

## The implementation was recovered, not rewritten

Two stale bytecode files survived in `rag/rag/providers/__pycache__/` from the
version deleted during 1.3 preparation — `fake.pyc` and `_vectors.pyc` — and
Python keeps docstrings as bytecode constants. Disassembly returned the design,
its reasoning, and all four constants exactly:

```text
_MAX_BATCH = 100   _BYTES_PER_FLOAT = 4   _DIGEST_SIZE = 64
_UINT32_MAX = 4294967295
```

Along with the arguments for each: why `l2_normalise` *moves* to a shared
module rather than being copied or imported from `gemini.py`; why the sleep is
per batch; why `time.sleep` rather than `asyncio.sleep`; why `hashlib` rather
than builtin `hash()`.

## Three mutation findings

**A claim measurement did not support.** The salt-vs-concatenation mutation
**survived**. Investigating showed why: the two texts *do* share digest blocks
under concatenation, but at different offsets, so no components align and the
cosine is zero either way. The docstring claimed it would produce "correlated
vectors"; measured, it produces none. The salt is still right — for unambiguity
by construction, not a measured defect — and the test that claimed to detect it
was **removed**, with the reason recorded in its place.

**The seam branch had no test.** Replacing `if settings.embedding_provider ==
"fake":` with `if False:` — so the setting is read and ignored — passed every
test of the provider and every test of the config. The central claim of the
stage, that the seam would pay out, was unasserted. Same shape as the
`expose_headers` gap at 2.4.

**A timing test charged CPU to the sleep**, then flaked on a loaded machine.
It now subtracts a zero-delay baseline and takes the **minimum** of three runs
— scheduling noise only ever makes a measurement larger, so the minimum is the
estimator that does not drift when the machine is busy.

## Test counts

**64 rag** (was 44), 224 backend, `tsc` and `eslint` clean.
