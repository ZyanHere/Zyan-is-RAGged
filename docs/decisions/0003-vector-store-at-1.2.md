# 0003 — Vector store at stage 1.2: keep Qdrant alongside Postgres

**Status:** accepted
**Date:** 2026-10-11

## Context

Stage 1.2 introduces Postgres to hold a durable record of what ingestion was
attempted. That makes this the moment to ask a question that had no force
before: **if the system now runs Postgres anyway, should the vectors live there
too?**

`pgvector` is a Postgres extension that stores embeddings as a column type and
indexes them for approximate nearest-neighbour search. It supports HNSW indexes
and is a genuinely capable vector store, not a toy.

The argument for it is at its strongest right now and gets weaker afterwards,
because the cost of migrating grows with every stage that assumes two stores.

## Options considered

| Option | Datastores | Transactional consistency | Filtering | Quantization |
|---|---|---|---|---|
| **pgvector** | one | vectors and metadata in one transaction | SQL `WHERE` | limited |
| **Qdrant (embedded)** | two | none across the boundary | rich payload filters | scalar + binary |
| Qdrant (server) | two | none across the boundary | rich payload filters | scalar + binary |

## Decision

**Keep Qdrant. Postgres owns documents, ingestion jobs and application state;
Qdrant owns vectors and semantic retrieval.**

### The honest reason

This is a learning project, and **the two-store split preserves a class of
problem that one store would remove.**

Stage 6.4 — distributed locks, leases and fencing — exists in its current form
specifically because *Qdrant has no conditional write*. There is no
compare-and-set and no "reject if version < N", so a stale worker's write
cannot be refused by the storage layer. The exercise is to work out where the
authoritative check can live, and the answer is that the commit point has to
move to the only place with atomicity: Postgres.

With pgvector, the vectors would already be in Postgres. The write would be a
row in a transaction, the fencing check would be an ordinary `UPDATE … WHERE
version = ?`, and most of that stage would evaporate.

> A worker that has lost ownership must be unable to commit — and the check has
> to happen somewhere that can enforce atomicity. If your storage layer cannot
> do conditional writes, the commit point must move somewhere that can.

That idea generalises to systems far beyond this one, and it is only learnable
here because the two stores disagree.

**This is a curriculum reason, not an engineering one, and it should be stated
that way.** In an interview, *"we kept two stores because it preserved a
cross-store consistency problem I wanted to solve"* is a defensible answer.
*"Qdrant is better"* is not, and is not what this decision says.

### The secondary reasons, which are engineering ones

Two capabilities Qdrant has that pgvector handles less well, both of which
later stages depend on:

- **Payload filtering.** Stage 5.1 requires a hard tenant filter on *every*
  vector query. Qdrant filters on indexed payload fields natively. pgvector can
  do it with a SQL `WHERE`, but combining a filter with an ANN index is where
  pgvector's planner gets awkward — pre-filtering can fall back to a sequential
  scan, post-filtering can return fewer rows than requested.
- **Quantization.** Stage 13.1 measures the recall cost of scalar and binary
  quantization, and 13.0's capacity model turns on it: at 768 dimensions the
  difference between float32 and binary is roughly 30× in memory. Qdrant
  supports both natively.

Neither of these would be decisive alone. They are listed because they are real
and they point the same way.

## What we are giving up

Stating this plainly, because the decision is a trade and the costs are not
small:

- **Two datastores to run, back up and reason about.** Two connection
  lifecycles, two failure modes, two things to get right at stage 15.3.
- **No transaction spanning both.** A document row can commit while its vectors
  fail, or the reverse. This is the dual-write problem, and it is *precisely*
  what stages 2.2 (idempotency), 6.4 (fencing) and 14.1 (the outbox pattern)
  spend their time on. We are choosing to own that problem.
- **The chunk text is stored twice** once Postgres exists — once in the Qdrant
  payload, once wherever Postgres ends up keeping it. Stage 1.2 does not
  resolve this; it is noted so it is not discovered as a surprise.
- **A real migration cost later.** Moving to pgvector after stage 5.1 or 13.1
  means re-embedding the corpus and rewriting retrieval. The cheapest moment to
  switch is now, and we are declining it knowingly.

## When to revisit

- **The two-store consistency work turns out to be the wrong lesson for the
  time it costs.** If stage 6.4 becomes a month of yak-shaving rather than a
  week of insight, that is evidence, and consolidating is a legitimate response.
- **Operational cost starts to matter.** At stage 15.3 a managed Postgres with
  pgvector is one service to pay for and monitor; Postgres plus Qdrant Cloud is
  two.
- **Measured retrieval quality is indistinguishable.** If, with the stage 3.1
  harness in place, pgvector scores the same on this corpus, the "rich
  filtering and quantization" argument weakens to a theoretical one.

## Consequences

- `rag/` keeps its vector-store seam in `vector_store.py`. Nothing outside that
  module knows Qdrant exists, so a future pgvector implementation is one new
  file plus a config change — the same shape as the embedding provider seam.
- Postgres is added at stage 1.2 for application state only. **The backend must
  not learn what a vector is**, and `rag` must not learn what a document row
  is. The dependency direction in `docs/architecture/current.md` is unchanged.
- Qdrant stays embedded for now. Moving it to a server is a `QDRANT_URL` change,
  triggered at stage 1.3 when a separate worker process needs concurrent access
  that embedded mode's single-process lock forbids.

## Related

- `docs/decisions/0002-embedding-provider.md` — the embedding model, which this
  decision does not touch
- `docs/curriculum.md` §6.4 — the fencing exercise this decision preserves
- `docs/curriculum.md` §13.0–13.1 — the capacity and quantization work
- `rag/rag/vector_store.py` — the seam that keeps this reversible
