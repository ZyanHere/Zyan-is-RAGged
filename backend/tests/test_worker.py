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
from app.worker import process_one, reap, run

PDF = b"%PDF-1.4 pretend this is a real document"


# ── Why each upload gets distinct bytes — stage 2.2 ──────────────────────────
#
# `uq_documents_content_hash` means two uploads of **identical bytes** are one
# document, and the second insert is refused. A shared `PDF` constant therefore
# made every test that accepts more than one document fail on uniqueness while
# testing something else entirely.
#
# Separate uploads are separate files, so the helpers below append a unique
# marker. A test that wants a genuine duplicate passes the same bytes twice,
# deliberately. The long version of this is in `test_repositories.create`.
def _unique(pdf: bytes) -> bytes:
    return pdf + b" " + uuid.uuid4().hex.encode()


# A long lease, because these tests are about the loop rather than
# about expiry. The reaper's tests set a short one deliberately.
def _settings(**overrides) -> Settings:
    """Settings for a worker, with a long lease unless a test says otherwise.

    `lease_seconds` goes through `setdefault` rather than being a keyword
    argument, so a test can override it without colliding with the default.
    """
    defaults = {
        "database_url": "postgresql+asyncpg://unused/unused",
        "lease_seconds": 60.0,
    }
    return Settings(**{**defaults, **overrides})


SETTINGS = _settings()

# Retries with effectively no waiting, for tests that watch a job recover.
IMPATIENT = _settings(max_attempts=5, retry_base_seconds=0.001)

# A long backoff, for tests proving a requeued job *stays* out of the queue
# rather than being picked straight back up.
PATIENT = _settings(max_attempts=5, retry_base_seconds=300.0)


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


async def accept(
    database: Database,
    filename: str = "zephyr-test.pdf",
    content: bytes | None = None,
) -> uuid.UUID:
    """Commit an upload the way the API does, and return its document id."""
    async with session_scope(database.session_factory) as session:
        service = IngestionService(session, DocumentRepository(session), FakeAgent())
        accepted = await service.accept_upload(
            filename=filename,
            content=content if content is not None else _unique(PDF),
            content_type="application/pdf",
        )
        return accepted.document.document_id


async def read_job(database: Database, document_id: uuid.UUID):
    """The job's state, read on a fresh connection."""
    async with database.engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, started_at IS NULL AS not_started, "
                    "       finished_at IS NULL AS not_finished, error, chunk_count, "
                    "       attempts, next_attempt_at, failure_kind "
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
    # Explicit bytes, because the assertion below is byte-for-byte: the worker
    # must ingest what was *stored*, not a placeholder it invented.
    document_id = await accept(database, content=PDF)

    try:
        assert await process_one(database, SETTINGS, agent) is True

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
    assert await process_one(database, SETTINGS, FakeAgent()) is False


async def test_a_rejected_document_fails_on_the_first_attempt(
    database: Database,
) -> None:
    """**Changed twice now, and the second change is this one.**

    At 1.3 a 4xx ended the job outright. At 2.1 it became provisional — the
    job returned to `queued` with the agent's reason, because nothing yet
    distinguished a broken file from a broken dependency.

    Stage 2.3 ends it again, deliberately and for a different reason: a
    document that is not a PDF will not become one. Four of the five attempts
    2.1 spent on it could never have succeeded, and the message the user reads
    is identical either way — so the retries bought nothing and delayed the
    answer.

    Note what is asserted about the error: **no "gave up after N attempts"
    suffix.** The suffix only earns its place when retries actually happened,
    and on a permanent failure the user should read the engine's own words
    unadorned.
    """
    document_id = await accept(database, "notes.txt")

    try:
        agent = FakeAgent(status_code=400, body={"detail": "'notes.txt' is not a PDF."})
        assert await process_one(database, PATIENT, agent) is True

        job = await read_job(database, document_id)
        assert job.status == "failed", "a permanent failure does not wait"
        assert job.error == "'notes.txt' is not a PDF.", (
            "no attempt-count suffix: nothing was retried"
        )
        assert job.failure_kind == "permanent"
        assert job.attempts == 1, "one claim, not five"
        assert job.not_finished is False

        assert await process_one(database, PATIENT, FakeAgent()) is False, (
            "a terminal job must not be claimable again"
        )
    finally:
        await cleanup(database, [document_id])


