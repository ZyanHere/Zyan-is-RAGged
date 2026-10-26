# Current architecture

**What the system is *today*.** Not the destination — `../curriculum.md` has
that. Updated at the end of every stage, so it is never aspirational.

**Stage:** **2.3 complete. 2.4 not started.**
**Last updated:** 2026-10-27

## How to read this file

Two different kinds of statement live here, and conflating them is how a
document like this becomes fiction:

| Mark | Means |
|---|---|
| **✅** | **verified** — it exists, it runs, and a test or a recorded run proves it |
| **○** | **planned** — the architecture has a place for it; nothing is built |
| **⚠** | **known gap or stale** — true today and not how it should stay |

Anything unmarked is a description of the *design*, which is stable whether or
not the thing is built yet.

---

## Stage status

| Stage | Status | Evidence |
|---|---|---|
| **1.1** Working synchronous pipeline | ✅ complete | 4/4 citation tests resolve to the correct page; 3/3 bad-upload cases return 400/422 rather than 500; baseline run recorded (3 pages, 1,269 chars, 3 chunks, 4.0s ingest) |
| **1.2** Persist what happened | ✅ complete | migration round-trips up→down→up with no autogenerate drift; 3 induced crashes → 3 detectable rows; the citation's `document_id` is byte-identical to the Postgres primary key |
| **1.3** Ingestion out of the request cycle | ✅ complete | `202` in 38 ms, and 45 ms with the agent *paused*; a worker drained the queue and the citation still resolved to page 2; two claimers proved to take different jobs; the client reached a terminal state with nothing touching the page |
| **2.1** Job lifecycle, leases and retries | ✅ complete | 10 real process kills → every document terminal in 9.8 s with one worker and no intervention; the six-day-old stranded row recovered itself in 25 ms; a worker that loses its lease is proved unable to commit (`test_lease_handover.py`) |
| **2.2** Idempotency | ✅ complete | a doubly-indexed document repaired 9 → 3 points by re-ingestion, then 3 → 3 on a repeat; orphaned points 39 → 0; 5 concurrent uploads of one file → 1 document, one `202` and four `200`; Postgres and Qdrant agree 7/7 |
| **2.3** Failure classification and the DLQ | ✅ complete | a poison document costs 1 attempt instead of 5; the retry budget measured at 302.1s and 221.1s across two runs, where 22s had been fatal; the dead-letter list distinguishes the two kinds and only the recoverable one offers a retry |
| **2.4** Seeing inside | ○ not started | its trigger is `[measured]`: every `logger.info` in the backend is discarded |

**Built ahead of its stage, for reasons recorded in the Evolution Map:**

| Thing | Planned at | Built at | Why |
|---|---|---|---|
| ✅ Docker Compose + Postgres | 15.1 | 1.2 | Postgres needs it |
| ✅ Agent container | 15.1 | 1.2 | Windows Smart App Control refuses `grpcio`'s unsigned binary, which `qdrant-client` imports. The policy does not reach inside a Linux container, so the agent moved into one and the security control stayed on |

---

## Layers and dependency direction

```text
frontend  :3000  ──HTTP──▶  backend  :8000  ──HTTP──▶  agent  :8001  ──import──▶  rag
                                 │                        ▲
                            Postgres                      │
                                 │                        │
                              worker  ────────HTTP────────┘
                          (python -m app.worker)
```

**The worker is new at stage 1.3**, and where it sits is a decision rather than
an accident. It talks to the agent over HTTP exactly as the backend does, which
keeps two properties: the `backend → rag` import ban holds, and **the agent
remains the only process touching Qdrant**, so embedded mode survives. A worker
that imported `rag` directly would have forced a Qdrant server immediately —
embedded Qdrant takes an exclusive lock on its folder.

The queue between the API and the worker is a Postgres table, not a broker.

The arrows only point one way.

| Forbidden | Why |
|---|---|
| `backend` → `rag` | the backend must learn that a document was indexed from the agent's HTTP response, never by reaching into the engine |
| `backend` → `agent` (import) | they talk over HTTP; a direct import would couple deploys |
| `agent` → `backend` | the engine side never calls back up the stack |
| `rag` → anything above it | it is a library. This is what lets the eval harness import it with no chatbot in the loop |
| `frontend` → agent or rag | the backend is the only thing the browser talks to |

⚠ **This is not enforced.** `tools/check_dependencies.py` exists and can check
it, but **nothing runs it** — there is no CI in this repository. This file
previously claimed the rule "runs in CI and fails the build on a violation",
which was never true. The rule currently holds because it has been followed by
hand, which is exactly the situation the sentence was warning about. Minimal CI
is the next piece of infrastructure work (Evolution Map 15.2, flagged there as
overdue).

