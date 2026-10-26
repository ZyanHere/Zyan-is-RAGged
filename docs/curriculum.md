# myRAG — Evolution Map

**What this is:** the complete destination, laid out as a causal chain, plus the
deliberate journey we walk to reach it. Each stage is entered only when the
previous system actually produces the problem it solves — or when a stated
product requirement establishes a capability that must exist.

**How to read it:** the `Next trigger` of every stage is the `Problem` of the
next one. If you reach a stage whose trigger you cannot observe in your own
running system, and no product requirement forces it, **you are not ready for
that stage** — skip it and come back.

**Stage sizes are deliberately uneven.** Some are an afternoon. Some are a
month. A stage is done when its completion criteria are met and you can explain
the tradeoff, not when a number of days has passed.

---

## The governing philosophy

> **Nothing critical gets skipped. Nothing substantial gets introduced randomly.
> Difficult concepts are taught when they become relevant, and every
> implementation and experiment serves a clear product or learning purpose.**

Four commitments follow from that, and they are the whole document:

1. **Every substantial task names its reason** — a product capability plus an
   observed problem or a stated requirement. Nothing is built because it appears
   in a roadmap.
2. **Critical work is never dropped for being hard.** Security, data integrity,
   failure handling, concurrency correctness, migrations and testing appear
   wherever the product's scope requires them. Unfamiliar is a reason to teach,
   not a reason to omit.
3. **Verification is part of the build, not a separate curriculum.** Each stage
   carries the kind of test that proves *its* claim.
4. **Numbers are labelled by provenance.** A measurement, a requirement, a
   hypothesis and an illustration are four different things, and this document
   says which one every number is.

---

## Evidence labels

The previous version of this document stated illustrative numbers in the same
voice as measured ones. That is how a plan quietly becomes a set of false
beliefs. Every quantitative claim now carries one of these:

| Label | Means | Obligation |
|---|---|---|
| **`[measured]`** | observed in this system, with the run recorded | cite where |
| **`[requirement]`** | an external or product constraint we accept | say whose |
| **`[hypothesis]`** | plausible, unverified | say how to verify it, before building on it |
| **`[illustration]`** | a shape of outcome, not a prediction | never quote as fact |

**The rule:** you may not claim a target was achieved without a `[measured]`
before *and* after. "It feels faster" is not a result, and neither is "the
number in the plan said 240s".

### What counts as evidence

**A number is not the only form of proof, and demanding one everywhere is its
own kind of dishonesty** — it pushes you into inventing metrics for claims that
were never quantitative. A constraint either holds or it does not, and
"100% of impossible states rejected" is a worse statement of that than a test
which fails the moment the constraint is removed.

| Kind of claim | What proves it | Example in this project |
|---|---|---|
| **quantitative** — faster, cheaper, higher recall | a `[measured]` before and after, same method both times | 1.3's p95 upload latency; 4.1's recall@5 |
| **correctness invariant** — this state cannot exist | a test that **fails** when the invariant is removed | 1.2's four CHECK constraints: a `processing` row cannot carry a `finished_at` |
| **ordering / state machine** — this happens before that | a mutation test: break the ordering and watch the test fail | 1.2's commit-before-calling-the-agent, proven by deleting the commit |
| **security** — this cannot be reached or leaked | an adversarial test set that grows every time you invent a new attempt | 5.1's cross-tenant leak attempts; 5.0's malformed uploads |
| **concurrency** — this holds with N actors | a test that reproduces the race *before* the fix exists | 6.1's quota oversell; 2.1's double-claim |
| **failure handling** — this survives X dying | failure injection at each point in the sequence | 2.1's crash points; 7.2's provider outage |
| **capacity / behaviour under load** | a measurement, with the configuration recorded alongside it | 11.1's saturation point |

Several stages produce both kinds. Where a stage's claim is an invariant rather
than a magnitude, **the test is the evidence and no number is required** — but
the test must have been *seen to fail*, or it proves nothing.

---

## Why work enters a stage

There are exactly two legitimate reasons. Every stage declares which one it is.

**A — Real need.** The running system exhibits a problem you can demonstrate, or
a product requirement establishes a capability that must exist. Most stages are
this.

**B — Controlled teaching experiment.** A realistic risk matters enough to
understand deliberately, but waiting for it to occur naturally would be
impractical, unsafe, or impossible at this scale. We reproduce it on purpose.

A stage of type **B** must say so in its header, and must answer:

- what engineering question it answers;
- why ordinary observation is insufficient;
- how its result changes the product's design.

**Not legitimate:** inventing a production incident to justify a technology you
wanted to use. If you build something for the learning alone, label it **B** and
say so out loud — do not dress it as a need.

**Also not legitimate:** deliberately slowing the system so an assumed failure
appears. A controlled slowdown is a valid instrument only when the engineering
question is explicitly stated and cannot be answered otherwise — and the number
it produces is a property of the simulation, not of the real provider.

---

## Before you build test infrastructure

Test harnesses, fake dependencies, synthetic workloads and benchmarks are
themselves substantial engineering. They appear in this document only where they
are earned, and every one must answer five questions **before** a line is
written:

1. **What engineering question** do we need to answer?
2. **Why are ordinary tests or direct observation insufficient?**
3. **Why is this specific mechanism necessary** rather than a simpler one?
4. **What is the minimum implementation** that answers the question?
5. **What will we do with the result** — which decision does it change?

> **Do not build elaborate infrastructure to prove a simple property.** A
> twenty-line script that answers the question beats a framework that answers it
> beautifully.

This gate exists because of a real mistake. The fake embedding provider was
built mid-implementation as an unexplained detour: Stage 1.3's measurement was
blocked by a provider quota, and nothing in the plan had said so. The gate is
where that conversation now happens — before the detour, not during it.

---

## The stage template

Every stage answers the same **seven questions**:

1. What capability are we building?
2. What problem or requirement necessitates it?
3. What do I need to understand before implementing it?
4. What is the smallest implementation that solves it?
5. What proves it works?
6. What must be true before we call it complete?
7. What remaining limitation justifies the next stage?

The table has **eleven rows**, because four of them are supporting detail rather
than separate questions: `Now` sets the scene for the problem, `Diagnose` and
`Root cause` are how you come to understand it, and `Covers` is an index for
interview preparation rather than part of the stage's logic.

| Question | Row | Answers |
|---|---|
| 1 | **Capability** | what user-facing or system capability this creates |
| — | **Now** | the state of the system entering this stage |
| 2 | **Problem** | the observed limitation or stated requirement that necessitates it — with an evidence label |
| — | **Diagnose** | how you see the problem for yourself, before fixing it |
| — | **Root cause** | the structural reason, not the symptom |
| 3 | **Learn** | the engineering concepts needed *before* implementing |
| 4 | **Build** | the smallest meaningful implementation that solves it |
| 5 | **Verify** | the tests, experiments and observations that prove it works |
| 6 | **Done when** | the completion criteria — all of them, not just the number |
| 7 | **Next trigger** | the remaining limitation that justifies the next stage |
| — | **Covers** | interview surface |

**Older stages used a shorter form.** The two rows that were missing everywhere
were **Capability** and **Done when** — questions 1 and 6, and the ones that let
you tell "the code runs" from "the stage is finished".

### What "Done when" always includes

A stage is **not** complete because the code runs or a number moved. Completion
requires all six:

1. The capability works within its stated scope.
2. Relevant correctness **and failure** cases are verified.
3. The design decisions and tradeoffs are understood and written down.
4. Every claim is supported by evidence of the labelled kind.
5. Remaining limitations are documented — including what was deliberately left
   broken, and why.
6. The next stage has a justified reason to begin.

### Teaching order, for anything unfamiliar

1. The concrete problem, in plain language.
2. The concept, and why simpler approaches are insufficient.
3. How it applies to **myRAG's** actual architecture and data flow.
4. Agree the design and the tradeoffs.
5. Implement one focused increment.
6. Verify, and discuss what was learned.

**No implementation prompt before step 4.**

---

## Essential, conditional, optional

The CORE/ADV/OPT marks describe **interview value**. They do not describe
necessity, and reading them as necessity is how security and data-integrity work
gets skipped. Every stage therefore also carries a necessity class:

| Class | Means |
|---|---|
| **`[required]`** | the current capability is **incorrect or unsafe** without it |
| **`[required-when]`** | becomes required the moment a named condition holds — a second user, a second process, real data |
| **`[deferrable]`** | optional sophistication; the system is correct without it |

**Nothing is silently removed.** Where something is deferred, this document says
what is deferred, why, and the condition that un-defers it.

### Ratings

| Mark | Meaning |
|---|---|
| **CORE** | Interview mastery. Gets asked. Do these. |
| **ADV** | Advanced. Strong differentiator, not a prerequisite for employment. |
| **OPT** | Optional. Do when curious or when the system genuinely demands it. |

### The interview-readiness checkpoint

**After Module 10 you should have enough backend and systems knowledge to hold
serious backend interviews.** That is not the same as "employable" — hiring also
turns on DSA, communication, prior experience, role fit and competition, none of
which this project supplies.

What Module 10 buys you is that the *systems* half of the interview stops being a
weakness.

**Apply throughout.** Modules 11–19 are not a prerequisite to applying; they are
what you keep doing while applying. Waiting until Module 19 to start interviewing
would be a serious mistake.

---

## Destination versus journey

These are two documents wearing one cover, and conflating them is what made the
old version read as a checklist.

**The destination** is all nineteen modules. It exists so the territory is
complete — so that when an interviewer asks about graph retrieval or
geo-distribution you can answer rather than discover the gap live. Much of it
will never be built. That is not failure; a map is not a to-do list.

**The journey** is the ordered path we actually walk, and it is short:

```text
  DONE      1.1   working synchronous pipeline
  DONE      1.2   persist what happened
  DONE      1.3   ingestion out of the request cycle
  DONE      2.1   job lifecycle, leases, retries
  DONE      2.2   idempotency
  DONE      2.3   failure classification and the dead-letter queue
  ────────────────────────────────────────────────────── you are here
  NEXT      2.4   seeing inside
            3.1   retrieval metrics       ← blocked: needs a real document corpus
            3.2   failure attribution
            3.3   answer quality gating
            4.x   answer quality — which stages is decided by 3.2's distribution
            5.0   untrusted input         ← added in this revision
            5.1   tenancy and isolation
            5.2   authentication
            6.x   contention
            ...
```

Everything past Module 6 is destination, not plan. **We re-plan at Module 4**,
once 3.2 tells us what is actually broken rather than what we guessed.

---

## Implementation status

Verified against the repository, not assumed. Anything this document says about
the system's current state is checkable here.

| Stage | Status | Evidence |
|---|---|---|
| **1.1** Working synchronous pipeline | **COMPLETE** | 4/4 citation tests hit the right page; 3/3 break-it cases; provenance confirmed end to end |
| **1.2** Persist what happened | **COMPLETE** | Alembic round-trip clean; 3 induced crashes → 3 detectable rows `[measured]`; citation `document_id` === Postgres PK |
| **1.3** Ingestion out of the request cycle | **COMPLETE** | `202` in 38ms with the agent paused `[measured]`; a worker drained the queue and the citation still resolved to the right page; two claimers proved to take different jobs; one stranded row created deliberately |
| **2.1** Job lifecycle, leases and retries | **COMPLETE** | 10 real process kills → every document terminal in 9.8s, no intervention `[measured]`; the 1.3 stranded row recovered itself in 25ms; a worker that loses its lease is proved unable to commit |
| **2.3** Failure classification and the DLQ | **COMPLETE** | a poison document costs **1 attempt instead of 5** `[measured]`; the retry budget measured at **302.1s and 221.1s across two runs** (median ~302s, a 37% spread from full jitter), where 22s had been fatal; `outage.pdf`, dead since this stage's trigger, replayed to `done` from the dead-letter list in one click |
| **2.2** Idempotency | **COMPLETE** | a doubly-indexed document repaired 9 → 3 points by re-ingestion `[measured]`; orphaned points 39 → 0; 5 concurrent uploads of one file → 1 document; Postgres and Qdrant agree 7/7 |

**Test counts** `[measured]`: 44 `rag` · 179 `backend` · 0 `agent` · 0
frontend, plus `tsc` and `eslint` clean. **Nothing runs any of them
automatically** — see the note at 15.2.

**The stranded job — now closed, and worth keeping the record of:**

```text
document_id  01a153cd-13ce-7786-995f-369c0c82377e
job_id       01a153cd-13e3-733b-94ec-7588edc0366a
status       processing, started 2026-10-19, never finished   ← the trigger
```

A worker claimed it and was killed. It sat there for six days, which was the
point: it was stage 2.1's trigger, left in place on purpose.

**It recovered itself in 25ms** the first time a worker ran with a reaper
`[measured]` — `reclaimed 1 abandoned job(s)` → `claimed … attempt=2` →
`ingestion done`, with no human action. That is the stage closing its own
trigger, and it is the most convincing demonstration 2.1 produced.

It then became **stage 2.2's** trigger, because recovering it meant ingesting
it twice: Qdrant held six points where Postgres recorded three, each
`chunk_index` present twice under two different random ids. Re-ingesting it
after 2.2's deterministic ids brought it to three `[measured]`. One row, two
stages, both triggers real rather than imagined.

**Built ahead of schedule, for stated reasons:**

| Thing | Planned at | Built at | Why |
|---|---|---|---|
| Docker / Compose | 15.1 | 1.2 | Postgres needs it; later the agent was containerised because Windows Smart App Control refuses `grpcio`'s unsigned binary |

**Known contradictions between this plan and reality, now corrected below:**

1. Stage 1.3's four-minute claim is **not reproducible** in this architecture.
   See 1.3.
2. `QDRANT_URL` was said to be forced at 1.3. It is not — only if the worker
   imports `rag` directly. See 1.3 and 12.1.
3. Stage 12.1 promised to delete "that in-memory conversation dict". **No such
   dict exists** — conversation persistence was deferred by ADR 0001 and never
   built. Corrected.
4. The fake embedder was listed as arriving at 2.4 and again at 11.1. It was
   built early, then **removed again** — see the change log. It arrives at 2.4,
   and 11.1 now refers back rather than rebuilding it.
5. **The frontend appears nowhere in this document**, and it is 23 TypeScript
   files with Redux Toolkit, RTK Query and zero tests. Added as a cross-cutting
   concern.
6. `docs/architecture/current.md` still says *"pre-1.1. Skeleton only; nothing
   is built yet."* Stale by two complete stages. Not fixed by this revision —
   flagged as a task.

---

## Cross-cutting concerns

Things that arrive when needed rather than as a module.

### Docker

Arrived at **1.2**, because Postgres needs it. Not a deployment milestone — a
local development necessity. Module 15.1 is therefore a *completion* of
containerisation (worker, backend, a clean-machine story), not its introduction.

### The fake embedding provider

**Arrives at 2.4.** A provider behind the existing seam that returns a
deterministic vector after a configurable delay, so provider slowness can be
simulated precisely.

It is needed because a hosted embedding API's free tier cannot sustain any load
measurement — ours rejects a large ingest with a 429 in about a second
`[measured]` — so every load-test failure would be a quota artefact rather than
an observation about concurrency.

> **It was built early, during 1.3 preparation, and then removed.** The build
> was sound and the safeguards were real — explicit opt-in, a startup warning,
> every chunk labelled `fake-embedding` in its payload, and a config refusal if
> it was pointed at the production collection. What was wrong was the
> *sequencing*: it arrived as an unexplained detour in the middle of a stage
> that had not said it would need one, and three further pieces of engineering
> followed before Stage 1.3 itself began.
>
> It returns at **2.4**, where the plan places it and where the stage that needs
> it can introduce it properly. The implementation is recoverable from this
> session's history, so rebuilding it is not from scratch.
>
> **The consequence for 1.3 is real and is accepted:** without it there is no
> way to measure a "before" p95, so 1.3 is verified by correctness, ordering and
> failure-injection tests instead of by a latency number. The revised evidence
> rule permits exactly that, and 1.3's justification was never the latency
> figure — see the stage.

### Structured logging and correlation IDs

Still **2.4**, and the trigger is now stronger than when it was written.
Discovered during 1.3 preparation `[measured]`: uvicorn configures no root log
handler, so `logging.lastResort` passes only WARNING and above and **every
`logger.info` in this codebase has been silently discarded** — including the
backend's own "database pool ready". A one-line `basicConfig` was added to the
agent to make its startup line visible. That is a floor, not a design; 2.4 is
where logging becomes real.

### The frontend

**Absent from every previous version of this document, which was a real gap.**
myRAG has a client: Next.js App Router, Redux Toolkit, RTK Query, 23 TypeScript
files. It is the thing that makes the system a product rather than an API.

Two consequences this document now carries:

- **Every stage that changes the API has a client consequence**, and the stage
  owns it. 1.3's `202 Accepted` is the clearest case: it turns the upload from a
  request/response into a polled state machine, and the client has to grow one.
- **The frontend has zero tests** `[measured]`, and **the condition that made
  that indefensible has now been met.** This document said testing the client
  was `[required-when]`, with 1.3 as the condition, because polling and
  terminal-state detection are real state rather than rendering. 1.3 is done.
  The tests are not written.

  Stated as an outstanding debt rather than quietly re-scheduled, because a
  `[required-when]` whose condition fires and is then ignored is how this kind
  of plan rots. What is untested today:

  | Behaviour | Why it matters |
  |---|---|
  | polling starts when a document is `queued` or `processing` | without it the UI never updates and looks frozen |
  | polling **stops** when everything is terminal | without it an idle tab requests forever |
  | `queued` and `processing` render differently | collapsing them hides that the queue is not draining |
  | a `202` body with null counts renders without blanks | the receipt is not a result |

  The transition was verified by hand at the end of 1.3 — watched in a browser,
  `QUEUED` → `DONE` with nothing touching the page. **That is an observation,
  not a regression test**, and it will not notice when someone breaks it.

### Security

Scattered across 5.1, 5.2 and 17.4 in the previous version, which let the most
time-sensitive items sit behind an ADV module. Collected here with the condition
that makes each one required:

| Concern | Required when | Stage |
|---|---|---|
| Upload size limits | from the first public endpoint | **done** at 1.1 |
| File-type validation by content, not extension | from the first upload | **done** at 1.1 (PDF magic bytes) |
| Secrets never in the repo or image | now | **done** — `.env` gitignored, `.dockerignore` excludes it |
| Parser resource exhaustion (bombs, pathological PDFs) | the moment an untrusted person can upload | **5.0** |
| Tenant data isolation | the moment a second user exists | **5.1** |
| Prompt-injection structural defence | the moment one user's document can reach another's prompt | **minimum at 5.1**, full at 17.4 |
| Authentication | the moment tenancy is claimed rather than proven | **5.2** |
| Transport security, secret rotation | the moment it leaves localhost | **15.3** |
| Backup with a tested restore | the moment data exists you would be sad to lose | **15.4** — and see the note there |

**The two that moved in this revision:** parser resource exhaustion got a stage
of its own (5.0), and prompt-injection defence got a mandatory minimum at 5.1
instead of waiting for 17.4. Both are cases of `[required-when]` work that the
CORE/ADV marks were hiding.

### Testing

**A thread, not a module.** Each kind arrives where it first proves something.

| Kind | Answers | Arrives | Status |
|---|---|---|---|
| unit | does this function behave? | 1.1 | **done** |
| integration | do the pieces agree across a real DB? | 1.2 | **done** |
| regression, named after the bug | has a fixed bug come back? | continuous | **done** |
| client/UI | does the client's state machine behave? | 1.3 | **overdue** — the condition fired, see above |
| capacity probe | what is this system's current limit? | 2.4 | needs the fake provider |
| concurrency | does it hold with N actors? | 2.1 | — |
| failure injection | what happens when a dependency dies? | 2.1 | — |
| RAG evaluation | did answer quality change? | 3.1 | — |
| load testing harness | what breaks first, and at what rate? | 11.1 | — |

**The rule that matters most: every failure you fix gets a regression test named
after it.** Done consistently, the suite becomes a written history of every way
this system has broken — the best defence against regressions and the best
interview material the project produces.

**A capacity probe is not a load-testing harness,** and conflating them is how
a stage turns into a month of k6. The probe is a script that answers one
question about one scenario; the harness at 11.1 is a reusable instrument with
workload models and warm-up.

**Neither is possible before the fake provider exists**, which is why both sit
at or after 2.4 and why **1.3 carries no load measurement at all**. That is a
deliberate deferral: measuring concurrency against a free tier that refuses the
traffic would produce a number about the quota, not about the system.

---

## The constitutional rule

> **Never add a technology because you reached its chapter. Add it only because
> the running system produced a problem that technology solves, or a stated
> requirement establishes a capability it provides.**

```text
Need a cache?          prove repeated expensive work, with numbers.
Need Redis?            prove the current mechanism cannot meet the requirement.
Need more workers?     prove one cannot meet the throughput/SLO.
Need partitioning?     prove the data topology is the bottleneck.
Need Kafka?            only if a genuine event-streaming requirement appears.
                       It probably will not. That is fine.
```

This rule outranks the module order. If you reach Module 9 and your query volume
genuinely does not justify a cache, **skip it and come back** — an unjustified
cache is worse than none, because now you own an invalidation problem you did not
need.

