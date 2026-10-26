# 0002 — Stage 2.2 baseline: what Postgres and Qdrant actually disagree about

**Date:** 2026-10-26
**Stage:** 2.2 (Idempotency), run *before* any code change so the before-numbers
are real rather than remembered.
**Status:** complete. All figures `[measured]`.

## Why this exists

Stage 2.2's **Problem** row was labelled `[hypothesis]` — *"after a retry the
same fact is cited twice from the same page, and the Qdrant point count is
double what it should be"*. 2.1's retries have now run, so the hypothesis is
testable. It is also the stage's **Diagnose** step: *compare chunk count to
expected; inspect duplicate payloads*.

## Method

Two independent reads, neither of which trusts the other's bookkeeping.

**Postgres**, via `psql` against the running container — every document with its
latest job, and the SHA-256 of its stored bytes computed by the database:

```sql
SELECT d.id, length(u.content), encode(sha256(u.content),'hex')
  FROM documents d LEFT JOIN document_uploads u ON u.document_id = d.id;
```

**Qdrant**, by scrolling every point's `document_id` and `chunk_index`.

Qdrant is still **embedded** — a library inside the agent container holding an
exclusive lock on the `myrag_agent_qdrant_data` volume — so no host process and
no second process in that container can open it while the agent runs. The audit
therefore ran in a one-shot container built from the agent image, with the agent
stopped:

```bash
docker compose stop agent
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "<scratchpad>/audit:/audit:ro" --entrypoint python agent /audit/qdrant_audit.py
docker compose start agent
```

`MSYS_NO_PATHCONV=1` is required: Git Bash rewrites `/audit` into a Windows path
and the container then looks for `/app/agent/C:/Program Files/Git/audit/...`.

Downtime: a few seconds, in development. The agent came back `healthy`.

## Results

### Qdrant holds four times as many documents as Postgres

| | documents | points |
|---|---|---|
| in Qdrant | **22** | **54** |
| live in Postgres | **4** | **15** |
| **orphans** — in Qdrant, no Postgres row | **18** | **39** (72% of the collection) |

The orphans are the third defect, and it was found by accident rather than
predicted: **`ON DELETE CASCADE` stops at the edge of Postgres.** Deleting a
document row removes its job and its blob and leaves its vectors behind. Three
quarters of the index is the residue of deleted test documents.

Those 39 points are not inert. They are returned by `search()` like any others,
so a question today can be answered with a citation to a document that no longer
exists — and `GET /documents/{id}` on it returns 404. Retrieval quality
measurement at 3.1 would have been measuring against this.

### One document is doubly indexed, and the duplication is index-level

```text
document                               Postgres   Qdrant   chunk_index values
01a153bf-1ac5-76e6-95ed-2dbfd5c89768      3          3      [0, 1, 2]        ✓
01a153cd-13ce-7786-995f-369c0c82377e      3          6      [0,0, 1,1, 2,2]  ✗
01a153d3-76f2-7170-acfe-ccdcbe3d05f5      3          3      [0, 1, 2]        ✓
01a158e4-f2f8-7175-9ff1-8b22511217f3      3          3      [0, 1, 2]        ✓
```

`01a153cd` has `attempts = 2`. It is the job that was stranded at the end of
1.3, recovered itself when 2.1's reaper first ran, and was therefore ingested
twice.

**The `chunk_index` column is the proof, and it is more precise than the count.**
Each index appears exactly twice, under two different random point ids. The two
runs produced identical chunks and could not overwrite each other, because
`vector_store.py:159` mints `uuid.uuid4()` per point per run. Nothing about the
*content* differs; only the id does. That is exactly the defect
`uuid5(namespace, f"{document_id}:{chunk_index}")` removes.

So the stage's **Problem** row moves from `[hypothesis]` to **`[measured]`**:
one retry, one document, 6 points where 3 are correct — a 100% overcount on the
affected document, and the second embedding bill was paid in full.

### Every document in the database is the same file

| document | bytes | SHA-256 |
|---|---|---|
| 01a153bf-… | 1244 | `b385a0c2a483ab00c1070883c85c29ae53145637aed53ad3b1cd1b4c2efea295` |
| 01a153cd-… | 1244 | `b385a0c2…` *(identical)* |
| 01a153d3-… | 1244 | `b385a0c2…` *(identical)* |
| 01a158e4-… | 1244 | `b385a0c2…` *(identical)* |

Four documents, four blobs, four embedding bills, **one file**. Not a surprise
in itself — `models.py:133` says `filename` is deliberately not unique and that
nothing deduplicates yet — but it turns the second defect from a scenario into
the entire contents of the database.

**This changes the Layer 1 migration**, and the change is recorded with the plan
rather than hidden in the code. The plan expected to backfill every row's hash
and then create a unique index, and said the migration would fail loudly on
genuine duplicates. It would fail on *every* row. See the decision below.

## Decision forced by the data: backfill the canonical row only