---

## What each layer owns

### `frontend/` :3000 — Next.js

⚠ **This description was stale and is corrected.** It previously said the
frontend was "kept from v0, deliberately not developed further". It was
developed: Next.js App Router, Redux Toolkit, RTK Query, 23 TypeScript files,
with a deliberate three-way split between server state (the RTK Query cache),
client/domain state and local component state.

```text
✅ upload a PDF and see what ingestion actually did (pages, pages-with-text,
   chunks, characters — so a partial extraction is visible, not hidden)
✅ the document list, read from the server, surviving a refresh, showing
   failures as well as successes
✅ ask a question and read an answer with its citations
✅ polling a job to a terminal state — starts when something is `queued` or
   `processing`, stops when everything is terminal
○  an authenticated state                       (5.2)
```

⚠ **Zero tests, and no longer defensible.** The argument was that the client
had rendering rather than logic. Stage 1.3 ended that: polling, terminal-state
detection and the self-cancelling interval are a state machine, and the only
thing that has ever verified them is one person watching a browser once.

The Evolution Map records this as an outstanding debt rather than rescheduling
it. Four behaviours are untested: polling starts, polling stops, `queued` and
`processing` render differently, and a `202` body of nulls renders without
blanks.

### `backend/` :8000 — the reliability layer

Owns everything that must be durable and correct. Knows nothing about prompts,
models or embeddings.

```text
✅ PostgreSQL — documents, ingestion_jobs, status lifecycle, Alembic
✅ the repository layer, and service-owned transaction boundaries
✅ the ordering invariant: record the attempt and COMMIT before any work starts
✅ the queue — `ingestion_jobs` with a `queued` state, claimed by
   `SELECT … FOR UPDATE SKIP LOCKED`
✅ the worker — a separate process, `python -m app.worker`
✅ leases, heartbeats and a reaper; retry with exponential backoff and full
   jitter, bounded by `max_attempts`                            (2.1)
✅ content-hash deduplication, and a re-attempt on a failed document as a new
   job rather than a new document                               (2.2)
✅ failure classification from the agent's status code; a permanent failure
   stops at attempt one; the dead-letter list and a replay endpoint (2.3)
○  structured logging · metrics · request_id across processes   (2.4)
○  auth · users / tenants                       (5.1 – 5.2)
○  quotas · rate limiting · caching              (6.x, 8.x, 9.x)
```

It says *"process document 123"* and decides whether the result means `done`,
`retry` or `failed`.

**The invariant worth naming**, because it is what 1.2 bought:

```text
API     INSERT documents + ingestion_jobs + document_uploads  →  COMMIT  →  202
                                                                  ↑
                                              everything after this line can
                                              crash; none of it can erase the
                                              fact that the upload happened

              ··· an arbitrary gap, possibly a restart ···

worker  claim (FOR UPDATE SKIP LOCKED)  →  COMMIT
        call the agent  →  record outcome  →  COMMIT
```

**The claim commits before the work starts**, separately from it. That is not
tidiness: if both were one transaction, a crash would roll the claim back and
the job would quietly return to `queued`. At 1.3 that mattered because it would
have destroyed 2.1's trigger by accident; now that the reaper exists it still
matters, because a rollback would hide the crash entirely — the job would look
as though it had never been attempted, and `attempts` would never grow. The
reaper requeuing an *expired* claim is the visible version of the same
recovery. It also releases the database connection for the duration of the
ingest, so a 45-second job does not hold a pool slot.

✅ Mutation-tested: removing that commit fails
`test_the_row_is_durable_before_the_agent_is_called`.

✅ **A dead worker's job comes back.** Every claim carries a `lease_token` and
an expiry; the worker renews it every `lease_seconds / 3` on its own session;
every worker reaps expired leases before it claims. Every write that finishes a
job carries the token, so a worker that was reaped affects **zero rows**
instead of overwriting whoever holds the job now.

The row 1.3 left stranded on purpose — `01a153cd-13ce-7786-995f-369c0c82377e`,
`processing` since 2026-10-19 — **recovered itself in 25 ms** the first time a
worker ran with a reaper, with no human action. That closed 2.1's trigger and
created 2.2's, because recovering it meant ingesting it twice.

✅ **Re-processing is safe.** Point ids are derived from
`(document_id, chunk_index)`, and an ingestion prunes every point of that
document which is not one it just wrote. Running a job once or five times
leaves the same index.

✅ **The client stops polling**, because jobs now reach terminal states.