**The one exception, stated precisely.** A controlled teaching experiment (type
**B**) may introduce a mechanism before the system demands it, *provided* the
stage is labelled, the engineering question is written down, and the result is
connected to a design decision. Module 6 is the honest example: quotas are a real
product requirement, and the isolation-anomaly laboratory inside it is a
deliberate experiment.

**What this rule does not license.** It is not permission to skip hard things. If
the product's scope makes a capability incorrect or unsafe without some piece of
work, that work is `[required]` and the rule does not apply to it — correctness is
not a technology you adopt when curious.
---

# MODULE 1 — Foundation: make it work

Goal: one document in, one cited answer out. Deliberately naive.

**Audit verdict:** 1.1 and 1.2 are complete and were correctly sequenced and
sufficiently specified. Their content is preserved as written, with the two
template rows filled in retrospectively from what was actually verified. 1.3 was
**premature and dependent on an unproven assumption** and is rewritten.

### 1.1 — Working synchronous pipeline · **CORE** · `[required]` · **COMPLETE**

*Reason: A — real need (the starting point).*

| | |
|---|---|
| **Capability** | upload a PDF, ask a question, get an answer that cites the page it came from |
| **Now** | nothing, or the current half-built agent |
| **Problem** | — this is the starting point |
| **Diagnose** | — |
| **Root cause** | — |
| **Learn** | HTTP, REST, request lifecycle, validation, service/repository layering, the RAG pipeline end to end |
| **Build** | `POST /documents` (sync) → extract → fixed chunking → embed → Qdrant. `POST /query` → embed → top-k → prompt → cited answer. **Record provenance from the first line of code**: every chunk carries its page number, and later its section path and bounding box |
| **Verify** | upload a non-PDF; upload an empty file; ask a question with nothing indexed. Unit tests for extraction, chunking and config |
| **Done when** | it answers a question about a 10-page PDF citing a real page; all three break-it cases return a correct status code rather than a 500 |
| **Next trigger** | upload a 300-page PDF: the request hangs, then the browser times out. Did any of it save? No way to tell |
| **Covers** | HTTP · REST · API design · validation · layering · RAG basics · **provenance** |

**What completion actually produced** `[measured]`: 4/4 citation tests resolved
to the correct page (budget→p1, lead→p2, X-4021→p3, plus abstention when the
corpus cannot answer); 3/3 break-it cases returned 400/422 rather than 500; 35
unit tests at the time, now 77. Baseline run: 3 pages, 1,269 characters, 3
chunks, 4.0s ingest, ~12s query.

> **Provenance is the one thing you cannot add later.** Every other stage in
> this document can be retrofitted onto a running system. Page numbers cannot:
> if extraction discards them, the information is gone and no downstream stage
> can reconstruct it. Citations, evaluation against gold pages, and failure
> attribution all depend on it. Carry `page` through extraction → chunking →
> indexing from day one, even while everything else is deliberately naive.

### 1.2 — Persist what happened · **CORE** · `[required]` · **COMPLETE**

*Reason: A — real need (observed at 1.1).*

| | |
|---|---|
| **Capability** | every upload leaves a durable record of what was attempted and what happened to it, visible after a crash |
| **Now** | sync pipeline; the only record a document exists is its chunks in Qdrant |
| **Problem** | a timed-out upload leaves the system in an unknown state — partially indexed is indistinguishable from not indexed. **True by construction**, not by measurement: before this stage there was no table in which an attempt could have been recorded, so the detection rate was 0% with nothing to measure. The 100% after it *is* `[measured]` |
| **Diagnose** | count points in Qdrant before and after an interrupted upload |
| **Root cause** | no durable record of intent. The vector index is a *result*, not a log of what was attempted |
| **Learn** | relational modelling, ACID, transactions, indexes, connection pooling, migrations |
| **Build** | Docker Compose + Postgres. `documents`, `ingestion_jobs`. Status lifecycle. Alembic. Repository layer |
| **Verify** | kill the process mid-ingest; confirm the partial state is now *visible*. Integration tests against a real Postgres |
| **Done when** | interrupted ingests are detectable; the migration round-trips up→down→up cleanly; autogenerate reports no drift; the invariant (commit before calling the agent) is mutation-tested |
| **Next trigger** | you can see the failure now, and the request still blocks for the whole ingest |
| **Covers** | DB design · SQL · ACID · transactions · indexes · pooling · migrations · service/repo layering |

**What completion actually produced** `[measured]`: 3 induced crashes → 3
detectable rows, from 0% by construction. The citation's `document_id` is
byte-identical to the Postgres primary key, proving the id flows down. Best
single piece of evidence: a document that answers live queries — its chunks are
in Qdrant — while its job row still says `processing / finished_at = NULL`. 49
backend tests, including four CHECK constraints that make an impossible job state
unrepresentable.

**Deliberately left broken, and documented:** a job whose process dies stays
`processing` forever. Nothing retries it, reclaims it, or notices. That is 2.1's
trigger.

**There were three such rows; there is now one.** The original three were lost
when a `downgrade base` during 1.3's schema work dropped both tables — a
heavier command than the `downgrade -1` that was wanted. They were development
debris and reproducible, but the `[measured]` claim that rested on them was not
true for a while, which is exactly the failure mode the evidence labels exist to
prevent. The replacement row was created deliberately at the end of 1.3 and its
id is recorded in the implementation status above.

### 1.3 — Ingestion out of the request cycle · **CORE** · `[required]` · **COMPLETE**

*Reason: A — real need. The trigger was rewritten in this revision; the old one
was a hypothesis stated as fact.*

> **Renamed.** It was "Asynchronous ingestion", and that name misleads: the
> backend was already `async def` everywhere and this stage added none. Those
> are two unrelated things wearing one word —
>
> | | means | had it before 1.3? |
> |---|---|---|
> | `async def` / `await` | a way of writing code that waits | **yes** |
> | asynchronous ingestion | work happening outside the request | no |
>
> The whole stage could have been built in synchronous code. What changed is
> *where* the work runs, not how it is written.

> **This stage was the reason for the whole revision.** Read the audit before
> the stage.

#### What completion actually produced

`[measured]`, from the end-to-end runs:

| Claim | Evidence |
|---|---|
| the upload response no longer depends on document size | `202` in **38 ms**, and in **45 ms** — the second with the agent container *paused*, so no ingest was possible at all |
| an agent outage is invisible at upload time | that same paused-agent upload returned `202`, not `503`. At 1.2 it was a 503 |
| a worker drains the queue | it found the job 1.3's own route had left `queued` and drove it to `done` in ~3s |
| **the citation chain survives the process split** | `document_id 01a153bf-1ac5-…` minted by the API, claimed by the worker, written to Qdrant, returned in a citation — resolving to page 2, where the fact is |
| two workers never take the same job | `test_claim_concurrency.py`, with the mutation proving plain `FOR UPDATE` blocks where `SKIP LOCKED` does not |
| the client reaches a terminal state with no refresh | watched: a row went `QUEUED` → `DONE` with its page and chunk counts while nothing touched the page |
| a killed worker leaves a visible row | one, deliberately, id above |

**No latency claim is made**, and none was available to make — see Step 0.

#### Two things 1.3 produced that it did not set out to

Both are consequences worth carrying into 2.1 rather than footnotes:

**A stuck job makes the client poll forever.** `useDocuments` polls while
anything is non-terminal, and a stranded `processing` row never becomes
terminal. The network log showed 31 requests and climbing. The UI is being
honest — something genuinely *is* unfinished — but one abandoned job now costs
perpetual background traffic. A lease is what gives the client something true
to say instead.

**Graceful shutdown can take as long as `AGENT_TIMEOUT`.** The worker's stop is
cooperative: `run()` checks the stop event *between* jobs and does not cancel
the one in flight. So a `SIGTERM` during a 120-second ingest outlives Docker's
default 10-second patience and becomes a `SIGKILL` — turning a clean stop into
exactly the stuck row the cooperative stop was meant to avoid. Mitigated by a
lease at 2.1; properly fixed by cancellation and drain at 12.3.

#### Audit of the previous version

The old trigger read: *"a 300-page PDF blocks one worker process for four
minutes; concurrent uploads make the API unresponsive"*, and the measure read
*"p95 upload response: 240s → <200ms. API availability during bulk ingest:
degraded → unaffected"*.

Three problems.

**1. The four minutes is not reproducible in this architecture** `[hypothesis,
refuted by analysis]`. The embedding provider batches 100 texts per call. A
300-page PDF produces roughly 300 chunks, which is **3 network round trips**, not
300. At the observed ~4s per call that is about 12 seconds. Four minutes requires
a provider that is slow or throttled, not a document that is large. Building
toward a 240s "before" number would have meant *manufacturing* it.

**2. "Concurrent uploads make the API unresponsive" is probably false as
written** `[hypothesis]`. The agent's ingest route is a plain `def`, so FastAPI
runs it on a threadpool and the event loop stays free. That pool holds 40 threads
`[measured]`. Twenty concurrent uploads use twenty of them. The curriculum's own
"upload 20 documents at once" is *below the ceiling it was supposed to expose*.

**3. The problem that was never written down** — part observed, part expected:

```text
AGENT_TIMEOUT = 120s        vs        an ingest with no upper bound

on timeout:   backend records `failed`, returns 503        ← test-covered
              agent keeps working and writes the chunks     ← NOT yet observed
              → a document the database calls failed, that answers queries
```

**The middle line is a `[hypothesis]`.** 1.2 demonstrated the same divergence by
*killing* a process, and that run is recorded — but a timeout firing against a
still-running agent has never been observed, and the two are not the same event.
One is induced by an operator; the other would happen unattended, which is
exactly why it is the stronger argument for this stage *if it holds*.

What **is** established, independent of that: work is lost on any restart (three
`processing` rows exist right now), there is no retry without re-uploading the
bytes, and there is no progress signal — a long spinner is indistinguishable
from a hang.

#### The stage, corrected

| | |
|---|---|
| **Capability** | upload returns immediately with a job id; the document indexes in the background; the client can ask how it is going and see it finish |
| **Now** | durable records, synchronous ingestion, an unbounded request |
| **Problem** | slow unbounded work runs inside the request/response cycle. Four consequences, and **they do not all have the same evidence behind them** — see *What is actually established* below: (a) killing the process mid-ingest leaves chunks in the index and a job row saying `processing` `[measured]` at 1.2; (b) **a 120s timeout is expected to produce that same divergence unattended, with the backend recording `failed` while the agent runs to completion** `[hypothesis]`; (c) any restart loses in-flight work and leaves a `processing` row — three exist now `[measured]`; (d) there is no retry without re-uploading, because the bytes live only inside the request `[measured]` — they are a request-scoped object and nothing else holds them |
| **Diagnose** | kill the agent mid-ingest and look at the two stores — that reproduction already exists from 1.2 and the rows are still there. Read `AGENT_TIMEOUT` against the fact that `rag.ingest` has no upper bound. **The timeout divergence cannot be reproduced yet** — see *What is actually established* below |
| **Root cause** | the request is both the unit of work and the unit of durability. Those have to be separated |
| **Learn** | queues, background workers, producer/consumer, `202 Accepted`, polling vs push, `SELECT … FOR UPDATE SKIP LOCKED`, where bytes live between accept and process |
| **Build** | see the six pieces below |
| **Verify** | see verification below |
| **Done when** | all six of the standard criteria, plus: **the upload response no longer depends on document size** — provable without a stopwatch, because the handler no longer calls the agent at all; a worker killed mid-job leaves a row a human can find; the client shows progress and reaches a terminal state without a manual refresh. **No latency claim is made** — see Step 0 |
| **Next trigger** | kill the worker mid-job. The document sits at `processing` forever. Nothing retries it — and now it is a *worker* that died, not a request, so nobody is waiting to notice |
| **Covers** | queues · workers · async processing · job state · API design (202/polling) · client-side state machines |

#### Step 0 — there is no measurement, and that is the honest position

**This stage carries no load measurement.** The previous version of it opened
with a capacity probe: N concurrent uploads, p50/p95, `/health` pollers. That
probe needed the fake embedding provider, because Gemini's free tier rejects a
large ingest with a 429 in about a second `[measured]` — so a measurement taken
against the real provider would describe the quota, not the system.

The fake provider was built, and then removed as out of sequence. It returns at
**2.4**. Until then:

| What we wanted to measure | Status |
|---|---|
| upload p50/p95 under concurrent load | not measurable |
| whether either `/health` degrades under load | not measurable |
| the 40-thread pool ceiling | not measurable |

**So what justifies the stage without a number?** Three things that are not
magnitudes, and the evidence rule in the front matter is explicit that an
invariant is proven by a test rather than by a metric:

1. **Work in the request cycle is lost on restart.** Three `processing` rows
   exist right now `[measured]` and nothing recovers them.
2. **There is no retry without re-uploading**, because the bytes live only
   inside the request `[measured]` — that is a structural fact about the code,
   not a performance claim.
3. **The request has no upper bound**, so `AGENT_TIMEOUT` is a guess standing in
   for a queue. Its own comment in `backend/app/core/config.py` says so.

None of those improve by being timed. They are fixed by moving the work out of
the request, and the proof is that a worker can be killed and the document still
reaches a terminal state.

**What is deliberately given up:** the ability to say "p95 went from X to Y".
That claim can be made retrospectively at 2.4, once the fake provider exists and
the same probe can be pointed at both architectures — the async one being the
only one still running by then, but the synchronous path is a `git checkout`
away. Writing it down now stops it being quietly forgotten.

**What was measured instead**, and it turned out to be enough:

> `202` in **38 ms**, and **45 ms** with the agent container *paused* — a state
> in which no ingest could possibly have happened.

That second number is the better evidence, and it is not a latency measurement.
It shows the response time is independent of the work, because there was no
work. A stopwatch comparison would have been weaker: it would have proved the
new path is faster, which was never in doubt, rather than proving the
structural claim — that the handler no longer does the thing.

#### What is actually established, and what is not

The previous version of this stage read as though the timeout divergence had
been observed. **It has not.** Separating the two matters, because (b) is the
consequence that most justifies the stage and it is the one with the weakest
evidence behind it.

| Claim | Evidence | Status |
|---|---|---|
| killing the agent mid-ingest leaves chunks indexed and the job row at `processing` | a recorded run at 1.2 — a document that answered live queries while its job said `processing / finished_at = NULL` | **`[measured]`** |
| a stranded `processing` row exists right now | `SELECT status, count(*) FROM ingestion_jobs` — one, id recorded in the implementation status | **`[measured]`** |
| the backend records `failed` and returns 503 when the agent call raises `AgentUnavailableError` | an existing unit test with an injected stub agent | **verified by test** — the backend half only |
| **a real 120s timeout produces the divergence on its own, with the agent running to completion and writing the chunks afterwards** | **none. Never run** | **`[hypothesis]`** |
| 20 concurrent uploads do not exhaust the 40-thread pool | — | `[hypothesis]` |

**Why (b) is still worth stating as the stage's problem.** Its two halves are
each established separately — the backend's timeout handling by unit test, the
agent's indifference to its caller by the 1.2 crash run — and the composition is
the obvious consequence. But "obvious consequence of two verified halves" is a
hypothesis, not a measurement, and the reproduction below is what would
retire it.

**The reproduction is deferred, not dropped.** It needs an ingest slow enough
to exceed 120s on demand, which is what the fake provider's configurable delay
was for. Without it the only way to force a timeout is a genuinely large
document, and the free tier refuses one.

So (b) stays a `[hypothesis]` through this stage and is settled at **2.4**: one
upload with the delay above `AGENT_TIMEOUT`. Recorded here so it is not
forgotten — and if it turns out the agent *does* abandon work when its caller
disconnects, that is a more interesting result than the expected one.

**It does not block 1.3.** (a), (c) and (d) are established, and the queue fixes
all four regardless of which way (b) resolves.

#### Step 1 — the six pieces

```text
POST /documents  →  store the bytes  →  INSERT job (queued)  →  COMMIT  →  202 + job id

worker process:  claim a queued job  →  ingest  →  mark done/failed

GET /documents/{id}  →  current status
```

| | Piece | Note |
|---|---|---|
| 1 | a `queued` status | a **hand-written** migration — autogenerate cannot see inside a CHECK constraint, so this is also the stage that teaches when autogenerate is not enough |
| 2 | a claim query | `SELECT … FOR UPDATE SKIP LOCKED`. `SKIP LOCKED` is the whole trick: it steps over locked rows instead of waiting, so two workers never take the same job |
| 3 | a worker process | a second entry point and its own container |
| 4 | **somewhere for the bytes to live** | the decision the old plan omitted entirely — see below |
| 5 | `202` + `GET /documents/{id}` | the route stops returning a result |
| 6 | client polling | RTK Query's `pollingInterval`, stopping on a terminal status |

#### Step 2 — where the bytes live

**This is the decision that actually blocks you**, and the previous version of
this document did not mention it. Return `202` immediately and the worker has no
file: the request that carried it is gone.

| Option | Tradeoff | Verdict |
|---|---|---|
| `bytea` column in Postgres | transactional with the job row, trivially consistent — but bloats the database, every WAL write and every backup | **start here** — correctness first, and the corpus is tiny |
| Shared volume between backend and worker | simple and fast — breaks the moment they are on different machines | skip; it trades the right property for the wrong one |
| Object storage (MinIO/S3) | the production answer, and what 15.3 assumes | `[required-when]`: the database size becomes a problem, or 12.1 separates the processes across machines |

Deferring object storage is a real deferral with a named trigger, not an
omission.

#### Step 3 — verification

| Kind | What it proves |
|---|---|
| integration | upload returns `202` with a job id; polling reaches `done`; chunks exist and cite the right pages |
| failure injection | kill the worker mid-job → the row stays `processing` and is findable. **This is 2.1's trigger, created on purpose** |
| concurrency | two workers, one queued job, `SKIP LOCKED` → it is claimed exactly once |
| client | polling starts on `202`, stops on a terminal status, and does not poll forever on `failed`. **The frontend's first real test** |
| regression | the timeout divergence from the audit above must become impossible, or if still possible, documented with its window |

#### What 1.3 does *not* force

**`QDRANT_URL` is not required here.** The previous version said embedded Qdrant
"stops being fine at stage 1.3, when a separate worker process appears". That is
only true if the worker imports `rag` directly. If the worker calls the agent
over HTTP — which `docs/architecture/current.md` already documents as the plan —
the agent remains the only process touching the index and embedded mode survives.
The trigger for a Qdrant server moves to **12.1**, when a second process
genuinely needs the index. Corrected in this revision.

**No leases, no reaper, no retries.** A dead worker leaves a stuck row. That is
deliberate: 2.1's measure requires a stuck row to exist, and a stage whose
trigger you have quietly prevented is a stage you cannot learn from.

**No Redis.** A Postgres-backed queue is sufficient at this volume and teaches
`SKIP LOCKED`, which is the more transferable thing.

---

# MODULE 2 — Durable ingestion: make it survive

Goal: the pipeline recovers from its own failures without a human.

**Audit verdict:** correctly sequenced, and 2.1–2.3 were already well specified.
Each gains `Capability`, `Done when` and evidence labels. **2.4 changed
materially**: the fake embedder is removed from its Build (already built), and
its trigger is now stronger because a concrete observability failure has been
measured.

### 2.1 — Job lifecycle, leases and retries · **CORE** · `[required]`

*Reason: A — real need. The trigger will exist by construction after 1.3.*

| | |
|---|---|
| **Capability** | a document always reaches a terminal state, with no human intervention, even when workers die |
| **Now** | async ingestion; a dead worker orphans its job permanently |
| **Problem** | a **worker** killed mid-ingest leaves the document stuck at `processing` forever, and nothing recovers it `[measured]` — demonstrated at the end of 1.3 and still sitting in the database, id in the implementation status. Worse than the 1.2 version of the same failure: no request is open, so nobody is waiting to notice, and the only symptom is a row nobody is looking at. **Plus a second cost 1.3 surfaced:** the client polls forever, because the job never reaches a terminal state |
| **Diagnose** | query for jobs in `processing` older than N minutes. Notice that nothing else in the system would ever have told you |
| **Root cause** | claiming a job is permanent. Nothing distinguishes "in progress" from "abandoned" |
| **Learn** | job state machines, visibility timeout, lease/heartbeat, at-least-once delivery, exponential backoff, jitter |
| **Build** | states `queued → processing → done / failed`. `SELECT … FOR UPDATE SKIP LOCKED` to claim. A lease with expiry; a reaper that requeues expired leases. Retry with backoff + jitter |
| **Verify** | kill workers repeatedly during a batch; confirm every document eventually reaches a terminal state. Concurrency test: a reaper and a live worker must not both own one job. Failure-injection test per crash point (before claim, mid-ingest, after write, before commit) |
| **Done when** | zero orphans after a run of induced crashes; the stranded row from 1.3 is recovered or explicitly closed; the lease duration is a justified number, not a guess; a worker that loses its lease cannot still mark the job done; **the client stops polling a job that has been abandoned**, because it has been told something truthful about it |
| **Next trigger** | the retry re-ran the whole pipeline. The document now has duplicate chunks, and you paid to embed it twice |
| **Covers** | job queues · state machines · leases · `SKIP LOCKED` · retries · backoff · jitter · at-least-once |

