"""The repository, against a real database.

These tests assert behaviour the repository is responsible for — not that
SQLAlchemy works. The two that matter most are the ones about *transaction
boundaries*, because that is the thing stage 1.2 exists to get right and the
thing a unit test with a mocked session could never check.
"""

import hashlib
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    FailureKind,
    IngestionJob,
    IngestionStatus,
)
from app.repositories.documents import DocumentRepository


@pytest.fixture
def repo(session: AsyncSession) -> DocumentRepository:
    return DocumentRepository(session)


# Not a real PDF. The repository stores whatever it is handed — the magic-byte
# check lives in `rag.extraction`, which these tests never reach.
CONTENT = b"%PDF-1.7 pretend this is 2649 bytes of document"

# Long enough that nothing in these tests expires mid-assertion.
# Expiry behaviour belongs to the reaper's own tests, where the
# lease is deliberately short.
LEASE = 60.0


async def create(
    repo: DocumentRepository,
    filename: str = "zephyr-test.pdf",
    content: bytes | None = None,
    request_id: str | None = None,
):
    """A document, its bytes and a **queued** job — what an upload produces.

    ── The hash is derived, never passed in ────────────────────────────────────

    `content_hash` is computed here from `content`, exactly as the upload route
    does it. A helper that let a test supply a hash unrelated to its bytes could
    manufacture states the real system cannot reach, and the tests built on it
    would be describing a different program.

    ── Why the default content is unique per call — stage 2.2 ──────────────────

    It used to be one shared constant, which was fine while nothing deduplicated
    and became wrong the moment `uq_documents_content_hash` existed: two
    `create(repo)` calls in one test are two uploads of **identical bytes**, and
    the database now correctly refuses the second.

    `test_two_documents_are_listed_newest_first` is the one that caught it. It
    creates `first.pdf` and `second.pdf` — two different documents by any
    ordinary reading — and they shared the constant. It was testing ordering,
    broke on uniqueness, and was never wrong.

    **This is the fifth time a new constraint has broken a correct test for a
    reason it was not about.** The pattern each time: the helper knew less about
    the schema than the schema did. So the default is now distinct per call,
    which is also what it always meant — separate uploads are separate files.

    A test that wants a *duplicate* says so by passing the same `content=`
    twice, which reads as the deliberate choice it is.

    ── `request_id` defaults to None — stage 2.4 ──────────────────────────────

    Not to a generated value. `None` is what the column holds for every job
    written before 2.4 and for anything a worker or a script creates outside a
    request, so it is the honest default and the one most tests should see.

    A test about correlation passes one explicitly, which makes the id visible
    in the test that depends on it rather than hidden in this helper.
    """
    if content is None:
        content = CONTENT + b" " + uuid.uuid4().hex.encode()

    return await repo.create_document_with_job(
        filename=filename,
        content=content,
        content_type="application/pdf",
        content_hash=hashlib.sha256(content).hexdigest(),
        request_id=request_id,
    )


async def create_and_claim(
    repo: DocumentRepository, filename: str = "zephyr-test.pdf"
):
    """An upload a worker has already picked up.

    **The `mark_job_*` methods require this state, not the one `create` leaves
    behind.** Marking a `queued` job done would set `finished_at` on a row with
    no `started_at`, and `ck_ingestion_jobs_started_at_matches_status` refuses
    that — correctly, because "it finished and never started" cannot be true.

    So the claim is not a formality these tests could skip: it is the
    transition that makes completion legal. Going through the real
    `claim_next_queued_job` rather than hand-writing a `processing` row means
    they exercise the same sequence the worker does.
    """
    document, job = await create(repo, filename)
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None and claimed.job_id == job.id, (
        "the claim should have taken the job just created"
    )
    # Returned so callers can prove ownership: since stage 2.1 every write
    # that finishes a job needs the token the claim minted.
    return document, job, claimed


# ── Transaction boundaries ───────────────────────────────────────────────────


