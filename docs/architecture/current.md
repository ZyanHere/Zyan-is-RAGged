# Current architecture

**What the system is *today*.** Not the destination — `../curriculum.md` has
that. Updated at the end of every stage, so it is never aspirational.

**Stage:** **1.3 complete. 2.1 not started.**
**Last updated:** 2026-10-21

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
| **2.1** Job lifecycle, leases and retries | ○ not started | its trigger is in the database — see *Deliberately left broken* |

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
○  retries · leases · DLQ                       (2.1 – 2.3)
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
the job would quietly return to `queued` — which is stage 2.1's job to do
deliberately, and doing it by accident here would have destroyed 2.1's trigger.
It also releases the database connection for the duration of the ingest, so a
45-second job does not hold a pool slot.

✅ Mutation-tested: removing that commit fails
`test_the_row_is_durable_before_the_agent_is_called`.

⚠ **Deliberately left broken:** a job whose worker dies stays `processing`
forever. Nothing retries it, reclaims it or notices — and since 1.3 there is no
request open either, so the only symptom is a row nobody is looking at.

**One such row exists**, created on purpose at the end of 1.3 by pausing the
agent, letting a worker claim the job, and killing the worker:

```text
document_id  01a153cd-13ce-7786-995f-369c0c82377e
job_id       01a153cd-13e3-733b-94ec-7588edc0366a
```

It is 2.1's trigger. The Evolution Map's rule is *leave it broken; make it
visible*.

⚠ **It also makes the client poll forever**, because `useDocuments` polls while
anything is non-terminal and this never becomes terminal. The UI is being
honest — something genuinely is unfinished — but one abandoned job now costs
perpetual background requests. A lease is what gives the client something true
to say instead.

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

⚠ **Nothing deletes these rows**, so the database now grows with the corpus
rather than with its metadata. Accepted deliberately: stage 2.2 re-indexes
documents, and a re-index with no stored input is a re-upload. **Object storage
is the fix**, and its trigger is named — when the database size becomes a
problem, or when 12.1 puts the backend and the worker on different machines.

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

---

## Recovering the old system

The original streaming chat application — frontend, backend, agent, in-memory
history, no RAG — is tagged and pushed:

```bash
git checkout v0-chat-app
```

---

## Decided at 1.3

Both of these were open questions in the previous version of this file.

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
  the frontend section. What is open is whether to do them before 2.1 or
  alongside it.
- **Whether `tools/check_dependencies.py` is worth keeping** if nothing runs it.
  It becomes genuinely useful the moment there is CI, and dead weight otherwise.
