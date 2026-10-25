"""Claiming a job under concurrency. Stage 1.3.

**This is the file that proves the queue is a queue.** Everything else about
1.3 is plumbing; the one property that cannot be hand-waved is that two workers
polling the same table never take the same job. If they do, the document is
ingested twice, embedded twice — real money — and chunked twice, so the same
fact gets cited twice from the same page.

── Why these tests do not use the usual fixtures ───────────────────────────────

The `session` fixture in `conftest.py` wraps every test in one transaction and
rolls it back, which is what makes the rest of the suite fast and isolated. It
also makes concurrency untestable: two sessions sharing one transaction cannot
contend for a row lock, because they *are* the same transaction.

So these tests open their own engines, commit for real, and clean up after
themselves — the same trade `test_the_row_is_durable_before_the_agent_is_called`
makes for the same reason.

── The three things asserted ───────────────────────────────────────────────────

1. one queued job, two claimers → exactly one wins
2. two queued jobs, two claimers → each gets a different one, **and neither
   waits**
3. without `SKIP LOCKED`, the second claimer blocks — the mutation that shows
   the clause is load-bearing rather than decorative
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import new_id
from app.repositories.documents import DocumentRepository

CONTENT = b"%PDF-1.7 concurrency probe"

# Long enough that a non-blocking claim always finishes inside it, short enough
# that a blocked one is detected quickly rather than hanging the suite.
PATIENCE_SECONDS = 3.0

# These tests are about locking, not expiry. A long lease keeps the reaper's
# concerns out of them.
LEASE = 60.0


async def seed_queued_jobs(engine, count: int) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Commit `count` documents each with one `queued` job.

    Raw SQL on purpose. The repository writes `processing` jobs until Layer 3,
    and going through the ORM here would mean reproducing its session
    machinery for no benefit — the test is about what the database does under
    contention, not about how rows get there.
    """
    document_ids = [new_id() for _ in range(count)]
    job_ids = [new_id() for _ in range(count)]

    async with engine.begin() as conn:
        for index, (document_id, job_id) in enumerate(zip(document_ids, job_ids)):
            await conn.execute(
                text(
                    "INSERT INTO documents (id, filename, byte_size, content_type) "
                    "VALUES (:id, :name, :size, 'application/pdf')"
                ),
                {
                    "id": document_id,
                    "name": f"queued-{index}.pdf",
                    "size": len(CONTENT),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO document_uploads (document_id, content) "
                    "VALUES (:id, :content)"
                ),
                {"id": document_id, "content": CONTENT},
            )
            # `started_at` omitted entirely, which is now NULL — the column has
            # no default since stage 1.3, which is what makes `queued` writable.
            await conn.execute(
                text(
                    "INSERT INTO ingestion_jobs (id, document_id, status) "
                    "VALUES (:id, :doc, 'queued')"
                ),
                {"id": job_id, "doc": document_id},
            )

    return document_ids, job_ids


async def delete_documents(engine, document_ids: list[uuid.UUID]) -> None:
    """Cascades to jobs and uploads, so one DELETE is the whole cleanup."""
    async with engine.begin() as conn:
        for document_id in document_ids:
            await conn.execute(
                text("DELETE FROM documents WHERE id = :id"), {"id": document_id}
            )


async def test_two_claimers_cannot_take_the_same_job(
    test_database_url: str,
) -> None:
    """One queued job, two workers. Exactly one wins and the other gets `None`.

    The sequence matters. While worker A's transaction is open it holds a row
    lock, and `SKIP LOCKED` makes B treat that row as absent — so B gets
    `None` rather than a duplicate. After A commits, the row is `processing`
    and no longer matches the `queued` filter, so B still gets nothing on a
    retry. Two different mechanisms, and the job is protected by both.
    """
    engine_a = create_async_engine(test_database_url)
    engine_b = create_async_engine(test_database_url)
    factory_a = async_sessionmaker(bind=engine_a, expire_on_commit=False)
    factory_b = async_sessionmaker(bind=engine_b, expire_on_commit=False)

    document_ids, job_ids = await seed_queued_jobs(engine_a, 1)

    try:
        async with factory_a() as session_a, factory_b() as session_b:
            repo_a = DocumentRepository(session_a)
            repo_b = DocumentRepository(session_b)

            claimed_by_a = await repo_a.claim_next_queued_job(lease_seconds=LEASE)
            assert claimed_by_a is not None, "the only worker to try should win"
            assert claimed_by_a.job_id == job_ids[0]

            # A has not committed. The row is locked, and `SKIP LOCKED` is what
            # turns "wait for it" into "there is nothing here".
            claimed_by_b = await asyncio.wait_for(
                repo_b.claim_next_queued_job(lease_seconds=LEASE),
                timeout=PATIENCE_SECONDS,
            )
            assert claimed_by_b is None, (
                "a second worker claimed a job another worker already holds — "
                "SKIP LOCKED is missing or the status filter is wrong"
            )

            await session_a.commit()

            # Now committed as `processing`, so it fails the `queued` filter.
            assert await repo_b.claim_next_queued_job(lease_seconds=LEASE) is None
    finally:
        await delete_documents(engine_a, document_ids)
        await engine_a.dispose()
        await engine_b.dispose()