async def test_a_rate_limit_is_retried_despite_being_4xx(
    database: Database,
) -> None:
    """`429` is the exception that shows the rule is not about the number.

    4xx normally means *this request is wrong*, and `classify` treats it as
    permanent for that reason. A rate limit is the one 4xx that means *you
    were right, come back later* — the server asking you to wait, not telling
    you the request was bad.

    Nothing in this system emits a 429 today. A provider will, and without
    this carve-out every document in flight during a rate-limit window would
    be permanently failed on its first attempt — a strictly worse outcome than
    the 22-second budget this stage exists to fix.
    """
    document_id = await accept(database, "rate-limited.pdf")

    try:
        agent = FakeAgent(
            status_code=429, body={"detail": "Too many requests, retry later."}
        )
        assert await process_one(database, PATIENT, agent) is True

        job = await read_job(database, document_id)
        assert job.status == "queued", "a rate limit is worth waiting out"
        assert job.failure_kind == "transient"
        assert job.attempts == 1
    finally:
        await cleanup(database, [document_id])


async def test_a_storage_failure_is_transient(database: Database) -> None:
    """A 500 from the agent is *our* infrastructure, not the document.

    `VectorStoreError` is deliberately a 500 and not a 502 — Qdrant is ours,
    not a third party — and either way the document is blameless. Classifying
    it permanent would throw away a perfectly good upload because a disk was
    briefly unhappy.
    """
    document_id = await accept(database, "storage-blip.pdf")

    try:
        agent = FakeAgent(
            status_code=500, body={"detail": "Could not write to the collection."}
        )
        assert await process_one(database, PATIENT, agent) is True

        job = await read_job(database, document_id)
        assert job.status == "queued"
        assert job.failure_kind == "transient"
    finally:
        await cleanup(database, [document_id])


async def test_a_provider_outage_is_survived_rather_than_fatal(
    database: Database,
) -> None:
    """**The defect stage 2.1 exists to fix, as a test.**

    Before this stage an unreachable agent meant `status = 'failed'`, which
    nothing ever left. `docker compose restart agent` — three seconds of
    downtime — therefore destroyed every document being processed at that
    moment, permanently, and the only recovery was a human noticing and
    re-uploading the file.

    Now the outage is survivable. The document waits, tries again, and
    finishes. **No human anywhere in that sentence**, which is the measure of
    this stage.
    """
    document_id = await accept(database)

    try:
        assert await process_one(database, IMPATIENT, UnreachableAgent()) is True

        job = await read_job(database, document_id)
        assert job.status == "queued", (
            "a provider outage must not permanently destroy a document"
        )
        assert "Could not reach the agent" in job.error

        # The outage ends.
        assert await process_one(database, IMPATIENT, FakeAgent()) is True

        job = await read_job(database, document_id)
        assert job.status == "done"
        assert job.chunk_count == 3
        assert job.attempts == 2, "it took two tries, and the row says so"
    finally:
        await cleanup(database, [document_id])


