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
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Document,
    DocumentUpload,
    IngestionJob,
    IngestionStatus,
    new_id,
)


def make_document(**overrides: object) -> Document:
    defaults = {
        "filename": "zephyr-test.pdf",
        "byte_size": 2649,
        "content_type": "application/pdf",
    }
    return Document(**{**defaults, **overrides})


def make_job(**overrides: object) -> IngestionJob:
    """A job that satisfies every constraint unless a test overrides one.

    **`started_at` is explicit, and has to be.** It lost its `server_default`
    at stage 1.3 so that a `queued` job could be written with NULL — see the
    column's docstring — which means a job built directly in a test now
    inserts NULL and violates `started_at_matches_status`.

    Defaulting it here keeps each test violating only the constraint it names.
    Without it, five existing tests failed for a reason none of them was about:
    the same trap stage 1.2 hit from the other direction, where a test named
    one constraint and broke two. **Adding a constraint can break a correct
    test just as easily as changing one.**

    `queued` jobs pass `started_at=None` explicitly, which reads as the
    deliberate choice it is.

    **The lease defaults are conditional, and that is the point.** Stage 2.1
    added `lease_matches_status`: a `processing` job holds a lease and nothing
    else does. A flat default would therefore be wrong for three of the four
    statuses, so the helper looks at the status it ends up with — which is the
    same rule the constraint enforces, written once.

    This is the third time a new constraint has broken correct tests for a
    reason none of them was about. Centralising the "satisfy everything else"
    knowledge here is what stops it being a fourth.
    """
    merged: dict[str, object] = {
        "status": IngestionStatus.PROCESSING,
        "started_at": func.now(),
        **overrides,
    }

    if merged["status"] is IngestionStatus.PROCESSING:
        merged.setdefault("lease_token", new_id())
        merged.setdefault(
            "lease_expires_at",
            datetime.now(timezone.utc) + timedelta(seconds=60),
        )

    return IngestionJob(**merged)


# ── Round trip ───────────────────────────────────────────────────────────────


