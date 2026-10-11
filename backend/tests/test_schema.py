"""The database enforces the invariants — not the application.

Every test here tries to write something the schema should refuse. If the
constraint were only a convention in Python, each of these would pass and the
bad row would land in the table.

That distinction is the whole reason the constraints are in the migration
rather than in a service method: a repository can be bypassed by a script, a
migration, or the next piece of code someone writes in a hurry. The database
cannot.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Document, IngestionJob, IngestionStatus, new_id


def make_document(**overrides: object) -> Document:
    defaults = {
        "filename": "zephyr-test.pdf",
        "byte_size": 2649,
        "content_type": "application/pdf",
    }
    return Document(**{**defaults, **overrides})


# ── Round trip ───────────────────────────────────────────────────────────────


async def test_a_document_and_its_job_round_trip(session: AsyncSession) -> None:
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(document_id=document.id, status=IngestionStatus.PROCESSING)
    )
    await session.commit()

    loaded = (
        await session.execute(
            select(Document)
            .where(Document.id == document.id)
            .options(selectinload(Document.jobs))
        )
    ).scalar_one()

    assert loaded.filename == "zephyr-test.pdf"
    assert loaded.byte_size == 2649
    assert len(loaded.jobs) == 1
    assert loaded.jobs[0].status is IngestionStatus.PROCESSING


async def test_timestamps_come_back_timezone_aware(session: AsyncSession) -> None:
    """`TIMESTAMPTZ`, not `TIMESTAMP`.

    A naive datetime here would mean the column is `timestamp without time
    zone`, which stores whatever it was handed and loses the offset. The bug
    surfaces months later as a report that is an hour out, and by then the data
    is already wrong.
    """
    document = make_document()
    session.add(document)
    await session.commit()

    assert document.created_at.tzinfo is not None
    assert document.updated_at.tzinfo is not None


async def test_the_database_clock_sets_the_timestamp(session: AsyncSession) -> None:
    """`server_default=func.now()` — not a value from this process.

    At stage 12.1 there are several API instances with independent clocks, and
    "which happened first" needs one authority. This asserts the timestamp is
    close to the *database's* now, not the test runner's.
    """
    db_now = (await session.execute(text("SELECT now()"))).scalar_one()

    document = make_document()
    session.add(document)
    await session.commit()

    assert abs((document.created_at - db_now).total_seconds()) < 5


# ── Status constraints ───────────────────────────────────────────────────────


async def test_an_unknown_status_is_rejected(session: AsyncSession) -> None:
    """`ck_ingestion_jobs_status_allowed`.

    Written as raw SQL on purpose. Going through the ORM would be stopped by
    the Python enum before the statement was ever sent, which proves only that
    Python works. The point is that the *database* refuses it.

    Note `finished_at` is supplied even though this test is not about it. With
    `finished_at` NULL, the row violates `finished_at_matches_status` as well —
    `(status = 'processing')` is false while `(finished_at IS NULL)` is true —
    and Postgres reports whichever constraint it happens to reach first. The
    test would still pass for the wrong reason, and would keep passing if
    `status_allowed` were deleted.

    **A test that names one constraint has to satisfy every other one.**
    """
    document = make_document()
    session.add(document)
    await session.flush()

    with pytest.raises(IntegrityError, match="status_allowed"):
        await session.execute(
            text(
                "INSERT INTO ingestion_jobs (id, document_id, status, finished_at) "
                "VALUES (:id, :doc, 'cancelled', now())"
            ),
            {"id": new_id(), "doc": document.id},
        )


async def test_a_processing_job_may_not_have_a_finish_time(
    session: AsyncSession,
) -> None:
    """`ck_ingestion_jobs_finished_at_matches_status`, first half."""
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(
            document_id=document.id,
            status=IngestionStatus.PROCESSING,
            finished_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError, match="finished_at_matches_status"):
        await session.flush()


@pytest.mark.parametrize(
    "status", [IngestionStatus.DONE, IngestionStatus.FAILED]
)
async def test_a_terminal_job_must_have_a_finish_time(
    session: AsyncSession, status: IngestionStatus
) -> None:
    """`ck_ingestion_jobs_finished_at_matches_status`, second half.

    This is what makes "stuck in processing" a structurally visible state: a
    job with no finish time is, by definition, still running. Stage 1.2 creates
    that visibility; stage 2.1's lease and reaper are what fix it.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(
            document_id=document.id,
            status=status,
            error="something went wrong",
            finished_at=None,
        )
    )

    with pytest.raises(IntegrityError, match="finished_at_matches_status"):
        await session.flush()