```sql
UPDATE documents d SET content_hash = h.hash
  FROM (
    SELECT DISTINCT ON (encode(sha256(u.content), 'hex'))
           u.document_id, encode(sha256(u.content), 'hex') AS hash
      FROM document_uploads u JOIN documents dd ON dd.id = u.document_id
     ORDER BY encode(sha256(u.content), 'hex'), dd.created_at, dd.id
  ) h
 WHERE d.id = h.document_id;
```

The oldest document per hash group gets the hash. Its duplicates keep `NULL`,
which the unique index permits without limit because Postgres treats NULLs as
distinct.

**Why not delete the three duplicates.** It is the obvious fix and it destroys
data to satisfy a constraint invented after the data was written. These rows
were created under a rule the system genuinely had at the time — *every upload
is a document*. Rewriting them into one document would backdate a decision, and
the two things a reader would then want to know (how many times was this
uploaded, and when) would be gone. It would also delete the only live specimen
of the duplicate-chunk corruption, which is the stage's headline measure.

**Why not skip the backfill entirely.** Also non-destructive, and it leaves
dedupe not applying to any pre-2.2 document: a fifth upload of these bytes
would create a fifth document. Backfilling the canonical row makes the next
upload of this file dedupe correctly, which is the behaviour the stage is for.

**The cost, stated plainly.** Three rows carry `NULL` forever and are
permanently exempt from the uniqueness rule. A future reader will find
duplicates that the constraint should have prevented, and the explanation is
this file. The alternative — `NOT NULL` — would require inventing a hash for
documents whose bytes do not exist, which is worse.

## Carried into the implementation

1. The baseline for the two measures: **orphan points 39 → 0** and
   **`01a153cd` 6 points → 3**.
2. `chunk_index` is contiguous from 0 in all 22 documents, including the
   corrupt one (`[0,0,1,1,2,2]` is contiguous with duplicates). The tail-delete
   in Layer 4 depends on that, and a test now asserts it.
3. The audit script becomes `tools/qdrant_orphans.py` in Layer 5, with the
   `MSYS_NO_PATHCONV=1` and agent-stopped requirements documented beside it.

## Note on an unrelated warning

The one-shot container printed, after the results:

```text
Exception ignored while calling deallocator <function QdrantClient.__del__>:
ImportError: sys.meta_path is None, Python is likely shutting down
```

`QdrantClient.__del__` imports during interpreter shutdown, when imports no
longer work. Harmless — it fires after the output is flushed, and the `__del__`
only closes a local store that the process is about to release anyway. Worth
recording so it is not mistaken for a failed audit next time. The fix, if it
ever matters, is `contextlib.closing` around the client; `get_client` is
`lru_cache`d precisely so nothing closes it mid-process, so this is left alone.

---

## Addendum — Layer 1 mutation tests (2026-10-26)

Two of the new schema tests make claims that could pass for the wrong reason, so
both were mutated against the development database inside a transaction that was
rolled back. The constraint and the four rows were verified intact afterwards.

**Mutation 1 — is the database refusing duplicate hashes, or is SQLAlchemy?**

```sql
ALTER TABLE documents DROP CONSTRAINT uq_documents_content_hash;
INSERT INTO documents (…, content_hash) VALUES (…, 'ccc…'), (…, 'ccc…');
→ INSERT 0 2
```

Both rows landed. The test is proving the constraint.

**Mutation 2 — would `NULLS NOT DISTINCT` break the un-hashable rows?**

The answer is stronger than the test asserts: the constraint **cannot be
created** at all.

```sql
ALTER TABLE documents ADD CONSTRAINT uq_documents_content_hash
      UNIQUE NULLS NOT DISTINCT (content_hash);
→ ERROR: could not create unique index "uq_documents_content_hash"
  DETAIL: Key (content_hash)=(null) is duplicated.
```

So nullable-with-NULLS-DISTINCT is not merely the convenient choice over
`NOT NULL` — given the three duplicate rows the backfill deliberately left
alone, it is the **only** form of this constraint the existing data admits
without deleting rows or inventing hashes. That is worth knowing because the
reverse mistake is one keyword away in the migration and would fail at deploy
time rather than in review.

**Result of Layer 1:** 105 backend tests pass. `upgrade → downgrade -1 →
upgrade` all exit 0, and `--autogenerate` produces an empty `upgrade()`, so the
models and the migrated schema agree.

---

## Addendum — Layer 2 mutation tests found an untested invariant (2026-10-26)

`get_by_content_hash` reuses `_latest_job_subquery`, whose whole job is to
return the *current* attempt. Its new test asserted exactly that, so the query
was mutated to check the test was load-bearing.

**Mutation A — `queued_at DESC` → `ASC`: the test stayed green.**

That should be impossible. The recency ordering is the only reason the query
returns the second job rather than the first.

**Mutation B — `id DESC` → `ASC`: the test failed.**

So the test was driven entirely by the tiebreaker, and said nothing about
recency.

### Root cause: `session.commit()` in a test does not advance the clock