async def test_a_document_and_its_job_round_trip(session: AsyncSession) -> None:
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        make_job(document_id=document.id)
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
                "INSERT INTO ingestion_jobs "
                "(id, document_id, status, started_at, finished_at) "
                "VALUES (:id, :doc, 'cancelled', now(), now())"
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

    job = make_job(
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
        make_job(document_id=new_id())
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
        make_job(document_id=document.id)
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


# ── The queued state (stage 1.3) ─────────────────────────────────────────────


async def test_a_queued_job_round_trips(session: AsyncSession) -> None:
    """The state the API writes and a worker later claims.

    **This test is why `started_at` has no `server_default`.** The first
    version of the migration kept one, reasoning that existing writers would
    then need no change. This test failed: SQLAlchemy reads `started_at=None`
    on a defaulted column as "no opinion", omits it from the INSERT, and lets
    `now()` fill it in — so the row came back with a start time and violated
    `started_at_matches_status`. A queued job was unwritable.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    job = IngestionJob(
        document_id=document.id,
        status=IngestionStatus.QUEUED,
        started_at=None,
    )
    session.add(job)
    await session.flush()

    fetched = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.id == job.id)
        )
    ).scalar_one()

    assert fetched.status is IngestionStatus.QUEUED
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.queued_at is not None, "the database clock should set this"


async def test_a_queued_job_may_not_have_a_start_time(
    session: AsyncSession,
) -> None:
    """`ck_ingestion_jobs_started_at_matches_status`, first half.

    "Queued" means nobody has picked it up. A start time says otherwise, and
    the pair is incoherent rather than merely untidy — stage 2.1's reaper asks
    "how long has this been running?", and this row would answer for a job that
    never started.

    Every other constraint is satisfied: the status is legal, `finished_at` is
    NULL as a non-terminal state requires, and nothing is failed. So Postgres
    can only report this one.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(
            document_id=document.id,
            status=IngestionStatus.QUEUED,
            started_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError, match="started_at_matches_status"):
        await session.flush()


@pytest.mark.parametrize(
    ("status", "finished_at", "error", "lease"),
    [
        (IngestionStatus.PROCESSING, None, None, True),
        (IngestionStatus.DONE, datetime.now(timezone.utc), None, False),
        (IngestionStatus.FAILED, datetime.now(timezone.utc), "not a PDF", False),
    ],
)
async def test_a_job_past_queued_must_have_a_start_time(
    session: AsyncSession,
    status: IngestionStatus,
    finished_at: datetime | None,
    error: str | None,
    lease: bool,
) -> None:
    """`ck_ingestion_jobs_started_at_matches_status`, second half.

    Each case is constructed to violate **only** this constraint — the lesson
    from stage 1.2, where a test named one constraint, broke two, and passed on
    whichever Postgres reported first:

        processing  finished_at NULL      satisfies finished_at_matches_status
        done        finished_at set       satisfies it the other way
        failed      finished_at + error   also satisfies failed_requires_error

    `finished_after_started` survives a NULL `started_at` on purpose:
    `finished_at >= NULL` evaluates to NULL, and a CHECK only rejects FALSE.
    The two constraints lean on each other rather than each carrying a NULL
    branch.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(
            document_id=document.id,
            status=status,
            started_at=None,
            finished_at=finished_at,
            error=error,
            # Stage 2.1 made this parametrisation sharper. A `processing` row
            # must now *also* hold a lease, so without one this case would
            # break two constraints and Postgres would report whichever it
            # reached first — the exact trap this test's docstring describes,
            # arriving from a third direction.
            lease_token=new_id() if lease else None,
            lease_expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=60)
                if lease
                else None
            ),
        )
    )

    with pytest.raises(IntegrityError, match="started_at_matches_status"):
        await session.flush()


def test_only_done_and_failed_are_terminal() -> None:
    """What the client polls on, and what stage 2.1's reaper looks for.

    A pure function over the enum, so no database: the point is that `queued`
    and `processing` are both non-terminal but are *not* interchangeable, which
    is the distinction the stage exists to create.
    """
    assert IngestionStatus.QUEUED.is_terminal is False
    assert IngestionStatus.PROCESSING.is_terminal is False
    assert IngestionStatus.DONE.is_terminal is True
    assert IngestionStatus.FAILED.is_terminal is True


# ── Stored uploads (stage 1.3) ───────────────────────────────────────────────


async def test_an_upload_round_trips_byte_for_byte(
    session: AsyncSession,
) -> None:
    """The bytes a worker will read after the request that carried them is gone.

    Asserted byte-for-byte rather than by length: `bytea` round-tripping
    through asyncpg is the sort of thing that works until a NUL or a high byte
    appears, and a PDF is full of both.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    content = b"%PDF-1.7\x00\xff\n binary \x80\x81 payload \x00"
    session.add(DocumentUpload(document_id=document.id, content=content))
    await session.flush()

    fetched = (
        await session.execute(
            select(DocumentUpload).where(
                DocumentUpload.document_id == document.id
            )
        )
    ).scalar_one()

    assert fetched.content == content
    assert fetched.created_at is not None


async def test_a_document_can_have_only_one_upload(
    session: AsyncSession,
) -> None:
    """Enforced by making the foreign key the primary key.

    A second row for the same document has no meaning — there is one file —
    and without the constraint the worker's lookup would have to decide which
    of two inputs was the real one.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(DocumentUpload(document_id=document.id, content=b"%PDF-1.7 a"))
    await session.flush()

    session.add(DocumentUpload(document_id=document.id, content=b"%PDF-1.7 b"))

    with pytest.raises(IntegrityError, match="pk_document_uploads"):
        await session.flush()


async def test_deleting_a_document_deletes_its_upload(
    session: AsyncSession,
) -> None:
    """`ON DELETE CASCADE`, so the bytes cannot outlive the document.

    This matters more than it looks: the uploads table is the only place in
    this system that grows with the size of the corpus rather than with its
    metadata, and an orphaned 25 MB row that nothing references is invisible
    until a disk fills.
    """
    document = make_document()
    session.add(document)
    await session.flush()
    session.add(DocumentUpload(document_id=document.id, content=b"%PDF-1.7 x"))
    await session.flush()

    await session.delete(document)
    await session.flush()

    remaining = (
        await session.execute(
            select(DocumentUpload).where(
                DocumentUpload.document_id == document.id
            )
        )
    ).scalar_one_or_none()

    assert remaining is None


# ── The lease (stage 2.1) ────────────────────────────────────────────────────


async def test_a_processing_job_must_hold_a_lease(
    session: AsyncSession,
) -> None:
    """`ck_ingestion_jobs_lease_matches_status`, first half.

    **The subtle half.** A `processing` row with no lease is not merely untidy
    — it is *invisible to the reaper*, because `lease_expires_at < now()` is
    false when the column is NULL. The job would be stuck forever in exactly
    the state the recovery mechanism was built to find, and the mechanism would
    never see it.

    That is the state every pre-2.1 row was in, which is why the migration had
    to give them an already-expired lease rather than leave them alone.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        make_job(
            document_id=document.id,
            status=IngestionStatus.PROCESSING,
            lease_token=None,
            lease_expires_at=None,
        )
    )

    with pytest.raises(IntegrityError, match="lease_matches_status"):
        await session.flush()


