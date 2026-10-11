"""The repository, against a real database.

These tests assert behaviour the repository is responsible for — not that
SQLAlchemy works. The two that matter most are the ones about *transaction
boundaries*, because that is the thing stage 1.2 exists to get right and the
thing a unit test with a mocked session could never check.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionStatus
from app.repositories.documents import DocumentRepository


@pytest.fixture
def repo(session: AsyncSession) -> DocumentRepository:
    return DocumentRepository(session)


async def create(repo: DocumentRepository, filename: str = "zephyr-test.pdf"):
    return await repo.create_document_with_job(
        filename=filename, byte_size=2649, content_type="application/pdf"
    )


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
    assert job.status is IngestionStatus.PROCESSING


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
    _, job = await create(repo)
    await session.flush()

    await repo.mark_job_done(
        job.id,
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
    _, job = await create(repo)
    await session.flush()

    message = "'notes.txt' is not a PDF. It starts with b'just som'."
    await repo.mark_job_failed(job.id, error=message)
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
    _, job = await create(repo)
    await session.flush()

    before = (await session.execute(text("SELECT now()"))).scalar_one()
    await repo.mark_job_failed(job.id, error="unknown")
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
    document, first_job = await create(repo)
    await session.flush()
    await repo.mark_job_failed(first_job.id, error="transient provider error")

    await session.execute(
        text(
            "INSERT INTO ingestion_jobs (id, document_id, status, started_at) "
            "VALUES (gen_random_uuid(), :doc, 'processing', "
            "        now() + interval '1 minute')"
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
