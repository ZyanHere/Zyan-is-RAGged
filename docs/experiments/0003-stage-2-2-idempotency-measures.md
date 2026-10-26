# 0003 — Stage 2.2: the idempotency measures

**Date:** 2026-10-26
**Stage:** 2.2 (Idempotency), Layer 4 — the engine.
**Status:** the headline measure is complete. All figures `[measured]`.
**Baseline:** `0002-stage-2-2-baseline-audit.md`.

## The headline: a doubly-indexed document repairs itself

The baseline audit found document `01a153cd-13ce-7786-995f-369c0c82377e`
holding **6 points where Postgres records 3** — it was the job stranded at the
end of 1.3, recovered by 2.1's reaper, and therefore ingested twice.

The only action taken in each run below is inserting one `queued` row, which is
exactly what a re-upload produces. No script touches Qdrant to fix anything; a
real worker claims the job and calls the real agent.

| Run | Target document | Collection total | What it shows |
|---|---|---|---|
| 1 | 6 → **9** | 54 → 57 | the first fix was wrong |
| 2 | 9 → **3** | 57 → 51 | the corrected fix repairs it |
| 3 | 3 → **3** | 51 → 51 | and is idempotent |

Run 2 is the measure: **duplicate chunks for one re-ingested document, 9 → 3,
with Postgres independently recording 3.** Run 3 is the property the stage
exists to establish — re-processing changes nothing.

Each run completed in **4.4–4.7s**, ordinary worker, no intervention.

## Run 1 failed, and that is the most useful part of this file

```text
BEFORE  01a153cd-… -> 6 points  [0, 0, 1, 1, 2, 2]
AFTER   01a153cd-… -> 9 points  [0, 0, 0, 1, 1, 1, 2, 2, 2]
```

The re-ingestion **added three more points.** Deterministic ids were in place
and working; the plan's replacement step was wrong.

### Why

The plan paired `uuid5` point ids with a **tail delete** — remove
`chunk_index >= n` after upserting, on the reasoning that the upsert overwrites
`0 … n-1` and only a *shrinking* re-ingest leaves anything behind. Both halves
are individually true and together they miss the actual case:

- the six existing points were written by `uuid.uuid4()`, so the three new
  derived ids match none of them and overwrote nothing;
- those six carry chunk indices **0, 1 and 2**, so `>= 3` reached none of them
  either.

**The general lesson: points written under a different id scheme are
identifiable only by `document_id`, never by index.** A tail delete repairs
nothing that predates the scheme — so it makes future ingestions idempotent
while leaving every existing duplicate exactly where it was. A fix that passes
its unit tests and fixes nothing.

Worth noting how it was caught. Every unit test passed, and six separate
mutations of `_point_id` were each caught by the test that claimed to cover
them. The id scheme was genuinely correct and genuinely well tested. **Only the
end-to-end measure against real data found the gap**, which is the argument for
the curriculum's rule that a stage is not done until it has produced a number.

### The correction

`delete_chunks_except(document_id, keep_ids=...)` replaces
`delete_chunks_from(document_id, chunk_index=n)`. `upsert_chunks` now returns
the ids it wrote, and the pipeline prunes everything else belonging to that
document:

```python
point_ids = upsert_chunks(chunks, vectors, ...)
delete_chunks_except(document_id, keep_ids=point_ids)
```

Identifying the survivors by *what they are not* covers both cases at once — a
shrinking re-ingest, and any point from any earlier scheme. The guarantee
becomes unconditional: **after a successful ingestion the store holds exactly
the chunks that ingestion wrote** for that document.

Still after the upsert, never before. Deleting first would leave the document
unsearchable until the write landed, and permanently absent if embedding then
failed. Duplicate chunks are a bad outcome; losing a working document is worse.

### Two consequences worth recording

**It removed a cross-module coupling rather than adding one.** The tail delete
depended on `chunk_index` being contiguous from 0 — an invariant living in
`chunking.py` and relied on in `vector_store.py`. The prune needs nothing from
`chunking.py` at all. `test_chunking.py`'s docstrings were corrected
accordingly: what the point ids still require is that indices do not *repeat*
(a repeat would make two chunks derive one id, and one would overwrite the
other), not that they are contiguous.

**It costs a filter that grows with the document.** `keep_ids` goes into the
request, so a 1,000-chunk book is roughly 36 KB of ids. Qdrant evaluates it
only against that document's points, so the work is bounded, but the payload is
not constant.

The constant-size alternative is a **generation stamp** — an `ingest_id` on
every chunk's payload, deleting `document_id = X AND ingest_id != current`,
which is two conditions regardless of size. It is how index swaps are normally
done, and it costs a payload field plus a new concept in `Chunk`. Deferred,
because nothing is measured as slow and the id list is exactly expressive.
**Trigger:** a document large enough that the filter payload shows up in a
measurement, or the moment anything else needs to reason about "which run wrote
this" — likely 2.4's `request_id` threading.

## A citation to a document that does not exist

