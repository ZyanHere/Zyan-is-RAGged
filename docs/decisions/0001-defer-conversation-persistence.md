# 0001 — Defer conversation persistence until RAG is real

**Status:** accepted
**Date:** 2026-09-04
**Supersedes:** the M1 ordering in `docs/architecture/system-design.md`

## Context

The system design put M1 (streaming **and** persistence) before M2 (dumb RAG).
Streaming shipped; persistence had not started.

The stated reason for putting persistence in M1 was ordering, not value:

> Streaming changes the shape of the whole request path. If you build
> persistence first, you would write "save the assistant message", then rewrite
> it for streaming.

## Decision

**Skip conversation persistence for now. Go straight to M2 (dumb RAG).**

Conversation history stays in the in-memory dict in
`backend/app/api/routes/chat.py` until persistence earns its place.

## Why

**The ordering constraint expired.** Streaming is done, so persistence no longer
risks being written twice. Nothing now holds RAG behind it.

**It is not on the critical path to the product.** RAG is both the point of the
product and the stated learning goal. Conversation CRUD is generic web work.

**The retrofit cost is low.** `chat.py` reads and writes one dict; swapping that
for a repository call is contained, and the frontend change is additive.
Persistence is a layer to slide underneath, not a foundation to pour first.

**Qdrant will be the first persistent store, and that is the right one.** M2
needs somewhere to keep documents and chunks — and that somewhere is a vector
database, not Postgres. Chunk payloads carry `document_id`, filename and page,
so uploaded documents survive restarts even while conversations do not.

## Consequences

**Accepted costs**

- Conversations are lost on backend restart and on browser refresh.
- The sidebar conversation list stays empty (`getConversations()` returns `[]`).
- Running more than one backend worker would split memory per process, so we
  stay single-worker.

**Mitigations**

- Documents — the slow, expensive thing — persist in Qdrant, so RAG iteration is
  not affected by restarts.
- Testing during M2 is single questions against documents, not long chats.

## When to revisit

Any of:

- conversations need to survive a refresh for real use (first external user)
- multiple backend workers are needed
- a feature requires reading past conversations (long-term memory, analytics)
- documents need metadata that does not belong in a vector payload
  (ownership, quotas, ingestion job state)

The last one is the most likely trigger, and it will probably arrive with
multi-document uploads rather than with chat.

## Related

- `docs/architecture/system-design.md` — M1/M2 milestones
- `todos/001-conversation-history-growth.md` — the other consequence of keeping
  history in a list