async def test_two_claimers_take_different_jobs_without_waiting(
    test_database_url: str,
) -> None:
    """Two queued jobs, two workers, no contention and no queueing.

    **This is the test that distinguishes `SKIP LOCKED` from plain
    `FOR UPDATE`.** Both are correct — neither lets two workers hold one job —
    but plain `FOR UPDATE` makes worker B *block* on the row A is holding, so
    N workers process one job at a time and the whole exercise is pointless.

    The `wait_for` is the assertion. If B were blocking, it would not return
    until A committed, and this would time out.
    """
    engine_a = create_async_engine(test_database_url)
    engine_b = create_async_engine(test_database_url)
    factory_a = async_sessionmaker(bind=engine_a, expire_on_commit=False)
    factory_b = async_sessionmaker(bind=engine_b, expire_on_commit=False)

    document_ids, job_ids = await seed_queued_jobs(engine_a, 2)

    try:
        async with factory_a() as session_a, factory_b() as session_b:
            claimed_by_a = await DocumentRepository(
                session_a
            ).claim_next_queued_job(lease_seconds=LEASE)

            claimed_by_b = await asyncio.wait_for(
                DocumentRepository(session_b).claim_next_queued_job(
                    lease_seconds=LEASE
                ),
                timeout=PATIENCE_SECONDS,
            )

            assert claimed_by_a is not None
            assert claimed_by_b is not None
            assert claimed_by_a.job_id != claimed_by_b.job_id, (
                "both workers claimed the same job"
            )
            assert {claimed_by_a.job_id, claimed_by_b.job_id} == set(job_ids)

            await session_a.commit()
            await session_b.commit()
    finally:
        await delete_documents(engine_a, document_ids)
        await engine_a.dispose()
        await engine_b.dispose()


async def test_without_skip_locked_the_second_claimer_blocks(
    test_database_url: str,
) -> None:
    """The mutation: prove `SKIP LOCKED` is doing the work.

    The repository's claim cannot block, so the only way to show what the
    clause buys is to issue the same statement without it and watch the second
    claimer wait. A test that has never been seen to fail proves nothing, and
    this is the failing version — pinned here permanently rather than tried
    once and forgotten.

    The blocked statement is cancelled by `wait_for`, which can leave an
    asyncpg connection unusable. That is why this uses a throwaway engine it
    disposes immediately, and why the lock holder is on a different one.
    """
    holder_engine = create_async_engine(test_database_url)
    blocked_engine = create_async_engine(test_database_url)

    document_ids, _job_ids = await seed_queued_jobs(holder_engine, 1)

    plain_for_update = text(
        "SELECT id FROM ingestion_jobs "
        " WHERE status = 'queued' "
        " ORDER BY queued_at, id "
        " LIMIT 1 "
        "   FOR UPDATE"  # ← no SKIP LOCKED
    )

    try:
        async with holder_engine.connect() as holder:
            # Hold the row lock, uncommitted.
            locked = (
                await holder.execute(
                    text(
                        "SELECT id FROM ingestion_jobs WHERE status = 'queued' "
                        "ORDER BY queued_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"
                    )
                )
            ).scalar_one_or_none()
            assert locked is not None, "the seed should have left one queued job"

            async with blocked_engine.connect() as blocked:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(
                        blocked.execute(plain_for_update),
                        timeout=PATIENCE_SECONDS,
                    )
    finally:
        await blocked_engine.dispose()
        await delete_documents(holder_engine, document_ids)
        await holder_engine.dispose()