**On the measure — the framing was wrong, and the run proved it.**

"Orphaned jobs after 10 induced crashes: 10 → 0" was written as a
`[requirement]`. It is **not measurable as stated**, and the reason is a
property of the design rather than of the apparatus: **every worker reaps
before it claims**, so orphans cannot accumulate to 10 in the first place. The
highest number observed at any instant was 1. A measure that assumes a state
the system prevents is a measure of nothing.

What was actually run and what it showed `[measured]`:

> **10 real process kills** — `TerminateProcess`, no graceful shutdown, each
> worker killed while holding a job — then **one ordinary worker**.
> Every document reached a terminal state in **9.8 seconds** with no
> intervention. `attempts` distribution `{1: 9, 2: 1}`.

The technique still mattered and is worth reusing: the agent container is
paused first so every ingest hangs and a kill always lands mid-job. At 1.2 a
naive kill-at-t=5s lost a race against a rate limit.

**The lesson is about writing measures, not about this one.** A target number
can encode an assumption about the architecture — here, that orphans pile up —
and when the architecture makes that assumption false, the honest move is to
report what happened instead of engineering the system into the shape the
measure expected.

### 2.2 — Idempotency · **CORE** · `[required]`

*Reason: A — real need, created by 2.1's retries.*

| | |
|---|---|
| **Capability** | re-processing a document is safe: the index ends up the same whether a job ran once or five times |
| **Now** | jobs retry reliably, and retries corrupt data |
| **Problem** | after a retry the same fact is indexed twice from the same page, and the point count for that document is double what it should be `[measured]` — 2.1's reaper recovered the 1.3 stranded row, which ingested it a second time: Qdrant held 6 points where Postgres recorded 3, each `chunk_index` present twice under two different random ids. **A second problem was found while diagnosing the first** and is not a retry effect at all: `ON DELETE CASCADE` stops at the edge of Postgres, so deleting a document leaves its vectors behind — **39 of 54 points (72%) belonged to documents that no longer existed** `[measured]` |
| **Diagnose** | compare Qdrant's point count per document against the `chunk_count` of its latest successful job. `chunk_index` is the sharper tool than the count: `[0,0,1,1,2,2]` says *doubly indexed*, where `6 vs 3` only says *wrong* |
| **Root cause** | the pipeline is not idempotent: re-running it produces new rows rather than replacing old ones. Point ids are random by deliberate choice at 1.1 |
| **Learn** | idempotency, natural keys, content addressing, deterministic ids, unique constraints, upsert, HTTP idempotency keys |
| **Build** | SHA-256 content hash on `documents`, unique. Deterministic point ids. **Upsert-then-prune**, not delete-then-upsert — see the corrections below. A reconciliation tool for the orphans. `Idempotency-Key` headers deferred with a trigger |
| **Verify** | upload the same file 5× concurrently; re-ingest a document repeatedly. Point count must stay constant. Concurrency test on the content-hash uniqueness path — two simultaneous uploads of the same bytes |
| **Done when** | duplicate chunks after repeated retries are zero; wasted embedding calls are **eliminated** (measuring them needs a counter, which is 2.4); the behaviour of a *second* upload of identical bytes is a decided and documented product question, not an accident |
| **Next trigger** | every failure is retried identically. ~~They retry forever, burning quota~~ — **that turned out to be false**: 2.1's `max_attempts` already bounds it and a corrupt PDF costs no quota at all. The real cost is the opposite one, and 2.3 measured it |
| **Covers** | idempotency · content addressing · unique constraints · upsert · HTTP idempotency keys |

**Why the random point ids at 1.1 were correct.** Deterministic ids would have
pre-fixed the duplicate-chunk corruption this stage exists to reproduce. The
decision is recorded as D3, and it paid out exactly as intended: by the time
this stage ran there was a real doubly-indexed document to measure rather than
a scenario to imagine.

**Four corrections this stage made to its own plan**, each forced by something
measured. Full write-ups in `docs/experiments/0002-…` and `0003-…`.

1. **`uuid5(uuid.UUID(document_id), chunk_index)` crashes.** The engine has
   never required `document_id` to be a UUID — `rag/tests/test_pipeline.py`
   passes `"doc-1"`, and `pipeline.py` states that identity belongs to whoever
   owns the durable record. A fixed namespace with the id in the *name* keeps
   that contract. Tightening it so the id scheme could be prettier would have
   been the engine taking back a decision it deliberately delegated.

2. **Delete-then-upsert is the wrong order, and a tail delete does not work at
   all.** Deleting first leaves a working document unsearchable until the write
   lands, and permanently absent if embedding then fails. But upserting first
   and deleting `chunk_index >= n` repairs *nothing* that predates the id
   scheme — the measure showed 6 points becoming 9. **Points written under a
   different id scheme are identifiable only by `document_id`, never by
   index.** The fix is to prune everything that is not one of the ids just
   written, which makes the guarantee unconditional: after a successful
   ingestion the store holds exactly the chunks that ingestion wrote.

3. **`Idempotency-Key` headers are deferred, not built.** For an upload, *the
   same request* **is** *the same bytes*, which the content hash identifies
   with no client cooperation and no key store. On this endpoint a key is
   strictly weaker — two different keys carrying identical bytes would both be
   honoured. **Trigger:** the first endpoint whose identity is not derivable
   from its body, such as a POST that charges money, or 12.1's conversation
   turns.

4. **A duplicate upload returns `200`, not `409`.** The request is "make sure
   this document is indexed", and it already is. A browser retrying a timed-out
   `POST` is the common cause, and `409 Conflict` would report failure for an
   upload that worked. A duplicate of a document whose last attempt **failed**
   queues a new job on the *same* document — one document, many jobs, which is
   the first real payout on 1.2's two-table split.

**The orphans were not predicted by this plan at all.** They are a dual-write
failure: Postgres and Qdrant are two stores with no transaction between them,
and `ON DELETE CASCADE` reaches only one of them. `tools/qdrant_orphans.py`
reconciles them and took 39 → 0, but it is a *cleanup*, not a fix — nothing yet
prevents the next one. That is Module 14's outbox, and `DELETE /documents/{id}`
is deliberately not built until it exists, because deleting a row and then its
vectors recreates exactly the orphan this stage just removed.

**What the orphans actually cost, which is the part worth remembering.** A live
query answered confidently and cited a document that returns 404. Three
quarters of the index was text from deleted documents, and retrieval quality
measurement at 3.1 would have been scored against it.

### 2.3 — Dead-letter queue · **CORE** · `[required]`

*Reason: A — real need. **Not the one originally written down** — the retries are bounded and cost no quota; the cost is in the other direction. See the Problem row.*

| | |
|---|---|
| **Capability** | a permanently broken document stops consuming resources, and an operator can see it, inspect it and replay it |
| **Now** | every failure retried identically, with one budget tuned for neither kind |
| **Problem** | **the stated problem was false, both halves, and measuring it is what showed that.** A corrupt PDF was bounded at **5 attempts over 14.6s** by 2.1's `max_attempts`, and cost **zero embedding quota** — `rag/pipeline.py` extracts before it touches a provider `[measured]`. The real cost runs the other way: a **valid** document uploaded during an outage was **permanently destroyed after 22 seconds** `[measured]`, a window `docker compose restart agent` fits inside. One policy, two opposite failures, tuned for neither |
| **Diagnose** | feed in a corrupt PDF and count attempts; then upload a *valid* one with the dependency stopped and time how long before it is abandoned. The second is the one nobody thinks to run |
| **Root cause** | no distinction between *transient* failure (retry) and *permanent* failure (stop) |
| **Learn** | error classification, poison messages, DLQ, operator tooling, alerting |
| **Build** | classify on the agent's **HTTP status** — 4xx permanent, 5xx and no-response transient, with 429 carved out. Permanent fails at attempt 1; transient gets a budget measured in minutes, with a **cap on any single delay**. `failure_kind` on `ingestion_jobs`. The DLQ is a **query, not a table** — see below. `GET /documents?status=failed` and `POST /documents/{id}/retry` |
| **Verify** | the classifier over the whole status table, including codes nothing emits yet. A 429 must requeue **despite being 4xx**. No single delay may exceed the cap at any attempt. And the budget must be simulated against the real `Settings`, not against a literal — see the correction below |
| **Done when** | a permanent failure costs exactly one attempt; the transient budget is a measured number rather than a computed one; every status the agent can return has a classification; the replay path is exercised end to end, not just written |
| **Next trigger** | all of this is happening invisibly, and 2.3 proved it the hard way. **Both of this stage's defects were found by going and looking** — a corrupt PDF fed in by hand, a valid one uploaded with the agent stopped. Nothing would have reported either. The dead-letter list is a page someone has to remember to open, there is no count of how deep it is, and every `logger.info` in the backend is still discarded `[measured]` |
| **Covers** | DLQ · error classification · poison messages · operator tooling |

**Already half-built, inadvertently — and the useful half was not the one we
expected.** `rag/errors.py` says its hierarchy is where this distinction belongs
when 2.3 needs it. It turned out the backend does not need the hierarchy at all.

The backend never imports `rag`; it learns what happened from the agent's HTTP
response. The agent *already* maps the engine's errors onto status codes, so the
classification arrives for free:

```text
400 / 413 / 422   permanent — the request can never succeed
429               transient — 4xx by number, "come back later" by meaning
500 / 502 / 503   transient — the system failed you
(no response)     transient — nothing was judged about this document
```

That is the HTTP specification's own semantics, and keeping the backend ignorant
of the engine is what made the 1.3 worker split possible in the first place.

**The DLQ is a query, not a table.** The roadmap said *"move to DLQ"*. A separate
table buys nothing here: dead jobs already cannot clog the queue (`failed` is
terminal and the claim only matches `queued`), replay already exists
(`create_job_for_document`, built at 2.2), and a separate table would duplicate
the foreign key, make the latest-job join read two tables, and lose the attempt
history 1.2's two-table split exists to keep. The thing a broker's DLQ isolates
against — dead messages blocking live ones — is a broker problem this schema does
not have.

**The retry budget was got wrong by a factor of three, and the test meant to
catch it did not.** The first attempt set `max_attempts = 8` and documented it as
"about three minutes", reasoning from the sum of the ceilings. What a document
actually experiences is the sum of the *draws*, and full jitter halves every one:
the realised coverage was a **median of 91s, p10 of 55s** over 20,000 simulated
runs. One document in ten gave up after 55 seconds.

The test that was supposed to pin this asserted the ceilings of a hardcoded
`RetryPolicy(max_attempts=8, ...)`, so it agreed with itself while the system ran
a policy nobody had checked. It now reads `Settings()` and simulates. **Two
lessons, both general:** a test that asserts a literal instead of the
configuration cannot detect drift, and reasoning about a bound is not the same as
measuring a distribution.

**`Idempotency-Key`-style operator ergonomics are deliberately minimal.** One
button, one document. Bulk replay waits for someone to have enough dead rows to
want it.

### 2.4 — Seeing inside · **CORE** · `[required]`

*Reason: A — real need, and now with a measured failure behind it.*

| | |
|---|---|
| **Capability** | you can answer "is ingestion healthy right now?" in seconds, and follow one upload across two processes |
| **Now** | a reliable pipeline you cannot observe |
| **Problem** | two things, both concrete. You cannot answer "is ingestion healthy?" without hand-written SQL. And **every `logger.info` in this codebase is currently discarded** `[measured]` — uvicorn installs no root handler, so `logging.lastResort` passes only WARNING and above, and the backend's own "database pool ready" has never once appeared in a log |
| **Diagnose** | try to answer the health question and time yourself. Then grep a backend log for a line you know the code emits |
| **Root cause** | no logging configuration, no structured output, and no correlation across the API/worker boundary |
| **Learn** | structured logging, correlation IDs, counters vs gauges vs histograms, the RED method. **Learn the distinction now:** `request_id` is *yours* — one inbound API call, propagated by you into the job row. `trace_id` / `span_id` are the tracing system's, and arrive at 10.2. Conflating them is why people bolt on tracing later and find it useless |
| **Build** | real logging configuration. JSON logs with a `request_id` threaded API → worker. Counters for jobs by state, a histogram for job duration, a gauge for queue depth. `/metrics`. **Also: the fake embedder**, behind the provider seam — and with it, the capacity probe and the deferred 1.3 measurements listed below |
| **Verify** | induce a failure and trace it end to end using only the correlation id. Assert, in a test, that a log line the code emits actually reaches a handler — the bug above would have been caught by one such test |
| **Done when** | an induced failure is diagnosable from logs alone in seconds; a `request_id` from an upload response appears on the worker's log lines for that job; no log statement in the codebase is silently discarded |
| **Next trigger** | the system is reliable, and the answers are still often wrong. You have no idea how often, or which part is at fault |
| **Covers** | structured logging · correlation IDs · metrics · RED |

**This stage inherits three deferrals from 1.3**, all of which need the fake
embedder and none of which block anything before now:

| Deferred from 1.3 | What to do here |
|---|---|
| upload p50/p95 under concurrent load | the capacity probe, against the async architecture — and against the synchronous one, which is a `git checkout` away, for the before/after pair |
| whether either `/health` degrades under load | the same probe's two pollers, on separate connection pools |
| does a 120s timeout really produce the Postgres/Qdrant divergence? | one upload with the delay above `AGENT_TIMEOUT` |

**The fake embedder was built early once and removed as out of sequence.** Its
design is settled — deterministic hashed vectors, per-batch delay, explicit
opt-in, a startup warning, `fake-embedding` in every payload, and a config
refusal if it is pointed at the production collection. Rebuilding it here is
re-applying a known design, not inventing one.
---

# MODULE 3 — Measurement: stop guessing

**The turning point of the entire project.** Before this you are guessing; after
it every change is evidence-driven. Do not skip it, do not shrink it.

**The eval set is a primary artifact of this project, not a side experiment.** It
is version-controlled, it grows with every new document format and failure mode,
and it is the thing that makes every later claim checkable. Treat it with the
same care as the source code — because every "this improved retrieval by 14%"
you will ever say depends on it.

**Audit verdict:** correctly sequenced and well specified, with **one missing
prerequisite that will block you** and a set of illustrative numbers that read
as measurements.

> ### Blocker: 3.1 needs real documents, and the project has none
>
> `[measured]` The only documents in this repository are synthetic PDFs
> generated in-memory by `rag/tests/fixtures/pdf_builder.py` — single column, no
> tables, no headers, no images. That file's own docstring says it: *"It is
> emphatically not an evaluation corpus."*
>
> An eval set built on them would produce flattering numbers that mean nothing,
> and worse, it would hide exactly the failures Module 4 exists to fix — because
> multi-column interleaving, header pollution and flattened tables cannot occur
> in documents that have none of those things.
>
> **So 3.1 has a prerequisite that is not engineering work:** collect 5–10 real
> documents with real layout problems. Technical PDFs, a scanned page, something
> two-column, something with a table that matters. This is an afternoon of
> finding files, and it gates the most important module in the document.
>
> **Decision needed:** which corpus. Public standards documents and papers are
> the easy answer; anything you actually care about reading is the better one.

### 3.1 — Retrieval metrics · **CORE** · `[required]`

*Reason: A — real need. Without this, every later quality claim is unfalsifiable.*

| | |
|---|---|
| **Capability** | any change to retrieval can be answered with "it moved recall@5 by N on the eval set" instead of an opinion |
| **Now** | reliable pipeline, unknown quality |
| **Problem** | you change chunk size. Are answers better? You ask three questions and it "feels" fine. That is not knowledge |
| **Diagnose** | you cannot — that is the problem |
| **Root cause** | no ground truth, so no attribution. "Bad answer" could be extraction, chunking, embedding, retrieval, context or generation |
| **Learn** | ground truth datasets, Recall@K, Precision@K, MRR, nDCG, slicing by question type |
| **Build** | 30–50 hand-written questions over 5–10 **real** documents, each with a gold answer and the page(s) that contain it. A runner that calls retrieval **directly**, no chatbot in the loop. Metrics, sliced by question type. Include deliberately unanswerable questions — 17.3 calibrates abstention against them |
| **Verify** | run against a deliberately broken chunker; confirm the metric drops. That is the only way to know the instrument works |
| **Done when** | **this stage produces the baseline every later stage is compared against** — committed, versioned, reproducible by one command; the runner is deterministic given a fixed corpus and model; the instrument is validated against a known-bad configuration |
| **Next trigger** | the baseline is low enough to matter and you cannot say which layer is responsible |
| **Covers** | evaluation · ground truth · IR metrics · experiment design |

**On the numbers.** The previous version said *"recall@5 is 41%. Now: why?"*
That is an `[illustration]` — a plausible shape, not a prediction, and this
project has never measured recall at all. **Whatever 3.1 measures is the real
baseline**, and 4.x's sequencing depends on it rather than on 41%.

### 3.2 — Failure attribution · **CORE** · `[required]`

*Reason: A — real need. Module 4 cannot be sequenced without it.*

| | |
|---|---|
| **Capability** | every failing question has a named cause, so effort goes to the layer that is actually losing recall |
| **Now** | a number that says the system is bad, with no cause |
| **Problem** | the baseline is short of acceptable and you do not know which layer loses the difference |
| **Diagnose** | for each failure, inspect the pipeline output at every stage: did extraction get the text? did a chunk contain the gold span? was it retrieved? was it ranked in the top-k? |
| **Root cause** | failures were being treated as one undifferentiated category |
| **Learn** | failure taxonomies, root-cause attribution, per-layer instrumentation |
| **Build** | a taxonomy (`extraction / chunking / embedding / retrieval / ranking / context / generation`) and a script that labels each failing question automatically where possible, manually where not |
| **Verify** | inject a known fault at each layer; confirm the classifier attributes it correctly. A classifier you have not fault-injected is a classifier you are trusting blindly |
| **Done when** | every failing question in the eval set has a cause; the distribution is written down; the classifier has been validated at each layer |
| **Next trigger** | the distribution names the dominant layer. **That is what decides which 4.x stages exist at all** |
| **Covers** | failure taxonomy · diagnosis · per-layer tracing |

### 3.3 — Answer quality and regression gating · **CORE** · `[required]`

*Reason: A — real need. Retrieval quality and answer quality are different things.*

| | |
|---|---|
| **Capability** | a change that makes answers worse is blocked before it merges |
| **Now** | retrieval is measurable; answer quality is not |
| **Problem** | retrieval improves and you cannot tell whether *answers* improved |
| **Diagnose** | hand-score 15–20 answers; compare to an LLM judge's scores |
| **Root cause** | no automated answer-quality signal, and no protection against regressions |
| **Learn** | LLM-as-judge, judge calibration, faithfulness vs correctness, regression gates |
| **Build** | a judge, calibrated against your hand scores until it roughly agrees. Citation accuracy. A one-command run that compares to baseline and fails on regression |
| **Verify** | make a change you know is worse; confirm the gate catches it |
| **Done when** | judge/human agreement ≥80% `[requirement — our threshold for trusting it]`; the gate blocks a known-bad change; the baseline comparison runs in one command |
| **Next trigger** | you have a measuring instrument and a ranked list of what is broken. Go fix the biggest one |
| **Covers** | LLM-as-judge · calibration · regression testing · CI for quality |

**This is where CI becomes genuinely overdue** — see the note at 15.2. A
regression gate nothing runs automatically is a regression gate in name only.

---

# MODULE 4 — Answer quality

Entered only with a baseline and an attribution distribution in hand. Each stage
is one experiment: hypothesis → change → re-run → keep or delete.

**Work upstream first.** The pipeline is `extract → chunk → embed → retrieve →
rerank → assemble → generate`, and a defect at any stage poisons everything after
it. Tuning chunk size on garbled text is wasted effort. Let the attribution
distribution from 3.2 pick the stage, and when two stages are implicated, fix the
earlier one first.

**Audit verdict:** well sequenced and specified, and the module's numbers are the
worst offenders in the document for stating illustrations as facts. All are now
labelled. **Which of 4.0–4.6 you actually build is decided by 3.2** — this module
is a menu whose order is fixed, not a list to complete.

> **Technique catalogue:** `docs/architecture/system-design.md` §8 lists the full
> ladder for each stage with failure modes and metrics. This module is the
> *sequencing*; that document is the *reference*.

### 4.0 — Extraction quality · **CORE** · `[required-when]` *(attribution names extraction)*