✅ **Failures are classified, and the two kinds are treated oppositely.** The
agent's HTTP status decides it — 4xx permanent, 5xx and no-response transient,
with 429 carved out as the one 4xx that means *come back later*. A permanent
failure stops at attempt one; a transient one gets 15 attempts with any single
wait capped at 60 seconds. That covers a **median of ~5 minutes** of outage —
a median and not a promise: full jitter makes the realised budget vary, and
two measured runs gave up at 302.1s and 221.1s.

✅ **An operator can see and re-drive what died.** `GET /documents?status=failed`
is the dead-letter queue — a query, not a table — and
`POST /documents/{id}/retry` queues a fresh attempt without needing the original
file. The UI offers that retry only on a *transient* failure: a button on a file
that cannot be read would teach the user the system is flaky rather than that
their file is unreadable.

⚠ **All of it is still invisible from outside.** There is no metric for the
dead-letter depth, no alert when it grows, and **every `logger.info` in the
backend is still discarded** `[measured]` — uvicorn installs no root handler, so
`logging.lastResort` passes only WARNING and above. The dead-letter list is a
page someone has to remember to open. That is 2.4's trigger.

### `agent/` :8001 — the AI application layer

Not "agentic work" — most of what it does is not agentic at all. It is the AI
**service** layer.

```text
✅ LLM calls behind a provider seam (OpenRouter)
✅ embedding provider selection, validated at startup
✅ RAG orchestration: ingest and query endpoints
✅ one exception-to-status-code table for both error vocabularies
○  agent orchestration proper                   (no stage yet; no trigger)
```

It imports `rag` and returns results the backend can act on.

⚠ **No startup validation.** The agent has no `lifespan`, so a missing
`GOOGLE_API_KEY` surfaces as a 500 on someone's first upload rather than a
refusal to start. This was built once during 1.3 preparation and removed with
the fake provider, since it was part of the same out-of-sequence detour. Worth
rebuilding — it is about twenty lines and mirrors the backend's `SELECT 1` — but
it needs its own reason and its own stage rather than arriving sideways.

⚠ **Related, and worse:** uvicorn installs no root log handler, so
`logging.lastResort` passes only WARNING and above and **every `logger.info` in
this codebase is silently discarded** — the backend's own "database pool ready"
has never appeared in a log. A one-line `logging.basicConfig` fixes the floor;
real structured logging is Evolution Map 2.4.

### `rag/` — the engine, as a library

Not a service. Imported by the agent, and — from 3.1 — imported **directly** by
the evaluation harness, which is what keeps retrieval numbers honest, since no
chatbot sits in the measurement path.

```text
✅ extraction (pypdf, 1-based pages, refuses a PDF with no text layer)
✅ chunking (fixed size + overlap, never spanning a page boundary)
✅ embedding behind a seam (one provider: Gemini; a second arrives at 2.4)
✅ indexing and retrieval (Qdrant, embedded mode)
○  reranking · context assembly · grounding      (4.x, 17.x)
○  evaluation                                    (3.1)
```

Conversation-blind by construction: it receives a standalone question and an
access context, never message history.

✅ **Provenance is carried end to end** — `page` survives extraction → chunking
→ the Qdrant payload → the citation, and it is the one property that could not
have been retrofitted.

## The rule that summarises all of it

> **Backend owns reliability around AI work. Agent owns AI behaviour. RAG owns
> retrieval mechanics.**

---

## Data stores

| Store | Runs as | Holds | Status |
|---|---|---|---|
| **Postgres** | Compose service, named volume | documents, ingestion jobs, **and the uploaded bytes** | ✅ |
| **Qdrant** | **embedded** — a library writing to a folder inside the agent container, on a named volume | chunk vectors and their payloads, including the chunk text | ✅ |

### `document_uploads` — the bytes, in the database

New at 1.3, and the decision behind it is the one most easily got wrong.

A `202` means the request carrying the file is gone before the work starts, so
the bytes need a home that outlives it — written in the **same transaction** as
the job, or a crash between the two leaves a job whose input does not exist.

`bytea` in a separate table, not a column on `documents`: the list endpoint
loads `Document` entities with the ORM, and a blob column there is pulled into
memory by any query that forgets to defer it. One that forgets would pull 25 MB
per row to render a sidebar.

⚠ **Nothing deletes these rows**, so the database grows with the corpus rather
than with its metadata. Accepted deliberately, and 2.2 made the reason concrete:
re-ingesting a document is now the ordinary repair for a bad index, and a
re-ingest with no stored input is a re-upload. **Object storage is the fix**,
and its trigger is named — when the database size becomes a problem, or when
12.1 puts the backend and the worker on different machines.

✅ **The same bytes are stored once.** `documents.content_hash` is the SHA-256
of the upload, unique, so a second upload of a file already held creates no
document, no blob and no job — it answers `200` with the existing document.
Three rows predating stage 1.3 carry `NULL` and are permanently exempt, which
`docs/experiments/0002-…` explains.

