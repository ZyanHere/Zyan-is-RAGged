# Current architecture

**What the system is *today*.** Not the destination — `../curriculum.md` has that.
Updated at the end of every module, so it is never aspirational.

**Stage:** pre-1.1. Skeleton only; nothing is built yet.
**Last updated:** 2026-09-25

---

## Layers and dependency direction

```text
frontend  :3000  ──HTTP──▶  backend  :8000  ──HTTP──▶  agent  :8001  ──import──▶  rag
```

The arrows only point one way. This is enforced by `tools/check_dependencies.py`,
which runs in CI and fails the build on a violation — an architecture rule that
lives only in a document gets broken within a month.

| Forbidden | Why |
|---|---|
| `backend` → `rag` | the backend must learn that a document was indexed from the agent's HTTP response, never by reaching into the engine |
| `backend` → `agent` (import) | they talk over HTTP; a direct import would couple deploys |
| `agent` → `backend` | the engine side never calls back up the stack |
| `rag` → anything above it | it is a library. This is what lets the eval harness import it with no chatbot in the loop |
| `frontend` → agent or rag | the backend is the only thing the browser talks to |

---

## What each layer owns

### `frontend/` :3000 — Next.js

Kept from v0, deliberately **not developed further**. It is a test harness for
seeing the system work, not a product surface. Talks to the backend only.

### `backend/` :8000 — the reliability layer

Owns everything that must be durable and correct. Knows nothing about prompts,
models or embeddings.

```text
auth · users / tenants · PostgreSQL · jobs · retries · leases · DLQ
quotas · rate limiting · caching · business logic · calls the agent
```

It says *"process document 123"* and decides whether the result means `done`,
`retry` or `failed`.

### `agent/` :8001 — the AI application layer

Not "agentic work" — most of what it does at first is not agentic at all. It is
the AI **service** layer:

```text
LLM calls · prompts · agent orchestration · RAG orchestration
```

It imports `rag`, and returns results the backend can act on:

```json
{ "document_id": "...", "chunks": 412, "pages": 300, "index_version": 3 }
```

### `rag/` — the engine, as a library

Not a service. Imported by the agent, and imported **directly** by the
evaluation harness — which is what keeps retrieval numbers honest, since no
chatbot sits in the measurement path.

```text
extraction · chunking · embedding · indexing · retrieval
reranking · context assembly · grounding · evaluation
```

Conversation-blind by construction: it receives a standalone question and an
access context, never message history.

---

## The rule that summarises all of it

> **Backend owns reliability around AI work. Agent owns AI behaviour. RAG owns
> retrieval mechanics.**

---

## Built so far

Nothing. `agent/app/providers/{base,openrouter}.py` is salvaged from v0 — the
provider seam, kept because it is genuinely good and because Module 2.4 needs a
fake embedder behind it.

Everything else is rebuilt stage by stage, starting at 1.1.

## Recovering the old system

The original streaming chat application — frontend, backend, agent, in-memory
history, no RAG — is tagged and pushed:

```bash
git checkout v0-chat-app
```

---

## Not yet decided

- **Where the ingestion worker lives.** Current plan: `backend/` runs it and
  calls the agent over HTTP per document. This deliberately leaves a future
  trigger in place — when a 2,000-page document times out that call, *that* is
  what earns progress-streaming or a shared queue.
- **Postgres schema.** Arrives at stage 1.2.
- **Whether the agent ever needs its own datastore.** Currently no.