| | |
|---|---|
| **Capability** | the text the system reasons over is actually what the document says |
| **Now** | naive text extraction; whatever pypdf returns is treated as truth |
| **Problem** | attribution says `extraction`. Symptoms: answers quote sentences that read as nonsense; a two-column PDF produces interleaved gibberish; headers and footers appear mid-paragraph; a whole document indexes to almost nothing |
| **Diagnose** | **read the extracted text yourself**, next to the original PDF. This is the one stage where eyeballing beats metrics. Also compare `page_count` against pages that yielded text — a large gap means a scanned document silently indexed as nothing |
| **Root cause** | PDF has no notion of reading order. It is a page-description format: it says "draw this glyph here", not "this paragraph follows that one". A naive extractor emits text in drawing order, which for multi-column layouts interleaves the columns |
| **Learn** | why PDF is not a text format · reading order · layout analysis · boilerplate removal · when to reach for a layout-aware extractor (Docling, unstructured) over a raw text extractor |
| **Build** | whatever the failures justify: strip repeated headers/footers; detect and reject near-empty extractions loudly rather than indexing nothing; move to a layout-aware extractor if multi-column is common in your corpus |
| **Verify** | feed a two-column academic paper, a document with heavy headers/footers, a scanned page, and a form. Each must either extract correctly or **fail loudly** — silent garbage is the enemy. Regression test per document class |
| **Done when** | extraction failures no longer appear in the attribution distribution; every class of document in the corpus either extracts or refuses; the refusal path is tested |
| **Next trigger** | the text is clean, and gold spans are still split across chunk boundaries |
| **Covers** | extraction · reading order · layout analysis · document formats · fail-loud design |

**Partly done already.** `rag` refuses a PDF that yields no extractable text and
reports `pages_with_text` alongside `page_count`, so the silent-scanned-document
failure is already loud, and the client already surfaces the gap. What remains is
reading-order and boilerplate work — which cannot start until a real corpus
exists.

### 4.1 — Chunking · **CORE** · `[required-when]` *(attribution names chunking)*

| | |
|---|---|
| **Capability** | a chunk that matches a question contains enough of the document to answer it |
| **Now** | fixed 1200-character chunks with 180 overlap, never tuned against evidence |
| **Problem** | attribution says chunking. Inspection shows gold spans split across two chunks, and chunks that are meaningless alone ("it rose by 12%" — what did?) |
| **Diagnose** | for each failure, check whether any single chunk fully contains the gold span |
| **Root cause** | character-count splitting ignores document structure |
| **Learn** | chunking strategies, the size/precision tradeoff, structure-aware splitting, overlap economics |
| **Build** | structure-aware chunking (respect headings/paragraphs); table-aware handling; tune size and overlap **as measured experiments, one variable at a time** |
| **Verify** | run each strategy against the same eval set; some will be worse — keep the evidence. Unit tests for each splitter; the existing page-boundary invariant must survive |
| **Done when** | the winning configuration beats the baseline on recall@5 with the run recorded; every experiment is written up including the ones that lost; chunk-contains-gold-span % is reported alongside recall |
| **Next trigger** | remaining failures are queries with product codes, names, exact phrases — a different kind of miss |
| **Covers** | chunking · experiment discipline · RAG quality |

**The full chunking ladder.** Structure-aware and table-aware are the CORE rungs;
the rest are here so the map is complete, not so you build them all. Each is
entered only if the failure slice justifies it.

| Rung | What it does | Add when | Rating |
|---|---|---|---|
| Fixed size + overlap | cut every N characters | starting point — **current** | CORE |
| **Structure-aware** | respect headings, paragraphs, page boundaries | facts split mid-sentence; chunks span unrelated sections | **CORE** |
| **Table-aware** | a table is one chunk, or row-groups with the header repeated | table questions fail; tables flattened to prose | **CORE** |
| **Parent–child** (small-to-big) | embed small precise chunks, return their larger parent for context | matched chunks are *right* but too small to answer from | **ADV** |
| Contextual | prepend an LLM-written summary of where the chunk sits, before embedding | chunks are meaningless alone | ADV |
| Semantic | split where embedding distance shifts, not at a character count | topic boundaries fall mid-chunk | ADV |
| Hierarchical | multi-level summaries: document → section → chunk | a 2,000-page doc needs "which section?" before "which chunk?" | ADV |
| Late chunking | embed the whole document, then pool per-chunk from the full-context embedding | chunk-level embeddings lose document context | OPT |

**Parent–child deserves attention** even though it is ADV: it is the cheapest fix
for the very common case where a 400-character chunk matches perfectly and then
does not contain enough surrounding text to answer from. Retrieve small, return
big.

### 4.2 — Embedding model selection · **ADV** · `[deferrable]`

| | |
|---|---|
| **Capability** | the embedding model is a measured decision rather than a setup default |
| **Now** | one embedding model, chosen on setup convenience rather than evidence |
| **Problem** | chunking is fixed and recall is still short of where it should be; or you want to know whether the model is leaving quality on the table |
| **Diagnose** | you cannot tell without swapping it — which is exactly why this needs the eval harness first |
| **Root cause** | the embedding model was never a measured decision. It was a default |
| **Learn** | embedding model families, dimensions vs quality, domain fit, the migration cost of changing models, MTEB and why leaderboards mislead on *your* corpus |
| **Build** | 2–3 candidates behind the existing provider seam. Re-embed the corpus for each. **Separate collections**, so you can A/B without destroying the incumbent |
| **Verify** | mix models in one collection deliberately; watch retrieval return nonsense. That failure is why `embedding_model` lives in the chunk payload — and the payload check already exists |
| **Done when** | one table: recall@5 per model on the same eval set, embed cost per 1k chunks, embed latency, index size. One winner, recorded as a decision |
| **Next trigger** | the best model still misses exact-token queries — a property of dense embeddings, not of the model |
| **Covers** | embedding models · benchmarking · migration cost · A/B methodology |

> **The most expensive experiment in the project**, and the one most likely to be
> blocked by cost rather than by engineering. Every candidate means re-embedding
> the entire corpus, and on a free tier that is slow or impossible. `[deferrable]`
> is honest: the system is correct with one model. Do it once, properly, on a
> corpus you have measured — then freeze the answer and record it.

### 4.3 — Hybrid retrieval · **CORE** · `[required-when]` *(exact-token failures appear)*

| | |
|---|---|
| **Capability** | a question containing a literal string from the corpus finds it |
| **Now** | dense-only search |
| **Problem** | queries containing exact tokens ("error code X-4021") fail, though the term is in the corpus verbatim |
| **Diagnose** | check whether the gold chunk exists and contains the literal term; confirm it was not retrieved |
| **Root cause** | embeddings capture meaning and lose exact tokens. Rare strings have no semantic neighbourhood |
| **Learn** | lexical vs semantic search, BM25, fusion (RRF), score normalisation |
| **Build** | BM25 alongside dense; fuse with Reciprocal Rank Fusion |
| **Verify** | keyword-only queries, semantic-only queries, mixed. Confirm **neither regresses** — the fusion must not trade one for the other |
| **Done when** | recall@5 improves on the exact-token slice without regressing the semantic slice; both slices are reported separately |
| **Next trigger** | recall@20 is materially better than recall@5 — the right chunk is retrieved and then ranked too low |
| **Covers** | BM25 · hybrid search · rank fusion · IR |

### 4.4 — Reranking · **CORE** · `[required-when]` *(recall@20 ≫ recall@5)*

| | |
|---|---|
| **Capability** | the chunks that reach the prompt are the best ones retrieved, not just the first five |
| **Now** | good candidate generation, poor ordering |
| **Problem** | a large gap between recall@20 and recall@5 |
| **Diagnose** | measure both; the gap *is* the diagnosis |
| **Root cause** | the retriever optimises for speed over precision; nothing re-scores candidates carefully |
| **Learn** | bi-encoder vs cross-encoder, the latency/quality tradeoff, MMR/diversity |
| **Build** | retrieve 50, rerank to 5 with a cross-encoder |
| **Verify** | measure added latency explicitly. Decide whether the quality is worth it, in writing |
| **Done when** | nDCG@5 and recall@5 both improve, **and** the added p95 latency is measured and accepted; the deciding number is quality gained per millisecond |
| **Next trigger** | the right chunks are retrieved and well ordered, and some answers are still wrong |
| **Covers** | reranking · cross-encoders · latency/quality tradeoffs |

### 4.5 — Query transformation · **ADV** · `[deferrable]`

| | |
|---|---|
| **Capability** | questions phrased differently from the document, and multi-part questions, still retrieve |
| **Now** | good retrieval for well-phrased questions |
| **Problem** | failures concentrate in questions whose wording differs from the document's, and multi-part questions needing two different facts |
| **Diagnose** | slice failures by question type; multi-hop and vocabulary-mismatch will stand out |
| **Root cause** | one query string, one search. No reformulation, no decomposition |
| **Learn** | query rewriting, multi-query, decomposition, HyDE, step-back prompting |
| **Build** | whichever the failure slice justifies — **not all of them** |
| **Verify** | measure added latency and cost per query; some techniques double both |
| **Done when** | recall improves on the specific failing slice, and the latency and cost increase are measured and accepted |
| **Next trigger** | evidence is retrieved correctly and the answer still misses parts of it |
| **Covers** | query understanding · multi-hop retrieval |

### 4.6 — Context assembly · **CORE** · `[required-when]` *(gold chunk in prompt, ignored)*

| | |
|---|---|
| **Capability** | the model actually uses the evidence it is given |
| **Now** | correct chunks retrieved and ranked; answers still incomplete |
| **Problem** | the gold chunk is in the prompt and the answer ignores it — usually when it sits in the middle of a long context |
| **Diagnose** | log the prompt position of the gold chunk against answer correctness |
| **Root cause** | lost-in-the-middle; noise dilution from padding to a fixed k |
| **Learn** | context ordering, token budgeting, relevance thresholds, deduplication, compression |
| **Build** | order strongest evidence first and last; drop below-threshold chunks instead of padding; deduplicate near-identical chunks; budget tokens explicitly |
| **Verify** | force 20 chunks into the prompt; measure the quality drop. **More context is not better**, and this is the experiment that proves it on your corpus |
| **Done when** | answer correctness vs k is plotted; correctness vs gold-chunk position is plotted; tokens per query is reported; `TOP_K` becomes a measured value rather than the default 5 |
| **Next trigger** | quality is respectable. Then a second person starts using it — and sees your documents |
| **Covers** | context engineering · prompt construction · lost-in-the-middle |

---

# MODULE 5 — Multi-user

**Audit verdict:** 5.1 and 5.2 are correctly sequenced and well specified.
**Two corrections, both of the same kind** — critical `[required-when]` work that
the CORE/ADV marks were hiding:

1. **A missing prerequisite stage.** The moment an untrusted person can upload,
   the parser becomes an attack surface. That was nowhere in the document. It is
   now **5.0**, and it comes before tenancy because it is about the upload path
   itself.
2. **Prompt-injection defence was at 17.4**, behind an advanced module, three
   modules after the system becomes multi-user. Its structural minimum is now
   **required at 5.1**.

### 5.0 — Untrusted input · **CORE** · `[required-when]` *(anyone but you can upload)* · **NEW**

*Reason: A — real need, established by a product requirement (multi-user), not
by an observed incident. This stage was added in this revision.*

**Why this is not an invented stage.** Everything in Module 5 assumes people
other than you upload files. The moment that is true, `pypdf` is parsing hostile
input on your server, and a PDF is a program-ish format with compression, nested
objects and recursion. The current system validates magic bytes and a size
limit — which is correct and insufficient. Omitting this would be exactly the
"skipping difficult work because it is unfamiliar" that this document forbids.

| | |
|---|---|
| **Capability** | a malicious or pathological upload cannot exhaust the server or crash the worker |
| **Now** | magic-byte check and a 25 MB limit, enforced at both the backend and the agent `[measured]` |
| **Problem** | `[requirement]` multi-user means untrusted uploads. A decompression bomb, a deeply nested object graph, or a PDF with a million tiny pages can consume unbounded CPU and memory inside the parser — and after 1.3 that happens in a **worker**, where nobody is watching the request |
| **Diagnose** | construct each case and run it through ingestion with the worker's resource usage visible. Time and memory are the observations |
| **Root cause** | input is validated for *shape* (is it a PDF?) and *size on disk*, never for *cost to process*. Those are different properties, and compression decouples them |
| **Learn** | resource-exhaustion attacks, decompression bombs, parser hardening, per-job resource limits, timeouts as a security control, fail-closed validation, why "it is only our own users" is not a threat model |
| **Build** | the minimum that bounds cost: a page-count ceiling; a wall-clock timeout per ingestion job; a memory ceiling on the worker process; reject rather than truncate, with a clear error. Content-type checked against content, which already happens |
| **Verify** | **failure injection with adversarial inputs** — a bomb, a 50,000-page document, a malformed object graph, an encrypted PDF. Each must be rejected with a classified error and bounded resource use. Every one becomes a regression test |
| **Done when** | each adversarial class is rejected and named; the worker's resource use is bounded under all of them; the limits are justified numbers written down, not guesses; nothing crashes the worker process |
| **Next trigger** | hostile input is contained, and every user can still see every other user's documents |
| **Covers** | input validation · resource exhaustion · parser hardening · threat modelling · fail-closed design |

**Deliberately deferred here, with triggers:** sandboxing the parser in a
separate process or container (`[required-when]` a parser CVE or a confirmed
escape matters), virus scanning (`[required-when]` files are ever served back to
users), and rate limiting per user (that is 8.2, and it needs identity first).

### 5.1 — Tenancy and isolation · **CORE** · `[required-when]` *(a second user exists)*

| | |
|---|---|
| **Capability** | each user sees only their own documents, and only their own documents reach their prompts |
| **Now** | single shared index; every document visible to everyone |
| **Problem** | `[requirement]` user B asks a question and gets an answer citing user A's document. Reproducible on demand today |
| **Diagnose** | index a document as A, query as B, observe the leak |
| **Root cause** | no ownership on data and no filter at query time |
| **Learn** | multi-tenancy models (shared table + filter vs schema vs database), data isolation, defence in depth, **and why a filter derived from a prompt is not a filter** |
| **Build** | `tenant_id` on every row and every chunk payload. A hard metadata filter on **every** vector query, derived from the caller — never from a prompt. **Plus the structural minimum of 17.4** — see below |
| **Verify** | **the adversarial test**: put a unique token in A's corpus; try every prompt you can invent as B to surface it. Every attempt becomes a regression test. Concurrency test: a query issued while a tenant's document is being deleted must not return its chunks |
| **Done when** | zero cross-tenant leaks across the adversarial attempt set; the filter is applied in one place that cannot be bypassed by adding a new query path; a test fails if a new vector query omits the filter |
| **Next trigger** | there is a `tenant_id`, and anyone can claim to be any tenant |
| **Covers** | multi-tenancy · data isolation · authorization at the data layer |

> **The 17.4 minimum, required here.** Prompt-injection defence was listed at
> 17.4, inside an ADV module, long after the system became multi-user. Two of
> its four structural invariants are `[required]` at *this* stage, because this
> is where a document someone else wrote can reach your prompt:
>
> - **untrusted-data delimiting** — document text is clearly bounded in the
>   prompt and labelled as data, never as instruction;
> - **no document-controlled tool access** — nothing in a retrieved chunk can
>   cause an action.
>
> The other two — ACL-aware filtering beyond tenancy, and privilege separation —
> stay at 17.4 because they need the ACL model from 5.3. **That is a deferral
> with a trigger, not an omission.**

### 5.2 — Authentication · **CORE** · `[required-when]` *(tenancy exists)*

| | |
|---|---|
| **Capability** | identity is proven, so the tenant filter means something |
| **Now** | tenancy enforced, identity unverified |
| **Problem** | `curl` with someone else's tenant id returns their data |
| **Diagnose** | do exactly that |
| **Root cause** | identity is claimed by the client rather than proven |
| **Learn** | authn vs authz, sessions vs tokens, password storage (and why you never invent it), cookie security, API keys |
| **Build** | session cookies (httpOnly, SameSite) for the browser; API keys for programmatic access; a `current_user` dependency. Internal service token for backend → agent |
| **Verify** | forged cookie, expired session, missing header, token from a deleted user. Each becomes a regression test. **The frontend grows an authenticated state** — unauthenticated, expired and logged-in are three client states, and they need tests |
| **Done when** | every unauthorized access attempt is blocked; auth overhead per request is measured; the agent refuses a request without the internal token; no endpoint is unauthenticated by omission rather than by decision |
| **Next trigger** | one user uploads 500 documents and everyone else's ingestion stops |
| **Covers** | authentication · sessions · API keys · cookie security |

### 5.3 — Authorization and audit · **ADV** · `[deferrable]`

| | |
|---|---|
| **Capability** | documents can be shared, with read-only access, and every access is attributable |
| **Now** | authenticated users, all-or-nothing access |
| **Problem** | you need a shared document, or read-only access, or "who deleted that?" |
| **Diagnose** | try to answer "who did what, when" from your logs |
| **Root cause** | no permission model and no audit trail |
| **Learn** | RBAC, ACL inheritance, audit logging, derived-data permissions |
| **Build** | roles; document-level ACLs; **derived chunks inherit the source document's ACL**; an append-only audit log |
| **Verify** | revoke access mid-query; confirm chunks stop being retrievable immediately. Concurrency test: revocation racing a retrieval |
| **Done when** | permission-change propagation time is measured; the audit log is complete for every mutating operation; derived data cannot outlive its source's permissions |
| **Next trigger** | — (enables the remaining two 17.4 invariants) |
| **Covers** | authorization · RBAC · ACL · audit |
---

# MODULE 6 — Contention

**This module exists because RAG does not naturally produce high-contention
concurrency.** Quotas are the honest way to create it: embeddings genuinely cost
money and providers genuinely rate-limit, so every real platform has this.

**Audit verdict:** the strongest module in the document, and it needed the
honesty labels most. 6.1 is a **real need** — a shared paid resource with no
accounting. 6.2 is a **controlled teaching experiment** and is now labelled as
one. Two sequencing errors corrected: both 6.3 and 8.2 reach for Redis before
anything introduces it.

### 6.1 — Quotas and atomic reservation · **CORE** · `[required-when]` *(multi-tenant + paid provider)*

*Reason: A — real need. Embedding spend is real money on a shared quota.*

| | |
|---|---|
| **Capability** | each tenant has a budget, and one tenant cannot spend another's |
| **Now** | unlimited embedding spend per tenant |
| **Problem** | one tenant's bulk upload exhausts the shared provider quota; every other tenant's ingestion fails. **Already observed in a degenerate form** `[measured]`: a single large ingest exhausts the free tier's per-minute cap and returns 429 |
| **Diagnose** | attribute embedding calls per tenant; correlate with others' failures |
| **Root cause** | a shared finite resource with no accounting and no admission control |
| **Learn** | shared mutable state, atomic operations, the read-modify-write race, reservation patterns |
| **Build** | per-tenant token budget. A job must **reserve** before embedding and **release or commit** after. **Start with the naive `SELECT` then `UPDATE`** — building the correct version first would skip the lesson |
| **Verify** | 50 concurrent workers against a budget of 100. **The naive version will oversell** — prove it with a failing test before fixing it. That test stays forever as a regression test |
| **Done when** | overspend under concurrency is zero; the naive failure is captured as a test that fails against the old implementation; the fix's mechanism is understood, not just copied |
| **Next trigger** | you fixed it with a lock. Throughput collapsed |
| **Covers** | shared state · race conditions · atomicity · reservation |

### 6.2 — Isolation anomalies: a laboratory · **CORE** · `[deferrable]` · **TEACHING EXPERIMENT**

*Reason: **B — controlled teaching experiment.** Labelled explicitly in this
revision.*

**The most transferable stage in the project.** "I know optimistic locking" is a
claim. "I reproduced write skew at READ COMMITTED, fixed it at SERIALIZABLE, and
measured the throughput cost" is evidence.

**Why type B, stated plainly, as the rules require:**

- **Engineering question:** which anomalies does Postgres's default isolation
  level actually permit, and which of them can our quota invariant suffer?
- **Why ordinary observation is insufficient:** these races are rare,
  non-deterministic and silent. Waiting for write skew to appear in a
  single-user system is waiting forever; and when it does appear in production,
  the symptom is a wrong number with no trace of how it got there.
- **How the result changes the design:** it decides whether the quota mechanism
  uses SERIALIZABLE, a materialised counter with a CHECK constraint, or an
  explicit lock — and gives a measured reason for the choice.

It is `[deferrable]` because 6.1's fix can be correct without this module. What
this buys is *knowing why* it is correct, which is the entire point of the
project.

| | |
|---|---|
| **Capability** | (no product capability — this stage produces knowledge and a test suite) |
| **Now** | you have one proven race (quota oversell) and no idea which *class* of anomaly it is |
| **Problem** | 6.1 oversold the budget. Why exactly? What does Postgres actually guarantee by default — and what does it not? |
| **Diagnose** | two `psql` sessions side by side, statements interleaved by hand. **Watch the anomaly happen in slow motion before you automate it** |
| **Root cause** | Postgres defaults to READ COMMITTED, which permits several anomalies people assume are impossible |
| **Learn** | the anomaly catalogue and which isolation level prevents each |
| **Build** | a reproducible test per anomaly. Each one: (a) demonstrate it, (b) fix it, (c) measure the fix's cost |
| **Verify** | each anomaly below must be reproduced **as a failing automated test** before you fix it |
| **Done when** | for each anomaly: does it occur at READ COMMITTED / REPEATABLE READ / SERIALIZABLE? Throughput and serialization-failure rate recorded at each level. Write skew fixed three ways and all three measured |
| **Next trigger** | you now know which level is correct, and the correct one is slow. How else can you get correctness? |
| **Covers** | isolation levels · ACID in practice · MVCC · the anomaly catalogue · locking vs isolation |

**The anomalies, each with a natural home in this system:**

