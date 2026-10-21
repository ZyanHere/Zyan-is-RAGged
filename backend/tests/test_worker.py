"""The worker loop. Stage 1.3.

── Why these tests use their own database wiring ───────────────────────────────

The worker creates its own sessions — two per job, deliberately — so it cannot
be handed the suite's shared, rolled-back `session`. It needs a real `Database`
whose `session_factory` commits, which is also the only way to test the thing
that matters here: that a crash *after* the claim leaves a committed
`processing` row rather than rolling the claim back.

So these tests build a `Database` against the test DSN, commit for real, and
clean up after themselves — the same trade `test_claim_concurrency.py` makes.

── What is not tested here ─────────────────────────────────────────────────────

Signal handling. `_install_signal_handlers` is three lines over a platform
difference, and a test for it would either send real signals to the test runner
or assert that a mock was called — the first is hostile and the second proves
only that the code says what it says. The shutdown *behaviour* it enables is
tested, via the `stop` event.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.db.models import IngestionStatus
from app.db.session import Database, create_database, session_scope
from app.errors import AgentUnavailableError
from app.repositories.documents import DocumentRepository
from app.services.ingestion import IngestionService
from app.worker import process_one, run

PDF = b"%PDF-1.4 pretend this is a real document"


class FakeAgent:
    """Stands in for the agent. Records what it was asked to ingest."""

    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self.body = body if body is not None else {
            "page_count": 3,
            "pages_with_text": 3,
            "characters_extracted": 1269,
            "chunk_count": 3,
        }
        self.calls: list[dict] = []

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        self.calls.append(kwargs)
        return self.status_code, self.body


class UnreachableAgent:
    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        raise AgentUnavailableError("Could not reach the agent at http://x:8001.")


class CrashingAgent:
    """Dies in a way nothing catches, like a real `kill -9`."""

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        raise KeyboardInterrupt("simulated process interruption")


@pytest.fixture
async def database(test_database_url: str):
    """A real `Database`, built exactly as the worker builds its own."""
    db = create_database(Settings(database_url=test_database_url))
    yield db
    await db.engine.dispose()


async def accept(database: Database, filename: str = "zephyr-test.pdf") -> uuid.UUID:
    """Commit an upload the way the API does, and return its document id."""
    async with session_scope(database.session_factory) as session:
        service = IngestionService(session, DocumentRepository(session), FakeAgent())
        accepted = await service.accept_upload(
            filename=filename, content=PDF, content_type="application/pdf"
        )
        return accepted.document_id


async def read_job(database: Database, document_id: uuid.UUID):
    """The job's state, read on a fresh connection."""
    async with database.engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, started_at IS NULL AS not_started, "
                    "       finished_at IS NULL AS not_finished, error, chunk_count "
                    "  FROM ingestion_jobs WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        ).one()


async def cleanup(database: Database, document_ids: list[uuid.UUID]) -> None:
    async with database.engine.begin() as conn:
        for document_id in document_ids:
            await conn.execute(
                text("DELETE FROM documents WHERE id = :id"), {"id": document_id}
            )


# ── One job, start to finish ─────────────────────────────────────────────────


async def test_the_worker_drives_a_queued_job_to_done(database: Database) -> None:
    """The happy path, and the whole point of the stage.

    An upload that the API only *recorded* becomes an indexed document, in a
    different process, with no request involved anywhere.
    """
    agent = FakeAgent()
    document_id = await accept(database)

    try:
        assert await process_one(database, agent) is True

        job = await read_job(database, document_id)
        assert job.status == "done"
        assert job.not_started is False, "a processed job has a start time"
        assert job.not_finished is False, "and a finish time"
        assert job.chunk_count == 3

        # The id the backend minted is the one the agent was told to index, and
        # it is the one that ends up in the Qdrant payload. The chain that
        # stage 1.2 established survives being split across two processes.
        assert len(agent.calls) == 1
        assert agent.calls[0]["document_id"] == str(document_id)
        assert agent.calls[0]["filename"] == "zephyr-test.pdf"
        assert agent.calls[0]["content"] == PDF, (
            "the worker must ingest the stored bytes, not an empty placeholder"
        )
    finally:
        await cleanup(database, [document_id])


async def test_an_empty_queue_is_not_an_error(database: Database) -> None:
    """`False`, not an exception. Idle is the normal state of a worker."""
    assert await process_one(database, FakeAgent()) is False


async def test_the_worker_records_a_rejected_document_as_failed(
    database: Database,
) -> None:
    """A 4xx from the agent is a failed job carrying the agent's own reason.

    Nobody is waiting on a response, so the error message *is* the user-facing
    output — it reaches them through the document list, which has rendered
    `error` since stage 1.2.
    """
    document_id = await accept(database, "notes.txt")

    try:
        agent = FakeAgent(status_code=400, body={"detail": "'notes.txt' is not a PDF."})
        assert await process_one(database, agent) is True

        job = await read_job(database, document_id)
        assert job.status == "failed"
        assert job.error == "'notes.txt' is not a PDF."
        assert job.not_finished is False
    finally:
        await cleanup(database, [document_id])


async def test_the_worker_records_an_unreachable_agent_as_failed(
    database: Database,
) -> None:
    """The job fails; the worker does not.

    An outage must not be the end of the worker process — the next job may
    well be fine, and if it is not, the failures are at least recorded.
    """
    document_id = await accept(database)

    try:
        assert await process_one(database, UnreachableAgent()) is True

        job = await read_job(database, document_id)
        assert job.status == "failed"
        assert "Could not reach the agent" in job.error
    finally:
        await cleanup(database, [document_id])


