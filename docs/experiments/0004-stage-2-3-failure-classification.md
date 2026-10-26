# 0004 — Stage 2.3: the stage whose premise was wrong

**Date:** 2026-10-26 / 27
**Stage:** 2.3 (Failure classification and the dead-letter queue)
**Status:** complete. All figures `[measured]` unless marked.

## Why this file leads with a correction

The Evolution Map's trigger for this stage said:

> *"a malformed PDF retries every 30s for a day and consumes the embedding
> quota by itself"* `[hypothesis]` — verifiable by feeding one in and counting
> attempts.

So one was fed in. Both halves of the claim are false.

```text
 2.1s  queued    attempts=1
 7.2s  queued    attempts=4
14.6s  failed    attempts=5   'poison.pdf' is not a valid PDF: Stream has
                              ended unexpectedly … (gave up after 5 attempts)
```

**Bounded at 14.6 seconds**, because stage 2.1's `max_attempts` already stopped
it. And it cost **no embedding quota at all**: `rag/pipeline.py` runs
`extract_pages` before it reads settings or touches a provider, so a corrupt PDF
never reaches an embedding call.

This is the **second** consecutive stage whose Problem row was written before
the preceding stage existed and was invalidated by it — 2.1's "orphans 10 → 0"
was the first. The pattern is worth naming: **a Problem row is a hypothesis
with a date on it, and the stage before it is the most likely thing to falsify
it.**

## The real failure runs the other way

A *valid* document, uploaded with the agent stopped:

```text
 2.1s  processing  attempts=1
12.1s  processing  attempts=4
22.0s  failed      attempts=5   Could not reach the agent … (gave up after 5)
```

**A good document permanently destroyed by 22 seconds of downtime.**
`docker compose restart agent` fits inside that window, and the only recovery
was a human noticing and re-uploading the file.

One retry policy, two opposite kinds of failure, tuned for neither: the backend
retried a `400` — a permanently true client error — five times, while giving a
transient outage twenty-two seconds.

## Measures

| Measure | Before | After |
|---|---|---|
| attempts spent on a poison document | **5** over 14.6s | **1** in 1.3s |
| outage survived before giving up | **22s** | **221–302s**, median ~302s |
| a dead document replayed from the list | *(no path)* | one click → `done` |

### The budget, measured rather than computed

With the agent stopped and never restarted, a valid document was retried until
the system gave up:

```text
   0.5s  queued      attempts=0
   3.7s  processing  attempts=2   kind=transient
  85.6s  processing  attempts=7   kind=transient
 211.4s  processing  attempts=13  kind=transient
 302.0s  failed      attempts=15  kind=transient

 MEASURE the retry budget: gave up after 302.1s and 15 attempts
```

**302.1 seconds against a simulated median of 302s.** The model and the
apparatus agree to within a second, which is the only reason to trust either.

### …and the second run gave up at 221.1s, which is the more useful number

A document uploaded into a 240-second outage **did not survive it**. It
exhausted all fifteen attempts at **221.1s** — nineteen seconds before the
dependency came back.

| run | attempts | gave up at |
|---|---|---|
| agent never restarted | 15 | **302.1s** |
| agent down 240s | 15 | **221.1s** |

Same configuration, same number of attempts, **a 37% spread**. That is full
jitter working as designed: each delay is `uniform(0, ceiling)`, so the total
is a sum of random draws, and the simulation's own p10 is 233s — this run
landed below even that.

**So "about five minutes" is a median, not a promise.** A given document gives
up somewhere between roughly 3.5 and 6 minutes, and an outage near the middle
of that range is survived more often than not rather than reliably. The table
in `max_attempts`'s docstring says p10/median/p90 for exactly this reason; a
single number would have been the same mistake as "about three minutes" was,
one layer down.

**The trade-off is deliberate and worth stating.** Full jitter buys protection
against the retry storm — fifty workers that failed against one outage must not
return in the same instant — and it pays for it in per-document predictability.
*Equal* jitter (half the delay fixed, half random) would halve the spread and
weaken the herd protection. Not changed, because nothing here has measured a
herd or complained about the spread. **Trigger:** a second worker exists and
the retry pattern is measured (12.2), or someone needs a tighter guarantee than
"usually five minutes".

Note `kind=transient` appearing from attempt 2 on a **`queued`** row. That is
the design decision — tying `failure_kind` to `error` rather than to
`status = 'failed'` — visible in the wild: a job waiting to retry says *why* it
is waiting.

## The classification was already at the boundary

`rag/errors.py` said its exception hierarchy was where transient-versus-
permanent belonged when 2.3 needed it. It was not needed.

The backend never imports `rag` — it learns what happened from the agent's HTTP
response — and the agent already maps the engine's errors onto status codes:

```text
400 / 413 / 422   permanent — the request can never succeed
429               transient — 4xx by number, "come back later" by meaning
500 / 502 / 503   transient — the system failed you
(no response)     transient — nothing was judged about this document
```

**4xx means the request can never succeed; 5xx means the system failed you.**
That is the HTTP specification's own semantics. Keeping the backend ignorant of
the engine is what made the 1.3 worker split possible, and it paid again here:
the classification arrived for free at a boundary that already existed.