Retrieval was checked after the prune, and the answer that came back is itself
evidence for the next layer:

```text
POST /query  →  citation [1] document_id 01a12abc-9048-7215-935c-3e37d6958385
```

```sql
SELECT count(*) FROM documents WHERE id = '01a12abc-9048-7215-935c-3e37d6958385';
→ 0
```

**The system answered a question using a document that is not in the
database.** `GET /documents/{that id}` would return 404 while the citation
points at it. This is the orphan problem the baseline audit found — `ON DELETE
CASCADE` stops at the edge of Postgres — and it is no longer an abstract count:
it is a user-visible wrong answer, reproduced on demand.

Collection total after run 3 is **51 points**. The four live documents account
for **12** (3 each, all now in agreement). The remaining **39 are orphans**, so
roughly three quarters of every search still ranks against text belonging to
documents nobody can look up. That is Layer 5.

## Method notes

Reading Qdrant requires the agent stopped, because embedded Qdrant holds an
exclusive lock on its storage volume:

```bash
docker compose stop agent
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "<scratchpad>/audit:/audit:ro" --entrypoint python agent /audit/qdrant_audit.py
docker compose start agent
```

The stop/start also reloads `rag` inside the agent, since `./rag/rag` is
bind-mounted read-only and uvicorn is not watching it. That was convenient
here and is a trap worth naming: **editing `rag` and re-running a measurement
without restarting the agent measures the old code.**

## Still to measure in this stage

| Measure | State |
|---|---|
| duplicate chunks after a re-ingest | **done**, 9 → 3, then 3 → 3 |
| orphan points | 39, cleanup is Layer 5 |
| five concurrent uploads of one file → one document | covered by tests; the live run belongs with Layer 5 |
| a job retried N times keeps a constant point count | covered by run 3's mechanism; the induced-retry version belongs with Layer 5 |

---

## Layer 5 — the orphans: 39 → 0

`tools/qdrant_orphans.py`, read-only by default.

```text
BEFORE   Postgres: 4 documents
         Qdrant:   22 documents, 51 points

         ORPHAN     18        39 points (76%)
         MISMATCH    0
         MISSING     0
         PENDING     0
         AGREED      4        12 points

AFTER    Postgres: 4 documents
         Qdrant:    4 documents, 12 points
         ORPHAN      0  —  "the two stores agree about which documents exist"
```

**MEASURE: orphaned points 39 → 0.** Re-running the tool afterwards reports no
orphans and deletes nothing, so it is idempotent too.

`MISMATCH 0` is itself a result: the only mismatch in the system was the 6-vs-3
document, and Layer 4's re-ingestion had already repaired it.

### The before/after that matters is not the count

Before the cleanup, a live query answered confidently and cited
`01a12abc-9048-7215-935c-3e37d6958385`:

> "The maintenance window is fixed at 02:00 to 04:00 UTC every Sunday, with a
> breach penalty of 15,000 pounds per calendar month … and a named escalation
> contact of Priya Raghunathan [1]."

That document does not exist. `SELECT count(*) FROM documents WHERE id = …`
returns 0, so `GET /documents/{id}` answers 404 for the very citation the
answer rests on.

After the cleanup, the same question returns:

> "The provided excerpts do not contain information about the maintenance
> window or escalation contact."

**The system went from confidently citing a document that does not exist to
correctly saying it does not know.** Every citation returned by a subsequent
query was then checked individually against `documents`, and all four resolved.

This is the clearest statement of why orphans are a correctness bug rather than
housekeeping: 76% of the index was text from deleted documents, and retrieval
quality measurement at 3.1 would have been scored against it.

### Four design decisions in the tool, and why

**Five groups, not two.** `orphan` is only one of the ways the stores disagree:

| Group | Meaning | Action |
|---|---|---|
| `agreed` | in both, counts match | none |
| `orphan` | in Qdrant, not in Postgres | **deleted here** |
| `mismatch` | in both, counts differ | re-ingest — keeps the text |
| `missing` | Postgres says N chunks, Qdrant has none | re-ingest; the dual write failed the other way |
| `pending` | in Postgres, never successfully ingested | expected |

Only `orphan` is ever deleted. Deleting a mismatch would throw away a working
document to satisfy a count, when re-ingesting repairs it — which is only true
because Layer 4 made re-ingestion safe.

**SQL, not the backend's API — a correction to the plan, for safety.** The plan
said to read the live list from `GET /documents`. That endpoint caps `limit` at
`MAX_PAGE_SIZE` (200), and **a truncated live list makes live documents look
like orphans.** This tool deletes orphans. The failure mode is deleting the
vectors of perfectly good documents, invisible until there are 201 of them.
Keyset pagination would fix it and is deliberately absent until needed, so a
direct `SELECT` with no ceiling is the safer input for a destructive tool — and
it needs no backend process running.

**The live list arrives as data, not as a database connection.** The tool runs
inside the agent image, and the agent must not learn about Postgres — the
dependency direction `tools/check_dependencies.py` exists to protect. Giving
this script a database driver would have put a Postgres dependency in the agent
image for a maintenance task.