| Anomaly | Reproduce with | Notes |
|---|---|---|
| **Dirty read** | try it — Postgres will *not* let you | READ UNCOMMITTED is an alias for READ COMMITTED here. Learning that it is unreachable is itself the lesson |
| **Lost update** | two workers read quota 100, both subtract 30, both write 70 | the classic read-modify-write race from 6.1 |
| **Non-repeatable read** | read a document's status twice in one transaction while another commits a change between | REPEATABLE READ fixes it |
| **Phantom read** | `COUNT(*)` chunks for a document twice while another inserts more | the row that appears from nowhere |
| **Write skew** | two tenants share a pool; each job checks "is total usage < limit?", both see OK, both proceed, the sum exceeds the limit | **the interesting one** — no row is written twice, every read is consistent, and the invariant still breaks. Only SERIALIZABLE (or an explicit lock/constraint) prevents it |

**Write skew deserves the most attention.** It is the anomaly that survives
REPEATABLE READ, it is invisible to people who think "I used a transaction, so I
am safe", and your quota system produces it naturally. Reproduce it, then fix it
three different ways — SERIALIZABLE, a materialised counter with a CHECK
constraint, and an explicit lock — and measure all three.

**This is also where 1.2's CHECK constraints pay off conceptually.** The database
already refuses impossible job states; the same instrument — a constraint the
application cannot talk its way around — is one of the three write-skew fixes.

### 6.3 — Optimistic vs pessimistic concurrency · **CORE** · `[required-when]` *(lock contention measured)*

| | |
|---|---|
| **Capability** | quota accounting is both correct and fast enough to not be the bottleneck |
| **Now** | correct quota accounting, serialised throughput |
| **Problem** | with a row lock, 50 workers process one at a time; throughput drops sharply `[hypothesis — 6.1's fix is what produces the number]` |
| **Diagnose** | measure throughput with and without the lock; observe lock wait time |
| **Root cause** | pessimistic locking serialises all contenders regardless of conflict |
| **Learn** | optimistic vs pessimistic locking, CAS, version columns, retry storms, isolation levels, deadlocks |
| **Build** | version column + compare-and-swap + bounded retry. Compare against `SELECT FOR UPDATE` and against an atomic `UPDATE … SET x = x - n WHERE x >= n` |
| **Verify** | push contention until the CAS retry rate is high enough that throughput collapses *differently*. Induce a deadlock deliberately and confirm it is detected and handled |
| **Done when** | throughput, p99 latency and retry rate recorded for each strategy at 5 / 50 / 500 concurrent actors; one strategy chosen with a written reason; the deadlock path is tested |
| **Next trigger** | quota is safe. Now two workers re-index the same document simultaneously and the index ends up mixed |
| **Covers** | optimistic/pessimistic locking · CAS · isolation levels · deadlocks · retry storms |

> **Sequencing correction.** The previous version also said *"and against a Redis
> atomic counter"*. **Redis does not exist in this system until 9.1**, and
> introducing it here for one comparison arm would violate the constitutional
> rule — a technology adopted because a table has a row for it.
>
> The Redis arm is **deferred, not deleted.** Trigger: once 9.1 has introduced
> Redis for a reason of its own, come back and add the fourth column. The table
> is better with it and it is not worth a dependency on its own.

### 6.4 — Distributed locks, leases and fencing · **ADV** · `[required-when]` *(concurrent re-index possible)*

*Reason: A — real need once re-indexing exists; the GC-pause reproduction inside
it is **type B**, a controlled experiment.*

| | |
|---|---|
| **Capability** | two simultaneous re-index runs for one document cannot leave a mixed index |
| **Now** | row-level concurrency solved; multi-step operations spanning two datastores unprotected |
| **Problem** | two re-index jobs for one document interleave. The index ends up holding chunks from both runs |
| **Diagnose** | reproduce with two workers and a deliberate pause between delete and upsert |
| **Root cause** | a multi-step operation across Postgres and Qdrant has no mutual exclusion — **and a lock alone cannot fix it**, because a lock can expire while its holder is still alive and still about to write |
| **Learn** | distributed locks, lease expiry, the **stale lock-holder problem**, fencing tokens, why "I held the lock" is not the same as "I still hold the lock" |
| **Build** | see the sequence below |
| **Verify** | the GC-pause simulation below — a **controlled teaching experiment**, because a real GC pause at the wrong moment cannot be waited for. Without fencing it corrupts; with fencing the stale write is rejected. **Build the unfenced version first and reproduce the corruption** |
| **Done when** | corrupted indexes across repeated induced interleavings are zero; how often the reject path fires is measured; whether stale workers clean up after themselves is decided and tested |
| **Next trigger** | correct under concurrency. Then the embedding provider starts failing |
| **Covers** | distributed locks · leases · fencing tokens · cross-system consistency · why locks are insufficient |

**The exact sequence you must make safe:**

```text
Worker A acquires the lease, gets token 41
Worker A pauses          (GC pause, VM suspend, network partition — pick one)

        lease expires

Worker B acquires the lease, gets token 42
Worker B writes its chunks                       ← legitimate, current owner

Worker A wakes up, still believing it holds the lease
Worker A attempts to write with token 41
                    ↓
            MUST BE REJECTED
```

**The error I want you to avoid:** do not assume the vector store will enforce
this. **Qdrant has no conditional write** — no compare-and-set, no "reject if
version < N". Hand it a stale write and it will cheerfully accept it. Any design
that says "Redis issues a fencing token and Qdrant checks it" is wrong.

So the real exercise is deciding **where the authoritative check lives**, and the
only place you have atomicity is Postgres:

```text
documents.index_generation   monotonically increasing, owned by Postgres

acquiring the lease   →  UPDATE documents
                         SET index_generation = index_generation + 1
                         WHERE id = ?
                         RETURNING index_generation        ← this is the token

before committing     →  UPDATE documents
                         SET indexed_generation = :token
                         WHERE id = ? AND index_generation = :token

                         0 rows affected  →  you are stale. Abort.
                                             Delete anything you wrote. Do not retry blindly.
```

The vector write becomes the *uncommitted* part, and Postgres holds the commit
point. A stale worker can still write garbage to Qdrant — what it cannot do is
mark that garbage authoritative, and the next successful run **both overwrites
and removes it**: stage 2.2's point ids are derived from
`(document_id, chunk_index)`, and the ingestion prunes every point of that
document which is not one of the ids it just wrote. So a stale worker's output
survives only until the next successful run of the same document, whatever ids
it happened to use.

**The transferable lesson is not "Redis plus Qdrant".** It is:

> A worker that has lost ownership must be unable to commit — and the check has
> to happen at a point where something can enforce atomicity. If your storage
> layer cannot do conditional writes, the commit point must move somewhere that
> can.

That idea generalises to every distributed system you will ever work on, and it
is a genuinely good interview answer.

---

# MODULE 7 — Resilience

**Audit verdict:** correctly sequenced and well specified. One note on
instruments: **7.1's induced slowness is the fake embedder's delay**, which 2.4
builds — so by the time this module is reached the only *new* fault tool needed
is one that drops connections mid-body.

### 7.1 — Timeouts and retry discipline · **CORE** · `[required]`

| | |
|---|---|
| **Capability** | a slow dependency degrades throughput instead of consuming the system |
| **Now** | external calls with a single blunt timeout; `AGENT_TIMEOUT` is 120s `[measured]` and is a placeholder for a missing queue |
| **Problem** | the embedding provider gets slow. Workers hang for minutes. The queue backs up with nothing visibly failing |
| **Diagnose** | latency histogram per external dependency; count workers in flight |
| **Root cause** | no timeout means a slow dependency is worse than a dead one — it consumes capacity indefinitely |
| **Learn** | timeouts (connect vs read vs total), retry budgets, jitter, the thundering herd |
| **Build** | explicit timeouts everywhere, separated by kind. Retries with exponential backoff **and jitter**. A retry budget so retries cannot exceed a fraction of traffic. **Also: an `httpx.AsyncClient` that is reused** — the backend currently constructs a new one per call `[measured]`, so no connection is ever reused |
| **Verify** | the fake embedder's delay (from 2.4) for induced slowness; a separate fault for connections dropped mid-body. Failure-injection tests per dependency |
| **Done when** | p99 job duration under induced slowness is bounded; worker utilisation under slowness is measured; retry amplification factor is measured and capped; `AGENT_TIMEOUT` becomes a justified number rather than a placeholder |
| **Next trigger** | the provider goes fully down. Every job retries, fails, retries — you are DDoSing a dead service and burning your own capacity |
| **Covers** | timeouts · backoff · jitter · retry budgets |

### 7.2 — Circuit breaker · **CORE** · `[required-when]` *(a provider outage observed)*

| | |
|---|---|
| **Capability** | a dead dependency stops consuming the system's capacity, and recovery is automatic |
| **Now** | disciplined retries, still hammering a dead dependency |
| **Problem** | provider returns 100% errors; your system spends all capacity retrying |
| **Diagnose** | error rate per dependency; ratio of retry traffic to new traffic |
| **Root cause** | no concept of "this dependency is down; stop trying for a while" |
| **Learn** | circuit breaker states (closed/open/half-open), failure thresholds, recovery probing |
| **Build** | a breaker around each external provider. Open on threshold; reject fast; half-open probe to recover |
| **Verify** | point the provider at a black hole; confirm the breaker opens, the queue stops churning, and recovery is automatic when it returns. Test the half-open probe explicitly — an untested recovery path is a permanent outage waiting to happen |
| **Done when** | wasted calls during a timed outage are measured before and after; recovery time after restoration is measured; the thresholds are justified numbers |
| **Next trigger** | embedding is circuit-broken, and query traffic is also failing — one dependency took down an unrelated feature |
| **Covers** | circuit breakers · fail-fast · dependency isolation |

### 7.3 — Bulkheads and graceful degradation · **ADV** · `[required-when]` *(shared pools couple features)*

| | |
|---|---|
| **Capability** | queries keep working while ingestion is broken |
| **Now** | one failing dependency degrades everything |
| **Problem** | the embedding provider is down, and *queries* also fail — though answering from an existing index needs no ingestion |
| **Diagnose** | map which code paths share a connection pool, thread pool or worker pool |
| **Root cause** | shared resource pools couple unrelated failure domains |
| **Learn** | bulkhead pattern, resource partitioning, failure domains, degradation modes |
| **Build** | separate pools/concurrency limits for ingestion vs query. Define what "degraded" means: queries serve from the existing index; ingestion is paused and queued |
| **Verify** | take down each dependency in turn; confirm only the dependent feature degrades. **The client must show a degraded state honestly** rather than a generic error |
| **Done when** | query availability during an embedding outage is measured; "degraded" is a defined, documented, user-visible state |
| **Next trigger** | the system survives failures. Now it drowns in success |
| **Covers** | bulkheads · failure domains · graceful degradation |

---

# MODULE 8 — Overload

**Audit verdict:** correctly sequenced. One sequencing correction, the same kind
as 6.3: **8.2 specifies Redis, which does not exist yet, and does not need to.**

### 8.1 — Backpressure · **CORE** · `[required-when]` *(queue growth observed)*