The one thing the hierarchy would still be needed for is a *finer* policy than
status codes support — backing a rate limit off differently from a timeout, when
both are `EmbeddingError` and both are 502. That needs measured provider
behaviour and is stage 7.1.

## The retry budget was wrong by a factor of three

`max_attempts` was first set to **8** and documented as *"about ninety seconds
on average and three minutes at worst"*, reasoning from the sum of the ceilings
(2 + 4 + 8 + 16 + 32 + 60 + 60 = 182s).

What a document experiences is the sum of the **draws**, and full jitter halves
every one. Simulated over 20,000 runs of the real `delay_for`:

| config | p10 | median | p90 |
|---|---|---|---|
| 8 attempts, cap 60 | **55s** | **91s** | 126s |
| 12 attempts, cap 60 | 154s | 211s | 269s |
| **15 attempts, cap 60** | **233s** | **302s** | 369s |
| 10 attempts, cap 120 | 159s | 242s | 326s |

**One document in ten gave up after 55 seconds** under the eight-attempt
policy — barely better than the 22 seconds this stage exists to fix. Two live
runs landed at 49.5s and 81.3s, both in that lower half, which is how the error
was noticed at all.

### The test written to pin this did not catch it

```python
policy = RetryPolicy(max_attempts=8, base_seconds=2.0, max_delay_seconds=60.0)
assert sum(ceilings) == 182.0, "worst case ~3 minutes"
```

Every assertion passed while the system ran a policy nobody had checked. Two
separate failures, both general:

1. **It asserted a literal, not the configuration.** `max_attempts` could change
   to anything and the test would keep agreeing with itself.
2. **It asserted a bound, not a distribution.** The worst case was right; the
   experience was three times worse.

It now reads `Settings()` and simulates. Swept across configurations it fails at
8 ("median of 91s"), 12 ("median of 212s") and 20 ("median of 452s"), and passes
only at 15 — so it brackets the decision rather than restating it.

## Three findings about the apparatus, not the system

**A measurement script reported "GAVE UP" when its own watch loop timed out.**
The database showed the document still `queued` at attempt 13, and a worker
later carried it to `done` at attempt 14. The script now has three outcomes —
`done`, `failed`, `INCONCLUSIVE` — because a timeout is not a result. It also
drives the agent restart from inside the polling loop rather than a concurrent
task (the host slept mid-run and the restart fired at 734s instead of 241s), and
reports any tick gap large enough to mean the machine stalled.

**A mutation-testing script aimed at an ambiguous anchor.**
`retry = await create_job_for_document(...)` appears twice; the mutation landed
in 2.2's duplicate-upload path instead of 2.3's retry endpoint and reported
SURVIVED for a code path the tests do not exercise. **A mutation that lands
somewhere unintended reads exactly like a missing test.** It now asserts each
anchor occurs exactly once.

**That same script keyed its backups on each file's basename**, and three of its
five targets are called `documents.py` — repository, route and schema shared one
backup file, so the restore would have written the wrong content back. Nothing
was corrupted only because the script asserts before writing. It now keys on the
full path and restores in a `finally`.

## A known environmental flake, recorded rather than explained away

Roughly **one backend run in six** fails or errors on an unrelated test and
passes on a rerun. Investigated rather than dismissed:

- **Not data pollution.** Running each test file in turn and querying
  `myrag_test` afterwards showed **0 leftover documents** every time.
- **Not connection exhaustion.** `max_connections` is 100; steady state is 3.
- **The captured failure is a `TimeoutError`** establishing a connection, not an
  assertion — and a timeout raises rather than returning wrong data, so an
  earlier suspicion that `assert len(rows) == 1` in a repository test was the
  cause was wrong.

It looks like Windows-to-Dockerised-Postgres port-forward latency, and the host
slept twice during this stage's work. **Trigger to investigate properly:** if it
exceeds roughly one run in five, or ever fails deterministically.

## What the user sees

The dead-letter list carries this stage's own history side by side:

```text
  poison.pdf      permanent  attempts=5   ← before classification
  poison-2.pdf    permanent  attempts=1   ← after
  outage.pdf      transient  attempts=5
```

`?status=ded` answers **422**, not an empty list — which is the whole reason the
query parameter is typed. `{"items": []}` reads as *"nothing has failed"*, the
most dangerous possible answer to the question this endpoint exists to answer.

And the two failures are offered different things:

| | notice | button |
|---|---|---|
| **transient** | "This was the service, not the file — 8 attempts. It may work now." | **Try again** |
| **permanent** | "Retrying will not help — the file itself cannot be read. Upload a different copy, or a text-based PDF if this one is scanned." | none |

The button is **absent**, not disabled, on a permanent failure. A disabled
control still suggests the action is meaningful; there is not one for a file
that cannot be read, and offering it would teach the user the system is flaky
rather than that their file is unreadable.

`outage.pdf` — dead since this stage's trigger — was replayed from that list in
one click:

```text
before             failed  attempts=5  kind=transient
POST .../retry →   202     queued  attempts=0  error=None
POST again     →   409
after worker   →   done    attempts=1  chunks=1
```

## Test counts

179 backend (was 122), 44 rag, `tsc` and `eslint` clean.