`queued_at` defaults to `now()`, which in Postgres is
`transaction_timestamp()` — fixed for the whole transaction. The test fixture
runs each test inside an outer transaction it rolls back afterwards, so a
`session.commit()` inside a test does **not** begin a new one.

**Every row written during one test therefore shares an identical `queued_at`**,
and `id DESC` silently decides every ordering question.

### Why this mattered beyond one test

`_latest_job_subquery` backs `get_document_with_latest_job`,
`list_documents_with_latest_job` and now `get_by_content_hash` — the read
endpoints and the duplicate-upload decision. Its primary sort had **no test
capable of failing**, and nothing in the suite would have noticed if it were
removed. The subquery's own docstring argues carefully for both columns; one of
the two arguments was unverified.

It is not academic. A job requeued by 2.1's reaper keeps its original
`queued_at` while later uploads arrive with larger uuid7 ids, so "which attempt
is current?" is a question the id alone answers wrongly for precisely the
documents under retry.

### The fix: make the two columns disagree

`test_recency_beats_the_id_tiebreaker` writes `queued_at` by hand so the
columns point at different rows:

```text
job A   minted first  (smaller uuid7)   queued_at = now
job B   minted second (larger uuid7)    queued_at = an hour ago
```

`queued_at DESC` picks A; `id DESC` picks B. Asserting A is the only way to show
which one leads. The existing test was renamed to
`test_the_lookup_returns_the_second_job_not_the_first` and its docstring now
states that it pins the tiebreaker, because that is what it does.

Re-mutated afterwards, each failure now lands on exactly one test:

| Mutation | Test that fails |
|---|---|
| `queued_at DESC → ASC` | `test_recency_beats_the_id_tiebreaker` |
| `id DESC → ASC` | `test_the_lookup_returns_the_second_job_not_the_first` |

**Result of Layer 2:** 112 backend tests pass; `--autogenerate` still produces
an empty `upgrade()`.

### A second, smaller consequence: every test helper reused the same bytes

`uq_documents_content_hash` broke twelve passing tests across four files, none
of which was about uniqueness. Each had an upload helper handing every document
one shared `PDF` constant — so two uploads in one test were two uploads of
identical bytes, which the database now correctly refuses.

This is the **fifth** time a new constraint has broken correct tests here, and
the pattern is identical every time: the helper knew less about the schema than
the schema did. The helpers now produce distinct bytes per call, which is what
they always meant (separate uploads are separate files), and the three tests
that genuinely assert on exact bytes or lengths pass their content explicitly.

---

## Addendum — Layer 3 mutation test caught a test that proved nothing (2026-10-26)

The whole of Layer 3 rests on one mechanism: the INSERT runs inside a SAVEPOINT
so that a unique-constraint violation can be recovered from instead of aborting
the request's transaction. `test_the_loser_of_the_race_does_not_raise` was
written specifically to pin it.

**Mutation — removed `begin_nested()`:**

| Test | Caught it? |
|---|---|
| `test_two_simultaneous_uploads_of_the_same_bytes` (`asyncio.gather`) | yes |
| `test_an_unrelated_integrity_error_is_not_swallowed` | yes |
| `test_the_loser_of_the_race_does_not_raise` | **no** |

The one written for the job was the one that did not fail.

### Why it passed without the savepoint

The test committed A's document and *then* called B's `accept_upload`, expecting
B's INSERT to collide. By that point A's row was committed, so **B's own
fast-path lookup found it** and B never attempted an INSERT at all. The test
exercised the fast path while claiming to exercise the recovery.

The lesson generalises past this test. The race window is *"the lookup returned
nothing, but by the time we insert, the row exists"* — and that window is
**inside one call**. No ordering of two calls from outside can land in it. A
test that tries to is testing something else and will say so only if mutated.

### The fix: simulate the stale read, not the ordering

`test_the_loser_of_the_race_recovers_instead_of_raising` forces B's first
lookup to miss — exactly what a concurrent caller observes — and leaves every
later lookup real. The INSERT, the constraint and the recovery lookup are all
genuine. It then asserts the lookup ran **twice**, which is what distinguishes
"recovered from a collision" from "took the fast path":

```python
assert calls["n"] == 2, (
    "the INSERT must have been attempted and recovered from — one "
    "lookup means B took the fast path and this test proved nothing"
)
```

Re-mutated, all three tests now fail without the savepoint, and the failure is
`PendingRollbackError`: the `IntegrityError` aborts the whole Postgres
transaction, so the recovery lookup cannot run and the caller receives a 500
for an upload that actually succeeded.

**Result of Layer 3:** 122 backend tests pass; `--autogenerate` still produces
an empty `upgrade()`.

### A coverage gap closed on the way

`POST /documents` had **no HTTP-level test at all** — surprising for the
route the whole product starts with, and unavoidable now: the `200`-versus-`202`
distinction *is* the layer, and a status code cannot be tested below the route.
`test_duplicate_upload.py` drives it through the real `client` fixture, starting
with `test_a_first_upload_is_accepted_and_queued`, without which every `200`
assertion that follows would be vacuous.
