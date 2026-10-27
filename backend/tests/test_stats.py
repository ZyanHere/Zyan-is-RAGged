"""`GET /stats` — is ingestion healthy right now? Stage 2.4.

Seeded states, read back through the endpoint. The jobs are built directly
rather than driven through the pipeline, because what is under test is the
*arithmetic*: that each state lands in the right bucket, and that two numbers
describing the same fact agree.

── The assertion worth reading first ───────────────────────────────────────────

`test_the_whole_snapshot_is_one_statement`. Separate queries see different
instants, so a job can be counted `queued` by one and `processing` by the next,
and the totals disagree with each other in a way that reads as a counting bug
rather than as a job doing its work. One statement is one snapshot, and that is
a property a reader cannot verify by looking at the route.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    FailureKind,
    IngestionJob,
    IngestionStatus,
    new_id,
)

PDF = b"%PDF-1.4 a document for the stats tests"


def make_document(session: AsyncSession, suffix: str) -> Document:
    import hashlib

    document = Document(
        filename=f"stats-{suffix}.pdf",
        byte_size=len(PDF),
        content_type="application/pdf",
        content_hash=hashlib.sha256(PDF + suffix.encode()).hexdigest(),
    )
    session.add(document)
    return document


async def seed(
    session: AsyncSession,
    suffix: str,
    *,
    status: IngestionStatus,
    error: str | None = None,
    failure_kind: FailureKind | None = None,
    next_attempt_at: datetime | None = None,
    queued_at: datetime | None = None,
    duration_seconds: float | None = None,
) -> IngestionJob:
    """One job in a chosen state, satisfying every constraint around it.

    The conditional fields are the schema's ten invariants written out once:
    a `processing` job holds a lease, a terminal one has a finish time, an
    error implies a kind. A helper that got any of them wrong would fail on a
    constraint rather than on the thing being tested — which has happened six
    times in this project and is why the knowledge lives in one place.
    """
    document = make_document(session, suffix)
    await session.flush()

    terminal = status in (IngestionStatus.DONE, IngestionStatus.FAILED)
    started = None if status is IngestionStatus.QUEUED else func.now()

    finished = None
    if terminal:
        finished = (
            func.now()
            if duration_seconds is None
            else func.now() + func.make_interval(0, 0, 0, 0, 0, 0, duration_seconds)
        )

    job = IngestionJob(
        document_id=document.id,
        status=status,
        started_at=started,
        finished_at=finished,
        error=error,
        failure_kind=failure_kind,
        next_attempt_at=next_attempt_at,
        attempts=0 if status is IngestionStatus.QUEUED else 1,
        request_id=None,
        **(
            {
                "lease_token": new_id(),
                "lease_expires_at": datetime.now(timezone.utc)
                + timedelta(seconds=60),
            }
            if status is IngestionStatus.PROCESSING
            else {}
        ),
        **({"queued_at": queued_at} if queued_at is not None else {}),
    )
    session.add(job)
    await session.flush()
    return job


# ── The buckets ──────────────────────────────────────────────────────────────


async def test_an_empty_system_reports_zeroes_and_nulls(client) -> None:
    """Nothing ingested yet is a real state, and it must not look like a fault.

    The percentiles are `None`, not `0.0`. Zero would read as "instant", which
    is the opposite of "nothing has finished" — and a dashboard showing a p95
    of zero is worse than one showing a blank.
    """
    body = (await client.get("/stats")).json()

    assert body["queue"] == {
        "claimable": 0,
        "waiting_for_retry": 0,
        "oldest_age_seconds": None,
    }
    assert body["in_flight"] == 0
    assert body["done"] == 0
    assert body["dead_letter"] == {"total": 0, "permanent": 0, "transient": 0}
    assert body["duration"] == {"p50_seconds": None, "p95_seconds": None}


async def test_each_state_lands_in_its_own_bucket(
    client, session: AsyncSession
) -> None:
    """A mixed system, counted. The control for every other test here."""
    await seed(session, "q", status=IngestionStatus.QUEUED)
    await seed(session, "p", status=IngestionStatus.PROCESSING)
    await seed(session, "d", status=IngestionStatus.DONE)
    await seed(
        session,
        "f",
        status=IngestionStatus.FAILED,
        error="not a PDF",
        failure_kind=FailureKind.PERMANENT,
    )
    await session.commit()

    body = (await client.get("/stats")).json()

    assert body["queue"]["claimable"] == 1
    assert body["in_flight"] == 1
    assert body["done"] == 1
    assert body["dead_letter"]["total"] == 1


async def test_a_job_waiting_out_its_backoff_is_not_a_backlog(
    client, session: AsyncSession
) -> None:
    """**The distinction `claimable` exists for.**

    A job with a future `next_attempt_at` is deliberately asleep — stage 2.1's
    backoff, working. Counting it as backlog would report "two jobs waiting"
    when one is waiting *on purpose*, and send someone looking for a worker
    that is not missing.
    """
    await seed(session, "now", status=IngestionStatus.QUEUED)
    await seed(
        session,
        "later",
        status=IngestionStatus.QUEUED,
        next_attempt_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        error="the agent did not respond",
        failure_kind=FailureKind.TRANSIENT,
    )
    await session.commit()

    queue = (await client.get("/stats")).json()["queue"]

    assert queue["claimable"] == 1, "only one job can actually be picked up"
    assert queue["waiting_for_retry"] == 1


async def test_the_dead_letter_is_split_by_what_can_be_done_about_it(
    client, session: AsyncSession
) -> None:
    """The split is the actionable part.

    A pile of `permanent` is a corpus problem — someone is uploading scans.
    A pile of `transient` is infrastructure, and every one is worth replaying.
    One number cannot distinguish them, and the responses are opposite.
    """
    await seed(
        session,
        "perm",
        status=IngestionStatus.FAILED,
        error="not a valid PDF",
        failure_kind=FailureKind.PERMANENT,
    )
    for n in range(2):
        await seed(
            session,
            f"trans{n}",
            status=IngestionStatus.FAILED,
            error="could not reach the agent",
            failure_kind=FailureKind.TRANSIENT,
        )
    await session.commit()

    dead = (await client.get("/stats")).json()["dead_letter"]

    assert dead == {"total": 3, "permanent": 1, "transient": 2}


# ── The number that says whether the queue is moving ─────────────────────────


async def test_the_oldest_queued_age_grows_with_a_stale_job(
    client, session: AsyncSession
) -> None:
    """**Depth cannot tell a busy system from a stopped one; this can.**

    Three hundred jobs draining steadily is healthy. Three that have not moved
    in an hour is an outage. Depth reports the first as worse, which is why
    the age is the number to put on a dashboard.
    """
    await seed(
        session,
        "ancient",
        status=IngestionStatus.QUEUED,
        queued_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    await seed(session, "fresh", status=IngestionStatus.QUEUED)
    await session.commit()

    queue = (await client.get("/stats")).json()["queue"]

    assert queue["claimable"] == 2, "depth alone says only that two are waiting"
    assert queue["oldest_age_seconds"] > 7000, (
        "the age is what reveals that one of them has been stuck for hours"
    )


async def test_a_finished_job_does_not_count_towards_the_oldest_wait(
    client, session: AsyncSession
) -> None:
    """Otherwise the number only ever grows.

    `queued_at` is on every job forever, including the ones that completed
    months ago. Without the `status = 'queued'` filter the oldest wait would
    be the age of the oldest row in the table, which is a fact about the
    project rather than about the queue.
    """
    await seed(
        session,
        "old-but-done",
        status=IngestionStatus.DONE,
        queued_at=datetime.now(timezone.utc) - timedelta(days=7),
    )
    await session.commit()

    queue = (await client.get("/stats")).json()["queue"]

    assert queue["oldest_age_seconds"] is None


# ── Durations ────────────────────────────────────────────────────────────────


async def test_percentiles_describe_the_successful_jobs(
    client, session: AsyncSession
) -> None:
    """Known durations in, known percentiles out.

    `percentile_cont` interpolates, so the median of 1, 2, 3, 4 seconds is
    2.5 rather than one of the inputs. That is the right behaviour for a
    latency summary and is worth pinning: a reader who expects a sample value
    would otherwise file the interpolation as a bug.
    """
    for n, seconds in enumerate([1.0, 2.0, 3.0, 4.0]):
        await seed(
            session,
            f"timed{n}",
            status=IngestionStatus.DONE,
            duration_seconds=seconds,
        )
    await session.commit()

    duration = (await client.get("/stats")).json()["duration"]

    assert duration["p50_seconds"] == pytest.approx(2.5, abs=0.1)
    assert duration["p95_seconds"] == pytest.approx(3.85, abs=0.1)


async def test_a_failed_job_does_not_drag_the_percentiles(
    client, session: AsyncSession
) -> None:
    """Duration is a statement about work that *succeeded*.

    A job that failed after 30 seconds of retrying says something about the
    failure path, not about how long indexing takes. Mixing them makes p95
    move when the agent is down, which is exactly when someone is reading it
    to decide whether indexing is slow.
    """
    await seed(session, "fast", status=IngestionStatus.DONE, duration_seconds=1.0)
    await seed(
        session,
        "slow-failure",
        status=IngestionStatus.FAILED,
        duration_seconds=300.0,
        error="could not reach the agent",
        failure_kind=FailureKind.TRANSIENT,
    )
    await session.commit()

    duration = (await client.get("/stats")).json()["duration"]

    assert duration["p50_seconds"] == pytest.approx(1.0, abs=0.1)


# ── One snapshot ─────────────────────────────────────────────────────────────


async def test_the_whole_snapshot_is_one_statement(
    client, session: AsyncSession
) -> None:
    """**A property a reader cannot check by looking at the route.**

    Separate queries see separate instants. A job counted `queued` by the
    first and `processing` by the second makes the totals disagree with each
    other — which reads as a bug in the counting rather than as a job doing
    its work, and sends whoever noticed it into the wrong code.

    Counted with a SQLAlchemy event listener rather than trusted, because "it
    looks like one query" is exactly the kind of claim that stops being true
    when someone adds a field.
    """
    await seed(session, "counted", status=IngestionStatus.QUEUED)
    await session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    # `get_bind()` returns the *sync* Engine underneath the async wrapper —
    # which is the one that emits `before_cursor_execute`, because that event
    # fires at the DBAPI boundary rather than at the async façade.
    engine = session.get_bind().engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = await client.get("/stats")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, (
        f"the snapshot took {len(selects)} queries, so its numbers describe "
        f"{len(selects)} different instants:\n" + "\n".join(selects)
    )


async def test_the_dead_letter_count_agrees_with_the_list(
    client, session: AsyncSession
) -> None:
    """Two paths to one fact must not disagree.

    `/stats` counts with SQL; `GET /documents?status=failed` filters the
    latest-job join. They are different queries over the same truth, and the
    day they diverge the dashboard and the list would each be convincing on
    their own.
    """
    for n in range(3):
        await seed(
            session,
            f"dead{n}",
            status=IngestionStatus.FAILED,
            error="not a valid PDF",
            failure_kind=FailureKind.PERMANENT,
        )
    await seed(session, "alive", status=IngestionStatus.DONE)
    await session.commit()

    counted = (await client.get("/stats")).json()["dead_letter"]["total"]
    listed = (
        await client.get("/documents", params={"status": "failed"})
    ).json()["items"]

    assert counted == len(listed) == 3


async def test_the_counts_add_up(client, session: AsyncSession) -> None:
    """Every job is in exactly one bucket, and none is in none.

    Cheap, and it catches a filter that overlaps or a state nobody thought
    about — which is how a status added later quietly goes uncounted.
    """
    await seed(session, "a", status=IngestionStatus.QUEUED)
    await seed(
        session,
        "b",
        status=IngestionStatus.QUEUED,
        next_attempt_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        error="transient",
        failure_kind=FailureKind.TRANSIENT,
    )
    await seed(session, "c", status=IngestionStatus.PROCESSING)
    await seed(session, "d", status=IngestionStatus.DONE)
    await seed(
        session,
        "e",
        status=IngestionStatus.FAILED,
        error="not a PDF",
        failure_kind=FailureKind.PERMANENT,
    )
    await session.commit()

    body = (await client.get("/stats")).json()
    total_rows = (
        await session.execute(text("SELECT count(*) FROM ingestion_jobs"))
    ).scalar_one()

    counted = (
        body["queue"]["claimable"]
        + body["queue"]["waiting_for_retry"]
        + body["in_flight"]
        + body["done"]
        + body["dead_letter"]["total"]
    )

    assert counted == total_rows == 5