@pytest.mark.parametrize(
    ("status", "terminal", "error"),
    [
        (IngestionStatus.QUEUED, False, None),
        (IngestionStatus.DONE, True, None),
        (IngestionStatus.FAILED, True, "not a PDF"),
    ],
)
async def test_only_a_processing_job_may_hold_a_lease(
    session: AsyncSession,
    status: IngestionStatus,
    terminal: bool,
    error: str | None,
) -> None:
    """`ck_ingestion_jobs_lease_matches_status`, second half.

    A lease outliving its work is how a stale write gets accepted after the
    fact: the conditional UPDATE checks the token, so a terminal job that still
    carries one is a job a long-asleep worker can still overwrite.

    Each case satisfies every other constraint, so only this one can fire.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        IngestionJob(
            document_id=document.id,
            status=status,
            # **Both timestamps come from the database clock.** Using a Python
            # `datetime.now()` for `finished_at` broke this test on first run:
            # the value is computed when pytest collects the parameters, while
            # `started_at` is computed at INSERT — so `finished_at` was
            # *earlier* and `finished_after_started` fired instead of the
            # constraint being tested.
            #
            # `func.now()` is `transaction_timestamp()`, so both land on the
            # same instant and `>=` holds. The fourth time in this project a
            # test has broken on a constraint it was not about.
            started_at=None if status is IngestionStatus.QUEUED else func.now(),
            finished_at=func.now() if terminal else None,
            error=error,
            lease_token=new_id(),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
    )

    with pytest.raises(IntegrityError, match="lease_matches_status"):
        await session.flush()


async def test_a_lease_token_without_an_expiry_is_refused(
    session: AsyncSession,
) -> None:
    """`ck_ingestion_jobs_lease_expiry_matches_token`.

    The two columns are one fact and must move together. A token with no
    expiry never lapses, so nothing ever reclaims it — a permanent claim, which
    is precisely what stage 2.1 exists to abolish. An expiry with no token has
    nothing to check ownership against.

    Either alone is a silent hole in the recovery path, which is why this is a
    constraint rather than a convention.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(
        make_job(
            document_id=document.id,
            lease_token=new_id(),
            lease_expires_at=None,
        )
    )

    with pytest.raises(IntegrityError, match="lease_expiry_matches_token"):
        await session.flush()


async def test_attempts_cannot_be_negative(session: AsyncSession) -> None:
    """Cheap, and it catches the decrement nobody meant to write.

    `attempts` is the bound on how much one document can cost, so a negative
    value is an unbounded retry loop waiting to happen.
    """
    document = make_document()
    session.add(document)
    await session.flush()

    session.add(make_job(document_id=document.id, attempts=-1))

    with pytest.raises(IntegrityError, match="attempts_non_negative"):
        await session.flush()