**Embedded Qdrant means exactly one process may hold the storage folder.** That
is fine while the agent is the only writer — **including now that a worker
exists**, because the worker reaches the index through the agent over HTTP
rather than importing `rag`.

○ A Qdrant *server* (`QDRANT_URL`) is one config change away and arrives when a
second process genuinely needs the index. This file and the Compose comments
once said that happens at 1.3; **it did not** — 1.3 shipped with a worker and
embedded Qdrant survived, because the worker talks to the agent rather than to
the index. The trigger is 12.1, when a second *agent* instance appears.

⚠ There is a leftover second collection, `loadtest`, holding 3 vectors from a
fake embedding provider that **no longer exists in the code**. They are
labelled `fake-embedding` in their payload so they cannot be mistaken for real
ones, and nothing queries that collection — but they are now orphan garbage
rather than evidence, and deleting the collection is the right cleanup. Not done
unilaterally, because deleting data is not mine to decide.

### ⚠ Two stores, no transaction between them

This is the structural gap in the system as it stands, and 2.2 measured its
cost rather than fixing it.

`ON DELETE CASCADE` reaches jobs and uploads. It does **not** reach Qdrant, so
deleting a document leaves its vectors in place, searchable, attributable to
nothing. At the start of 2.2, **39 of 54 points (72%) belonged to documents
that no longer existed** — and a live query cited one of them, producing a
confident answer whose source returns 404.

✅ `tools/qdrant_orphans.py` reconciles the two stores and took that to **0**.
It reports five groups (`agreed`, `orphan`, `mismatch`, `missing`, `pending`)
and deletes only orphans; a mismatch is repaired by re-ingesting, which 2.2 made
safe.

⚠ **It is a cleanup, not a fix.** Nothing prevents the next orphan. The fix is
a transactional outbox (Module 14), and **`DELETE /documents/{id}` is
deliberately not built until it exists** — deleting a row and then its vectors,
with a crash in between, recreates exactly this.

It runs inside the agent image with the agent stopped, because embedded Qdrant
holds an exclusive lock, and it takes the live document list as a **file**
rather than a database connection, because the agent must not learn about
Postgres.

---

## Recovering the old system

The original streaming chat application — frontend, backend, agent, in-memory
history, no RAG — is tagged and pushed:

```bash
git checkout v0-chat-app
```

---

## Decided at 2.2

- **What identifies a document** — the SHA-256 of its bytes, not its filename.
  A re-upload under a different name returns the original document, with its
  original name, because the bytes are the identity.
- **What a duplicate upload does** — `200 OK` with the existing document and
  nothing queued; `202` only when work was actually enqueued. A duplicate of a
  document whose last attempt *failed* queues a new job on the same document:
  one document, many jobs, which is the first real payout on 1.2's two-table
  split.
- **How a re-ingest replaces a document** — upsert under derived ids, then
  prune every point of that document which is not one just written. Never
  delete first: that leaves a working document unsearchable, and permanently
  absent if embedding then fails.
- **`Idempotency-Key` headers are deferred.** For an upload, *the same request*
  **is** *the same bytes*. The trigger is the first endpoint whose identity is
  not derivable from its body.

## Decided at 2.1

- **How ownership of a job is proved** — a `lease_token` minted per claim and
  carried by every completing write, so a stale worker affects zero rows.
  Expiry alone is not enough: a re-claimed job has a *fresh* expiry, so an
  expiry check would pass for a worker that no longer owns it.
- **Where the reaper runs** — inside the worker loop, before each claim. No new
  process to deploy and watch.

## Decided at 1.3

Both of these were open questions in an earlier version of this file.

- **Where the ingestion worker lives** — `backend/` runs it, `python -m
  app.worker`, and it calls the agent over HTTP per document. Load-bearing for
  more than it looks: it keeps the agent the only process touching Qdrant,
  which is what let embedded mode survive the stage.
- **Where the uploaded bytes live** — Postgres `bytea`, in `document_uploads`,
  written in the same transaction as the job. Object storage when the size
  hurts or 12.1 splits the processes.

Both are still running on the host rather than in containers; that is 15.1.

---

## Not yet decided

- **Whether the agent ever needs its own datastore.** Currently no.
- **When to write the client's tests.** They are overdue, not undecided — see
  the frontend section. Two stages have now passed with the condition fired and
  nothing written, which makes this the oldest open debt in the project.
- **Whether `tools/check_dependencies.py` is worth keeping** if nothing runs it.
  It becomes genuinely useful the moment there is CI, and dead weight otherwise.
