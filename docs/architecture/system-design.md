# myRAG — Product System Design (Step 1)

**Scope:** the application only — frontend, backend, agent/AI. The API/SDK platform (Step 2 of the product bible) is deliberately out of scope here.

**Status:** design. Nothing below is a commitment to build now — Section 10 turns it into an ordered build plan.

**How to read this**

This document is a *map of the whole territory*, not a to-do list. Sections 1–9 describe the finished system so that every concept you will meet while learning (memory, checkpoints, HITL, reranking, guardrails, evals…) already has a named home. Section 10 says what to actually build, in what order, and what "done" means at each step.

Two conventions used throughout:

- **Ladder tables** — `v1` is what we build first; later rungs are added *only* when the benchmark shows a gap (product bible central rule). A rung listed here is not a promise to build it; it is a promise that we know where it would go.
- **Failure modes** — each subsystem lists how it breaks. These map to the failure taxonomy in Section 9, which is what turns a bad answer into a specific fix.

---

## Table of contents

1. [Service topology & responsibility boundaries](#1-service-topology--responsibility-boundaries)
2. [Data stores — who owns what](#2-data-stores--who-owns-what)
3. [End-to-end data flows](#3-end-to-end-data-flows)
4. [Service contracts](#4-service-contracts)
5. [Frontend design](#5-frontend-design)
6. [Backend design](#6-backend-design)
7. [Agent service design](#7-agent-service-design)
8. [RAG engine design](#8-rag-engine-design)
9. [Cross-cutting concerns & the failure catalogue](#9-cross-cutting-concerns--the-failure-catalogue)
10. [Build order — milestones](#10-build-order--milestones)

---

## 1. Service topology & responsibility boundaries

Three services, three processes, three ports.

```text
┌──────────────────┐     HTTP/SSE      ┌──────────────────┐    HTTP/SSE     ┌──────────────────┐
│    FRONTEND      │ ────────────────▶ │     BACKEND      │ ──────────────▶ │      AGENT       │
│  Next.js :3000   │ ◀──────────────── │  FastAPI :8000   │ ◀────────────── │  FastAPI :8001   │
│                  │                   │                  │                 │  + LangGraph     │
│  UI, UX, client  │                   │  identity, data, │                 │  + RAG engine    │
│  state, streams  │                   │  orchestration   │                 │  + workers       │
└──────────────────┘                   └──────────────────┘                 └──────────────────┘
                                              │                                      │
                                              ▼                                      ▼
                                    Postgres · Object store               Vector DB · Redis
                                    Redis (queue, cache)                  (checkpoints, memory)
```

### 1.1 The one rule

> **The frontend never talks to the agent. The backend never talks to an LLM.**

Every hop goes through the backend. This is layered access (option A), and it is what makes auth, rate limiting, quotas, and audit possible later — they all live in exactly one place.

### 1.2 Responsibility table

| Concern | Frontend | Backend | Agent |
|---|:--:|:--:|:--:|
| UI, rendering, client state | ✅ | ❌ | ❌ |
| Identity, sessions, auth | ❌ | ✅ | ❌ |
| Conversation & message persistence | ❌ | ✅ | ❌ |
| Document records, upload, object storage | ❌ | ✅ | ❌ |
| Access control decisions (who may see what) | ❌ | ✅ | ❌ |
| Access control *enforcement* at retrieval | ❌ | ❌ | ✅ |
| Job creation / status tracking | ❌ | ✅ | ❌ |
| Job execution (parse → chunk → embed → index) | ❌ | ❌ | ✅ |
| Prompting, LLM calls, model config, API keys | ❌ | ❌ | ✅ |
| Retrieval, reranking, context assembly | ❌ | ❌ | ✅ |
| Grounding, citations, abstention | ❌ | ❌ | ✅ |
| Agent memory & checkpoints | ❌ | ❌ | ✅ |
| Guardrails (prompt injection, output safety) | ❌ | partial¹ | ✅ |
| Rate limiting, quotas | ❌ | ✅ | ❌ |
| Evals / benchmark harness | ❌ | ❌ | ✅ |

¹ The backend does *transport-level* protection (payload size, request rate, file type). *Semantic* protection (injection, grounding, output safety) is the agent's job.

### 1.3 Why the agent is a separate service

Not ceremony — four concrete reasons:

1. **Different runtime shape.** Chat is latency-sensitive and streaming. Ingestion is minutes-long batch work. They need different concurrency models and scaling behaviour.
2. **Different dependency tree.** The agent pulls in LangChain/LangGraph, Docling, torch, embedding models — heavy, slow-installing, frequently-upgraded. The backend stays light.
3. **Secret isolation.** Model API keys exist in exactly one process. The backend can be compromised without leaking them.
4. **Replaceability.** The agent is the part we will rewrite most. A hard HTTP boundary means rewriting it never touches the backend.

---

## 2. Data stores — who owns what

| Store | Purpose | Owner | Dev choice | Prod option |
|---|---|---|---|---|
| **Postgres** | Users, conversations, messages, documents, jobs, audit | Backend | Docker Postgres | Managed PG (Neon/RDS/Supabase) |
| **Object storage** | Raw uploaded files, extracted assets (page images) | Backend (writes), Agent (reads) | MinIO in Docker | S3 / R2 |
| **Vector DB** | Chunks + embeddings + chunk metadata | Agent | **Qdrant** (Docker) | Qdrant Cloud / Pinecone |
| **Redis** | Job queue, cache, rate limits, LangGraph checkpoints, short-term memory | Shared, namespaced | Docker Redis | Managed Redis |

### 2.1 Store rules

- **One writer per table.** Postgres is written only by the backend. The vector DB is written only by the agent. Cross-service reads happen over HTTP, not by reaching into someone else's database.
- **Redis is shared but namespaced:** `q:*` (queues), `cache:*`, `rl:*` (rate limits), `ckpt:*` (checkpoints), `mem:*` (memory). Never a bare key.
- **Object storage is the only place raw bytes live.** Postgres stores a *pointer* (bucket + key + checksum), never the file.

### 2.2 Vector DB choice — Qdrant vs Pinecone

Both are correct answers; they optimise for different things.

| | Qdrant (recommended for Step 1) | Pinecone |
|---|---|---|
| Cost while iterating | Free, local Docker | Free tier, then per-index cost |
| Reindex speed (you will reindex *constantly* while benchmarking) | Fast, local disk | Network round-trips |
| Metadata filtering (needed for ACL + versioning) | Rich, first-class | Good |
| Hybrid (dense + sparse/BM25) in one engine | Native | Requires extra setup |
| Ops burden | You run it | Managed |

**Decision:** Qdrant locally, behind a `VectorStore` interface (Section 8.6) so Pinecone is a config swap, not a rewrite. The product bible already names Qdrant.

### 2.3 Core relational schema (backend-owned)

Shaped now so multi-tenancy later is a filter, not a migration (product bible §10.1).

```text
tenants        (id, name, created_at)
users          (id, tenant_id, email, role, created_at)

documents      (id, tenant_id, owner_id, filename, mime_type, size_bytes,
                checksum_sha256, storage_key, page_count,
                status, error_code, error_message,
                version_id, is_active, superseded_by,
                created_at, processed_at)

conversations  (id, tenant_id, owner_id, title, created_at, updated_at,
                archived_at)

messages       (id, conversation_id, role, content,
                citations_json, usage_json, latency_ms,
                stop_reason, created_at)

jobs           (id, tenant_id, document_id, type, status, attempts,
                idempotency_key, last_error, created_at, updated_at)

audit_log      (id, tenant_id, actor_id, action, target_type, target_id,
                metadata_json, created_at)
```

Notes that matter later:

- `checksum_sha256` gives free deduplication and idempotent re-upload.
- `version_id` / `is_active` / `superseded_by` implement versioning by *deactivation*, never deletion — retrieval filters to active by default.
- `citations_json` on messages means a rendered answer stays reproducible even if the document is later re-indexed.
- `tenant_id` on every row from day one, even single-tenant.

---

## 3. End-to-end data flows

Three flows carry the whole product. Everything else is a variation.

### 3.1 Flow A — Chat (the read path)

The latency-critical path. Target: first token visible fast, full answer streamed.

```text
 USER types → presses Enter
   │
   ├─ FRONTEND
   │    1. validate non-empty, not already streaming
   │    2. optimistic: append user message to UI immediately
   │    3. POST /api/conversations/{id}/messages  (Accept: text/event-stream)
   │       abortable via AbortController (powers the Stop button)
   │
   ├─ BACKEND
   │    4. authn/authz: who is this, do they own this conversation
   │    5. rate limit check (Redis)
   │    6. persist the user message (Postgres)   ← durable before any model call
   │    7. load recent history + access context
   │    8. POST agent /chat/stream {messages, access_context, conversation_id}
   │    9. proxy the SSE stream through, unbuffered
   │   10. accumulate the full reply as it passes
   │   11. on stream end: persist assistant message + citations + usage
   │       on client disconnect: persist the partial, mark it interrupted
   │
   ├─ AGENT  (LangGraph run — Section 7.3)
   │   12. load checkpoint / short-term memory for this thread
   │   13. INPUT GUARDRAILS (injection scan, PII, size)
   │   14. ROUTE: does this need retrieval? (chit-chat and follow-ups may not)
   │   15. if yes → RAG ENGINE:
   │            query transform → retrieve → rerank → assemble context
   │   16. EVIDENCE SUFFICIENCY gate → if weak, take the abstain branch
   │   17. GENERATE with evidence, streaming tokens out as they arrive
   │   18. OUTPUT GUARDRAILS: citation verification, grounding check
   │   19. emit citations event, usage event, done event
   │   20. write checkpoint + any long-term memory
   │
   └─ FRONTEND
       21. render tokens as they arrive (streaming bubble)
       22. on citations event → render source cards
       23. on done → finalise message, re-enable input
       24. on error → inline error with Retry
```

**Key property:** steps 6 and 11 make the conversation durable independent of the stream. A dropped connection loses the stream, never the history.

### 3.2 Flow B — Ingestion (the write path)

Async by construction. A 2,000-page PDF takes minutes; nothing may block an HTTP request on it.

```text
 USER drops a file
   │
   ├─ FRONTEND
   │    1. client-side validate: type, size, count
   │    2. POST /api/documents (multipart)  with upload progress
   │    3. receive {document_id, status: "queued"} immediately
   │    4. subscribe to status (poll or SSE) — show a per-file progress row
   │
   ├─ BACKEND
   │    5. authn/authz + quota check
   │    6. stream bytes to object storage (never buffer whole file in RAM)
   │    7. compute checksum → if identical doc exists for tenant, short-circuit (dedupe)
   │    8. INSERT documents row (status=queued)
   │    9. enqueue job on Redis with idempotency_key = checksum+tenant
   │   10. return 202 Accepted
   │
   ├─ AGENT WORKER  (separate process from the agent API)
   │   11. claim job (visibility timeout so a crash re-queues it)
   │   12. callback: status=processing
   │   13. RAG INGESTION PIPELINE (Section 8):
   │         extract → normalise to canonical document model → chunk
   │         → embed → upsert into vector DB (tenant/ACL/version in metadata)
   │   14. emit progress callbacks (pages done / total) for the UI
   │   15. on success → callback status=ready, page_count, chunk_count
   │       on failure → classify error, retry with backoff,
   │                    after N attempts → dead-letter + status=error
   │
   └─ BACKEND
       16. apply callbacks to Postgres; frontend's next poll sees the change
```

**Why a worker and not a direct HTTP call:** a 10-minute HTTP request is a broken design — it dies to proxy timeouts, cannot resume, and cannot report progress. The queue also gives retries, backpressure, and crash recovery for free.

### 3.3 Flow C — Status & lifecycle

```text
Poll:    GET /api/documents?status=processing   every 2s while any doc is in flight,
         backing off to 10s, stopping entirely when none are.
         (Upgrade path: SSE at /api/documents/events — same data, no polling.)

Delete:  DELETE /api/documents/{id}
         → backend marks deleted → enqueues purge job
         → agent worker deletes chunks from the vector DB
         → backend deletes the object and the row
         Deleting a document MUST delete its derived vectors. A "deleted"
         document whose chunks still answer questions is a data-leak bug.

Reindex: new version → old chunks is_active=false (not deleted)
         → new chunks written → retrieval filters to active by default
```

---

## 4. Service contracts

The interfaces between services. These are the things that must stay stable; everything behind them is free to change.

### 4.1 Frontend ⇄ Backend (public API)

| Method | Path | Purpose | Milestone |
|---|---|---|---|
| `GET` | `/health` | liveness | M0 ✅ |
| `POST` | `/api/conversations` | create conversation | M1 |
| `GET` | `/api/conversations` | list (paginated) | M1 |
| `GET` | `/api/conversations/{id}` | detail + messages | M1 |
| `PATCH` | `/api/conversations/{id}` | rename / archive | M1 |
| `DELETE` | `/api/conversations/{id}` | delete | M1 |
| `POST` | `/api/conversations/{id}/messages` | **send message → SSE stream** | M1 |
| `POST` | `/api/documents` | upload (multipart) | M2 |
| `GET` | `/api/documents` | list + filter + paginate | M2 |
| `GET` | `/api/documents/{id}` | detail + status | M2 |
| `DELETE` | `/api/documents/{id}` | delete + purge vectors | M2 |
| `GET` | `/api/documents/{id}/content` | signed URL for source preview | M4 |
| `POST` | `/api/messages/{id}/feedback` | 👍/👎 + reason (eval signal) | M5 |
| `GET` | `/api/me` | user, quotas, limits | M6 |

### 4.2 Backend ⇄ Agent (internal API)

Never exposed to the browser. Authenticated with a shared internal token.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat/stream` | conversation + access context → SSE token stream |
| `POST` | `/ingest` | (worker-invoked) run ingestion for a document |
| `POST` | `/purge` | delete all vectors for a document |
| `POST` | `/retrieve` | retrieval only, no generation (debug + eval harness) |
| `GET` | `/health` | liveness + model reachability |

### 4.3 The SSE event protocol

One protocol, used agent→backend and backend→frontend unchanged. Named events, JSON payloads.

```text
event: start        data: {"message_id": "...", "model": "..."}
event: status       data: {"stage": "retrieving"}        # UI: "Searching documents…"
event: status       data: {"stage": "reranking"}
event: status       data: {"stage": "generating"}
event: token        data: {"text": "The "}               # the hot path
event: citations    data: {"citations": [ ... ]}         # once, before done
event: usage        data: {"input_tokens": N, "output_tokens": N, "cost_usd": 0.0}
event: done         data: {"stop_reason": "end_turn"}
event: error        data: {"code": "AGENT_TIMEOUT", "message": "...", "retryable": true}
```

Design notes:

- **`status` events are a UX feature, not debug output.** RAG has a multi-second gap before the first token; showing "Searching your documents…" is the difference between "thinking" and "broken".
- **Citations arrive as one event before `done`**, not per-token — they are only known once generation completes verification.
- **`error` can arrive mid-stream** after tokens have already rendered. The frontend must handle a partial answer plus an error, not assume error means nothing rendered.
- **Heartbeat comment (`: ping`) every 15s** so proxies don't kill an idle stream during a long retrieval.

### 4.4 The access context

Passed backend → agent on every request. The backend is the *authority* on identity; the agent is the *enforcer* at retrieval time.

```json
{
  "tenant_id": "t_123",
  "user_id": "u_456",
  "allowed_document_ids": null,
  "roles": ["owner"],
  "include_inactive_versions": false
}
```

`allowed_document_ids: null` means "all documents in the tenant". The agent converts this into a hard metadata filter on every vector query. **Never a prompt instruction** — filtering must be structural, because a prompt can be argued with and a filter cannot.

### 4.5 Error contract

Every backend error, one shape:

```json
{ "error": { "code": "RATE_LIMITED", "message": "human readable",
             "retryable": true, "retry_after_s": 30, "request_id": "req_..." } }
```

`code` is a stable machine string the frontend switches on. `message` is for humans. `request_id` correlates across all three services in logs.

---

## 5. Frontend design

**Stack:** Next.js 16 (App Router) · React 19 · TypeScript · Tailwind v4.

### 5.1 State architecture — three distinct layers

The single most important frontend decision, and the reason "just add Redux" is the wrong instinct here: **most of this app's state is server state**, which needs caching, revalidation, and polling — not a reducer.

| Layer | What lives here | Tool | Why |
|---|---|---|---|
| **Server state** | conversations, messages, documents, upload status, user | **TanStack Query** | caching, dedup, retries, background refetch, `refetchInterval` for ingestion polling, optimistic updates + rollback |
| **Client state** | sidebar open, active conversation id, theme, filters, composer draft | **Zustand** | tiny, no boilerplate, no provider pyramid |
| **Stream state** | in-flight assistant message, token buffer, abort controller | **local `useReducer` in one hook** | lives and dies with a single request; putting it in a global store causes re-render storms at 60 tokens/sec |

Rules:
- Server data is **never** copied into Zustand. One source of truth per datum.
- The streaming buffer is **never** in a global store. Token-rate updates must touch one component subtree.
- Query keys are structured and centralised: `['conversations']`, `['conversation', id]`, `['documents', {status, page}]` — so invalidation is precise.

*(Redux Toolkit + RTK Query remains a valid alternative — the layer split above is the part that matters; the libraries are swappable.)*

### 5.2 Route & component structure

```text
src/
├── app/
│   ├── layout.tsx                 providers, fonts, theme, error boundary
│   ├── page.tsx                   redirect → /chat
│   ├── chat/
│   │   ├── layout.tsx             sidebar + main shell
│   │   ├── page.tsx               new conversation
│   │   └── [conversationId]/page.tsx
│   ├── documents/page.tsx         document library
│   ├── error.tsx                  route error boundary
│   ├── not-found.tsx
│   └── global-error.tsx           last-resort boundary
├── components/
│   ├── chat/                      ChatWindow, MessageList, MessageBubble,
│   │                              StreamingMessage, CitationCard, SourcePanel,
│   │                              ChatInput, MessageActions, EmptyState
│   ├── documents/                 UploadZone, UploadQueue, DocumentTable,
│   │                              DocumentRow, StatusBadge, DeleteDialog
│   ├── layout/                    Sidebar, ConversationList, TopBar, MobileNav
│   └── ui/                        Button, Dialog, Toast, Skeleton, Tooltip,
│                                  Badge, Spinner, VirtualList
├── hooks/                         useChatStream, useConversations, useDocuments,
│                                  useUpload, useAutoScroll, useHotkeys
├── lib/                           api client, sse parser, query client,
│                                  env validation, formatters, errors
├── stores/                        ui.store.ts, composer.store.ts
└── types/                         shared domain types (mirror backend schemas)
```

### 5.3 Streaming — the hard part of the UI

Consuming SSE correctly is where chat UIs usually break.

**Mechanics**
- Use `fetch` + `ReadableStream` (not `EventSource` — it can't POST or set auth headers).
- Parse SSE incrementally with a buffer. **Chunks split mid-event**; a naive `split('\n\n')` per chunk drops data. Keep a carry-over buffer across reads.
- Batch token appends with `requestAnimationFrame`. Calling `setState` per token at 60 tok/s causes visible jank; coalescing to ~16ms frames does not.
- Hold an `AbortController` per stream — that's the Stop button, and it must also fire on unmount and on navigation.

**Required UX states**

| State | UI |
|---|---|
| Submitted, nothing back yet | user bubble + animated dots |
| `status: retrieving` | "Searching your documents…" with a subtle spinner |
| Tokens arriving | live text + blinking cursor + **Stop** button |
| Stopped by user | keep partial text, mark "stopped", offer Regenerate |
| Citations arrived | source cards fade in under the message |
| Done | cursor removed, actions enabled (copy, regenerate, feedback) |
| Error after partial | keep the partial text, inline error card, **Retry** |
| Network dropped mid-stream | detect stall (no event > 30s), offer Retry; never hang forever |

**Auto-scroll rule:** stick to the bottom *only while the user is already at the bottom*. If they scroll up to read, do not yank them back — show a "↓ New messages" pill instead. This is the single most-complained-about behaviour in chat UIs.

### 5.4 File management — complete specification

**Upload**
- Accept: drag-drop, click-to-browse, paste. Multi-file.
- Client-side gate before any request: extension + MIME allowlist, per-file size cap (e.g. 50 MB), per-batch count cap (e.g. 10), total-quota check from `/api/me`.
- Show a **per-file row** with its own progress bar and its own error — one bad file must not fail the batch.
- Real upload progress needs `XMLHttpRequest.upload.onprogress` (`fetch` has no upload progress). Wrap it once in the api client.
- Client-side checksum (Web Crypto SHA-256) lets us warn "already uploaded" before spending bandwidth.
- Cancel per file, retry per file.

**Status lifecycle (visible to the user)**
```text
queued → uploading → processing → ready
                        └────────→ error (with reason + Retry)
```
`processing` should show real substeps when the backend reports them: *extracting → chunking → embedding → indexing*, with page counts on long documents. A 2,000-page PDF sitting on "processing" with no detail feels broken; the same wait with "embedding — page 840/2000" feels fine.

**Listing — "how many to show"**
- Sidebar/compact: **5 most recent**, with a "View all" link. Never an unbounded list in a nav rail.
- Documents page: **server-side pagination, 25 per page**, with search + filter (status, type, date) + sort.
- Virtualise (`@tanstack/react-virtual`) any list that can exceed ~100 rows. At 10 M documents the client must never receive an unpaginated list — that constraint is designed in from the first version, not retrofitted.
- Poll only while something is `processing`, and stop polling when the tab is hidden (`visibilitychange`).

**Delete**
- Confirmation dialog naming the file; explain that answers will no longer cite it.
- Optimistic removal with rollback on failure.
- Warn if the document is referenced by citations in existing conversations.

### 5.5 Chat surface

- **Markdown rendering** with `react-markdown` + `remark-gfm`. **Sanitise** (`rehype-sanitize`) — model output is untrusted; unsanitised HTML is a direct XSS path.
- **Code blocks**: syntax highlighting, language label, copy button. Highlighting must be lazy-loaded — it is heavy and most messages have no code.
- **Streaming markdown caveat:** partial markdown is frequently invalid mid-stream (an unclosed ``` fence). Render the streaming text as plain text (or a fence-tolerant renderer) and switch to full markdown on `done`, otherwise the layout flickers violently.
- **Citations**: numbered inline markers `[1]`, hovering highlights the corresponding source card; clicking opens the **source panel** showing the excerpt, document name, page, and a "view in document" link.
- **Message actions**: copy, regenerate, 👍/👎 feedback (feeds evals), and "show retrieved context" in dev mode — that last one is your debugging lifeline.
- **Virtualise** long conversations; a 500-message thread must not mount 500 markdown trees.

### 5.6 Composer (input)

Auto-resizing textarea (cap ~200px) · Enter sends, Shift+Enter newline (inverted on mobile) · disabled while streaming with Stop offered instead · draft persisted per conversation in Zustand + `localStorage` so a refresh doesn't lose typing · character/token counter near the limit · attach button shared with the upload flow · `/` command palette hook (future) · paste-image support (future, multimodal).

### 5.7 Error handling — the full taxonomy

Every failure needs a *decided* UX. Undecided cases are what make an app feel unfinished.

| Failure | Detection | UX | Recovery |
|---|---|---|---|
| Backend unreachable | fetch rejects | full-width banner "Can't reach server" | auto-retry w/ backoff + manual |
| Agent down (502 from backend) | `code: AGENT_UNAVAILABLE` | inline "AI service unavailable" | Retry |
| Auth expired (401) | interceptor | redirect to login, preserve draft | re-auth |
| Forbidden (403) | interceptor | "You don't have access" | — |
| Rate limited (429) | `retry_after_s` | countdown on the send button | auto-enable at zero |
| Validation (422) | field errors | inline under the field | fix + resubmit |
| Payload too large (413) | pre-checked client-side too | per-file error row | remove/replace file |
| Stream stalls | no event > 30s | "Connection stalled" + Retry | abort + retry |
| Stream errors mid-answer | `event: error` | keep partial + error card | Regenerate |
| Model refusal | `stop_reason: refusal` | neutral explanation, not a crash | rephrase |
| **Abstention** (no evidence) | normal answer, `citations: []`, flag | *not an error* — a first-class "I don't have evidence for that" card, suggesting an upload | upload doc |
| Ingestion failed | doc `status: error` | row shows reason (corrupt / unsupported / OCR failed) | Retry / Remove |
| Quota exceeded | `code: QUOTA_EXCEEDED` | upgrade/cleanup prompt | delete docs |
| Unexpected render crash | error boundary | route-level fallback, rest of app alive | reload section |

**Global rules:** every mutation surfaces a toast on failure; every retryable error offers exactly one obvious retry affordance; no `catch {}` that silently swallows; every error carries `request_id` and shows it in a dev-visible detail so a user report is traceable.

### 5.8 Performance, accessibility, quality

**Performance** — Server Components for static shell, Client Components only where interactive · route-level code splitting · lazy-load markdown/highlighting/virtualisation · memoise message bubbles (`React.memo`) so a streaming message doesn't re-render history · `next/font` to avoid layout shift · budget: LCP < 2.5s, INP < 200ms.

**Accessibility** — keyboard-navigable everywhere · visible focus rings · `aria-live="polite"` on the streaming region so screen readers announce the answer · labelled inputs and buttons · dialogs trap focus and restore it · respect `prefers-reduced-motion` · WCAG AA contrast in both themes.

**Theming** — light/dark/system via `data-theme` + CSS custom properties, no flash-of-wrong-theme (inline script before paint).

**Observability** — error boundary reports to Sentry (or console in dev) · log `request_id` on every failure · Web Vitals reporting · a dev-only debug panel showing retrieved chunks, scores, timings, and token usage.

**Testing** — Vitest + Testing Library for hooks/components (SSE parser and `useChatStream` deserve real unit tests, including split-chunk cases) · MSW to mock the API deterministically · Playwright for the two critical journeys: *upload → processed → ask → cited answer* and *send → stream → stop → regenerate*.

**Security** — no secrets in `NEXT_PUBLIC_*` · sanitise all rendered model output · validate env at boot (fail fast on a missing API base URL) · no `dangerouslySetInnerHTML` on model text, ever.

---

## 6. Backend design

**Stack:** FastAPI · SQLAlchemy 2 + Alembic · Pydantic v2 · Redis · httpx.

Today the backend is a pass-through. That is fine — but the *structure* below is what it grows into, and each piece has a milestone.

### 6.1 What the backend is

> The **control plane**. It owns identity, durability, and access decisions. It knows *nothing* about prompts, models, or embeddings.

Litmus test: if a change requires touching a prompt, it does not belong in the backend. If it requires touching a database table, it does not belong in the agent.

### 6.2 Structure

```text
backend/app/
├── main.py                 app factory, middleware, exception handlers
├── core/                   config, security, logging, dependencies
├── api/routes/             health, conversations, messages, documents, feedback, me
├── api/internal/           callbacks from the agent worker (job status)
├── schemas/                Pydantic request/response models
├── models/                 SQLAlchemy ORM models
├── repositories/           DB access (no SQL in route handlers)
├── services/
│   ├── agent_client.py     HTTP+SSE client for the agent  ← the only outbound AI path
│   ├── conversation_service.py
│   ├── document_service.py
│   ├── storage.py          object storage (S3/MinIO)
│   └── queue.py            job enqueue
├── middleware/             request id, logging, rate limit, CORS, timing
└── migrations/             Alembic
```

Layering: **route → service → repository → DB.** Routes do validation and HTTP concerns only.

### 6.3 Streaming proxy

The subtle part of the backend. Requirements:

1. **Do not buffer.** Stream chunks through as they arrive; buffering defeats the entire point.
2. **Accumulate while proxying** so the complete answer can be persisted at the end.
3. **Detect client disconnect** and still persist what was generated (mark it interrupted) — the tokens were paid for.
4. **Propagate cancellation**: client aborts → backend aborts its request to the agent → agent stops generating. Without this, a user pressing Stop keeps costing money.
5. **Timeouts**: generous (streams are long) but finite; emit a proper `error` event rather than dying silently.

### 6.4 Idempotency, races, and concurrency

The "advanced backend concepts" bucket — designed now, implemented at M6.

| Hazard | Mitigation |
|---|---|
| Double-submit (double-click, retry) | `Idempotency-Key` header; cache the response keyed on it (Redis, 24h) |
| Duplicate uploads | `checksum_sha256` unique per tenant → return the existing document |
| Two workers claim one job | atomic claim (`SELECT … FOR UPDATE SKIP LOCKED`, or Redis visibility timeout) |
| Concurrent messages in one conversation | per-conversation advisory lock; second request queues or 409s |
| Lost update on rename | optimistic concurrency via `updated_at` / version column |
| Delete during ingestion | job checks a cancellation flag between stages; purge runs after |
| Orphaned vectors after failed delete | reconciliation job sweeps vectors with no live document |
| Thundering-herd polling | jittered intervals + `ETag`/`If-None-Match` on list endpoints |
| Runaway cost | per-tenant token budget checked *before* dispatching to the agent |

### 6.5 Auth, rate limiting, quotas (M6)

- **Auth:** session cookie (httpOnly, SameSite=Lax) for the browser; internal shared-secret header for backend→agent. Structure the code as a `current_user` dependency from day one — then adding real auth is swapping the dependency, not rewriting routes.
- **Rate limiting:** Redis sliding window, per user and per tenant, different budgets per route class (chat vs upload vs read). Always return `Retry-After`.
- **Quotas:** documents, storage bytes, monthly tokens. Enforced *before* the expensive operation, surfaced via `/api/me` so the UI can warn early.

### 6.6 Observability & testing

Structured JSON logs with `request_id` on every line · OpenTelemetry traces spanning frontend → backend → agent → model (one trace id answers "where did the 8 seconds go?") · metrics: request rate/latency/error by route, queue depth, job duration, tokens and cost per tenant · `/health` (liveness) and `/ready` (DB + Redis + agent reachable).

Testing: pytest + httpx `AsyncClient` · a test Postgres per run · the agent mocked at the HTTP boundary (including SSE) · contract tests asserting response shapes match what the frontend types expect.

---

## 7. Agent service design

**Stack:** FastAPI · LangChain (model/vector abstractions) · Redis · Qdrant · the RAG engine (Section 8). LangGraph enters later, and only on evidence — see §7.4.

### 7.1 The internal split: RAG engine vs chat orchestrator

**RAG is a subsystem of the chatbot, not the whole of it — and the chatbot's concerns must not leak into it.** Memory, routing, chit-chat, clarification, and human-in-the-loop are *conversation* concerns. They live outside the RAG engine, which stays independently usable.

```text
agent/app/
├── rag_engine/          ← STATELESS. Documents in, grounded answers out.
│   │                      Knows nothing about conversations, users, or turns.
│   ├── api.py              THE interface (§7.2) — the only entry point
│   ├── ingestion/          job orchestration for the write path
│   ├── extraction/         bytes → structure
│   ├── document_model/     the canonical form
│   ├── chunking/
│   ├── embeddings/
│   ├── indexing/
│   ├── retrieval/
│   ├── reranking/
│   ├── context/            assemble the evidence into a prompt
│   ├── generation/         evidence → answer (single-turn)
│   ├── grounding/          sufficiency, citations, verification, abstention
│   └── safety/             CONTENT-level: untrusted delimiting, ACL filters
│
├── chat_orchestrator/   ← STATEFUL. Owns the conversation.
│   ├── pipeline.py         M1–M3: a plain function. No graph.
│   ├── question_resolution/  coreference → standalone question
│   ├── routing/            chit-chat vs retrieval vs clarify vs refuse
│   ├── memory/             short_term, long_term, summarizer, store
│   ├── hitl/               interrupt points, approval protocol
│   ├── tools/              non-retrieval tools
│   └── graph/              LangGraph — added only when §7.4's gate opens
│
├── shared/              providers (OpenRouter/Anthropic), config, tracing
├── workers/             ingestion worker, purge worker
└── evaluation/          two suites: rag_engine and orchestrator, measured separately
```

The payoff is not tidiness. It is that **Step 2's `/query` and `/retrieve` endpoints are exactly `rag_engine.api`** — a RAG engine entangled with chat orchestration cannot be exposed as a platform API without a rewrite.

### 7.2 The interface — and the rule that enforces it

```python
rag_engine.retrieve(question: str, access: AccessContext, opts) -> list[Evidence]
rag_engine.answer(question: str, access: AccessContext, opts)   -> GroundedAnswer
```

`GroundedAnswer` = `{text, citations[], evidence[], sufficiency, usage, trace}`.

> **The rule: the RAG engine never sees conversation history.**
>
> It receives a *standalone question* and an access context. Nothing else. No message list, no user profile, no memory, no thread id.

This one rule resolves every ambiguous case cleanly:

| Concern | Home | Why |
|---|---|---|
| "What about 2024?" → resolve against prior turns | **Orchestrator** | needs conversation |
| Rewriting / expanding / HyDE on a standalone question | **RAG engine** | doesn't need conversation |
| Deciding this message needs no retrieval at all | **Orchestrator** | a conversation judgement |
| Deciding the retrieved evidence is insufficient | **RAG engine** | a property of the evidence |
| Asking the user a clarifying question | **Orchestrator** | a turn-taking act |
| Abstaining because evidence is weak | **RAG engine** | returned as a `GroundedAnswer` with `sufficiency: insufficient` |
| Remembering the user prefers short answers | **Orchestrator** | conversation state |

If the orchestrator ever wants to pass message history *into* the engine, that is the signal the boundary is being violated — resolve the question first instead.

**Testable consequence:** the RAG engine can be exercised end to end by the benchmark with no chatbot present at all. That is what keeps Section 8 measurable independently of Section 7.

### 7.3 Provider abstraction — OpenRouter first, paid later

Starting on OpenRouter's free tier and switching later is a *design constraint*, not an afterthought.

```text
providers/base.py
    get_chat_model(purpose)  → LangChain BaseChatModel
    get_embedding_model()    → LangChain Embeddings
```

- `purpose` lets different jobs use different models: `chat` (best), `rerank`/`classify` (cheap+fast), `judge` (strong, eval-only), `summarize` (cheap).
- OpenRouter is OpenAI-compatible → `ChatOpenAI(base_url="https://openrouter.ai/api/v1", model="...")`. Switching to first-party Anthropic later is a config change plus one adapter file.
- **Free-tier realities to design around:** aggressive rate limits (need a retry/backoff wrapper and a request queue), no prompt caching, weaker structured-output reliability (validate and repair JSON rather than trusting it), variable latency, and model availability that changes. Therefore: **never call a provider SDK directly from graph nodes** — always through `providers/`, so all of this is handled in one place.
- **Embeddings are the sticky choice.** Changing an embedding model invalidates every stored vector and forces a full reindex. Pick one deliberately, record it in the vector metadata, and treat a change as a migration.

### 7.4 The orchestrator — a function first, a graph only when earned

**M1–M3 use no LangGraph at all.** The orchestrator is a plain function:

```python
def handle_turn(history, user_message, access) -> GroundedAnswer:
    question = resolve_question(history, user_message)   # coreference only
    return rag_engine.answer(question, access)
```

That is the entire orchestrator until the benchmark says otherwise. It is trivially debuggable, and — the point — it lets the RAG engine be measured without any orchestration confounding the numbers.

**The gate for introducing a graph.** LangGraph is adopted when at least one of these is a *named, measured* failure, not an anticipated one:

| Graph capability | Adopt when the benchmark shows |
|---|---|
| Conditional routing | measurable cost/latency waste retrieving for messages that need no retrieval |
| Loops (retrieve → judge → re-query) | questions failing that a second, reformulated retrieval would answer |
| Checkpoints | runs that must survive interruption, or HITL becomes required |
| Interruption (HITL) | ambiguous questions failing that a clarifying turn would fix |

Until one of those is on the board, a graph is machinery without a job. When the gate does open, the migration is contained — the orchestrator's function body becomes nodes; **`rag_engine.api` does not change.**

**Graph state, when that time comes** (the object flowing through every node):

```python
class OrchestratorState(TypedDict):
    # input — conversation-level
    messages: Annotated[list[BaseMessage], add_messages]
    access_context: AccessContext
    conversation_id: str
    # working — conversation decisions ONLY
    route: Literal["direct", "retrieve", "clarify", "refuse"]
    resolved_question: str          # standalone; the only thing the engine receives
    # returned by the engine — opaque to the orchestrator
    result: GroundedAnswer | None   # text, citations, evidence, sufficiency, trace
    # meta
    trace: list[StepTrace]
    usage: Usage
    errors: list[AgentError]
```

Note what is *absent*: `retrieved`, `reranked`, `context`, `search_queries`, `sufficiency`. Those are RAG-engine internals. They surface for debugging through `GroundedAnswer.trace`, but the orchestrator never manipulates them — the moment it does, retrieval strategy has leaked into conversation logic.

**Node graph.** Note that the entire RAG pipeline is *one node* from the orchestrator's point of view. The orchestrator does not know whether that node did dense retrieval or an eleven-stage hybrid rerank — that is the boundary doing its job.

```text
   CHAT ORCHESTRATOR                          │  RAG ENGINE
                                              │
        ┌──────────────┐                      │
        │  load_memory │  thread state +      │
        │              │  long-term facts     │
        └──────┬───────┘                      │
        ┌──────▼────────────┐                 │
        │ resolve_question  │  coreference →   │
        │                   │  standalone Q    │
        └──────┬────────────┘                 │
        ┌──────▼───────┐                      │
        │    route     │  chit-chat? needs docs? ambiguous?
        └──┬────┬───┬──┘                      │
   direct │    │   │ clarify → ask, end turn  │
          │    │   └──────────────┐           │
          │    │ retrieve         │           │
          │    ▼                  │           │
          │  ┌──────────────────┐ │           │   ┌─────────────────────────────┐
          │  │ rag_engine       │─┼───────────┼──▶│ transform → retrieve →      │
          │  │   .answer(Q,acl) │ │           │   │ rerank → context →          │
          │  │                  │◀┼───────────┼───│ sufficiency → generate →    │
          │  └────────┬─────────┘ │           │   │ verify_citations            │
          │           │           │           │   │   → GroundedAnswer          │
          │           │           │           │   └─────────────────────────────┘
          │           │           │           │     (abstains internally when
          └────┬──────┘           │           │      evidence is insufficient)
        ┌──────▼───────┐          │           │
        │ memory_write │◀─────────┘           │
        └──────┬───────┘                      │
               ▼  checkpoint + respond        │
```

Every node writes a `StepTrace`, and the engine returns its own trace inside `GroundedAnswer`. Together they make failures classifiable (Section 9) — and because the two traces are separate, a failure is immediately attributable to *orchestration* or *retrieval*, which is precisely the distinction the failure taxonomy needs.

### 7.5 Memory — all four kinds

The word "memory" covers four different mechanisms. Conflating them is the usual source of confusion.

| Kind | Question it answers | Lifetime | Storage | Milestone |
|---|---|---|---|---|
| **Short-term (thread)** | "what did we say earlier in *this* chat?" | one conversation | messages + Redis checkpoint | M4 |
| **Checkpoints** | "resume this run exactly where it stopped" | per graph step | LangGraph `RedisSaver` | M4 |
| **Long-term semantic** | "what facts do I know about this user/domain?" | forever | vector store `mem:*` namespace | M8 |
| **Long-term episodic** | "what happened in past conversations?" | forever | Postgres + vector index | M8 |
| **Procedural** | "how should I behave here?" (learned prefs, few-shots) | forever | key-value / prompt fragments | M8 |

**Short-term needs a compaction strategy** — a long conversation exceeds context. Ladder: keep last N turns (v1) → rolling summary of older turns + last N verbatim → recursive summarisation → semantic retrieval over the thread's own history.

**Checkpoints** are what make HITL and crash-resume possible: the graph persists after each node, so a run can be paused, inspected, edited, and resumed. They also give time-travel debugging — replay a bad answer from any node.

**Long-term memory needs a write policy**, or it fills with garbage: extract candidate facts after a turn → deduplicate against existing memories → only persist above a confidence threshold → attach provenance and timestamp → allow the user to view and delete (a "what do you remember about me" panel is both a UX feature and a privacy requirement).

### 7.6 Human-in-the-loop

LangGraph `interrupt()` before a designated node pauses the run and persists state; a later resume continues from that exact point.

| Use case | Interrupt before | Milestone |
|---|---|---|
| Ambiguous question → ask a clarifying question | `retrieve` | M8 |
| Low-confidence answer → "is this what you meant?" | `generate` | M8 |
| Destructive tool (delete, send) → approve | tool node | M9 |
| Reviewer edits retrieved context before answering (debug) | `generate` | dev only |

The frontend protocol: an `interrupt` SSE event carries the question and options; the UI renders an approval card; the reply resumes the run by thread id.

### 7.7 Security & guardrails

> **The security model is architectural. Classifiers are monitoring, not defence.**
>
> Prompt-injection classifiers are unreliable — they miss novel phrasings and produce false positives on legitimate content. A system that *relies* on one has no security model; it has a filter and a hope. Design so that a successful injection cannot do anything worth doing.

#### The four structural invariants

These are the security model. Each is testable, and none depends on a model's judgement.

| # | Invariant | Enforced by | Test that proves it |
|---|---|---|---|
| **1** | **ACL/tenant filtering at query time** | a hard metadata filter on every vector query, applied in `rag_engine.retrieve` from the `AccessContext` — never a prompt instruction | tenant A's corpus contains a unique token; tenant B cannot surface it by any prompt |
| **2** | **Retrieved content is data, never instructions** | delimited, id-tagged blocks, explicitly marked untrusted in the prompt template | a document containing "ignore previous instructions and…" changes no behaviour |
| **3** | **Privilege separation** | the RAG engine has no credentials beyond read access to its own index; the backend holds identity; the agent holds model keys | compromising the engine yields no write path and no user data |
| **4** | **No document-controlled tool access** | retrieved content can never reach a tool-call decision path — tools are selected from the *user's* turn and the orchestrator's state, never from evidence text | a planted document instructing a tool call triggers nothing |

Invariant 4 is the one that most often goes missing, and it is why tools live in `chat_orchestrator/`, not in the RAG engine. The engine reads documents; it must never be able to *act* on what it reads.

#### Optional monitoring (not defence)

- Prompt-injection classifier over ingested content and user turns — **for visibility**: log, flag, count. It may inform a review queue. It must never be the reason the system is considered safe, and disabling it must not change the security posture.
- PII detection (log/redact per policy), size/token caps, abuse and off-topic filtering, language detection.

#### Output checks

**Grounding check** (every factual claim traceable to a retrieved span) · **citation verification** (does the cited span actually *support* the claim, not merely exist) · PII leakage check · refusal handling · schema validation where structured output is required.

These belong to `rag_engine/grounding/` — they are properties of the answer-and-evidence pair, not of the conversation.

### 7.8 Evaluation — two suites, measured separately

Evaluation is a sibling of both subsystems, not a part of either. **The split matters:** if the RAG engine and the orchestrator are scored together, a routing bug and a retrieval bug are indistinguishable in the numbers.

```text
evaluation/
├── dataset/          benchmark questions + gold answers + gold evidence
├── rag_suite/        ← calls rag_engine.api DIRECTLY. No chatbot involved.
│                       single-turn, stateless: the honest measure of retrieval quality
├── chat_suite/       ← multi-turn: coreference, routing, memory, clarification
├── metrics/          Recall@K, Precision@K, MRR, nDCG, faithfulness,
│                     correctness, citation accuracy, abstention correctness,
│                     latency p50/p95, cost/query
├── judge/            LLM-as-judge (calibrated against ~15–20 hand-scored answers)
└── regression/       compare a run to the baseline; fail on regression
```

`rag_suite` is the one that exists first (M3) and the one the central rule refers to. `chat_suite` only becomes meaningful once there is orchestration worth testing — which, per §7.4, is not until a graph is earned.

Two modes: **offline** (the benchmark suites, run on every pipeline change — CI for RAG) and **online** (production signals: 👍/👎, abstention rate, latency, cost, retrieval-score distributions).

### 7.9 Observability

LangSmith or Langfuse tracing (every node, prompt, retrieval, and token) · per-request token and cost accounting returned in the `usage` event so cost is visible per answer, not discovered on a monthly bill · a `/retrieve` debug endpoint returning chunks with scores · replay-from-checkpoint for post-mortems.

---

## 8. RAG engine design

Lives at `agent/app/rag_engine/`. Two pipelines share one canonical document model, behind the single interface in §7.2.

```text
INGESTION (write, offline)                   QUERY (read, online)
──────────────────────────                   ────────────────────
ingestion/   job orchestration               retrieval/    find candidates
extraction/  bytes → structure               reranking/    order them well
document_model/  canonical form              context/      assemble the prompt
chunking/    structure → chunks              generation/   evidence → answer
embeddings/  chunks → vectors                grounding/    sufficiency, citations,
indexing/    vectors → store                               verification, abstention
                                             safety/       content-level: untrusted
                                                           delimiting, ACL filters
```

**What is deliberately *not* here:** memory, routing, chit-chat handling, clarification, HITL, tools, conversation state. Those are `chat_orchestrator/` (§7.1). Evaluation is a sibling of both (§7.8), because it measures them separately.

`generation/` belongs to the engine because grounding and citation verification are inseparable from the call that produced the claims — but it is **single-turn generation from supplied evidence**, not conversation management.

### 8.1 `extraction/` — bytes → structure

| | |
|---|---|
| **Job** | Turn a file into text **plus structure**: headings, reading order, tables, figures, page provenance. |
| **v1** | PDF only, PyMuPDF text + basic table extraction. |
| **Ladder** | Docling (layout + tables + reading order) → OCR for scanned pages (Tesseract/PaddleOCR) → vision model for charts/diagrams → per-format handlers (DOCX, PPTX, HTML, XLSX, images) |
| **Failure modes** | scanned PDF yields empty text · two-column text interleaved (reading-order failure) · table flattened into unparseable prose · headers/footers polluting content · figure captions detached from figures · encrypted or corrupt file · 2,000-page memory blowup |
| **Metrics** | text coverage %, table detection F1, reading-order accuracy, pages/sec |

**Non-negotiable:** extraction records **provenance** (page, bbox, section path) for every unit. Provenance lost here can never be recovered downstream, and citations are impossible without it.

### 8.2 `document_model/` — the canonical form

Every format converges here. Built once (product bible §10.1), consumed by everything after.

```text
Document
├── document_id, tenant_id, owner_id, acl
├── version {version_id, is_active, superseded_by}
├── metadata {source, format, page_count, language, created_at}
├── sections[]      {type: heading|paragraph|table|figure|image|code|list,
│                    content, level, page, bbox, section_path, order}
├── relationships[] {type: reference|caption_of|continues|part_of, from, to}
└── provenance      per-section page/bbox/table_id
```

**Failure modes:** structure flattened to plain text · provenance dropped · cross-references lost · table semantics (row/column headers) destroyed.

### 8.3 `chunking/` — structure → retrievable units

| | |
|---|---|
| **v1** | Recursive character split, ~512 tokens, ~15% overlap, never crossing a page boundary; provenance carried onto every chunk. |
| **Ladder** | structure-aware (respect headings/sections) → table-aware (a table is one chunk, or row-groups with the header repeated) → parent–child (embed small, return large) → contextual (prepend an LLM-written summary of where this chunk sits — big measured wins) → semantic (split on embedding-distance shifts) → hierarchical (multi-level summaries) → late chunking |
| **Failure modes** | a sentence split mid-fact · a table cut in half · a chunk with no context ("it increased by 12%" — *what* did?) · chunks so large that the real fact is diluted · overlap so high the index bloats |
| **Metrics** | Recall@K by chunk strategy, chunk size distribution, % of gold evidence contained wholly within one chunk |

Chunking is the highest-leverage, most-underrated knob in RAG. It is also the reason the benchmark must exist before tuning.

### 8.4 `embeddings/` — chunks → vectors

| | |
|---|---|
| **v1** | One strong general model; batch, retry, cache by content hash. |
| **Ladder** | benchmark 2–3 candidates on *our* corpus → domain-specific model → multilingual → multi-vector (ColBERT-style) → multimodal (image embeddings for charts) |
| **Failure modes** | model/index dimension mismatch · normalisation mismatch with the distance metric · silent truncation of over-long chunks · rate limits during bulk ingest · **model change invalidating the whole index** |
| **Metrics** | Recall@K per model, embed cost/1k chunks, embed latency, cache hit rate |

Record the embedding model id and dimension **in the index metadata**. Mixing two models in one collection produces silently wrong retrieval.

### 8.5 `indexing/` — vectors → store

Collection layout: one collection, tenant-filtered (simple, good to millions) — shard per tenant only when profiling demands it.

Every chunk's payload carries: `tenant_id`, `document_id`, `version_id`, `is_active`, `acl`, `page`, `section_path`, `chunk_index`, `content_hash`, `embedding_model`.

**Filters applied on every single query, without exception:** `tenant_id`, ACL, `is_active`. These are structural (Section 7.6).

**Failure modes:** stale vectors after re-upload · orphaned vectors after delete (data leak) · missing payload index making filters slow · unbounded upsert batch timing out · index rebuild with no way to serve during it.

**Operational needs:** idempotent upsert keyed on `content_hash`, delete-by-`document_id`, and a reconciliation sweep for orphans.

### 8.6 `retrieval/` — the deep section

Retrieval is where most RAG quality lives, so it gets the full ladder. **Each rung is added only when the benchmark shows the failure it fixes.**

| Level | Technique | Add when the benchmark shows |
|---|---|---|
| **1** | **Dense vector search** (top-k, cosine) | — this is v1 |
| **2** | **+ BM25 → hybrid** with RRF fusion | keyword/rare-term queries fail: product codes, names, IDs, exact phrases. Dense embeddings are lossy on exact tokens. |
| **3** | **+ Metadata filtering** (date, type, document, section) | the right doc exists but the wrong-era/wrong-type one wins |
| **4** | **Query transformation** — rewriting, multi-query, decomposition, HyDE, step-back | question wording ≠ document wording; multi-hop questions need sub-questions |
| **5** | **Contextual retrieval** (chunk + LLM-written context, indexed together) | chunks are individually meaningless without their section |
| **6** | **Parent–child / small-to-big** | matched chunks are right but too small to answer from |
| **7** | **Hierarchical / summary-first** | a 2,000-page doc needs "which section?" before "which chunk?" |
| **8** | **Multi-hop / iterative** (retrieve → reason → retrieve again) | answers require chaining facts across pages/documents |
| **9** | **Agentic retrieval** (the model chooses tools/strategies per query) | question types are so heterogeneous that no fixed strategy wins |
| **10** | **Graph retrieval** (entity/relationship graph over the corpus) | questions are about relationships spanning many documents |
| **11** | **Multimodal retrieval** (image/chart embeddings) | chart/diagram questions fail with text-only retrieval |

**Retrieval failure modes, named precisely** (these are the labels used in Section 9):

- `relevant_document_missed` — the right document never entered the candidate set
- `relevant_chunk_missed` — right document, wrong chunk retrieved
- `ranking_failure` — the right chunk was retrieved but ranked below the cutoff
- `semantic_drift` — embeddings matched topic, not the specific fact
- `keyword_blindness` — exact term present in the corpus, missed by dense-only search
- `over_retrieval` — k too large, correct chunk buried in noise
- `filter_too_strict` — metadata filter excluded the answer
- `multi_hop_failure` — each hop retrievable, chain not followed
- `temporal_confusion` — retrieved the outdated version of a fact

**Metrics:** Recall@{1,5,10,20}, Precision@K, MRR, nDCG@10, plus all of them **sliced by question type and difficulty** (§5.2 of the product bible). One flat Recall number hides exactly the information you need.

### 8.7 `reranking/`

| | |
|---|---|
| **Job** | Reorder the top ~50 candidates into the best ~5 with a slower, more accurate model. |
| **v1** | None. (Retrieval must be the proven bottleneck first.) |
| **Ladder** | cross-encoder (bge-reranker / Cohere Rerank) → LLM listwise rerank → diversity-aware (MMR) so k results aren't five near-duplicates → recency/authority weighting |
| **Failure modes** | latency blowup for marginal quality · reranker trained on a different domain scoring worse than retrieval · over-filtering that drops needed context |
| **Metrics** | nDCG before vs after, added latency, answer-quality delta — *the deciding question is quality gained per millisecond added* |

### 8.8 `context/` — assembling the prompt

Goal: **the smallest sufficient context, not the largest possible one.**

Responsibilities: token budgeting (reserve room for the answer) · deduplication of near-identical chunks · ordering (**lost-in-the-middle** is real — put the strongest evidence first and last) · parent-context reconstruction · optional compression (extract only relevant sentences) · relevance thresholding (drop weak chunks entirely rather than padding to k) · clear delimiting and labelling of each source so citations can reference it.

**Failure modes:** `too_much_context` (noise drowns signal, cost balloons) · `insufficient_context` (over-trimmed) · `ordering_problem` (key evidence buried mid-prompt) · context overflow silently truncating the *end*, which is often the question itself.

### 8.9 `grounding/` — evidence, citations, abstention

Three mechanisms:

1. **Sufficiency gate (pre-generation):** score whether the evidence can answer the question at all. Insufficient → abstain instead of generating. *Abstention is a feature, and the benchmark's "impossible" questions exist to test it.*
2. **Citation binding (during generation):** the model must attach a source id to each factual claim; the prompt enumerates sources with stable ids.
3. **Citation verification (post-generation):** programmatically check that each cited span actually supports its claim. A citation that exists but doesn't support the claim is worse than none — it manufactures false confidence.

**Contradictions:** when sources disagree, **surface both with provenance and state the conflict**. Do not silently resolve. (Product bible §12.2 — deliberately narrow scope.)

**Failure modes:** `unsupported_claim` (hallucination with a citation attached) · citation pointing at the wrong page · over-abstention on answerable questions · under-abstention on impossible ones.

### 8.10 `generation/`

Prompt structure (fixed, cache-friendly): system role & rules → **untrusted document content, delimited and id-tagged** → conversation history → question → output-format instructions.

Concerns: streaming · temperature low for factual work · stop reasons handled · refusal handled · retry/fallback across models · **token and cost accounting per call** · deterministic prompt prefixes so caching works when we move to a paid provider.

**Failure modes:** `hallucination` · `incomplete_answer` (only part of a multi-part question) · `reasoning_error` (right evidence, wrong inference) · ignoring provided evidence in favour of parametric memory · format violations.

### 8.11 How the engine is measured

Evaluation lives *outside* the engine (§7.8) — `evaluation/rag_suite/` calls `rag_engine.api` directly, with no chatbot in the loop. That is deliberate: retrieval quality measured through a conversation is retrieval quality confounded by routing, coreference, and memory.

The point restated: **every change to extraction, chunking, embeddings, retrieval, reranking, context, or prompts re-runs `rag_suite` before it counts as done.** That is the product bible's central rule made mechanical.

### 8.12 Scale — what changes at 10 M documents / 2,000-page files

Designed for now, implemented when profiling demands it (Principle 6).

| Pressure | First thing that breaks | Response |
|---|---|---|
| One 2,000-page PDF | extraction memory + wall time | stream page-by-page; checkpoint per page-range; resumable jobs; per-page progress |
| Thousands of docs | ingestion throughput | worker pool; per-format pools only when profiling shows the bottleneck |
| 10 M+ chunks | vector search latency & RAM | quantisation (scalar/binary), HNSW tuning, payload indexes, sharding |
| Many tenants | noisy-neighbour | per-tenant queues and quotas; ACL filters already structural |
| Re-embedding everything | downtime | blue/green collections: build the new index alongside, atomic alias swap |
| Cost | embedding + generation spend | cache embeddings by content hash, cache identical queries, batch APIs, smaller models for non-critical roles |

---

## 9. Cross-cutting concerns & the failure catalogue

### 9.1 Configuration & secrets

Each service owns its own `.env`; no shared secrets file. Model API keys exist **only** in the agent. All config is validated at boot (Pydantic Settings / a Zod-style check in the frontend) so a missing variable fails loudly at startup, not mysteriously at 2am. `.env.example` in every service, `.env` never committed.

### 9.2 Local development

`docker-compose.yml` at the root brings up Postgres, Redis, Qdrant, and MinIO. The three application services run on the host with hot reload (faster iteration than containerising them). One `make dev` (or `dev.ps1`) starts everything in the right order: infra → agent → backend → frontend.

### 9.3 The master failure taxonomy

Every failed benchmark case gets exactly one label. This is what converts "the answer was bad" into "fix *this*".

```text
INGESTION_FAILURE      extraction · ocr · reading_order · table · visual
REPRESENTATION_FAILURE structure_lost · provenance_lost · relationship_lost
CHUNKING_FAILURE       split_mid_fact · context_orphaned · table_split · size_wrong
EMBEDDING_FAILURE      model_mismatch · truncation · domain_gap
RETRIEVAL_FAILURE      relevant_document_missed · relevant_chunk_missed ·
                       ranking_failure · keyword_blindness · semantic_drift ·
                       filter_too_strict · multi_hop_failure · temporal_confusion
RERANKING_FAILURE      reordered_wrongly · over_filtered
CONTEXT_FAILURE        too_much_context · insufficient_context · ordering_problem
GENERATION_FAILURE     hallucination · incomplete_answer · reasoning_error ·
                       ignored_evidence · format_violation
GROUNDING_FAILURE      unsupported_claim · wrong_citation · over_abstention ·
                       under_abstention
GUARDRAIL_FAILURE      injection_succeeded · pii_leaked · acl_bypass
SYSTEM_FAILURE         timeout · worker_crash · rate_limit · infrastructure ·
                       stream_interrupted
UX_FAILURE             misleading_state · lost_work · unclear_error
```

**Rule:** a failure without a label does not get a fix attempt. Guessing is what the taxonomy exists to prevent.

### 9.4 Security posture (Step 1 scope)

Transport TLS in any deployed environment · secrets only in the agent · encryption at rest for uploads (storage-level) · ACL enforced structurally at retrieval · every document's derived data inherits the source document's ACL · deletion means the vectors go too · PII stance decided explicitly (v1: **out of scope, documented**, not silently ignored) · prompt-injection treated as a first-class threat (§7.6) · all model output sanitised before rendering.

### 9.5 Cost & latency

Measured before targeted (product bible §21). Recorded per query: input/output tokens, embedding calls, retrieval time, rerank time, generation time, total p50/p95, cost. Tracked in the *same* harness as quality, so a change that improves recall while doubling latency is a visible trade-off rather than a silent regression.

---

## 10. Build order — milestones

Each milestone: what gets built, and what "done" means.

**M0–M3 are a fixed sequence** — you cannot measure before something exists to measure, so this much is ordered by necessity, not by evidence.

**Everything after M3 is a gate, not a date.** Each capability below is entered when a *named benchmark failure* demands it, and skipped or deferred when it doesn't. The order shown is the likely one, not a schedule. This is the central rule applied to the plan itself: an unconditional milestone would be the same mistake as an unconditional feature.

| # | Milestone | Entry condition |
|---|---|---|
| M0 | Skeleton chatbot | — ✅ mostly done |
| M1 | Real chat product | M0 complete. Streaming + persistence. **No RAG, no graph.** |
| M2 | Dumb RAG | M1 complete. Upload → naive answer with citations. **Still no graph.** |
| M3 | The benchmark | M2 complete. Measurement exists; baseline recorded. |
| — | *— every gate below requires a named failure in the M3 benchmark —* | |
| G1 | Retrieval intelligence | `RETRIEVAL_FAILURE` is the dominant category |
| G2 | Orchestration (LangGraph, routing, memory) | §7.4's gate opens — waste, loops, or ambiguity measured |
| G3 | Grounding & guardrails | `GROUNDING_FAILURE`; or before any untrusted-document exposure |
| G4 | HITL | ambiguous questions fail that a clarifying turn would fix |
| G5 | Scale & hardening | profiling shows a real bottleneck, or real documents exceed capacity |
| P1 | Frontend production pass | independent of the benchmark — gated on the product being used |
| P2 | Backend production pass | independent — gated on multi-user or public exposure |

P1 and P2 are deliberately *not* benchmark-gated: auth, accessibility, and error handling are correctness requirements of a product, not hypotheses about retrieval. They are sequenced by when the product meets real users, not by what the benchmark says.

---

### M0 — Skeleton chatbot ✅ (essentially complete)

Three services talking; a message reaches a model and comes back.

**Remaining:** switch the agent to the OpenRouter provider (free tier) behind `providers/`.
**Done when:** typing a message in the browser returns a real model answer through backend → agent.

---

### M1 — Real chat product

The chatbot becomes genuinely usable. **No RAG yet** — deliberately, because streaming and persistence are hard enough alone and are far easier to debug without retrieval in the picture.

- **No LangGraph, no memory subsystem.** The orchestrator is `handle_turn()` — a function (§7.4)
- Postgres + Alembic; conversations and messages persisted
- SSE streaming end-to-end (agent → backend proxy → frontend), Stop button, cancellation propagated
- Frontend state architecture installed (TanStack Query + Zustand + stream hook, §5.1)
- Conversation list, switching, rename, delete; history survives refresh
- Error taxonomy implemented (§5.7); markdown rendering + sanitisation
- Docker-compose for infra

**Done when:** you can hold a multi-turn conversation, watch tokens stream, stop mid-answer, refresh the page, and find the conversation intact.

---

### M2 — Dumb RAG (the first vertical slice of retrieval)

Deliberately naive. Its purpose is to make the pipeline *real* and to produce the first failures worth measuring.

- Upload → object storage → job queue → agent worker
- PDF text extraction → fixed-size chunking → one embedding model → Qdrant
- Retrieval: dense only, top-k. No hybrid, no rerank, no query rewriting
- **`rag_engine.api` exists from this milestone** — the orchestrator calls `answer()` and nothing else. Even naive, the boundary is real from day one
- **Still no graph.** The orchestrator remains a function
- Generation with retrieved context + citations; abstain if nothing retrieved
- Frontend: upload zone, per-file progress, status polling, document list, citation cards

**Done when:** you upload a PDF, ask a question about it, and get an answer citing a real page. Expect it to be mediocre — that is the point.

---

### M3 — The benchmark (measurement exists)

Now the naive system exists, an honest exam can be written against it.

- 30–50 questions over 5–10 real documents, with the full metadata schema (type, difficulty, gold answer, gold evidence, answerable, modality)
- `rag_suite` calls `rag_engine.api` **directly, with no chatbot in the loop** — this is what makes the retrieval numbers honest
- Automatic retrieval metrics (Recall@K, Precision@K, MRR, nDCG), sliced by question type
- LLM-judge for answer quality, **calibrated** against ~15–20 hand-scored answers
- Citation accuracy and abstention correctness
- **Record the baseline** — the number every future change is measured against
- One command runs the suite and prints a comparison to baseline

**Done when:** `run_benchmark` produces a scorecard with a per-failure-type breakdown, and you know exactly which layer is your worst.

*(This is the moment the project stops being vibes-based. Everything after is benchmark-gated.)*

---

### G1 — Retrieval intelligence

**Gate:** `RETRIEVAL_FAILURE` is the dominant category in the M3 baseline. (It usually is — which is why this is listed first rather than orchestration.)

Climb the §8.6 ladder one rung at a time. For each: form the hypothesis from a *named* failure, run the experiment, keep it if it helps, delete it if it doesn't, and **write the result down** in `docs/experiments/`.

Likely order, driven by what usually fails first: hybrid (BM25 + RRF) → reranking → contextual chunking/retrieval → query transformation → parent–child → multi-hop.

All of this happens **inside `rag_engine/`**. The orchestrator does not change, and neither does `rag_engine.api` — that is the boundary paying for itself.

**Done when:** each retained technique has a written experiment note showing its benchmark delta, and each rejected one has a note saying why.

---

### G2 — Orchestration (LangGraph, routing, memory)

**Gate:** §7.4's table — measured retrieval waste on no-retrieval messages, questions a reformulated second attempt would answer, or a requirement for interruption. **Not** "we will eventually want a graph."

- Migrate `chat_orchestrator/pipeline.py` from a function to a LangGraph graph
- Conditional routing; retry-with-new-question loop
- Redis checkpointer; short-term memory with a compaction strategy
- `status` SSE events driven by real graph stages
- LangSmith/Langfuse tracing across orchestrator nodes
- `chat_suite` in evaluation becomes meaningful; add multi-turn cases

Long-term memory (semantic, episodic, procedural) is a **separate sub-gate** — entered only when conversations demonstrably need cross-session recall, with the write policy and the user-visible/deletable memory panel from §7.5.

**Done when:** the `rag_suite` score is unchanged (orchestration must not degrade retrieval), `chat_suite` improves, and every answer has an inspectable two-part trace.

---

### G3 — Grounding & guardrails

**Gate:** `GROUNDING_FAILURE` appears in the benchmark — *or*, unconditionally, before any untrusted document reaches the system. The four structural invariants of §7.7 are not benchmark-gated; they are preconditions for exposure.

- The four structural invariants implemented and each covered by the adversarial test named in §7.7
- Citation verification (claim ↔ span), grounding checks, calibrated abstention
- Contradiction surfacing with provenance
- Optional: injection classifier wired as *monitoring* — logged and counted, never load-bearing

**Done when:** the benchmark's *impossible* questions are abstained on correctly, its *contradiction* questions surface both sources, a planted injection changes no behaviour, and a planted tool-call instruction in a document triggers nothing.

---

### G4 — Human-in-the-loop

**Gate:** ambiguous questions fail in the benchmark that a clarifying turn would fix. Requires G2 (checkpoints).

Clarifying questions via `interrupt()`; the `interrupt` SSE event and approval card; approval gates on any destructive tool.

**Done when:** an ambiguous benchmark question produces a clarifying turn and, once answered, a correct result — with the run resumed from its checkpoint rather than restarted.

---

### G5 — Scale & hardening

**Gate:** profiling shows a real bottleneck, or real documents exceed current capacity. Not before.

Per-page checkpointed extraction for 2,000-page files · resumable, idempotent jobs · dead-letter queue with an inspection path · worker pools sized by profiling · vector quantisation + HNSW tuning + payload indexes · blue/green reindex with alias swap · cost/latency dashboards · load testing · a backup/restore drill.

**Done when:** a 2,000-page PDF ingests without manual intervention and survives a mid-job worker kill; p95 query latency and cost/query meet the targets set against the M3 baseline.

---

### P1 — Frontend production pass

**Gate:** not benchmark-driven — entered when the product meets real users.

Virtualised lists · skeletons everywhere · optimistic updates with rollback · full a11y pass · light/dark with no theme flash · mobile layout · source panel with document preview · message actions · draft persistence · Sentry + Web Vitals · Vitest unit tests (SSE parser included) + MSW + two Playwright journeys.

**Done when:** both critical journeys pass in Playwright, Lighthouse a11y is ~100, and no interaction lacks a defined loading/error state.

---

### P2 — Backend production pass

**Gate:** not benchmark-driven — entered on multi-user or public exposure.

Auth (session cookies, `current_user` dependency, internal token for the agent) · rate limiting · quotas surfaced via `/api/me` · idempotency keys · the concurrency mitigations from §6.4 · OpenTelemetry tracing across all three services · structured logs · pytest suite with a real test DB.

**Done when:** two browsers with different users cannot see each other's data, a double-click cannot double-charge, and one trace id explains any slow request end to end.

---

## Appendix — the shortest possible summary

- **Three services.** Frontend never touches the agent; backend never touches an LLM.
- **Two subsystems inside the agent.** `rag_engine/` is stateless and conversation-blind; `chat_orchestrator/` owns memory, routing, and turns. The interface between them is two functions.
- **Two pipelines.** Ingest (async, queued, in the agent's workers) and chat (streamed, real-time).
- **Four stores.** Postgres (control plane) · object storage (bytes) · Qdrant (vectors) · Redis (queue, cache, checkpoints).
- **Security is structural.** Four testable invariants; classifiers are monitoring, never defence.
- **One rule.** Nothing is built beyond the current step without the benchmark naming the failure it fixes — and that applies to the milestones themselves, which is why everything after M3 is a gate, not a date.
- **Order.** Working chatbot → dumb RAG → **benchmark** → then whichever gate the baseline opens.