**It reuses `delete_chunks_except(document_id, keep_ids=[])`.** "Keep nothing"
deletes the whole document, so there is one deletion path in the system used
two ways — the pipeline passes the ids it just wrote, the tool passes none —
rather than a second delete function to keep correct.

### Both guards were tested with `--delete` passed

An export is a shell pipeline on the host and can fail quietly: a stopped
container, a wrong database name, a redirection that produced nothing. The
result is a file that reads as *"Postgres contains no documents"*, and acting
on it would delete the entire collection.

```text
$ … qdrant_orphans.py empty.csv --delete
REFUSING: /tmp/live.csv lists no documents. Either the export failed or the
database is empty; both are reasons not to delete anything. Nothing was changed.

$ … qdrant_orphans.py bad.csv --delete
/tmp/live.csv:1: expected 'id,chunk_count', got 'not-a-csv-line'. Refusing to
act on a list it cannot read.
```

Refusing on an empty list is right even though an empty database is possible:
in that case there is nothing worth this tool's risk, and the collection can be
dropped deliberately instead.

The tool also verifies its own work by **re-reading the store** after deleting,
rather than trusting the loop, and exits non-zero if anything is still
orphaned. A delete that silently matched nothing fails there instead of
surprising someone at the next audit.

---

## Layer 6 — the client, and a wiring bug it exposed

### `BaseQueryFn`'s `Meta` parameter was never declared

`uploadDocument` has to tell `200` from `202`, because both responses carry an
identical body and the status code is the only signal. The status lives on
`meta.response`, and `tsc` refused it:

```text
src/services/documentsApi.ts(179,31): error TS2339:
  Property 'response' does not exist on type '{}'.
```

`baseApi.ts` wraps `fetchBaseQuery` to normalise errors, and declared it as
`BaseQueryFn<string | FetchArgs, unknown, ApiFailure>`. `BaseQueryFn`'s fifth
type argument, `Meta`, defaults to `{}` — so the wrapper **discarded the meta
type the inner query already had**, and every `transformResponse` in the
application received `meta: {}`.

**No endpoint in this app could read a response header or a status code**, and
the compiler reported it as a missing property rather than as missing wiring.
It was never specific to uploads: anything wanting `Location`, an `ETag`, a
rate-limit header or a `Retry-After` would have hit the same wall and most
likely been worked around at the call site.

Fixed by naming the type the inner query actually passes:

```ts
BaseQueryFn<string | FetchArgs, unknown, ApiFailure, object, FetchBaseQueryMeta>
```

Worth recording as a category: a wrapper that widens or defaults a type
parameter removes a capability *silently*, and it only surfaces the first time
something needs it — which can be years later and in code that looks unrelated.

### End to end, through the running system

Backend on 8000, worker running, agent in Docker, frontend dev server, real
Qdrant.

```text
POST /documents  l6.pdf                  202   Location: /documents/01a1783f-7597-…
POST /documents  l6.pdf      (same)      200   Location: /documents/01a1783f-7597-…
POST /documents  renamed.pdf (same bytes) 200   filename returned: "l6.pdf"
```

The third is the one to look at: uploading identical bytes under a new name
returns the **stored** filename. The bytes are the identity, so a re-upload
does not rename anything — and the response names the row the user should go
and look at.

**Five concurrent uploads of one file**, through the real HTTP stack:

```text
status codes:  [200, 200, 200, 200, 202]
distinct document ids: 1
```

One caller created and queued; four found it already there. Which one wins is a
race and is not asserted — that exactly one does is the invariant.

### The UI

Driven by dispatching a real `change` event at the hidden file input, so the
component's own handler, mutation and render path all ran rather than the
mutation being called directly.

| | Receipt |
|---|---|
| new bytes | *"ui-check.pdf is queued. Indexing happens in the background — watch its row below for the result."* |
| same bytes again | *"ui-check.pdf was already indexed — these exact bytes are on the server, so nothing was uploaded again. Its row below is the one to look at."* |

The network log confirms `POST → 202` then `POST → 200`, the document count
stays at 7, and no console errors. The second upload was deliberately made
under the name `my-copy.pdf`: the receipt says **ui-check.pdf**, which is the
stored document's name and the row actually on screen.

Without this the dedupe is invisible and reads as a failure — a file dropped,
no new row, no error.

### Final reconciliation

After every live upload in this session:

```text
Postgres: 7 documents
Qdrant:   7 documents, 16 points
ORPHAN 0   MISMATCH 0   MISSING 0   PENDING 0   AGREED 7
```

## Stage 2.2 measures, complete

| Measure | Result |
|---|---|
| duplicate chunks for a re-ingested document | **9 → 3**, then **3 → 3** |
| orphaned points | **39 → 0** |
| five concurrent uploads of one file | **1 document**, one `202`, four `200` |
| the two stores agree | **7 / 7, every category zero** |
