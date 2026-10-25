"""What happens when a worker loses its job and does not know. Stage 2.1.

**This is the file that makes a reaper safe to have.** Everything else in 2.1
is bookkeeping; the one property that cannot be hand-waved is that a worker
which has lost its lease cannot still write a result.

Without it, adding a reaper introduces silent corruption:

    worker A claims job 7
    A pauses — a GC, a VM suspend, a laptop lid
    the lease expires; a reaper requeues job 7
    worker B claims it, indexes it, marks it done
    A wakes up and marks job 7 done
        → overwrites B's counts with A's
        → and the document is now in the index twice

Nothing errors. Nothing logs. The row looks plausible. That is the worst kind
of bug, and it is the one stage 6.4 generalises into fencing tokens across two
datastores — here, one table has atomicity, so a conditional UPDATE is the
whole implementation.

── Why these tests need their own engines ──────────────────────────────────────

The shared `session` fixture wraps each test in one transaction and rolls it
back. Two workers inside one transaction are not two workers — they cannot take
a lease from each other, because they are the same actor. So these commit for
real and clean up after themselves, as `test_claim_concurrency.py` does.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import new_id
from app.repositories.documents import DocumentRepository

CONTENT = b"%PDF-1.7 lease handover probe"

# Short enough that a test can out-wait it without being slow.
TINY_LEASE = 0.5

# Long enough that the *second* worker is never reaped mid-assertion.
SAFE_LEASE = 60.0

MAX_ATTEMPTS = 5


async def seed_one_queued_job(engine) -> uuid.UUID:
    """Commit one document, its bytes and one `queued` job."""
    document_id, job_id = new_id(), new_id()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO documents (id, filename, byte_size, content_type) "
                "VALUES (:id, 'handover.pdf', :size, 'application/pdf')"
            ),
            {"id": document_id, "size": len(CONTENT)},
        )
        await conn.execute(
            text(
                "INSERT INTO document_uploads (document_id, content) "
                "VALUES (:id, :content)"
            ),
            {"id": document_id, "content": CONTENT},
        )
        await conn.execute(
            text(
                "INSERT INTO ingestion_jobs (id, document_id, status) "
                "VALUES (:job, :doc, 'queued')"
            ),
            {"job": job_id, "doc": document_id},
        )
    return document_id


async def read_job(engine, document_id: uuid.UUID):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, attempts, chunk_count, error, "
                    "       lease_token IS NULL AS lease_released "
                    "  FROM ingestion_jobs WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        ).one()


async def cleanup(engine, document_id: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM documents WHERE id = :id"), {"id": document_id}
        )


async def test_a_worker_that_lost_its_lease_cannot_finish_the_job(
    test_database_url: str,
) -> None:
    """**The headline.** A's stale write must affect zero rows.

    The whole sequence, deliberately: A claims with a half-second lease, the
    lease lapses, a reaper requeues, B claims and completes. Then A — which
    has no idea any of that happened — tries to report its own result.

    The assertions that matter are the last two: A is *told* it failed
    (`False`, not an exception), and **B's numbers are the ones in the row**.
    """
    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    document_id = await seed_one_queued_job(engine)

    try:
        # ── Worker A claims, with a lease it will not renew ──────────────────
        async with factory() as session:
            repo = DocumentRepository(session)
            a = await repo.claim_next_queued_job(lease_seconds=TINY_LEASE)
            await session.commit()

        assert a is not None
        assert a.attempts == 1

        # ── A goes away. The lease lapses on its own. ────────────────────────
        await asyncio.sleep(TINY_LEASE + 0.2)

        # ── A reaper notices and requeues ────────────────────────────────────
        async with factory() as session:
            reaped = await DocumentRepository(session).reap_expired_leases(
                max_attempts=MAX_ATTEMPTS
            )
            await session.commit()

        assert reaped.requeued == 1, "the expired lease should have been reclaimed"
        assert reaped.abandoned == 0, "one attempt is not exhaustion"

        # ── Worker B claims the same job and finishes it ─────────────────────
        async with factory() as session:
            repo = DocumentRepository(session)
            b = await repo.claim_next_queued_job(lease_seconds=SAFE_LEASE)
            assert b is not None, "the requeued job must be claimable again"
            assert b.job_id == a.job_id, "it should be the same job"
            assert b.lease_token != a.lease_token, (
                "a new claim must mint a new token, or the stale worker's "
                "write would be indistinguishable from the live one"
            )
            assert b.attempts == 2, "the second claim is the second attempt"

            applied = await repo.mark_job_done(
                b.job_id,
                b.lease_token,
                page_count=9,
                pages_with_text=9,
                characters_extracted=900,
                chunk_count=9,
            )
            await session.commit()
            assert applied is True

        # ── A wakes up, still believing the job is its ───────────────────────
        async with factory() as session:
            repo = DocumentRepository(session)
            stale = await repo.mark_job_done(
                a.job_id,
                a.lease_token,
                page_count=1,
                pages_with_text=1,
                characters_extracted=1,
                chunk_count=1,
            )
            await session.commit()

        assert stale is False, (
            "a worker that lost its lease wrote to the job anyway — the "
            "ownership check is missing and a reaper is not safe to run"
        )

        job = await read_job(engine, document_id)
        assert job.status == "done"
        assert job.chunk_count == 9, (
            "the stale worker's result overwrote the live one"
        )
        assert job.attempts == 2
    finally:
        await cleanup(engine, document_id)
        await engine.dispose()


async def test_a_stale_worker_cannot_fail_a_job_someone_else_is_running(
    test_database_url: str,
) -> None:
    """The same protection on the failure path, and it matters more.

    Marking someone else's job `done` wrongly records a success. Marking it
    `failed` **destroys work that was going fine** — the live worker is still
    ingesting, and its eventual write will now also be rejected because the
    job is terminal and holds no lease.
    """
    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    document_id = await seed_one_queued_job(engine)

    try:
        async with factory() as session:
            repo = DocumentRepository(session)
            a = await repo.claim_next_queued_job(lease_seconds=TINY_LEASE)
            await session.commit()
        assert a is not None

        await asyncio.sleep(TINY_LEASE + 0.2)

        async with factory() as session:
            await DocumentRepository(session).reap_expired_leases(
                max_attempts=MAX_ATTEMPTS
            )
            await session.commit()

        async with factory() as session:
            repo = DocumentRepository(session)
            b = await repo.claim_next_queued_job(lease_seconds=SAFE_LEASE)
            await session.commit()
        assert b is not None

        # A, still asleep in its own mind, gives up.
        async with factory() as session:
            repo = DocumentRepository(session)
            stale = await repo.mark_job_failed(
                a.job_id, a.lease_token, error="A thinks this failed"
            )
            await session.commit()

        assert stale is False

        job = await read_job(engine, document_id)
        assert job.status == "processing", (
            "B is still working on this; a stale worker must not be able to "
            "declare it failed"
        )
        assert job.error is None
    finally:
        await cleanup(engine, document_id)
        await engine.dispose()


async def test_renewing_keeps_a_long_job_alive(test_database_url: str) -> None:
    """The heartbeat, in its simplest form.

    A job that outlives one lease period is not dead — it is working. Renewing
    is how it says so, and it is the reason a one-minute lease can cover a
    four-minute ingest.
    """
    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    document_id = await seed_one_queued_job(engine)

    try:
        async with factory() as session:
            repo = DocumentRepository(session)
            claimed = await repo.claim_next_queued_job(lease_seconds=TINY_LEASE)
            await session.commit()
        assert claimed is not None

        # Outlive the original lease, renewing as a working worker would.
        for _ in range(3):
            await asyncio.sleep(TINY_LEASE / 2)
            async with factory() as session:
                alive = await DocumentRepository(session).renew_lease(
                    claimed.job_id, claimed.lease_token, lease_seconds=TINY_LEASE
                )
                await session.commit()
            assert alive is True, "a renewing worker must keep its lease"

        # A reaper now finds nothing, because the lease is in the future.
        async with factory() as session:
            reaped = await DocumentRepository(session).reap_expired_leases(
                max_attempts=MAX_ATTEMPTS
            )
            await session.commit()

        assert reaped.total == 0, (
            "a worker that is still renewing was reclaimed anyway — the "
            "heartbeat is not extending the deadline"
        )
    finally:
        await cleanup(engine, document_id)
        await engine.dispose()


async def test_renewing_a_lease_you_have_lost_reports_failure(
    test_database_url: str,
) -> None:
    """How a worker finds out, rather than being told by a crash.

    `False`, not an exception: losing a lease is the system working, not an
    error. It is also the earliest possible warning — a worker that checks the
    result can stop before wasting an embedding call on work that will be
    thrown away.
    """
    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    document_id = await seed_one_queued_job(engine)

    try:
        async with factory() as session:
            repo = DocumentRepository(session)
            a = await repo.claim_next_queued_job(lease_seconds=TINY_LEASE)
            await session.commit()
        assert a is not None

        await asyncio.sleep(TINY_LEASE + 0.2)

        async with factory() as session:
            await DocumentRepository(session).reap_expired_leases(
                max_attempts=MAX_ATTEMPTS
            )
            await session.commit()

        async with factory() as session:
            still_mine = await DocumentRepository(session).renew_lease(
                a.job_id, a.lease_token, lease_seconds=TINY_LEASE
            )
            await session.commit()

        assert still_mine is False
    finally:
        await cleanup(engine, document_id)
        await engine.dispose()


async def test_an_exhausted_job_is_abandoned_rather_than_requeued(
    test_database_url: str,
) -> None:
    """The bound on a job that reliably kills its worker.

    Without it, a poison document cycles forever: claimed, crashes the worker,
    reaped, claimed again — each lap costing an ingest attempt and possibly
    embedding quota. The reaper gives up instead, and says so in the error.

    This is the floor under the poison-message problem. Stage 2.3 builds the
    proper handling — a dead-letter queue you can list, inspect and replay.
    """
    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    document_id = await seed_one_queued_job(engine)

    try:
        # Claim and abandon until the attempts are spent.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            async with factory() as session:
                repo = DocumentRepository(session)
                claimed = await repo.claim_next_queued_job(
                    lease_seconds=TINY_LEASE
                )
                await session.commit()

            assert claimed is not None, f"should still be claimable on #{attempt}"
            assert claimed.attempts == attempt

            await asyncio.sleep(TINY_LEASE + 0.1)

            async with factory() as session:
                reaped = await DocumentRepository(session).reap_expired_leases(
                    max_attempts=MAX_ATTEMPTS
                )
                await session.commit()

            if attempt < MAX_ATTEMPTS:
                assert reaped.requeued == 1 and reaped.abandoned == 0
            else:
                assert reaped.abandoned == 1 and reaped.requeued == 0, (
                    "the last attempt must be given up on, not requeued"
                )

        job = await read_job(engine, document_id)
        assert job.status == "failed"
        assert job.attempts == MAX_ATTEMPTS
        assert "Abandoned" in job.error
        assert job.lease_released is True, (
            "a terminal job must not still hold a lease, or a stale worker "
            "could write to it later"
        )

        # And it is not claimable again.
        async with factory() as session:
            repo = DocumentRepository(session)
            assert await repo.claim_next_queued_job(lease_seconds=SAFE_LEASE) is None
    finally:
        await cleanup(engine, document_id)
        await engine.dispose()