| | |
|---|---|
| **Capability** | the system refuses work honestly instead of accepting more than it can do |
| **Now** | unbounded queue |
| **Problem** | ingestion accepts far more jobs than embedding drains. Queue depth grows without limit; memory climbs; jobs sit for hours |
| **Diagnose** | queue depth over time; arrival rate vs service rate (Little's Law) |
| **Root cause** | the producer has no feedback from the consumer |
| **Learn** | backpressure, Little's Law, bounded queues, admission control, load shedding |
| **Build** | bounded queue. When full: reject with `429` and `Retry-After` rather than accept-and-die. Surface queue depth and estimated wait |
| **Verify** | generate several times the drain rate; confirm bounded memory and honest rejections. **The client must handle `429` with `Retry-After`** — that is a client test |
| **Done when** | memory under sustained overload is flat and measured; the rejection rate vs queue wait tradeoff is chosen deliberately; the queue bound is a justified number |
| **Next trigger** | fair rejection, and one aggressive client still consumes the whole queue |
| **Covers** | backpressure · bounded queues · load shedding · Little's Law |

### 8.2 — Rate limiting · **CORE** · `[required-when]` *(one client can starve others)*

| | |
|---|---|
| **Capability** | one client's burst cannot degrade everyone else |
| **Now** | global admission control, no per-client fairness |
| **Problem** | one client's script fills the queue; everyone else is rejected |
| **Diagnose** | request rate per client; queue occupancy by tenant |
| **Root cause** | admission control is global, not per-identity |
| **Learn** | token bucket vs leaky bucket vs sliding window, distributed rate limiting, fairness |
| **Build** | per-tenant and per-endpoint limits. Correct `429` + `Retry-After` + limit headers |
| **Verify** | burst traffic from one tenant; confirm others are unaffected. Concurrency test on the counter itself — a rate limiter with a read-modify-write race does not limit anything |
| **Done when** | a well-behaved tenant's throughput while another floods is measured before and after; the limiter's own counter is proven race-free |
| **Next trigger** | protected and fair, and the database starts refusing connections under load |
| **Covers** | rate limiting · token bucket · distributed counters · fairness |

> **Sequencing correction.** The previous version said *"per-tenant and
> per-endpoint limits in Redis"* and *"run two API instances and confirm the
> limit is shared, not doubled"*. **There is one API instance until 12.1**, so
> there is nothing to share and Redis buys nothing here. Postgres — which you
> already have, and which 6.3 just taught you to do atomic counters in — is
> sufficient.
>
> **The distributed requirement is deferred to 12.1**, where multiple instances
> actually exist. That is when "shared, not doubled" becomes a real test and
> when a shared counter store becomes a real need. Noted there.

### 8.3 — Resource exhaustion · **CORE** · `[required-when]` *(pool errors under load)*

| | |
|---|---|
| **Capability** | the system's concurrency is sized to what its datastores can actually serve |
| **Now** | pool sizes written out as SQLAlchemy's defaults, with the arithmetic documented but never tested `[measured]` — `db_pool_size=5`, `db_max_overflow=10` |
| **Problem** | under load: `too many clients already`, or requests queueing invisibly on pool checkout |
| **Diagnose** | pool utilisation, checkout wait time, active DB connections |
| **Root cause** | connection pools sized without regard to DB limits or worker count |
| **Learn** | connection pooling maths, pool sizing, queueing on checkout, file descriptors, PgBouncer |
| **Build** | size pools deliberately (workers × pool size ≤ DB max). Checkout timeouts. Pool metrics |
| **Verify** | deliberately over-provision workers; watch it fail; fix by sizing. **A controlled experiment** — the failure is induced, and the point is the arithmetic |
| **Done when** | error rate at multiples of normal load is measured before and after; pool wait p99 is measured; the sizing is derived from the formula, not tuned by feel |
| **Next trigger** | stable under load and slow. The same question is asked repeatedly and re-computed every time |
| **Covers** | connection pooling · resource limits · capacity |

**The arithmetic is already written down** in `backend/app/core/config.py` and has
never been tested against a real limit. This stage is where a comment becomes a
measurement.

---

# MODULE 9 — Caching

**Audit verdict:** correctly sequenced and the best system-design content in the
document. **This is where Redis genuinely arrives** — 6.3 and 8.2 both reached
for it early and both have been corrected to defer to here.

### 9.1 — Cache-aside · **CORE** · `[required-when]` *(repeated expensive work measured)*

| | |
|---|---|
| **Capability** | a repeated question is answered without redoing the expensive work |
| **Now** | every query re-embeds and re-searches |
| **Problem** | repeated identical questions; embedding cost and p95 latency both dominated by work already done. **Must be measured before building** — the constitutional rule applies with full force here |
| **Diagnose** | distribution of repeated queries; latency breakdown by stage |
| **Root cause** | deterministic, expensive, repeated computation with no memoisation |
| **Learn** | cache-aside, TTL, key design, hit rate, what is safely cacheable |
| **Build** | Redis. Cache query embeddings (content-addressed, effectively immutable) and retrieval results (TTL'd). **Keys must include tenant** |
| **Verify** | confirm a cache miss and a hit produce identical results. **Confirm tenant A never reads tenant B's cached entry** — a cross-tenant cache leak defeats 5.1 entirely, and this is a security test, not a performance test |
| **Done when** | p95 query latency, cache hit rate and embedding calls per query are measured before and after; the repeat rate that justified the cache is recorded; the tenant-isolation test exists |
| **Next trigger** | a document is re-indexed and the cache keeps serving the old answer |
| **Covers** | caching · cache-aside · TTL · key design |

### 9.2 — Invalidation · **CORE** · `[required]` *(once 9.1 exists)*

| | |
|---|---|
| **Capability** | updating a document updates what the system says about it |
| **Now** | cached results that outlive their source data |
| **Problem** | re-index a document; queries still return pre-update answers until TTL expiry |
| **Diagnose** | update a document, query immediately, compare |
| **Root cause** | no link between source-data mutation and cached derivatives |
| **Learn** | invalidation strategies, versioned keys, the correctness/complexity tradeoff, eventual consistency |
| **Build** | version-stamped cache keys per document/tenant — bump the version on re-index rather than hunting individual keys |
| **Verify** | re-index under concurrent query load; measure the stale window. A concurrency test, because the interesting case is a read racing the version bump |
| **Done when** | the stale-answer window is measured, not assumed; the chosen staleness is a documented product decision |
| **Next trigger** | a cached entry was built from several documents and only one of them changed |
| **Covers** | cache invalidation · versioned keys · eventual consistency |

### 9.3 — Multi-document invalidation · **CORE** · `[deferrable]`

**The best pure system-design problem in the project.** Single-document
invalidation was easy. This one has no clean answer, only tradeoffs — which is
exactly why it is worth doing.

| | |
|---|---|
| **Capability** | a cached answer drawn from several documents is invalidated when any of them changes |
| **Now** | version-stamped keys per document, which works when a cached thing depends on *one* document |
| **Problem** | a cached **answer** was built from documents A v7, B v12 and C v4. Only B changes. The cached answer is now wrong — and its key mentions no document at all, because the key is a hash of the *question* |
| **Diagnose** | cache an answer drawing on three documents; update one; query again; observe the stale answer and notice you have no mechanism that could have known |
| **Root cause** | the cache key is derived from the **input** (the question), but validity depends on the **output's dependencies** (whichever chunks happened to be retrieved) — which are not known until after the expensive work is done |
| **Learn** | dependency-aware invalidation, generation counters, the precision/complexity tradeoff, bounded staleness as a deliberate choice |
| **Build** | implement **at least two** of the strategies below and measure both |
| **Verify** | update one document in a large corpus; count how many cache entries were invalidated versus how many actually needed to be |
| **Done when** | stale-answer window, invalidation precision (necessary evictions ÷ total evictions) and hit rate under a realistic write rate are all measured for at least two strategies; **the choice is defended in writing** |
| **Next trigger** | correct invalidation, and a popular entry still causes a thundering herd at expiry |
| **Covers** | cache invalidation · dependency tracking · eventual consistency · bounded staleness · tradeoff analysis |

**The three real options:**

| Strategy | How | Precision | Cost |
|---|---|---|---|
| **Corpus generation counter** | one counter per tenant, bumped on *any* write; it is part of every cache key | terrible — one upload evicts everything | trivial to build, and often correct anyway |
| **Dependency tracking** | store, with each cached answer, the document ids and versions it used. On a document write, evict entries listing it (a reverse index) | exact | a second index to maintain, and it can be larger than the cache |
| **TTL + accept staleness** | short TTL, no invalidation, documented staleness window | none, by design | free — and the right answer more often than engineers like to admit |

**The point of the exercise is the argument, not the code.** Be able to say:
*"We chose a per-tenant generation counter. Writes are rare relative to reads —
measured at 1:400 — so over-invalidation costs us about 3% of hit rate, and it
removed an entire class of correctness bug. Dependency tracking would have been
exact, but the reverse index would exceed the cache itself, and for an
unmeasurable quality gain."*

That is a system-design interview answer. "I used Redis with a TTL" is not. Note
that the 1:400 and the 3% in that sentence are the numbers **you will have
measured** — quoting them without having is exactly what this revision exists to
prevent.

### 9.4 — Stampede and hot keys · **ADV** · `[required-when]` *(expiry spikes observed)*

| | |
|---|---|
| **Capability** | expiry of a popular entry does not cause a latency spike |
| **Now** | correct caching with pathological expiry behaviour |
| **Problem** | at expiry, a latency spike and a burst of identical expensive work |
| **Diagnose** | latency spikes correlated with TTL boundaries; duplicate in-flight computations |
| **Root cause** | nothing coordinates concurrent misses on the same key |
| **Learn** | cache stampede, single-flight, probabilistic early expiry, hot keys, cache penetration |
| **Build** | single-flight per key (lock or promise sharing); jittered TTLs; negative caching for known-missing keys |
| **Verify** | many concurrent requests for one key at the moment of expiry — a concurrency test by construction |
| **Done when** | duplicate computations per expiry drop to one, measured; spike magnitude measured before and after |
| **Next trigger** | Redis itself goes down. Everything fails, though a cache should be optional |
| **Covers** | stampede · single-flight · hot keys · negative caching |

### 9.5 — Cache as an optional dependency · **ADV** · `[required]` *(once Redis exists)*

**Reclassified in this revision.** It was `ADV` only, which read as optional. A
cache that takes the system down when it fails is a **reliability regression
introduced by 9.1** — fixing it is required, not sophisticated.

| | |
|---|---|
| **Capability** | the system works, slower, with the cache gone |
| **Now** | Redis is a hard dependency |
| **Problem** | stop Redis; the whole API errors |
| **Diagnose** | kill Redis and watch |
| **Root cause** | cache failures are not handled as cache *misses* |
| **Learn** | optional dependencies, fail-open vs fail-closed, degraded modes |
| **Build** | treat Redis errors as misses for caching; decide deliberately for rate limiting (fail-open risks abuse, fail-closed risks outage — **pick, and write down why**) |
| **Verify** | run the full test suite with Redis down. That is the test |
| **Done when** | availability with Redis down is measured; the fail-open/fail-closed decision for each use is written down with its reasoning |
| **Next trigger** | resilient and hard to reason about. Something is slow and you cannot say what |
| **Covers** | optional dependencies · fail-open/closed · degradation |

---

# MODULE 10 — Observability in depth

**End of the job-ready checkpoint.** With modules 1–10 done properly you can hold
a serious backend interview.

**Audit verdict:** correctly sequenced and specified. One clarification: 2.4
already built structured logging and metrics; **10.1 is aggregation and
visualisation**, not their introduction. The two are not duplicated.

### 10.1 — Metrics and dashboards · **CORE** · `[required-when]` *(metrics exist, no overview)*

| | |
|---|---|
| **Capability** | "is the system healthy?" is answered by looking at one screen |
| **Now** | metrics emitted at 2.4, never aggregated |
| **Problem** | answering "is the system healthy?" takes ten minutes and several terminals |
| **Diagnose** | time yourself answering it |
| **Root cause** | metrics exist but are not aggregated or visualised |
| **Learn** | RED (rate/errors/duration), USE (utilisation/saturation/errors), cardinality, dashboards |
| **Build** | Prometheus + Grafana. RED per endpoint; USE per pool; pipeline stage timings; cost per query |
| **Verify** | induce four different faults; identify each from the dashboard alone, without reading logs |
| **Done when** | time to identify a fault class is measured before and after; cardinality is bounded deliberately (an unbounded label is how a metrics system falls over) |
| **Next trigger** | you can see *that* p99 is high; you cannot see *where* the time goes |
| **Covers** | metrics · RED/USE · dashboards · cardinality |

### 10.2 — Distributed tracing · **CORE** · `[required-when]` *(latency crosses processes)*

| | |
|---|---|
| **Capability** | one slow request can be decomposed into where its time actually went |
| **Now** | per-service metrics, no per-request causality |
| **Problem** | a slow request crosses API → queue → worker → embedding → vector store; aggregates cannot attribute the latency |
| **Diagnose** | try to reconstruct one slow request from logs across three processes |
| **Root cause** | no trace context propagated across process and queue boundaries |
| **Learn** | tracing, spans, context propagation (including **through a queue**), sampling. The full picture: `HTTP request → trace/span → queue message (carrying trace context) → worker span → embedding span → vector-DB span`. A trace that stops at the queue boundary is the common failure, and **the async hop is exactly the interesting part** |
| **Build** | OpenTelemetry end to end. Trace id carried in job payloads so async work joins the same trace |
| **Verify** | inject latency at a random stage; find it from the trace in under a minute. Assert in a test that a worker span is a child of its API span — trace completeness across the async boundary is the property that breaks silently |
| **Done when** | time to localise a latency source is measured; trace completeness across async boundaries is asserted by a test; `request_id` from 2.4 and `trace_id` are distinct and both present |
| **Next trigger** | you can see everything. Now make it fast |
| **Covers** | tracing · context propagation · sampling |

### 10.3 — SLOs and alerting · **ADV** · `[deferrable]`

| | |
|---|---|
| **Capability** | "was today a good day?" has a numerical answer, and only real problems page you |
| **Now** | full visibility, no definition of "acceptable" |
| **Problem** | you cannot say whether today was a good day |
| **Diagnose** | try to define "healthy" numerically and notice you cannot |
| **Root cause** | no service level objectives |
| **Learn** | SLI/SLO/SLA, error budgets, alerting on symptoms not causes, alert fatigue |
| **Build** | SLOs (query p95, ingestion success rate, availability). Alerts on SLO burn, not on CPU |
| **Verify** | breach each SLO deliberately; confirm exactly one useful alert fires |
| **Done when** | each SLO is a number derived from measurement, not aspiration; alert precision (false alarms per real incident) is measured |
| **Next trigger** | — |
| **Covers** | SLO/SLI · error budgets · alerting |
---

# MODULE 11 — Performance engineering · **CORE**

**Audit verdict:** correctly sequenced but **duplicated against 1.3** in the
previous version, and its Build line referred to a tool that now exists.

> **11.1 is an upgrade, not a first build.** The capacity probe arrives at 2.4 —
> a script that answers one question about one scenario. 11.1 replaces it with a
> reusable instrument, and it must justify doing so against the five questions,
> like any other test infrastructure:
>
> 1. **Question:** what is the saturation point across a *realistic mixed*
>    workload — uploads and queries together, at varying concurrency — and which
>    resource saturates first?
> 2. **Why the 2.4 probe is insufficient:** it generates one operation at one
>    concurrency with no warm-up and no think time, and it suffers coordinated
>    omission. It can tell you "20 uploads took N seconds"; it cannot tell you
>    "throughput peaks at X rps and p99 degrades past Y".
> 3. **Why a real tool:** open-model load generation, percentile reporting that
>    is not wrong, and ramping are all things you would otherwise rebuild badly.
> 4. **Minimum:** one k6 or Locust scenario with a mixed workload and a ramp.
>    Not a framework, not a dashboard.
> 5. **What changes:** it names the first bottleneck, which is 11.2's input.
>
> **The fake embedding provider comes from 2.4** and is what makes this
> affordable. The previous version listed building it here, which would have been
> the third time it appeared in the document.

### 11.1 — Load testing harness · `[required-when]` *(a capacity question you cannot answer)*

| | |
|---|---|
| **Capability** | you can state, with evidence, how much load the system takes before it degrades |
| **Now** | measured at one concurrency by 2.4's probe; never under a realistic mixed workload |
| **Problem** | you cannot answer "how many concurrent users can this take?" |
| **Diagnose** | — this stage builds the instrument |
| **Root cause** | no repeatable, realistic load generation |
| **Learn** | open vs closed workload models, warm-up, percentiles vs averages, **coordinated omission** |
| **Build** | k6 or Locust. Realistic mixed workload. Fake embedder so load tests do not hit provider quota |
| **Verify** | ramp until something breaks; record **what broke first** — the number is secondary to the identity of the bottleneck |
| **Done when** | the saturation point is measured; throughput and p50/p95/p99 vs concurrency is a curve, not a point; the measurement is repeatable by one command and the delay/config is recorded alongside |
| **Next trigger** | you know it breaks at N. You do not know why |
| **Covers** | load testing · percentiles · workload modelling |

### 11.2 — Bottleneck isolation · `[required-when]` *(a known breaking point)*

| | |
|---|---|
| **Capability** | each performance change is attributable to a cause |
| **Now** | a known breaking point, unknown cause |
| **Problem** | past some load, p99 explodes |
| **Diagnose** | USE metrics per resource; flame graphs; per-stage timings |
| **Root cause** | whatever it turns out to be — **and it is usually not what you guessed** |
| **Learn** | profiling, Amdahl's law, queueing theory basics, the one-variable rule |
| **Build** | fix exactly one bottleneck, re-measure, repeat. Keep a log of every hypothesis, including the wrong ones |
| **Verify** | predict the *next* bottleneck before measuring; check whether you were right. Being wrong on the record is the most useful outcome |
| **Done when** | a table of "changed X → throughput Y → because Z" exists, with the failed hypotheses included. **The single best interview artifact this project produces** |
| **Next trigger** | one machine is optimised. The limit is now the machine |
| **Covers** | profiling · bottleneck analysis · capacity |

### 11.3 — Database performance · `[required-when]` *(the DB is the bottleneck)*

| | |
|---|---|
| **Capability** | queries are fast because their plans are understood, not because an index was guessed |
| **Now** | indexes written at 1.2 from reasoning, never validated against a plan |
| **Problem** | slow queries under load; lock contention; sequential scans |
| **Diagnose** | `EXPLAIN ANALYZE`, `pg_stat_statements`, lock views |
| **Root cause** | missing/wrong indexes, N+1 queries, over-broad transactions |
| **Learn** | query plans, index types, selectivity, transaction scope, N+1 |
| **Build** | indexes justified by plans; narrowed transaction boundaries; batched writes |
| **Verify** | drop an index and measure the damage. **A controlled experiment** — the point is understanding the number, and it confirms the index was earning its cost |
| **Done when** | query p99 before/after per fix; rows examined vs returned for each hot query; every index in the schema has a plan that justifies it |
| **Next trigger** | — |
| **Covers** | SQL performance · indexes · query plans · transaction scope |

**Already partly earned at 1.2:** the FK index on `ingestion_jobs.document_id`
was added deliberately because Postgres does not create them automatically, and
`lazy="raise"` on the relationships makes an accidental N+1 raise rather than
silently issue fifty round trips. This stage validates those choices against
real plans.

---

# MODULE 12 — Horizontal scale · **CORE**

**Audit verdict:** correctly sequenced, with **one factual error corrected** and
**two deferred requirements landing here**.

### 12.1 — Stateless services and load balancing · `[required-when]` *(restart is downtime)*

| | |
|---|---|
| **Capability** | the system survives losing an instance, and scales by adding them |
| **Now** | one API process, one agent process |
| **Problem** | a restart is downtime; one core is the ceiling |
| **Diagnose** | deploy and watch requests fail |
| **Root cause** | a single instance, and any in-process state |
| **Learn** | statelessness, session externalisation, load balancing, health checks, sticky-session pitfalls |
| **Build** | N instances behind a load balancer. **Real readiness/liveness endpoints** — currently both services have liveness only, deliberately, and this is the stage where readiness becomes load-bearing because something is making routing decisions from it |
| **Verify** | kill one instance under load; measure dropped requests. Confirm no request depends on hitting the same instance twice |
| **Done when** | requests lost during instance failure are measured; throughput vs instance count is plotted **and the non-linearity explained**; nothing in-process holds state that a second instance would need |
| **Next trigger** | the API scales; the workers do not coordinate |
| **Covers** | statelessness · load balancing · health checks · horizontal scaling |

> **Factual correction.** The previous version said *"remove in-process state
> (that in-memory conversation dict finally dies here)"*. **No such dict
> exists** `[measured]` — conversation persistence was deliberately deferred by
> ADR 0001 and never built, so there is nothing to remove. The stage stands on
> its real reason: one instance is a single point of failure and a hard ceiling.

> **Two requirements deferred from earlier stages land here**, both because they
> need a second instance to be meaningful at all:
>
> - **`QDRANT_URL` / a real Qdrant server.** Embedded Qdrant takes an exclusive
>   lock on its storage folder, so exactly one process may hold it. 1.3 does not
>   force this (the worker calls the agent over HTTP); a *second agent instance*
>   does. `[required-when]` — and the condition is here.
> - **A shared rate-limit counter.** 8.2's limiter is per-instance until now. Two
>   instances means the limit is doubled unless the counter is shared — which is
>   when "run two API instances and confirm the limit is shared, not doubled"
>   becomes a real test, and when Redis-or-equivalent becomes a real need.

### 12.2 — Worker scaling and coordination · `[required-when]` *(adding workers stops helping)*

| | |
|---|---|
| **Capability** | worker count is tuned to the real constraint rather than guessed |
| **Now** | multiple API instances, worker pool unexamined |
| **Problem** | adding workers stops improving throughput, or starts causing errors |
| **Diagnose** | throughput vs worker count; DB connections; provider rate limits |
| **Root cause** | a shared downstream limit — pool, provider quota, or lock contention |
| **Learn** | scaling limits, coordination cost, the shared-bottleneck principle |
| **Build** | tune worker concurrency against the real constraint; distribute provider quota across workers |
| **Verify** | over-scale deliberately; find where it gets *worse*. A controlled experiment, and the inflection is the lesson |
| **Done when** | the throughput-vs-worker-count curve is plotted, the knee is located, **and the constraint causing it is named** |
| **Next trigger** | compute scales. Data does not |
| **Covers** | worker pools · scaling limits · coordination |

### 12.3 — Zero-downtime deployment · **ADV** · `[required-when]` *(deploys lose work)*

| | |
|---|---|
| **Capability** | a deploy under load drops no requests and kills no in-flight jobs |
| **Now** | deploys drop requests and may break in-flight jobs |
| **Problem** | deploy under load; watch errors, and find a job killed mid-flight |
| **Diagnose** | error rate during deploy; jobs left in `processing` |
| **Root cause** | no graceful shutdown; no rolling strategy; schema changes not backward compatible |
| **Learn** | rolling/blue-green/canary, graceful shutdown, drain, **expand–contract migrations** |
| **Build** | SIGTERM handling that finishes or releases current work. Rolling deploy. Backward-compatible migrations in two phases |
| **Verify** | deploy a schema change under load **with old and new code running simultaneously**. That is the test, and it is the one people skip |
| **Done when** | errors during deploy are zero and measured; jobs lost per deploy are zero; at least one expand–contract migration has been performed as two deploys |
| **Next trigger** | — |
| **Covers** | deployment strategies · graceful shutdown · schema migration |

**This is where migrations become genuinely hard**, and it is worth saying why
1.2's migrations were easy: nothing was running against the schema. A migration
with live old code reading the same tables is a different discipline, and
expand–contract is the name of it.

---

# MODULE 13 — Data at scale · **ADV**

Mostly reasoning plus synthetic workloads. You will not operate a real
10M-document cluster, and pretending otherwise teaches nothing.

**Audit verdict:** 13.0 is excellent and stays as written. **13.1's synthetic
workload was specified at a size that is almost certainly infeasible** on
development hardware, and is corrected to a measurable size plus an explicit
extrapolation.

### 13.0 — Documents are not vectors · **CORE** · `[required]` *(before any scaling work)*

**Do this before any scaling experiment.** "10M documents" is not a scale unit —
it is an input to one. Getting this conversion wrong is how people design for the
wrong system by two orders of magnitude.

| | |
|---|---|
| **Capability** | (knowledge) you can convert a product-sized number into an infrastructure-sized one, in both directions |
| **Now** | a vague target of "10M documents" |
| **Problem** | try to answer "how much RAM does the index need?" and notice you cannot, because you never converted documents into vectors |
| **Diagnose** | measure your *own* corpus: pages per document, chunks per page, bytes per chunk |
| **Root cause** | the unit of scale for a vector store is the **vector**, and one document produces tens to hundreds of them |
| **Learn** | unit conversion chains, fan-out factors, back-of-envelope estimation, quantization economics |
| **Build** | a written model, measured from your real corpus, not guessed |
| **Verify** | have someone challenge each assumption — a system-design interview rehearsal |
| **Done when** | the model's inputs are all `[measured]` on your corpus; predicted vs actual is checked at a scale you can reach, **so you know the model's error before extrapolating** |
| **Next trigger** | the number is large enough that index configuration is an architectural decision, not a tuning detail |
| **Covers** | capacity estimation · fan-out · quantization tradeoffs · system design |

**The chain you must be able to walk in both directions:**

```text
documents → pages/doc → chunks/page → total chunks
          → dimensions → bytes/vector → raw size
          → + index overhead → + text payload → RAM & disk
          → nodes required → query throughput per node
```

**Worked example, 768 dimensions** — `[illustration]`, to show the shape of the
arithmetic. Your own numbers replace these:

| Docs | Pages/doc | Chunks/page | Total vectors |
|---:|---:|---:|---:|
| 10M | 10 | 2 | **0.2B** |
| 10M | 20 | 2.5 | **0.5B** |
| 10M | 50 | 2 | **1.0B** |

| Encoding | Bytes/vector | 500M vectors | 1B vectors |
|---|---:|---:|---:|
| float32 (raw) | 3,072 | 1.40 TB | 2.79 TB |
| float16 | 1,536 | 0.70 TB | 1.40 TB |
| int8 scalar quant | 768 | 0.35 TB | 0.70 TB |
| binary quant | 96 | **0.04 TB** | **0.09 TB** |

Plus HNSW graph overhead (roughly +50–100%) and the chunk text itself
(500M × ~1.2 KB ≈ 0.55 TB, which usually belongs in object storage or Postgres
rather than in the vector store's memory).

**Why this matters more than it looks:** at float32 this is a multi-terabyte,
multi-node, "we need a team" problem. At binary quantization it fits on a handful
of machines. That is a 30× architectural difference — and it is completely
invisible if you only ever say "10M documents".

**So the honest claim to practise is:** *"We measured 50 chunks per document on
our corpus. At 10M documents that is 500M vectors; at 768 dims int8 that is
~350 GB of vectors plus graph overhead, so roughly N nodes at M GB each. Our
100k-chunk experiment measured X ms p99, which extrapolates to Y."*

**Note one real measurement you already have:** at 1200-character chunks with a
page-boundary rule, a 3-page test document produced exactly 3 chunks
`[measured]` — one per page, because each page's text was shorter than the chunk
size. Fan-out is a property of your corpus's page density, and synthetic
fixtures will mislead you about it.

### 13.1 — Vector index scaling · `[deferrable]`

| | |
|---|---|
| **Capability** | index configuration is chosen from a measured recall/speed/memory curve |
| **Now** | one collection, modest size, default HNSW parameters |
| **Problem** | you cannot say how search latency and memory behave as the index grows |
| **Diagnose** | latency vs collection size; memory per vector; recall vs speed |
| **Root cause** | ANN index parameters and memory footprint scale with data |
| **Learn** | HNSW parameters, quantization, recall/speed/memory tradeoffs, index build cost |
| **Build** | tune HNSW; scalar/binary quantization; measure the recall cost against the 3.1 eval set |
| **Verify** | quantize aggressively; measure the retrieval quality you lost. Without the eval set this stage produces numbers with no quality axis |
| **Done when** | search p99 and memory vs index size are measured at **two or more** sizes so the curve has a slope; recall@5 delta from quantization is measured on the real eval set; the extrapolation to the target size states its error |
| **Next trigger** | one index cannot hold everything |
| **Covers** | ANN indexes · quantization · memory/quality tradeoffs |

> **Scope correction.** The previous version said *"synthetically load 10M
> chunks"*. At 768 float32 dimensions that is ~30 GB of raw vectors before graph
> overhead and payload — not a laptop experiment, and the embedding cost alone
> makes it impossible even with the fake provider's speed.
>
> **The honest version:** measure at the largest size your machine actually
> holds — 500k to 1M chunks is realistic — at **two or more** sizes so you have a
> slope, then extrapolate using 13.0's model and **state the error bound**.
> "We measured at 1M and our model predicts X at 500M, with these assumptions"
> is a credible claim. A fabricated 10M run is not.

### 13.2 — Partitioning and sharding · `[deferrable]`

| | |
|---|---|
| **Capability** | data is distributed so no single resource holds all the load |
| **Now** | single index, single DB |
| **Problem** | index exceeds one node; one large tenant dominates |
| **Diagnose** | size and traffic distribution per tenant; identify hot partitions |
| **Root cause** | no partition key; all load on one physical resource |
| **Learn** | partition key selection, hot partitions, rebalancing, fan-out queries, Postgres partitioning |
| **Build** | partition by tenant (with a plan for the tenant too large for one shard). Time-partition large tables. Document the routing |
| **Verify** | simulate a tenant far larger than the rest; observe hot-partition behaviour. **A controlled experiment**, since real skew cannot be waited for |
| **Done when** | p99 with and without hot partitions is measured; storage and query distribution are plotted; the rebalancing plan exists on paper even if unbuilt |
| **Next trigger** | reads dominate; writes are fine |
| **Covers** | partitioning · sharding · hot partitions · partition keys |

### 13.3 — Replication and read scaling · `[deferrable]`

| | |
|---|---|
| **Capability** | read load scales without touching the primary |
| **Now** | single primary serving reads and writes |
| **Problem** | read load saturates the primary |
| **Diagnose** | read/write ratio; primary CPU; replication lag once replicas exist |
| **Root cause** | reads and writes contending for one resource |
| **Learn** | replication, read replicas, replication lag, read-your-writes, consistency models |
| **Build** | read replica; route read-only queries to it; **identify which reads cannot tolerate lag** |
| **Verify** | write then immediately read from a replica; observe the stale read. Decide which paths must hit the primary — the upload→poll path from 1.3 is the obvious candidate and a correctness test, not a performance one |
| **Done when** | primary load reduction is measured; replication lag distribution is measured; every read path is classified as lag-tolerant or not |
| **Next trigger** | — |
| **Covers** | replication · read replicas · eventual consistency · read-your-writes |

### 13.4 — Capacity planning · `[deferrable]`

| | |
|---|---|
| **Capability** | you can state what the target scale costs and what breaks first |
| **Now** | measured system, no forward model |
| **Problem** | "what does 10M documents cost, and what breaks first?" |
| **Diagnose** | extrapolate from measured per-unit costs |
| **Root cause** | — this stage is reasoning, not repair |
| **Learn** | capacity modelling, cost per unit, growth projection, headroom |
| **Build** | a written model: storage/doc, embedding cost/doc, query cost, memory/vector. Project to the target. **Name the first thing to break** |
| **Verify** | have someone challenge your assumptions — a system-design interview rehearsal |
| **Done when** | predicted vs actual is checked at a scale you *can* test, and the model's error is stated; every input is `[measured]` or explicitly labelled an assumption |
| **Next trigger** | — |
| **Covers** | capacity planning · cost modelling · system design |

---

# MODULE 14 — Event-driven architecture · **ADV** · `[deferrable]`

**Honest warning, retained and strengthened:** this project may never produce a
genuine need for events. Enter only when you have two or more consumers that must
react to the same fact. **If you build it for the learning, label it type B and
say so** — do not claim it was justified.

### 14.1 — The outbox pattern · `[required-when]` *(a side effect must not be lost)*

| | |
|---|---|
| **Capability** | a state change and its side effect cannot disagree |
| **Now** | side effects performed inline after a DB commit |
| **Problem** | a document commits, then the notification/cache-invalidation/analytics step fails. The DB and the side effect disagree |
| **Diagnose** | kill the process between commit and side effect; observe divergence |
| **Root cause** | the dual-write problem: two systems, no shared transaction |
| **Learn** | dual-write, outbox, transactional guarantees across systems, at-least-once delivery |
| **Build** | write events to an `outbox` table in the same transaction as the state change; a relay publishes them |
| **Verify** | crash between commit and publish; confirm the event still goes out. Failure injection at each point in the sequence |
| **Done when** | lost events across repeated induced crashes are zero; the relay's own failure modes are tested |
| **Next trigger** | events are delivered more than once |
| **Covers** | outbox · dual-write · at-least-once |

**This is the same shape as 1.2's invariant**, one level up: commit the intent
before performing the effect, so a crash leaves a record rather than a mystery.
Recognising that is most of the lesson.

### 14.2 — Idempotent consumers and replay · `[required]` *(once 14.1 exists)*

| | |
|---|---|
| **Capability** | redelivering an event changes nothing |
| **Now** | at-least-once delivery, non-idempotent consumers |
| **Problem** | a redelivered event double-applies its effect |
| **Diagnose** | replay an event; observe the duplicate |
| **Root cause** | consumers assume exactly-once, which no delivery system provides |
| **Learn** | effectively-once processing, dedup keys, ordering, replay |
| **Build** | event ids + a processed-events table. Replay tooling |
| **Verify** | replay a day of events; state must be unchanged. That is the test |
| **Done when** | duplicate effects on replay are zero; ordering assumptions are written down and tested |
| **Next trigger** | — |
| **Covers** | idempotent consumers · delivery semantics · replay |

---

# MODULE 15 — Infrastructure and deployment · **CORE**

**Audit verdict:** correctly sequenced, with **one stage badly late** and **one
reclassification**. 15.1 is also partly done already.

> ### 15.2 (CI) — deferred on 2026-10-21, with a trigger
>
> `[measured]` There are **113 checks** — 78 backend tests, 35 rag tests,
> `tsc` and `eslint` — and **no automated gate**. Nothing runs them except a
> human remembering to.
>
> **Deferred deliberately.** Not because the argument against it won, but
> because the cost of adding it later is roughly flat — a workflow file and a
> Postgres service container — while the stages between here and then produce
> more interesting work. Recorded here so it does not become a thing nobody
> decided.
>
> **The trigger, named rather than vague:**
>
> | Condition | Why it forces the issue |
> |---|---|
> | **3.3's regression gate exists** | it is specified as *"a one-command run that compares to baseline and fails on regression"*. A gate nobody runs blocks nothing — a chunking change that drops recall 8% would merge unnoticed, which is the exact failure 3.3 exists to prevent |
> | **or: a broken commit reaches `main`** | the constitutional rule's own shape — an observed problem rather than an anticipated one. The first time `git bisect` lands on a commit whose tests never passed, the argument is over |
>
> Whichever comes first. **3.3 is the likely one**, and it is four stages away.
>
> ── The risk being accepted ───────────────────────────────────────────────────
>
> Every commit between now and then is green only because someone chose to
> check. Six commits for stage 1.3 were verified that way; nothing enforces the
> seventh. The failure is silent and found later, usually while debugging
> something unrelated.
>
> **The cheap mitigation, if that bites before the trigger fires:** a single
> `make check` or a `pre-push` git hook running the same four commands. Ten
> lines, no infrastructure, no GitHub Actions, and it converts "remembering" into
> "opting out". It is not CI — it runs on one machine and can be skipped with
> `--no-verify` — but it closes most of the gap for a solo developer.
>
> The full 15.2 (staging deploys, artifacts, the quality gate) stays here
> regardless.

### 15.1 — Containerisation and configuration · `[required-when]` *(it must run elsewhere)*

| | |
|---|---|
| **Capability** | the whole system starts on a clean machine from one command |
| **Now** | **partly done.** Compose runs Postgres and the agent; the agent is containerised and non-root; config is environment-driven with `.env` gitignored and excluded from the build context `[measured]`. The backend and the frontend still run on the host |
| **Problem** | it does not run anywhere else — and after 1.3 there is a worker that also needs an image |
| **Diagnose** | try to run it on a clean machine |
| **Root cause** | implicit dependencies and machine-specific config |
| **Learn** | Docker, layer caching, 12-factor config, secret handling, health endpoints |
| **Build** | the remaining Dockerfiles (backend, worker, frontend). Compose for the full stack. Config from environment; secrets never in images |
| **Verify** | run with a missing env var; it should **fail loudly at boot**, not mysteriously later. The agent already does this for its embedding configuration — extend the pattern |
| **Done when** | clean-machine setup time is measured; every service fails fast on missing configuration; no secret is in any image layer |
| **Next trigger** | deploys are manual and error-prone |
| **Covers** | Docker · 12-factor · secrets · health checks |

**Why the agent was containerised at 1.2 rather than here:** Windows Smart App
Control refuses to load `grpcio`'s unsigned compiled binary, which
`qdrant-client` imports. The policy governs the Windows host and not a Linux
container, so the agent moved into one and **the security control stayed on**.
That is a real constraint producing a real decision, not 15.1 arriving early for
its own sake.

### 15.2 — CI/CD · `[required-when]` *(a regression can reach main)* — **see the note above**

| | |
|---|---|
| **Capability** | a change that breaks something cannot merge |
| **Now** | 84 tests, run by hand `[measured]` |
| **Problem** | a regression reaches main; a deploy is forgotten |
| **Diagnose** | count defects that automated checks would have caught |
| **Root cause** | no automated gate |
| **Learn** | pipelines, test pyramid, build artifacts, deployment automation |
| **Build** | CI: lint, types, unit, integration, **and the RAG eval regression gate from 3.3**. CD to a staging environment |
| **Verify** | open a PR that regresses retrieval quality; confirm CI blocks it |
| **Done when** | every suite runs on every PR; the integration tests get a real Postgres in CI; the quality gate blocks a known-bad change; deploy time and failure rate are measured |
| **Next trigger** | it deploys to staging. Nothing is in the cloud |
| **Covers** | CI/CD · test automation · quality gates |

### 15.3 — Cloud deployment · `[required-when]` *(it must be reachable off your machine)*

| | |
|---|---|
| **Capability** | the system runs somewhere other people can reach, durably |
| **Now** | containers on a laptop |
| **Problem** | you need it reachable, durable and observable off your machine |
| **Diagnose** | — |
| **Root cause** | — |
| **Learn** | IaaS vs PaaS, managed services, VPC/networking, IAM, managed Postgres/Redis, object storage, cost, **secret management and rotation** |
| **Build** | deploy to **one** cloud (AWS or GCP — pick, do not learn both). Managed Postgres and Redis. Object storage for raw files — **which is also 1.3's deferred byte-storage trigger arriving**. Least-privilege IAM. Real secrets, rotated, never the Compose defaults |
| **Verify** | terminate an instance; delete a security-group rule; rotate a secret. Recover from each. **TLS everywhere** — the first time traffic leaves localhost |
| **Done when** | monthly cost is known; deploy time and recovery time are measured; no development credential survives anywhere in the deployed system |
| **Next trigger** | fixed capacity under variable load |
| **Covers** | cloud · managed services · IAM · networking · cost · secrets |

**The Compose defaults are a deliberate exception that ends here.** `myrag` /
`myrag_dev_password` are written into `docker-compose.yml` on purpose — a
throwaway container reachable only from one machine. Nothing resembling a
deployment may reuse them, and this is the stage that enforces it.

### 15.4 — Autoscaling and operations · **ADV** · *(split: see below)*

**Reclassified in this revision.** This stage bundled two things of very
different urgency, and the ADV mark applied to both hid one of them.

| Part | Class | Why |
|---|---|---|
| Autoscaling | `[deferrable]` | genuinely optional sophistication; fixed capacity is correct, just wasteful |
| **Backup with a tested restore** | **`[required-when]`** | the condition is *data exists that you would be sad to lose*. Not optional, not advanced — a system with no tested restore has no durability guarantee regardless of what its database promises |

| | |
|---|---|
| **Capability** | capacity follows demand; data survives its storage |
| **Now** | fixed instance counts, no backups at all |
| **Problem** | overprovisioned at night, saturated at peak. And separately: **nothing is backed up** |
| **Diagnose** | utilisation over time vs cost. For backups: try to answer "if the volume were deleted now, what would we lose?" |
| **Root cause** | static capacity, variable demand. And: durability was assumed from Postgres rather than established |
| **Learn** | autoscaling signals, scale-to-zero, cold starts, queue-depth-based worker scaling, backup/restore, RPO/RTO |
| **Build** | scale API on latency/CPU; scale **workers on queue depth** (the correct signal). Backups with a **tested** restore |
| **Verify** | a traffic spike; **and a restore drill from backup into a clean database**. An untested backup is not a backup |
| **Done when** | cost per request and scale-up time are measured; restore time is measured by actually doing it; RPO and RTO are stated numbers |
| **Next trigger** | — |
| **Covers** | autoscaling · operations · backup/restore |

---

# MODULE 16 — Document intelligence · **ADV**

> **Technique catalogue:** `docs/architecture/system-design.md` §8.1–8.2 covers
> extraction and the canonical document model in more detail than this module.

RAG breadth. Deliberately after the platform is solid: each new format is an
ingestion-pipeline change, and you want the measurement harness and reliable
pipeline in place before multiplying input types.

**Audit verdict:** correctly sequenced and correctly deferred. Each stage gains a
capability and a completion criterion; the prerequisite was already stated and is
now unmissable.

| Stage | Capability | Problem | Build | Done when | Covers |
|---|---|---|---|---|---|
| **16.1** DOCX/HTML/TXT/MD · **ADV** · `[required-when]` *(users upload them)* | non-PDF uploads work | users upload non-PDFs and they are rejected | per-format extractors behind one canonical document model | each format extracts with provenance intact; the eval set covers it; the rejection path still works for unsupported formats | document modelling · parser abstraction |
| **16.2** Scanned PDFs / OCR · **ADV** · `[required-when]` *(scanned docs matter)* | scanned documents are indexed rather than refused | a scanned PDF yields zero text; ingestion refuses it loudly (**already correct** — it does not silently succeed) | OCR fallback when extracted text is below a threshold per page | OCR path measured on the eval set; cost and latency per page measured; the loud refusal remains for OCR failures | OCR · pipeline branching · quality gates |
| **16.3** Tables · **ADV** · `[required-when]` *(table questions fail)* | questions about tabular data are answerable | questions about tabular data fail; inspection shows tables flattened to unreadable prose | table detection; table-aware chunking that keeps headers with rows | recall improves on the table question slice specifically | structured extraction · table-aware chunking |
| **16.4** Images and charts · **OPT** · `[deferrable]` | figures are findable | chart questions fail with text-only retrieval | vision model captions figures; captions are indexed; multimodal embeddings if justified | measured on a figure-question slice; cost per document stated | multimodal RAG · vision models |

**Each requires extending the eval set with that format before building it**, or
you cannot tell whether it worked. That is a hard prerequisite, not advice.

**16.2's trigger is already half-resolved:** `rag` refuses a PDF with no
extractable text and says why, so the dangerous silent-success case does not
exist. What remains is making those documents *work*, which is a feature, not a
bug fix.

---

# MODULE 17 — Advanced RAG · **ADV**

> **Technique catalogue:** `docs/architecture/system-design.md` §8.6 has the full
> eleven-level retrieval ladder with failure modes; §8.9 covers grounding.

**Audit verdict:** three stages here are marked CORE inside an ADV module, which
the previous version flagged. **One of them has moved**: 17.4's structural
minimum is now required at 5.1, because that is where the risk begins. The rest
stand.

| Stage | Capability | Problem | Build | Done when | Covers |
|---|---|---|---|---|---|
| **17.1** Contextual retrieval · **ADV** · `[deferrable]` | chunks carry their situating context | chunks are individually meaningless without their section | prepend an LLM-written situating summary to each chunk before embedding | recall improvement measured against the added ingestion cost per document | contextual retrieval · ingestion cost tradeoffs |
| **17.2** Grounding and citation verification · **CORE** · `[required-when]` *(answers are shown to anyone but you)* | a citation actually supports the claim it is attached to | answers cite a real chunk that does not actually support the claim | programmatic check that each cited span supports its claim | unsupported-citation rate measured; the check runs in the eval harness | grounding · faithfulness |
| **17.3** Abstention · **CORE** · `[required-when]` *(same)* | the system says "I don't know" instead of inventing | the system confidently answers questions the corpus cannot answer | evidence-sufficiency gate before generation; calibrate against the "impossible" eval questions from 3.1 | false-answer rate on unanswerable questions measured; the tradeoff against over-abstention is chosen deliberately | abstention · calibration |
| **17.4** Prompt-injection defence · **CORE** · **minimum `[required]` at 5.1** | a document cannot change the system's behaviour | a planted instruction in an uploaded document changes behaviour | the four structural invariants: ACL filtering, untrusted-data delimiting, privilege separation, **no document-controlled tool access** | each invariant has an adversarial test; the test set grows with every new attempt you invent | AI security · structural defence |
| **17.5** Contradiction surfacing · **ADV** · `[deferrable]` | disagreement between sources is visible rather than hidden | two documents disagree; the system silently picks one and sounds confident | detect conflicting evidence among retrieved chunks; **surface both with provenance and state the conflict** | conflict detection measured on a deliberately contradictory eval slice | conflict detection · provenance · honest uncertainty |
| **17.6** Multi-hop / agentic retrieval · **OPT** · `[deferrable]` | chained-fact questions work | questions requiring chained facts fail even with perfect single-shot retrieval | iterative retrieve → reason → retrieve, with a step budget | measured on a multi-hop slice; cost and latency per query bounded | agentic RAG · iterative retrieval |
| **17.7** Graph retrieval · **OPT** · `[deferrable]` | relationship questions across documents work | questions about *relationships* spanning many documents fail regardless of chunk quality | extract entities and relations into a graph; traverse it alongside vector search | measured on a relationship slice | graph RAG · entity extraction |
| **17.8** Multilingual retrieval · **OPT** · `[deferrable]` | cross-language retrieval works | the corpus or the questions are not all in one language | multilingual embedding model; measure cross-language recall explicitly | cross-language recall measured per language pair | multilingual embeddings |
| **17.9** Multi-vector / late interaction · **OPT** · `[deferrable]` | token-level detail survives on long chunks | single-vector embeddings lose token-level detail | ColBERT-style multi-vector retrieval | recall gain measured against the index-size cost | late interaction · multi-vector |

**17.2 and 17.3 are CORE and `[required-when]`** for the same reason: they are
the difference between a demo and something trustworthy, and the condition is the
moment anyone but you reads an answer.

**17.4's minimum moved to 5.1.** Two of its four invariants — untrusted-data
delimiting and no document-controlled tool access — are `[required]` the moment
one user's document can reach another user's prompt. The other two need 5.3's ACL
model and stay here. This was the clearest case in the document of critical
security work sitting behind an advanced label.

**On contradiction surfacing (17.5):** the scope boundary matters more than the
feature. Surface both sources and state the conflict; **do not attempt to decide
which is correct.** Automatic truth arbitration is a genuinely open research
problem and not this project's job. Knowing where to stop is the lesson.

**17.6–17.9 are OPT and likely to stay unbuilt.** They are on the map so the
territory is complete, and so that when an interviewer asks "how would you handle
relationship queries across documents?" you can answer rather than discover the
gap live.

---

# MODULE 18 — LLMOps · **ADV**

**Audit verdict:** correctly sequenced and deferred.

| Stage | Capability | Problem | Build | Done when | Covers |
|---|---|---|---|---|---|
| **18.1** Prompt versioning · **ADV** · `[required-when]` *(prompts change often)* | you can say which prompt produced a given answer, and roll back | a prompt tweak silently changes quality; nobody can say which version is live | prompts as versioned artifacts; eval run per version; rollback | every answer is attributable to a prompt version; a rollback has been performed | prompt management · reproducibility |
| **18.2** Online evaluation · **ADV** · `[required-when]` *(real users exist)* | real usage informs quality, not just the eval set | offline evals pass; real users are unhappy | thumbs up/down, abstention rate, retrieval-score distributions, sampled human review | online and offline signals are compared; a divergence has been investigated | online eval · feedback loops |
| **18.3** Cost and model routing · **ADV** · `[required-when]` *(cost matters)* | cost per answer is known and controllable | cost per answer is untracked and rising | per-request token/cost accounting; cheap model for easy queries, strong for hard; measure the quality cost | cost per answer measured; the routing's quality cost measured on the eval set | cost engineering · model routing |
| **18.4** Drift detection · **OPT** · `[deferrable]` | silent provider changes are caught | quality degrades without a deploy — the provider changed the model underneath you | periodic eval on a frozen set; alert on drift | a drift alert has fired at least once in a drill | drift · provider risk |

---

# MODULE 19 — Platform and SDK · **ADV**

Entered only when the engine is genuinely reliable.

**Audit verdict:** correctly sequenced and deferred.

| Stage | Capability | Problem | Build | Done when | Covers |
|---|---|---|---|---|---|
| **19.1** Public API design · **CORE** · `[required-when]` *(a second consumer)* | an external consumer can integrate without reading your source | a second consumer needs the engine and the internal API leaks internals | versioned public API, pagination, consistent errors, OpenAPI | the public surface is versioned and documented; an internal change has been made without breaking it | API design · versioning |
| **19.2** SDK · **ADV** · `[deferrable]` | integrators get retries and pagination for free | integrators hand-roll HTTP and get it wrong | thin typed clients; retries and pagination handled; examples | an example app built against the SDK alone | SDK design · DX |
| **19.3** Platform hardening · **ADV** · `[deferrable]` | external tenants can be onboarded and metered | external tenants, real quotas, real support | API keys with scopes, usage metering, per-tenant dashboards, docs | metering reconciles with provider bills; scopes are enforced and tested | multi-tenancy · metering |

---

# What this project cannot teach you

Study these elsewhere; do not pretend the project covers them. **This list is
itself a deferral record** — each row says what is missing and what substitutes.

| Gap | Why | Substitute |
|---|---|---|
| **Genuine high-contention concurrency** | Module 6 helps, but this is not a payments ledger or a ticket sale | build a small seat-booking or wallet service as a side exercise |
| **Consensus (Raft/Paxos)** | you use systems that implement it; you never build one | read the Raft paper; implement a toy leader election |
| **Real operations** | no real users, no on-call, no incident with consequences | chaos drills with a timer; write real postmortems for induced incidents |
| **Cost at scale** | you will never feel a $50k bill shape a decision | do the capacity/cost modelling in 13.4 seriously |
| **Multi-region / geo-distribution** | cannot meaningfully simulate cross-region latency and partitions | read; design on paper; discuss tradeoffs |
| **Database internals** | you use Postgres well; you do not learn its storage engine | separate study: B-trees, MVCC, WAL |
| **Team-scale engineering** | solo project | open-source contribution |
| **Security depth** | basic authn/authz, input validation and injection defence only | separate track: OWASP, threat modelling |
| **Kafka / stream processing** | no genuine trigger here | separate project if you need it — do not bolt it on |
| **Frontend engineering depth** | the client exists and is deliberately simple | it is not this project's subject, and that is a choice, not an oversight |

---

# The rules that make this work

1. **No stage without a reason** — an observed trigger, or a stated product
   requirement, or an explicitly labelled teaching experiment. If you cannot
   demonstrate the problem and no requirement forces it, you are not ready.
2. **Every stage produces evidence, and every claim carries its provenance.**
   What counts as evidence depends on the claim — see *What counts as evidence*
   in the front matter. A quantitative claim needs a `[measured]` before and
   after; a correctness, security or state-machine invariant needs an explicit
   test that fails against the broken version. **A stage with neither is not
   done**, and a number attached to the wrong label is worse than no number.
3. **One variable at a time.** Two changes in one experiment teaches nothing.
4. **Write up the failures too.** The experiment that made things worse is as
   valuable as the one that helped — and it is what makes you credible.
5. **Verification is part of the stage, not after it.** A stage without its
   proof is not finished, however well the code runs.
6. **Answer the five questions before building test infrastructure.** A fake, a
   harness, a synthetic workload and a benchmark are all substantial engineering
   and all need a reason.
7. **Critical work is never deferred for being hard.** Correctness, security,
   data integrity and failure handling are `[required]` or `[required-when]`, and
   those classes outrank CORE/ADV/OPT.
8. **Nothing is deleted silently.** Deferred work says what, why, and the
   condition that brings it back.
9. **"Mastered" means:** implemented it, broke it, debugged it, measured it, and
   can explain the tradeoff without notes.
10. **Modules 1–10 make you interview-ready.** Everything after is depth. Do not
    delay applying for jobs until Module 19.

---

# Change log

Why this document was revised, and what changed. Kept so the reasoning is
auditable rather than lost in a diff.

## 2026-10-27 — Stage 2.3 complete; the stage's own premise was wrong

**179 backend tests** (was 122), 44 rag, `tsc` and `eslint` clean.

**The roadmap's trigger for this stage was false, and measuring it is what
showed that.** It said a malformed PDF *"retries every 30s for a day and
consumes the embedding quota by itself"*. Both halves:

| Claim | Measured |
|---|---|
| retries for a day | bounded at **5 attempts over 14.6s** — 2.1's `max_attempts` already stopped it |
| consumes embedding quota | **zero** — `rag/pipeline.py` extracts before it reads settings or touches a provider |

**The real failure runs the other way.** A *valid* document uploaded during an
outage was **permanently destroyed after 22 seconds** — a window
`docker compose restart agent` fits inside, with no recovery but a human
re-uploading. This is the second stage running whose Problem row was written
before the preceding stage existed and was invalidated by it (2.1's "orphans
10 → 0" was the first). **A Problem row is a hypothesis with a date on it.**

| Reconciled | Was | Now |
|---|---|---|
| 2.3's Problem | `[hypothesis]`, quota exhaustion | `[measured]`, and false — the cost is lost documents |
| 2.3's Build | "move to DLQ" | a query, not a table; classify on HTTP status |
| `rag/errors.py` | "2.3 introduces that distinction" | it did, and **not here** — see below |
| `_record_failure` | argued for retrying everything | the rule it was waiting for now exists |
| test counts | 122 backend | 179 |

**The classification was already at the boundary.** `rag/errors.py` said its
hierarchy was where transient-versus-permanent belonged. It was not needed: the
backend never imports `rag`, and the agent already maps the engine's errors onto
status codes. **4xx means the request can never succeed; 5xx means the system
failed you** — the HTTP specification's own semantics, with `429` carved out as
the one 4xx that means *come back later*. Keeping the backend ignorant of the
engine is what made the 1.3 worker split possible, and it paid again here.

**The retry budget was wrong by a factor of three, and the test written to pin
it did not catch that.** `max_attempts = 8` was documented as "about three
minutes" by summing the ceilings. What a document experiences is the sum of the
*draws*, and full jitter halves every one: simulated over 20,000 runs the
realised coverage was a **median of 91s and a p10 of 55s**. One document in ten
gave up after 55 seconds.

The test asserted the ceilings of a hardcoded `RetryPolicy(max_attempts=8, …)`,
so it agreed with itself about a policy nobody ran. It now reads `Settings()` and
simulates, and fails at 8, 12 and 20 attempts while passing at 15. **Two general
lessons: a test asserting a literal instead of the configuration cannot detect
drift, and reasoning about a bound is not measuring a distribution.**

**Three findings about the apparatus, not the system:**

1. **A measurement script reported "GAVE UP" when its own watch loop timed
   out.** The database showed the document still `queued` at attempt 13, and a
   worker later took it to `done` at attempt 14. The script now has three
   outcomes — `done`, `failed`, `INCONCLUSIVE` — and detects host stalls
   instead of folding them into the numbers.
2. **A mutation-testing script aimed at an ambiguous anchor** and landed in
   2.2's duplicate-upload path instead of 2.3's retry endpoint, reporting
   SURVIVED for a code path the tests do not exercise. **A mutation that lands
   somewhere unintended reads exactly like a missing test.** It now asserts each
   anchor occurs exactly once.
3. **That same script keyed its backups on each file's basename**, and three of
   its five targets are called `documents.py`. Nothing was corrupted only
   because it asserts before writing. It now keys on the full path and restores
   in a `finally`.

**A known environmental flake, recorded rather than explained away.** Roughly one
backend run in six fails or errors on an unrelated test with a connection
`TimeoutError`, and passes on a rerun. It is not data pollution — no test file
leaves rows behind — and connections sit at 3 of a possible 100. It looks like
Windows-to-Dockerised-Postgres port-forward latency. **Trigger to investigate
properly:** if it exceeds roughly one run in five, or ever fails
deterministically.

## 2026-10-26 — Stages 2.1 and 2.2 complete; four plan corrections recorded

**122 backend tests** (was 78), **44 rag** (was 35), `tsc` and `eslint` clean.
Full write-ups in `docs/experiments/0002-stage-2-2-baseline-audit.md` and
`0003-stage-2-2-idempotency-measures.md`.

| Reconciled | Was | Now |
|---|---|---|
| 2.1 and 2.2's status | NOT STARTED / not written | both COMPLETE, with what they produced |
| the stranded row | "nothing has touched it, and nothing will" | **recovered itself in 25ms**, then became 2.2's trigger |
| 2.1's measure | "orphaned jobs 10 → 0" `[requirement]` | **not measurable as stated** — see below |
| 2.2's problem | `[hypothesis]` | `[measured]`, with the specimen |
| 2.2's Build | delete-then-upsert, idempotency keys | upsert-then-prune, keys deferred with a trigger |
| test counts | 78 backend / 35 rag | 122 / 44 |

**2.1's measure was unmeasurable, and the reason is architectural.** "Orphaned
jobs after 10 induced crashes: 10 → 0" assumes orphans accumulate. They cannot:
every worker reaps before it claims, so the highest count observable at any
instant was 1. The run is reported as what it was — 10 real process kills, every
document terminal in 9.8s with one ordinary worker and no intervention. **A
target number can encode an assumption about the architecture; when the
architecture makes it false, report what happened rather than reshaping the
system to fit the measure.**

**Four corrections 2.2 made to its own approved plan**, each forced by something
measured rather than by review:

| Correction | Found by |
|---|---|
| `uuid5(UUID(document_id), …)` crashes — the engine never required a UUID id | reading `test_pipeline.py` before writing code |
| delete-then-upsert is the wrong order, **and** a tail delete repairs nothing predating the id scheme | the end-to-end measure: 6 points became **9** |
| the orphan tool must read Postgres directly, not `GET /documents` | the endpoint caps `limit` at 200, and a truncated live list makes live documents look deletable |
| the migration cannot hash every row | **every document in the database was the same file**; the unique index would have failed on all four |

**The second one is the one worth remembering.** Every unit test passed, and six
separate mutations of the id function were each caught by the test claiming to
cover them. The scheme was correct and well tested. Only the end-to-end measure
against real data found that the *replacement* step repaired nothing — which is
the argument for this document's rule that a stage is not done until it has
produced a number.

**A problem this plan did not predict at all.** 72% of the vector store was
points belonging to documents that no longer existed: `ON DELETE CASCADE` stops
at the edge of Postgres. It is a dual-write failure, not a retry effect. A live
query cited one of them — a document `GET /documents/{id}` answers 404 for.
`tools/qdrant_orphans.py` took it 39 → 0, but it is a **cleanup, not a fix**:
nothing prevents the next one until Module 14's outbox. `DELETE /documents/{id}`
is deliberately still unbuilt for the same reason.

**Three findings about testing**, recorded because they generalise:

1. **A test can pass for a reason it does not state.** `queued_at DESC` in the
   latest-job query had **no test capable of failing** — inside a test,
   `session.commit()` does not advance `transaction_timestamp()`, so every row
   shares a timestamp and the `id DESC` tiebreaker silently decided every
   ordering. Found by mutation; fixed by making the two columns disagree.
2. **A test written for a mechanism may not reach it.** The savepoint test
   passed with the savepoint removed, because by the time it ran the winner's
   row was committed and the loser took the fast path. The race window is
   *inside one call* and cannot be hit by ordering two calls from outside.
3. **A new constraint breaks correct tests.** `uq_documents_content_hash` broke
   twelve tests across four files, none about uniqueness — every upload helper
   handed each document the same bytes. **Fifth occurrence**, same cause each
   time: the helper knew less about the schema than the schema did.

**A wiring bug surfaced by the client layer.** `baseApi.ts` wrapped
`fetchBaseQuery` without declaring `BaseQueryFn`'s `Meta` parameter, which
defaults to `{}` — so **no endpoint in the frontend could read a response header
or status code**, and `tsc` reported it as a missing property rather than
missing wiring. Not specific to uploads; anything wanting `Location`, an `ETag`
or `Retry-After` would have hit it.

## 2026-10-21 — Stage 1.3 complete; documents reconciled

Built over six layers, each leaving the suite green: schema and migration,
repository claim, service split, the `202` route, the worker process, the
polling client. **78 backend tests** (was 49), 35 rag, `tsc` and `eslint` clean.

**Renamed the stage.** "Asynchronous ingestion" → "Ingestion out of the request
cycle". The old name caused a real misunderstanding: the backend was already
`async def` everywhere and this stage added none. See the note at the stage.

| Reconciled | Was | Now |
|---|---|---|
| 1.3's status | NOT STARTED | COMPLETE, with a what-it-produced table |
| the journey | 1.3 NEXT | 1.3 DONE, 2.1 NEXT |
| test counts | 49 backend | 78 backend |
| **the stuck rows** | "three such rows exist right now" | **one**, with its id recorded |
| 2.1's trigger | `[hypothesis until 1.3 exists]` for the worker case | `[measured]` — a worker was killed holding a claim |
| the frontend test gap | "becomes required at 1.3" | **the condition fired and the tests are not written** — recorded as a debt |

**On the stuck rows.** The original three were destroyed during 1.3's schema
work by an `alembic downgrade base`, which drops the tables — heavier than the
`downgrade -1` that was intended. They were reproducible development debris,
but a `[measured]` claim in this document rested on them and was untrue for a
while. The replacement was created deliberately, by pausing the agent, letting
a worker claim the job, and killing the worker.

**Two findings 1.3 produced that it did not set out to**, both folded into 2.1:
a stranded job makes the client poll forever, and the worker's cooperative
shutdown can take as long as `AGENT_TIMEOUT` — long enough that Docker sends
`SIGKILL` and manufactures the very stuck row the clean stop was meant to avoid.

## 2026-10-17 — the fake embedding provider removed, 1.3 re-scoped

**Why.** The fake provider, the agent's startup validation, the fake/collection
guard and the load-test Compose overlay were all built during Stage 1.3
*preparation*, before 1.3 itself had begun. The build was sound; the sequencing
was not, and it is the mistake that prompted this whole revision. Removed, so
1.3 starts from the committed baseline. **The fake embedder returns at 2.4**,
where the plan places it and where a stage that needs it can introduce it with a
reason.

**Code is now exactly at `HEAD`.** 35 `rag` + 49 `backend` tests pass; 42 tests
were removed with the code they covered.

**The consequence, accepted rather than hidden:** 1.3 can no longer produce a
"before" p95. Gemini's free tier rejects a large ingest with a 429 in about a
second `[measured]`, so any load measurement would describe the quota, not the
system.

| Changed | From | To |
|---|---|---|
| **1.3 Step 0** | a capacity probe producing p50/p95 | **there is no measurement, and that is the honest position** — the stage is justified by three non-magnitudes instead: work lost on restart, no retry without re-upload, no upper bound on the request |
| **1.3 Verify** | included a before/after latency row | removed. Verification is integration, failure-injection, concurrency and client tests |
| **1.3 Done when** | — | states explicitly that **no latency claim is made**, and that "the response no longer depends on document size" is provable without a stopwatch, because the handler stops calling the agent at all |
| **1.3's timeout divergence** | reproduced with the fake delay | **deferred to 2.4**, which is where an on-demand slow ingest exists again. It stays a `[hypothesis]` and does not block 1.3 |
| **The collection-restriction note** | explained why `loadtest` did not weaken the test | removed; there is no fake provider to restrict |
| **2.4** | the fake embedder had been removed from its Build | **restored**, and it now also inherits 1.3's three deferred measurements in a table |
| **7.1, 11.1** | referred to the fake provider as already existing | corrected to point at 2.4 |
| **Capacity probe** | arrives 1.3 | arrives **2.4** — it cannot exist before the provider it depends on |
| Test counts | 139 | **84** |

**This is the document's own rule working as intended.** The five-question gate
asks what we will *do* with a measurement before building the instrument to take
it. Applied to 1.3, the answer turned out to be "nothing we cannot establish
with tests" — so the instrument waits for the stage that genuinely needs it.

## 2026-10-17 — evidence corrections

Applied after a second review, which caught two places where the revision had
reproduced the very fault it was written to fix.

| Fixed | Was | Now |
|---|---|---|
| **1.3's timeout divergence** | labelled `[measured]` "at 1.2" | **`[hypothesis]`.** What 1.2 measured was the *crash* case — a killed process leaving chunks indexed and the job row at `processing`. A **timeout** firing against a still-running agent is a different event and has never been run. The stage now carries a table separating the two, notes that the backend half of the timeout path *is* unit-tested with a stub agent while the agent-continues half is not, and keeps the reproduction |
| **"Every stage produces a number / no number, not done"** | a blanket rule | **evidence-based.** A quantitative claim needs a `[measured]` before and after; a correctness, security, ordering or concurrency invariant needs an explicit test that **fails against the broken version**. A new *What counts as evidence* table maps seven kinds of claim to what proves each |

**Two more of the same class, found by auditing every `[measured]` in the
file:** 2.1 said *"`kill -9` a worker mid-job"* is measured — the phenomenon is,
but there is no worker yet, so the noun was wrong and the worker case is now
labelled as following by construction once 1.3 exists. And 1.2's problem row
labelled the pre-1.2 blindness `[measured]` when it was **true by
construction** — there was no table an attempt could have been recorded in, so
there was nothing to measure. That is a stronger claim than a measurement, and
it should say so.

**Why the second one mattered.** The blanket rule pushed toward inventing
metrics for claims that were never quantitative — 1.2's real achievement is four
CHECK constraints that make an impossible job state unrepresentable, and
"interrupted ingests detectable: 0% → 100%" is a worse statement of that than a
test which fails when the constraint is dropped. Demanding a number everywhere
is its own kind of dishonesty.

## 2026-10-17 — consistency pass

Applied the same day, after review of the audit above.

| Fixed | Was | Now |
|---|---|---|
| **"seven questions" vs eleven rows** | the template claimed seven questions and then listed eleven rows | the seven questions are stated explicitly, and the table maps each row to a question number — four rows (`Now`, `Diagnose`, `Root cause`, `Covers`) are marked as supporting detail rather than separate questions |
| **1.3's divergence test vs the fake-provider restriction** | 1.3 said to reproduce the timeout divergence with the fake provider, which configuration refuses to run against the `documents` collection — an unflagged contradiction | 1.3 now states that both the probe and the reproduction run against `loadtest`, and explains why that does not weaken the test: the divergence is between Postgres and the vector store, and chunk presence is proved by a filtered point count, not by retrieval. **The restriction is preserved, not relaxed** |
| **1.3's Step 0** | did not mention the collection | names the overlay and says the agent refuses to start without it, by design |

**Also checked and found consistent:** all 56 numbered stages and all 20
table-form stages carry a necessity class; the journey list matches the stages
that exist, including the newly added 5.0; the test-count figure agrees with
the suites that exist; `test doubles` was removed from 2.4's Covers
line along with the fake embedder.

## 2026-10-17 — problem-driven audit and correction

**Why.** The fake embedding provider was built mid-implementation as an
unexplained detour. Stage 1.3's measurement turned out to be blocked by a
provider quota, which nothing in the plan had anticipated, and three further
pieces of engineering followed before the actual stage began. The plan had also
stated illustrative numbers in the same voice as measured ones — Stage 1.3's
"four minutes" chief among them — which made it a source of false beliefs rather
than a guide.

**Added**

| What | Where | Why |
|---|---|---|
| Governing philosophy | front matter | the document had rules but never stated its principle |
| Evidence labels | front matter | illustrations were indistinguishable from measurements |
| Two legitimate reasons for work (A: need, B: teaching experiment) | front matter | the old rule allowed only observed triggers, so honest experiments had to masquerade as needs |
| The five questions before test infrastructure | front matter | the direct fix for the detour that caused this revision |
| `Capability` and `Done when` rows | every stage | nothing distinguished "code runs" from "stage finished" |
| Necessity classes `[required]` / `[required-when]` / `[deferrable]` | every stage | CORE/ADV/OPT describes interview value and was being read as necessity |
| Destination vs journey | front matter | nineteen modules read as a to-do list |
| Implementation status, verified against the repo | front matter | the plan and the code had drifted and nothing said so |
| Frontend as a cross-cutting concern | front matter | **absent from every previous version**, despite being 23 files of real client state |
| Security thread with per-item conditions | front matter | security was scattered across 5.1, 5.2 and 17.4 with the urgent items behind an ADV mark |
| **Stage 5.0 — Untrusted input** | Module 5 | parser resource exhaustion had no home, and becomes required the moment anyone else can upload |
| Change log | here | — |

**Corrected**

| What | Was | Now |
|---|---|---|
| **1.3's trigger** | "a 300-page PDF blocks one worker for four minutes" | that is not reproducible — batching makes a 300-page PDF ~3 round trips. Re-grounded on the measured timeout divergence, lost work on restart, and no retry without re-upload |
| **1.3's measure** | "p95 240s → <200ms" | a capacity probe measures the real "before" first; 240s was never measured and would have had to be manufactured |
| **1.3's concurrency claim** | "concurrent uploads make the API unresponsive" | labelled `[hypothesis]`, and probably false at N=20 — the threadpool holds 40 `[measured]` |
| **1.3's missing decision** | not mentioned | where the file bytes live between accept and process, with three options and a trigger |
| **`QDRANT_URL` timing** | forced at 1.3 | only when a second process needs the index — moved to 12.1 |
| **12.1's in-memory dict** | "that in-memory conversation dict finally dies here" | no such dict exists; ADR 0001 deferred conversation persistence and it was never built |
| **Fake embedder** | arrives at 2.4, built again at 11.1 | already built at 1.3 prep, with its safeguards documented |
| **2.4's trigger** | "no instrumentation" | plus a measured one: every `logger.info` in the codebase is currently discarded |
| **6.3's Redis arm** | compared against a Redis counter | deferred — Redis does not exist until 9.1 |
| **8.2's Redis** | "limits in Redis", "run two API instances" | Postgres until 12.1, where a second instance makes sharing a real requirement |
| **9.5** | ADV only | `[required]` — a cache that takes the system down is a regression introduced by 9.1 |
| **11.1** | build a harness and a fake embedder | an upgrade of 1.3's probe, with the five questions answered |
| **13.1** | "synthetically load 10M chunks" | measure at a feasible size at two or more points, then extrapolate with a stated error bound |
| **15.2 (CI)** | Module 15 | flagged as overdue now: 84 tests `[measured]`, no automated gate |
| **15.4** | one ADV stage | split: autoscaling `[deferrable]`, **backup with a tested restore `[required-when]`** |
| **17.4** | Module 17 | structural minimum `[required]` at 5.1, the rest stays |
| **3.1** | no prerequisite | blocked on a real document corpus; the only documents in the repo are synthetic fixtures whose own docstring disclaims eval use |

**Retained unchanged**, because the audit found them correctly sequenced and
sufficiently specified: 1.1 and 1.2 (both complete); the constitutional rule;
Module 6's anomaly catalogue and fencing-token sequence; 9.3's three invalidation
strategies and the argument about them; 13.0's unit-conversion chain; Module
14's honest warning; the "what this project cannot teach you" table.

**Unverified assumptions that remain.** Every one is labelled `[hypothesis]` at
its stage; collected here so they are not forgotten:

| Assumption | Stage | How to verify |
|---|---|---|
| 20 concurrent uploads do not exhaust the 40-thread pool | 2.4 | the capacity probe — needs the fake embedder |
| the real ingest duration for a large document | 2.4 | calibration run with the fake embedder |
| a 120s timeout produces the Postgres/Qdrant divergence unattended | 2.4 | one upload with the delay above `AGENT_TIMEOUT` |
| ~~retries produce duplicate chunks~~ | 2.2 | **verified 2026-10-26.** 2.1's reaper recovered the 1.3 stranded row, ingesting it twice: 6 points where Postgres recorded 3, `chunk_index` `[0,0,1,1,2,2]` |
| a poison document consumes quota unboundedly | 2.3 | feed one in and count attempts |
| a row lock collapses throughput ~10× | 6.3 | 6.1's fix is what produces the number |
| repeated queries are common enough to justify a cache | 9.1 | measure the repeat rate before building |
| the chunks-per-document fan-out | 13.0 | measure on the real corpus, not fixtures |