async def test_a_job_that_keeps_failing_is_eventually_given_up_on(
    database: Database,
) -> None:
    """Retrying has to stop somewhere, or a broken document costs forever.

    `max_attempts` is the bound. The error says how many tries it took, which
    is the difference between "this document is bad" and "we were unlucky" —
    and it is the signal stage 2.3 will classify on when it builds a
    dead-letter queue worth inspecting.
    """
    document_id = await accept(database, "doomed.pdf")
    policy = _settings(max_attempts=3, retry_base_seconds=0.001)

    try:
        for attempt in range(1, 4):
            assert await process_one(database, policy, UnreachableAgent()) is True
            job = await read_job(database, document_id)
            assert job.attempts == attempt

            if attempt < 3:
                assert job.status == "queued"

        assert job.status == "failed", "the third attempt was the last"
        assert "gave up after 3 attempts" in job.error
        assert job.not_finished is False

        assert await process_one(database, policy, FakeAgent()) is False, (
            "a job that has been given up on must not be claimable again"
        )
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
            await process_one(database, SETTINGS, CrashingAgent())

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
            await process_one(database, SETTINGS, CrashingAgent())

        assert await process_one(database, SETTINGS, FakeAgent()) is False, (
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


# ── The heartbeat and the reaper (stage 2.1, layer 4) ────────────────────────


class SlowAgent:
    """An agent that takes longer than one lease period to answer.

    The realistic case, not an edge case: a 300-page PDF is several embedding
    round trips, and the whole point of a lease is that it must not expire
    underneath work that is genuinely progressing.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        await asyncio.sleep(self.seconds)
        return 200, {
            "page_count": 3,
            "pages_with_text": 3,
            "characters_extracted": 1269,
            "chunk_count": 3,
        }


async def test_an_expired_lease_is_not_a_revoked_one(
    database: Database,
) -> None:
    """A worker whose lease lapsed, but whose job nobody took, still finishes.

    **This was discovered by a test that passed when it should not have.**

    The first version of the heartbeat test ran a slow ingest under a short
    lease with no reaper anywhere, and asserted the job completed. It passed —
    and went on passing with the heartbeat deleted entirely, which meant it was
    proving nothing.

    The reason is a property of the design worth pinning down: **an expired
    lease does not invalidate the token.** The token changes only when somebody
    else claims the job. So expiry is *permission for others to take it*, not a
    revocation of this worker's right to finish.

    That is the right behaviour. If nobody reclaimed the work, throwing it away
    would be worse than committing it — the result is correct, it was merely
    produced by a worker that looked slow. The conditional write protects
    against a *handover*, which is the thing that can actually corrupt.

    The consequence for testing is the important part: a heartbeat can only be
    proven by a test with a reaper in it. See the next one.
    """
    settings = _settings(lease_seconds=0.3)
    document_id = await accept(database, "slow-but-alone.pdf")

    try:
        async with session_scope(database.session_factory) as session:
            claimed = await DocumentRepository(session).claim_next_queued_job(
                lease_seconds=settings.lease_seconds
            )
            await session.commit()
        assert claimed is not None

        # Let the lease lapse, with nothing around to notice.
        await asyncio.sleep(settings.lease_seconds + 0.2)

        async with session_scope(database.session_factory) as session:
            applied = await DocumentRepository(session).mark_job_done(
                claimed.job_id,
                claimed.lease_token,
                page_count=3,
                pages_with_text=3,
                characters_extracted=1269,
                chunk_count=3,
            )
            await session.commit()

        assert applied is True, (
            "an expired lease that nobody acted on must not throw away work "
            "that was finished correctly"
        )
        assert (await read_job(database, document_id)).status == "done"
    finally:
        await cleanup(database, [document_id])


async def test_without_a_heartbeat_a_slow_job_would_be_reclaimed(
    database: Database,
) -> None:
    """The control for the test above, so it is not passing by luck.

    Here the lease is allowed to lapse — no heartbeat, just a claim and a
    wait — and a reaper then finds the job. That is the behaviour the previous
    test proves the heartbeat prevents.

    Without this control, `test_the_heartbeat_keeps_a_slow_job_alive` would
    still pass if leases never expired at all.
    """
    settings = _settings(lease_seconds=0.4)
    document_id = await accept(database, "abandoned.pdf")

    try:
        async with session_scope(database.session_factory) as session:
            claimed = await DocumentRepository(session).claim_next_queued_job(
                lease_seconds=settings.lease_seconds
            )
            await session.commit()
        assert claimed is not None

        await asyncio.sleep(settings.lease_seconds + 0.2)

        reclaimed = await reap(database, settings)

        assert reclaimed.requeued == 1, (
            "a lease nobody renewed must lapse, or the heartbeat test above "
            "proves nothing"
        )
        job = await read_job(database, document_id)
        assert job.status == "queued"
    finally:
        await cleanup(database, [document_id])


async def test_the_loop_reclaims_an_abandoned_job_and_finishes_it(
    database: Database,
) -> None:
    """**The measure of stage 2.1, in one test.**

    A job is left exactly as a killed worker leaves it: `processing`, holding
    a lease nobody will ever renew. Then the worker loop is started and does
    nothing special — it reaps before claiming, as it always does.

    The document ends `done`. **No human, no manual requeue, no intervention.**

    Note `attempts == 2`: the row records that the first attempt was lost,
    which is the difference between a system that recovered and one that
    silently did the work once.
    """
    settings = _settings(lease_seconds=0.4, retry_base_seconds=0.001)
    document_id = await accept(database, "stranded.pdf")

    try:
        # Claim it and walk away — the state a `kill -9` leaves behind.
        async with session_scope(database.session_factory) as session:
            claimed = await DocumentRepository(session).claim_next_queued_job(
                lease_seconds=settings.lease_seconds
            )
            await session.commit()
        assert claimed is not None

        await asyncio.sleep(settings.lease_seconds + 0.2)

        job = await read_job(database, document_id)
        assert job.status == "processing", "the stranded state, before recovery"

        # An ordinary worker starts. Nothing is told about the stuck job.
        stop = asyncio.Event()
        agent = FakeAgent()

        async def stop_when_done() -> None:
            while True:
                current = await read_job(database, document_id)
                if current.status == "done":
                    stop.set()
                    return
                await asyncio.sleep(0.05)

        await asyncio.wait_for(
            asyncio.gather(
                run(database, settings, stop, agent), stop_when_done()
            ),
            timeout=15.0,
        )

        job = await read_job(database, document_id)
        assert job.status == "done"
        assert job.attempts == 2, (
            "the recovery should be visible in the row: one lost attempt, one "
            "that worked"
        )
    finally:
        stop.set()
        await cleanup(database, [document_id])


async def test_the_reaper_does_not_disturb_a_working_worker(
    database: Database,
) -> None:
    """**This is the heartbeat's real test**, and the only one that catches it.

    Reclaiming a job from a worker that is still working means the ingest runs
    twice and the first result is discarded — wasted embedding spend and, once
    stage 2.2 exists, a duplicate-chunk hazard.

    One `process_one` is in flight with a slow agent — 1.2s against a 0.6s
    lease, so two lease periods — while a reaper runs alongside it eight
    times. The heartbeat keeps the deadline moving and the reaper finds
    nothing, every time.

    ── Why the obvious heartbeat test does not work ───────────────────────────

    The intuitive version is "slow ingest, short lease, assert it completes".
    That version **passes with the heartbeat deleted**, because an expired
    lease does not invalidate the token — see
    `test_an_expired_lease_is_not_a_revoked_one`. Nothing had taken the job, so
    finishing it was allowed.

    A heartbeat is only observable when something is competing for the job.
    Verified by mutation: delete the heartbeat task and this test fails while
    every other test in the file still passes.
    """
    settings = _settings(lease_seconds=0.6)
    document_id = await accept(database, "busy.pdf")
    reaped_totals: list[int] = []

    async def reap_repeatedly() -> None:
        for _ in range(8):
            await asyncio.sleep(0.15)
            reaped_totals.append((await reap(database, settings)).total)

    try:
        await asyncio.gather(
            process_one(database, settings, SlowAgent(1.2)),
            reap_repeatedly(),
        )

        assert reaped_totals and all(total == 0 for total in reaped_totals), (
            f"a reaper took a job from a live worker: {reaped_totals}"
        )
        job = await read_job(database, document_id)
        assert job.status == "done"
        assert job.attempts == 1, "the job must not have been done twice"
    finally:
        await cleanup(database, [document_id])