# ── The stuck row this stage creates on purpose ──────────────────────────────


async def test_a_crash_after_the_claim_leaves_a_committed_processing_row(
    database: Database,
) -> None:
    """**Stage 2.1's trigger, manufactured and asserted.**

    The claim and the work are separate transactions, so a crash between them
    cannot roll the claim back. The row is left `processing`, with a start time
    and no finish time — a state that means exactly one thing, because
    `ck_ingestion_jobs_finished_at_matches_status` permits nothing else.

    Read on a **fresh connection**, so this is a claim about committed data
    rather than about an open transaction's own uncommitted writes.

    **If this test ever starts failing because the row went back to `queued`,
    stage 2.1 has been pre-solved by accident** — and the problem it exists to
    teach would have quietly disappeared. That is why the assertion is
    `processing` rather than "either is fine".
    """
    document_id = await accept(database, "stuck.pdf")

    try:
        with pytest.raises(KeyboardInterrupt):
            await process_one(database, CrashingAgent())

        job = await read_job(database, document_id)
        assert job.status == "processing", (
            "the claim must survive a crash during the work, or the stuck-row "
            "state stage 2.1 fixes cannot occur"
        )
        assert job.not_started is False
        assert job.not_finished is True
        assert job.error is None, "nothing got far enough to know why"
    finally:
        await cleanup(database, [document_id])


async def test_a_stuck_job_is_not_reclaimed_by_the_next_worker(
    database: Database,
) -> None:
    """And nothing recovers it. That is the gap, stated as a test.

    A second worker starting up finds nothing to do, because the row is
    `processing` and only `queued` is claimable. The document is stranded until
    a human or stage 2.1's reaper intervenes.
    """
    document_id = await accept(database, "stranded.pdf")

    try:
        with pytest.raises(KeyboardInterrupt):
            await process_one(database, CrashingAgent())

        assert await process_one(database, FakeAgent()) is False, (
            "a stuck job must not be silently picked up again — at this stage "
            "nothing distinguishes 'running' from 'abandoned'"
        )

        job = await read_job(database, document_id)
        assert job.status == "processing"
    finally:
        await cleanup(database, [document_id])


# ── The loop ─────────────────────────────────────────────────────────────────


async def test_the_loop_drains_everything_queued_then_idles(
    database: Database,
) -> None:
    """Three uploads, one pass, and then it stops when asked.

    Asserts the loop does **not** sleep between jobs: `worker_poll_seconds` is
    deliberately long here, so if the loop waited after each job this would
    exceed the timeout rather than finishing promptly. A fixed sleep between
    jobs would cap throughput at one job per interval no matter how fast the
    jobs are.
    """
    agent = FakeAgent()
    document_ids = [
        await accept(database, "one.pdf"),
        await accept(database, "two.pdf"),
        await accept(database, "three.pdf"),
    ]

    stop = asyncio.Event()
    settings = Settings(
        database_url=str(database.engine.url), worker_poll_seconds=30.0
    )

    async def stop_once_drained() -> None:
        while True:
            async with database.engine.connect() as conn:
                remaining = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM ingestion_jobs "
                            " WHERE status = 'queued'"
                        )
                    )
                ).scalar_one()
            if remaining == 0:
                stop.set()
                return
            await asyncio.sleep(0.05)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                run(database, settings, stop, agent), stop_once_drained()
            ),
            timeout=10.0,
        )

        assert len(agent.calls) == 3
        for document_id in document_ids:
            assert (await read_job(database, document_id)).status == "done"
    finally:
        stop.set()
        await cleanup(database, document_ids)


async def test_the_stop_event_interrupts_the_idle_wait(
    database: Database,
) -> None:
    """Shutdown does not wait out the poll interval.

    With a 30-second interval and a plain `asyncio.sleep`, stopping would take
    up to 30 seconds — long enough that Docker gives up waiting and sends
    `SIGKILL`, which turns every clean shutdown into an unclean one and creates
    exactly the stuck rows the cooperative stop exists to avoid.
    """
    stop = asyncio.Event()
    settings = Settings(
        database_url=str(database.engine.url), worker_poll_seconds=30.0
    )

    loop = asyncio.get_running_loop()
    started = loop.time()

    task = asyncio.create_task(run(database, settings, stop, FakeAgent()))
    await asyncio.sleep(0.1)  # let it reach the idle wait
    stop.set()

    await asyncio.wait_for(task, timeout=5.0)

    assert loop.time() - started < 5.0, "the stop event did not interrupt the wait"


async def test_an_unexpected_failure_does_not_kill_the_loop(
    database: Database,
) -> None:
    """One bad job must not stop every other job in the queue.

    The agent here raises a plain `RuntimeError` — not one of the failures
    `process_job` knows how to record — which is what a bug or a dropped
    database connection looks like from the loop's point of view.

    The job is left `processing` rather than marked failed, because the loop
    does not know how far the work got. Claiming knowledge it does not have
    would be worse than leaving the row visibly stuck.
    """

    class BuggyAgent:
        async def ingest_document(self, **kwargs) -> tuple[int, dict]:
            raise RuntimeError("something nobody anticipated")

    document_ids = [await accept(database, "buggy.pdf")]

    stop = asyncio.Event()
    settings = Settings(
        database_url=str(database.engine.url), worker_poll_seconds=0.05
    )

    task = asyncio.create_task(run(database, settings, stop, BuggyAgent()))
    try:
        await asyncio.sleep(0.4)  # several iterations
        assert not task.done(), "the loop should have survived the exception"

        job = await read_job(database, document_ids[0])
        assert job.status == "processing"
        assert job.error is None
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5.0)
        await cleanup(database, document_ids)