async def test_a_job_cannot_finish_before_it_started(
    session: AsyncSession,
) -> None:
    """`ck_ingestion_jobs_finished_after_started` — clock skew, or swapped args."""
    document = make_document()
    session.add(document)
    await session.flush()

    now = datetime.now(timezone.utc)
    session.add(
        IngestionJob(
            document_id=document.id,
            status=IngestionStatus.DONE,
            started_at=now,
            finished_at=now - timedelta(seconds=10),
        )
    )

    with pytest.raises(IntegrityError, match="finished_after_started"):
        await session.flush()


async def test_a_failed_job_must_say_why(session: AsyncSession) -> None:
    """`ck_ingestion_jobs_failed_requires_error`.

    A failure with no explanation is a failure nobody can diagnose. If the
    cause is genuinely unknown the code has to store `"unknown"` — which is at
    least honest, and which stage 2.3 will want when it starts classifying
    failures as transient or permanent.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(
            document_id=document.id,
            status=IngestionStatus.FAILED,
            finished_at=datetime.now(timezone.utc),
            error=None,
        )
    )

    with pytest.raises(IntegrityError, match="failed_requires_error"):
        await session.flush()


async def test_a_successful_job_records_its_numbers(session: AsyncSession) -> None:
    """The counts that make a scanned PDF detectable after the fact.

    Ten pages with three yielding text means seven pages are not in the index
    and no question will ever find them. Stage 1.1 shows that in the UI at
    upload time; storing it here is what makes it answerable later, for a
    document nobody was watching.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    job = IngestionJob(
        document_id=document.id,
        status=IngestionStatus.DONE,
        finished_at=datetime.now(timezone.utc),
        page_count=10,
        pages_with_text=3,
        characters_extracted=1269,
        chunk_count=5,
    )
    session.add(job)
    await session.commit()

    assert job.page_count - job.pages_with_text == 7


# ── Referential integrity ────────────────────────────────────────────────────


async def test_a_job_cannot_reference_a_missing_document(
    session: AsyncSession,
) -> None:
    session.add(
        IngestionJob(document_id=new_id(), status=IngestionStatus.PROCESSING)
    )

    with pytest.raises(IntegrityError, match="fk_ingestion_jobs_document_id"):
        await session.flush()


async def test_deleting_a_document_deletes_its_jobs(
    session: AsyncSession,
) -> None:
    """`ON DELETE CASCADE`, enforced by Postgres rather than by the ORM.

    Raw SQL for the delete, deliberately. SQLAlchemy's `delete-orphan` cascade
    would produce the same visible result by issuing its own DELETEs, which
    proves the ORM works. The database-level cascade is what protects you from
    anything that is not the ORM.
    """
    document = make_document()
    session.add(document)
    await session.flush()
    session.add(
        IngestionJob(document_id=document.id, status=IngestionStatus.PROCESSING)
    )
    await session.commit()

    await session.execute(
        text("DELETE FROM documents WHERE id = :id"), {"id": document.id}
    )

    remaining = (
        await session.execute(
            text("SELECT count(*) FROM ingestion_jobs WHERE document_id = :id"),
            {"id": document.id},
        )
    ).scalar_one()
    assert remaining == 0


# ── Loader strategy ──────────────────────────────────────────────────────────


async def test_an_unloaded_relationship_raises_instead_of_lazy_loading(
    session: AsyncSession,
) -> None:
    """`lazy="raise"` turns a latent async bug into an immediate, clear error.

    Under async SQLAlchemy a lazy load raises `MissingGreenlet` — an error that
    names greenlets, says nothing about the attribute, and appears far from the
    query that forgot to load it. `lazy="raise"` reports the real problem at the
    point of access.

    It also forces every query to declare what it needs, which is how an N+1 is
    prevented rather than discovered later by measurement.
    """
    document = make_document()
    session.add(document)
    await session.commit()

    fetched = (
        await session.execute(select(Document).where(Document.id == document.id))
    ).scalar_one()

    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = fetched.jobs