async def test_creating_a_document_does_not_commit(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The repository stages; the caller commits.

    This is the invariant the whole stage turns on. If the repository committed
    on the caller's behalf, the ordering

        record intent → COMMIT → call the agent → record outcome

    would be decided here rather than in the service that performs it, and the
    next method someone adds would commit too.

    Checked by asking the session whether a transaction is still open with
    changes in it, which is as close to "has this been made durable?" as the
    session can answer from inside its own transaction.
    """
    await create(repo)

    assert session.in_transaction(), "the caller's transaction should still be open"
    assert session.new or session.identity_map, "work should be staged, not gone"


async def test_rolling_back_discards_everything(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """A crash before the commit leaves no trace — which is the correct 1.2
    behaviour for work that was never acknowledged.

    What must *not* happen is the opposite: a commit that lands after the
    agent call and therefore loses the record when the process dies midway.
    """
    document, _ = await create(repo)
    await session.rollback()

    found = await repo.get_document_with_latest_job(document.id)
    assert found is None


async def test_ids_are_available_before_commit(repo: DocumentRepository) -> None:
    """`flush()` populates the ids without ending the transaction.

    This is why the flush is there. The backend has to hand `document.id` to
    the agent, which hands it to `rag.ingest(document_id=...)` and into the
    Qdrant payload — so the id must exist before the work starts, while the
    transaction is still the caller's to end.
    """
    document, job = await create(repo)

    assert document.id is not None
    assert job.document_id == document.id
    assert job.status is IngestionStatus.QUEUED


async def test_the_pair_is_created_together(repo: DocumentRepository) -> None:
    """A document with no attempt attached is a half-truth.

    They are one logical fact — this arrived, and we started work on it — so
    they are staged in one transaction and become durable together.
    """
    document, job = await create(repo)

    found = await repo.get_document_with_latest_job(document.id)
    assert found is not None
    found_document, found_job = found
    assert found_document.id == document.id
    assert found_job is not None
    assert found_job.id == job.id


# ── Terminal transitions ─────────────────────────────────────────────────────


async def test_marking_done_sets_status_and_finish_time_together(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """One UPDATE, because the CHECK constraint permits nothing else.

    `ck_ingestion_jobs_finished_at_matches_status` requires a job to be
    `processing` exactly while `finished_at` is NULL. Setting the status in one
    statement and the timestamp in another fails on the first — the constraint
    shapes the code rather than merely validating it.
    """
    _, job, claimed = await create_and_claim(repo)
    await session.flush()

    await repo.mark_job_done(
        job.id,
        claimed.lease_token,
        page_count=3,
        pages_with_text=3,
        characters_extracted=1269,
        chunk_count=3,
    )
    await session.commit()

    updated = await repo.get_job(job.id)
    assert updated is not None
    assert updated.status is IngestionStatus.DONE
    assert updated.finished_at is not None
    assert updated.chunk_count == 3
    assert updated.error is None


async def test_marking_failed_records_the_reason(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    _, job, claimed = await create_and_claim(repo)
    await session.flush()

    message = "'notes.txt' is not a PDF. It starts with b'just som'."
    await repo.mark_job_failed(
        job.id, claimed.lease_token, error=message, failure_kind=FailureKind.TRANSIENT
    )
    await session.commit()

    updated = await repo.get_job(job.id)
    assert updated is not None
    assert updated.status is IngestionStatus.FAILED
    assert updated.error == message
    assert updated.finished_at is not None
    assert updated.chunk_count is None


async def test_the_finish_time_comes_from_the_database(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """`func.now()`, not a timestamp from this process.

    At stage 12.1 there are several API instances with independent clocks, and
    "which finished first" needs one authority.
    """
    _, job, claimed = await create_and_claim(repo)
    await session.flush()

    before = (await session.execute(text("SELECT now()"))).scalar_one()
    await repo.mark_job_failed(
        job.id, claimed.lease_token, error="unknown", failure_kind=FailureKind.TRANSIENT
    )
    await session.commit()

    updated = await repo.get_job(job.id)
    assert updated is not None
    assert updated.finished_at is not None
    assert updated.finished_at.tzinfo is not None
    assert abs((updated.finished_at - before).total_seconds()) < 5


async def test_a_failure_without_a_reason_is_refused(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The repository cannot route around the constraint either.

    `mark_job_failed` requires `error`, but raw SQL could still try. The
    database is the thing that says no.
    """
    _, job = await create(repo)
    await session.flush()

    with pytest.raises(IntegrityError, match="failed_requires_error"):
        await session.execute(
            text(
                "UPDATE ingestion_jobs SET status='failed', finished_at=now(), "
                "error=NULL WHERE id = :id"
            ),
            {"id": job.id},
        )


# ── The latest-job query ─────────────────────────────────────────────────────


async def test_listing_returns_only_the_most_recent_attempt(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """`DISTINCT ON` — one row per document, the newest attempt.

    The second job is given an explicitly later `started_at`, computed by the
    database, rather than relying on insertion order.

    Two traps here, both of which bit while writing this test:

    **Postgres's `now()` is `transaction_timestamp()`** — the time the
    *transaction* began, not the statement. Every row written inside one
    transaction shares an identical value, and these tests run entirely inside
    one. So "most recent" cannot be established by inserting second.

    **Do not truncate the timestamp.** The first attempt here used
    `datetime.now(timezone.utc).replace(microsecond=0)`, which rounds *down* —
    producing an instant up to a second *earlier* than the transaction's own
    clock, so the "later" job sorted first. The failure looked like a broken
    query rather than a broken fixture.

    Using `now() + interval` keeps one clock and one direction.
    """
    document, first_job, first_claim = await create_and_claim(repo)
    await session.flush()
    await repo.mark_job_failed(
        first_job.id,
        first_claim.lease_token,
        error="transient provider error",
        failure_kind=FailureKind.TRANSIENT,
    )

    await session.execute(
        text(
            # A lease is required of any `processing` row since stage 2.1.
            # Given explicitly rather than via a helper, because this insert is
            # deliberately raw — it is constructing a *second* attempt that the
            # repository has no method for.
            "INSERT INTO ingestion_jobs "
            "  (id, document_id, status, started_at, lease_token, lease_expires_at) "
            "VALUES (gen_random_uuid(), :doc, 'processing', "
            "        now() + interval '1 minute', "
            "        gen_random_uuid(), now() + interval '1 hour')"
        ),
        {"doc": document.id},
    )
    await session.commit()

    rows = await repo.list_documents_with_latest_job()
    assert len(rows) == 1

    _, latest = rows[0]
    assert latest is not None
    assert latest.status is IngestionStatus.PROCESSING
    assert latest.id != first_job.id


async def test_listing_is_newest_document_first(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    await create(repo, filename="first.pdf")
    await session.commit()
    await create(repo, filename="second.pdf")
    await session.commit()

    rows = await repo.list_documents_with_latest_job()
    assert [document.filename for document, _ in rows] == [
        "second.pdf",
        "first.pdf",
    ]


async def test_a_document_with_no_job_still_appears(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The join is an OUTER join on purpose.

    A document with no attempt should not exist. Hiding it with an inner join
    would conceal precisely the kind of inconsistency this stage exists to make
    visible — and the whole stage is about seeing states that used to be
    invisible.
    """
    await session.execute(
        text(
            "INSERT INTO documents (id, filename, byte_size) "
            "VALUES (gen_random_uuid(), 'orphan.pdf', 1)"
        )
    )
    await session.commit()

    rows = await repo.list_documents_with_latest_job()
    assert len(rows) == 1
    document, job = rows[0]
    assert document.filename == "orphan.pdf"
    assert job is None


async def test_an_unknown_document_is_none(repo: DocumentRepository) -> None:
    from uuid import uuid4

    assert await repo.get_document_with_latest_job(uuid4()) is None


# ── Claiming queued work (stage 1.3) ─────────────────────────────────────────
#
# The repository still *creates* `processing` jobs — that flips in Layer 3 —
# so these tests enqueue directly. Which is the right dependency anyway: the
# claim's behaviour should not depend on what happens to be writing the rows.


async def enqueue(
    session: AsyncSession, filename: str = "queued.pdf", **job_overrides: object
) -> IngestionJob:
    """A document with its bytes and one `queued` job, staged not committed."""
    document = Document(
        filename=filename, byte_size=len(CONTENT), content_type="application/pdf"
    )
    job = IngestionJob(
        document=document,
        status=IngestionStatus.QUEUED,
        started_at=None,
        **job_overrides,
    )
    session.add_all([document, job])
    await session.flush()
    return job


async def test_claiming_returns_nothing_when_the_queue_is_empty(
    repo: DocumentRepository,
) -> None:
    """`None`, not an exception. An idle worker is the normal case.

    The worker loop calls this once per tick forever, so "nothing to do" has
    to be an ordinary return value rather than something to catch.
    """
    assert await repo.claim_next_queued_job(lease_seconds=LEASE) is None


async def test_claiming_moves_the_job_to_processing_and_stamps_a_start_time(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The state transition, and the two ids the worker needs.

    Note what is asserted about the return value: the ids come from the
    `UPDATE … RETURNING`, so they describe the row *after* the write. There is
    no second query here and no stale entity to re-read — which is the reason
    the claim is one statement rather than a SELECT followed by an UPDATE.
    """
    job = await enqueue(session)
    document_id = job.document_id

    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)

    assert claimed is not None
    assert claimed.job_id == job.id
    assert claimed.document_id == document_id

    fetched = (
        await session.execute(
            select(IngestionJob)
            .where(IngestionJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    assert fetched.status is IngestionStatus.PROCESSING
    assert fetched.started_at is not None, "a claimed job has started"
    assert fetched.finished_at is None, "and has not finished"


async def test_claiming_ignores_jobs_that_are_not_queued(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """Only `queued` is claimable.

    Without the status filter a worker would re-claim a job another worker is
    already running, or re-run one that finished — so this is the filter that
    makes the table a queue rather than a list of every job that ever existed.
    """
    await create_and_claim(repo)  # now `processing`
    await session.flush()

    assert await repo.claim_next_queued_job(lease_seconds=LEASE) is None, (
        "a job another worker is already running must not be claimable again"
    )


async def test_claiming_takes_the_oldest_queued_job_first(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """FIFO by `queued_at`.

    The timestamps are set explicitly rather than relying on insertion order,
    because `now()` is `transaction_timestamp()` — three jobs created in one
    transaction share an identical `queued_at` and this test would be asserting
    the tiebreaker instead. That case is the next test.
    """
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc)
    middle = await enqueue(session, "middle.pdf", queued_at=base - timedelta(minutes=5))
    oldest = await enqueue(session, "oldest.pdf", queued_at=base - timedelta(minutes=9))
    await enqueue(session, "newest.pdf", queued_at=base)

    first = await repo.claim_next_queued_job(lease_seconds=LEASE)
    second = await repo.claim_next_queued_job(lease_seconds=LEASE)

    assert first is not None and first.job_id == oldest.id
    assert second is not None and second.job_id == middle.id


async def test_jobs_queued_in_one_transaction_are_claimed_in_creation_order(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The `id` tiebreaker, doing real work.

    A batch upload writes several jobs in one transaction, so every one of them
    has the same `queued_at`. Ordering by that column alone leaves the planner
    free to return them in any order — not wrong, but not FIFO either, and
    different on different days.

    `id` is a UUIDv7, so it is both unique and time-ordered: it breaks the tie
    in the order the rows were created, which is what "first in" means.
    """
    first_in = await enqueue(session, "a.pdf")
    second_in = await enqueue(session, "b.pdf")

    assert first_in.queued_at == second_in.queued_at, (
        "both should share transaction_timestamp(), or this test proves nothing"
    )

    first_out = await repo.claim_next_queued_job(lease_seconds=LEASE)
    second_out = await repo.claim_next_queued_job(lease_seconds=LEASE)

    assert first_out is not None and first_out.job_id == first_in.id
    assert second_out is not None and second_out.job_id == second_in.id


# ── Stored uploads (stage 1.3) ───────────────────────────────────────────────


async def test_the_upload_is_written_with_the_document_and_read_back(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """Three rows in one transaction, and the bytes survive the round trip.

    This is what makes a worker possible: the file no longer lives only in the
    request that carried it.
    """
    content = b"%PDF-1.7\x00\xff binary \x80 payload"
    document, _job = await create(repo, content=content)

    assert await repo.get_upload_content(document.id) == content


async def test_the_recorded_size_comes_from_the_content(
    repo: DocumentRepository,
) -> None:
    """`byte_size` is derived, not passed.

    It used to be a parameter alongside the bytes, which invited the two to
    disagree — a caller passing a stale length would have produced a document
    whose recorded size did not match its stored content, with nothing to
    catch it.
    """
    content = b"%PDF-1.7 exactly this long"
    document, _job = await create(repo, content=content)

    assert document.byte_size == len(content)


async def test_reading_the_upload_of_an_unknown_document_returns_none(
    repo: DocumentRepository
) -> None:
    """`None` rather than raising.

    After this stage a job always has an upload — they are written together —
    so this should be unreachable. The worker still handles it, because "the
    input vanished" is a state worth recording on the job rather than a stack
    trace in a log nobody reads.
    """
    from app.db.models import new_id

    assert await repo.get_upload_content(new_id()) is None


# ── Leases and backoff (stage 2.1) ───────────────────────────────────────────


async def test_claiming_mints_a_lease_and_counts_the_attempt(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """A claim is now provisional, and says so in three columns.

    Before 2.1 a claim set a status and a start time and that was the whole of
    it — permanent by omission. The lease is what makes it temporary, and
    `attempts` is what stops a job that keeps killing its worker from being
    retried forever.
    """
    job = await enqueue(session)

    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None

    fetched = (
        await session.execute(
            select(IngestionJob)
            .where(IngestionJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    assert fetched.lease_token == claimed.lease_token
    assert fetched.lease_expires_at is not None
    assert fetched.attempts == 1 == claimed.attempts
    assert fetched.next_attempt_at is None, (
        "claiming is the attempt that was being waited for"
    )


async def test_each_claim_mints_a_different_token(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The token identifies the **claim**, not the worker.

    If it named the worker, a worker that lost a lease and later re-claimed the
    same job could not tell its two attempts apart — and a write left over from
    the first would be accepted during the second.
    """
    await enqueue(session)
    first = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert first is not None

    await repo.requeue_job(
        first.job_id,
        first.lease_token,
        error="try again",
        failure_kind=FailureKind.TRANSIENT,
        delay_seconds=0,
    )
    second = await repo.claim_next_queued_job(lease_seconds=LEASE)

    assert second is not None
    assert second.job_id == first.job_id
    assert second.lease_token != first.lease_token
    assert second.attempts == 2


async def test_a_requeued_job_waits_for_its_backoff(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The delay lives in the row, not in a worker's sleep.

    A worker that slept would hold a process doing nothing and would forget the
    delay entirely on restart. A timestamp survives both, and every worker
    honours it with one extra clause in the claim.
    """
    await enqueue(session)
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None

    await repo.requeue_job(
        claimed.job_id,
        claimed.lease_token,
        error="the agent did not respond",
        failure_kind=FailureKind.TRANSIENT,
        delay_seconds=300,
    )

    assert await repo.claim_next_queued_job(lease_seconds=LEASE) is None, (
        "a job still inside its backoff window must not be claimable"
    )


async def test_a_requeued_job_keeps_the_reason_it_is_waiting(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """`failed_requires_error` does not apply to a `queued` row, so this is a
    choice rather than a requirement.

    Keeping the error is what lets the client say "retrying after: the agent
    did not respond" instead of showing a row indistinguishable from a fresh
    upload.
    """
    job = await enqueue(session)
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None

    await repo.requeue_job(
        claimed.job_id,
        claimed.lease_token,
        error="provider timeout",
        failure_kind=FailureKind.TRANSIENT,
        delay_seconds=0,
    )

    fetched = (
        await session.execute(
            select(IngestionJob)
            .where(IngestionJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    assert fetched.status is IngestionStatus.QUEUED
    assert fetched.error == "provider timeout"
    assert fetched.started_at is None, (
        "a requeued job has no current attempt, and the constraint requires it"
    )
    assert fetched.lease_token is None


async def test_the_reaper_leaves_live_leases_alone(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The failure mode nobody tests for: a reaper that is too eager.

    Reclaiming a job from a worker that is still working means the work is done
    twice and the first result is discarded. The lease is the only thing
    standing between a long ingest and that, so the reaper must respect it.
    """
    await enqueue(session)
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None

    reaped = await repo.reap_expired_leases(max_attempts=5)

    assert reaped.total == 0


# ── Content hash and re-attempts (stage 2.2) ─────────────────────────────────


async def test_a_document_is_findable_by_its_content_hash(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The read that makes an upload idempotent.

    Note what it is *not*: a lookup by filename. The same bytes are the same
    document whatever they were called, which is the whole shift this stage
    makes.
    """
    content = CONTENT + b" findable"
    document, job = await create(repo, filename="original.pdf", content=content)
    await session.commit()

    found = await repo.get_by_content_hash(hashlib.sha256(content).hexdigest())

    assert found is not None
    fetched_document, fetched_job = found
    assert fetched_document.id == document.id
    assert fetched_job is not None and fetched_job.id == job.id, (
        "the lookup must return the latest job too — the caller's next "
        "decision depends on whether it failed"
    )


async def test_an_unknown_hash_finds_nothing(repo: DocumentRepository) -> None:
    """`None`, not an exception. A first upload is the ordinary case."""
    assert await repo.get_by_content_hash("f" * 64) is None


async def test_the_lookup_returns_the_second_job_not_the_first(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """A document with two attempts must report the second one.

    This is the assertion that makes the duplicate-upload decision possible:
    "the last attempt failed" is the signal that a re-upload should queue
    another one, and reading a stale job would answer it wrongly.

    ── What this actually proves, which is not what it first appeared to ──────

    It proves the **`id DESC` tiebreaker**, not recency — and that was found by
    mutating the query, not by reading it.

    Flipping `queued_at` to `ASC` in `_latest_job_subquery` left this test
    green. Flipping `id` to `ASC` broke it. The reason is the test fixture:
    `session.commit()` here runs inside the outer transaction the fixture rolls
    back, so it does not start a new one — and `queued_at` defaults to
    `now()`, which is `transaction_timestamp()`. **Every row written during one
    test therefore shares an identical `queued_at`**, and the tiebreaker
    decides every ordering question.

    That is worth knowing beyond this test. Any test that expects two commits
    to be ordered *in time* is relying on the tiebreaker without saying so, and
    will keep passing if the time ordering is broken.

    `test_recency_beats_the_id_tiebreaker` below is the one that pins the other
    half, by writing `queued_at` explicitly so the two columns disagree.
    """
    content = CONTENT + b" two attempts"
    document, first = await create(repo, content=content)
    await session.commit()

    second = await repo.create_job_for_document(document.id, request_id=None)
    await session.commit()

    found = await repo.get_by_content_hash(hashlib.sha256(content).hexdigest())

    assert found is not None
    _, latest = found
    assert latest is not None
    assert latest.id == second.id, "the later-minted id, not the first"
    assert latest.id != first.id


async def test_recency_beats_the_id_tiebreaker(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """`queued_at DESC` is the primary sort; `id DESC` only breaks ties.

    The two cannot be told apart by any test that lets the database supply
    `queued_at`, because within one test every default timestamp is identical —
    see the test above. So this one writes `queued_at` by hand and makes the
    two columns **disagree**:

        job A   minted first  (smaller uuid7)   queued_at = now
        job B   minted second (larger uuid7)    queued_at = an hour ago

    `queued_at DESC` picks A. `id DESC` picks B. Asserting A is therefore the
    only way to show which one leads.

    It matters in production rather than only in theory. A job requeued by the
    reaper keeps its original `queued_at` while new uploads arrive with later
    ids, so "which attempt is current?" is a question the id alone answers
    wrongly for exactly the documents this stage cares about.
    """
    document, _ = await create(repo)
    await session.commit()

    # Clear the slate: this test wants exactly the two jobs it writes.
    await session.execute(
        text("DELETE FROM ingestion_jobs WHERE document_id = :d"),
        {"d": document.id},
    )

    newest_but_older_id = IngestionJob(
        document_id=document.id,
        status=IngestionStatus.QUEUED,
        started_at=None,
        queued_at=func.now(),
    )
    session.add(newest_but_older_id)
    await session.flush()

    oldest_but_newer_id = IngestionJob(
        document_id=document.id,
        status=IngestionStatus.QUEUED,
        started_at=None,
        queued_at=func.now() - func.make_interval(0, 0, 0, 0, 1),
    )
    session.add(oldest_but_newer_id)
    await session.flush()

    assert oldest_but_newer_id.id > newest_but_older_id.id, (
        "uuid7 must be time-ordered, or this test is not testing a conflict"
    )

    found = await repo.get_document_with_latest_job(document.id)

    assert found is not None
    _, latest = found
    assert latest is not None
    assert latest.id == newest_but_older_id.id, (
        "the most recently queued job must win over the larger id"
    )


async def test_a_second_job_needs_no_second_document_or_blob(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """`create_job_for_document` adds one row and nothing else.

    The claim being tested is a cost claim: re-driving a document must not pay
    for a second copy of its bytes. One `document_uploads` row before, one
    after.
    """
    document, _ = await create(repo)
    await session.commit()

    job = await repo.create_job_for_document(document.id, request_id=None)
    await session.commit()

    assert job.status is IngestionStatus.QUEUED
    assert job.started_at is None, "a fresh attempt has not started"
    assert job.attempts == 0, (
        "a new attempt starts at zero — inheriting the failed job's count "
        "would mean a deliberate re-upload began halfway through its budget"
    )
    assert job.lease_token is None
    assert job.next_attempt_at is None, "claimable now, not after a backoff"

    documents = (
        await session.execute(
            select(func.count()).select_from(Document)
        )
    ).scalar_one()
    uploads = (
        await session.execute(
            text("SELECT count(*) FROM document_uploads")
        )
    ).scalar_one()
    jobs = (
        await session.execute(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.document_id == document.id)
        )
    ).scalar_one()

    assert (documents, uploads, jobs) == (1, 1, 2), (
        "one document, one blob, two attempts"
    )


async def test_a_second_attempt_is_claimable_like_any_other(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The new job must be ordinary, not special.

    If a re-attempt needed its own code path in the worker, the two-table
    design would have bought nothing. The proof that it does not is that the
    unmodified claim picks it up.
    """
    document, first = await create(repo)
    await session.commit()

    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None and claimed.job_id == first.id
    assert await repo.mark_job_failed(
        first.id,
        claimed.lease_token,
        error="broken on the first try",
        failure_kind=FailureKind.TRANSIENT,
    )
    await session.commit()

    second = await repo.create_job_for_document(document.id, request_id=None)
    await session.commit()

    reclaimed = await repo.claim_next_queued_job(lease_seconds=LEASE)

    assert reclaimed is not None
    assert reclaimed.job_id == second.id
    assert reclaimed.document_id == document.id
    assert reclaimed.attempts == 1, "its own first attempt, not the document's"


async def test_a_duplicate_hash_is_refused_by_the_database(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The repository does **not** guard against this, and must not.

    `create_document_with_job` could check for an existing hash first and
    refuse politely. It would also be wrong: two concurrent callers would both
    find nothing and both proceed, so the check would create a false sense of
    safety while the constraint did the actual work.

    So the method lets the INSERT fail, and the service decides what a
    duplicate means. This test pins that division of labour.
    """
    content = CONTENT + b" the very same bytes"
    await create(repo, filename="first.pdf", content=content)
    await session.flush()

    with pytest.raises(IntegrityError, match="uq_documents_content_hash"):
        await create(repo, filename="second.pdf", content=content)


# ── The dead-letter view (stage 2.3) ─────────────────────────────────────────


async def test_the_status_filter_reads_the_latest_job_only(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """**The whole correctness of the dead-letter list is this test.**

    A document that failed once and has since succeeded must not appear in
    `status=failed`. The operator's list is a list of things to *act on*, and
    a document someone already fixed is the one entry guaranteed to waste
    their time — worse, retrying it re-indexes a document that is perfectly
    fine.

    The bug this guards against is a one-word difference: filtering
    `IngestionJob.status` rather than the aliased latest job. Both compile,
    both return rows, and the wrong one is only visibly wrong for documents
    with more than one attempt — which is exactly the population the
    dead-letter list is about.
    """
    document, first = await create(repo)
    await session.commit()

    # Attempt one fails.
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None
    assert await repo.mark_job_failed(
        first.id,
        claimed.lease_token,
        error="the agent did not respond",
        failure_kind=FailureKind.TRANSIENT,
    )
    await session.commit()

    dead = await repo.list_documents_with_latest_job(
        status=IngestionStatus.FAILED
    )
    assert [d.id for d, _ in dead] == [document.id], "it is dead right now"

    # Attempt two succeeds.
    second = await repo.create_job_for_document(document.id, request_id=None)
    await session.commit()
    reclaimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert reclaimed is not None and reclaimed.job_id == second.id
    assert await repo.mark_job_done(
        second.id,
        reclaimed.lease_token,
        page_count=3,
        pages_with_text=3,
        characters_extracted=100,
        chunk_count=3,
    )
    await session.commit()

    dead_now = await repo.list_documents_with_latest_job(
        status=IngestionStatus.FAILED
    )
    assert dead_now == [], (
        "a document whose latest attempt succeeded is not dead, even though "
        "it still has a failed job in its history"
    )

    done = await repo.list_documents_with_latest_job(
        status=IngestionStatus.DONE
    )
    assert [d.id for d, _ in done] == [document.id]


async def test_an_unfiltered_list_still_shows_a_document_with_no_job(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The filter must not quietly turn the outer join into an inner one.

    A document with no job at all should be impossible — both rows are written
    in one transaction — and the unfiltered list has always shown it anyway,
    because hiding an inconsistency is how it survives.

    Adding a `WHERE` on the joined job would drop such a row from *every*
    listing if it were applied unconditionally. It is applied only when
    `status` is given, and this pins that.
    """
    document = Document(
        filename="orphaned.pdf",
        byte_size=10,
        content_type="application/pdf",
        content_hash=hashlib.sha256(b"orphaned").hexdigest(),
    )
    session.add(document)
    await session.commit()

    everything = await repo.list_documents_with_latest_job()
    rows = {d.id: j for d, j in everything}

    assert document.id in rows, "a job-less document must still be listed"
    assert rows[document.id] is None, "and its job must come back as None"


async def test_the_filter_accepts_every_status(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """Cheap, and it catches the filter being wired to the wrong column.

    `queued` is the interesting one: it is the only status a brand-new
    document has, so a filter that silently matched nothing would look
    plausible on `failed` (usually empty anyway) and be obviously wrong here.
    """
    document, _ = await create(repo)
    await session.commit()

    queued = await repo.list_documents_with_latest_job(
        status=IngestionStatus.QUEUED
    )
    assert [d.id for d, _ in queued] == [document.id]

    for other in (IngestionStatus.PROCESSING, IngestionStatus.DONE,
                  IngestionStatus.FAILED):
        assert await repo.list_documents_with_latest_job(status=other) == []


# ── Correlation (stage 2.4) ──────────────────────────────────────────────────


async def test_a_replay_carries_the_replay_request_not_the_upload(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """**The reason `request_id` is on the job and not on the document.**

    One document, two attempts, two requests. If the id lived on `documents`
    it would record the original upload forever — so the question a replay
    exists to answer, *"who asked for attempt two and why?"*, would point at a
    request from days earlier.
    """
    document, first = await create(repo, request_id="req-upload")
    await session.commit()

    second = await repo.create_job_for_document(
        document.id, request_id="req-replay"
    )
    await session.commit()

    assert first.request_id == "req-upload"
    assert second.request_id == "req-replay"
    assert second.document_id == document.id, "same document, different request"


async def test_a_job_created_outside_a_request_has_no_id(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """`None` is a legal, meaningful value — not a gap to be filled.

    Jobs written before stage 2.4, and anything a script or a future scheduler
    creates, have no request to attribute. Generating a placeholder would be
    worse than the null: it would look like a real id, and whoever searched the
    logs for it would find nothing with no way to tell whether the lines were
    missing or the id was invented.
    """
    _, job = await create(repo, request_id=None)
    await session.commit()

    assert job.request_id is None
async def test_the_claim_returns_the_request_that_created_the_job(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    """The API writes it; the worker must get it back.

    This is the whole mechanism in one test. The queue is a table, so the row
    is the *only* channel between the two processes — and the claim is an
    `UPDATE … RETURNING`, so the value the worker receives comes from the
    statement that performed the claim rather than from a second read that
    could see a different row.
    """
    document, job = await create(repo, request_id="req-upload-1")
    await session.commit()

    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)

    assert claimed is not None
    assert claimed.job_id == job.id
    assert claimed.request_id == "req-upload-1", (
        "the worker cannot log the API's request id unless the claim returns it"
    )


