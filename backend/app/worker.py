"""The ingestion worker. Stage 1.3.

    python -m app.worker

A second process whose entire job is a loop:

    claim a queued job  →  ingest it  →  record the outcome  →  repeat

── Why a separate process and not a background task ────────────────────────────

A `BackgroundTask`, an `asyncio.create_task` in the API, or a thread would all
move the work off the *request*. None of them moves it out of the *process*,
and that is what matters:

* the API's CPU would still do the extraction and chunking for every upload;
* a deploy or a crash would still kill whatever was mid-ingest, except now with
  no request open for anyone to notice;
* ingestion and serving would scale together, when the whole point is that they
  have different limits — the API is bound by request concurrency, the worker by
  the embedding provider's rate limit.

Separate processes mean `python -m app.worker` three times is three workers, and
`SKIP LOCKED` makes that safe with no further coordination.

── Why the database is the queue ───────────────────────────────────────────────

No Redis, no RabbitMQ, no SQS. A queue needs exactly one hard property — two
workers must never take the same job — and `SELECT … FOR UPDATE SKIP LOCKED`
provides it in one clause, against a database this system already runs, backs up
and reasons about.

The honest limit: a polling SQL queue tops out somewhere in the low thousands of
jobs per second and cannot fan one message out to several consumers. Both are
orders of magnitude from anything here, and the Evolution Map names the trigger
for a broker rather than assuming one.

── The two background jobs this process does besides ingesting ─────────────────

**A heartbeat**, for the job it is holding. A lease is a deadline, and the only
thing that distinguishes a slow worker from a dead one is whether it keeps
pushing that deadline forward. It runs on its own database session, because the
session doing the ingest is in the middle of a transaction and cannot be used
concurrently.

**A reaper**, before every claim. It finds jobs whose worker stopped renewing
and puts them back on the queue. Every worker runs it, so it is redundant by
construction — with one worker, recovery waits for the current job to finish,
which is acceptable because a single busy worker could not have processed the
stranded job anyway.

── What this still deliberately does not do ───────────────────────────────────

**It does not cancel work when the lease is lost.** A worker that discovers
mid-ingest that it has been reaped carries on to the end, and its final write
is rejected by the conditional UPDATE. The work is wasted but nothing is
corrupted. Cancelling an in-flight agent call needs real drain semantics and is
stage 12.3.

**It does not classify failures.** Everything retries until the attempts run
out — see `RetryPolicy`.
"""

import asyncio
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from app.core.config import Settings, get_settings
from app.db.session import Database, create_database, session_scope, verify_connectivity
from app.repositories.documents import (
    ClaimedJob,
    DocumentRepository,
    ReapResult,
)
from app.services import agent_client
from app.services.ingestion import AgentClient, IngestionService, RetryPolicy

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _heartbeat(
    database: Database, claimed: ClaimedJob, settings: Settings
) -> AsyncIterator[asyncio.Event]:
    """Keep renewing this job's lease until the block exits.

    ── Why a third of the lease ────────────────────────────────────────────────

    At `lease_seconds / 3`, two consecutive renewals can fail — a slow query, a
    brief network blip — before anyone is entitled to call this worker dead.
    Renewing once per lease period would make a single hiccup look like a
    death, and the job would be taken away from a worker that was fine.

    ── Why its own session ────────────────────────────────────────────────────

    The session doing the ingest is inside a transaction for the whole
    operation, and a SQLAlchemy session is not safe to use from two places at
    once. More importantly a renewal must be **visible to other processes
    immediately**, which means committing — and committing on the ingest's
    session would end its transaction half way through the job.

    So each beat opens its own short-lived session, writes, commits, closes.

    ── Why a failed beat does not stop the heartbeat ──────────────────────────

    A database blip is not a lost lease. If the renewals keep failing the lease
    lapses on its own and a reaper takes the job, which is the correct outcome
    arrived at without this loop having to decide anything. Giving up after one
    error would turn a one-second outage into a lost job.

    What *does* stop it is `renew_lease` returning `False` — a definite answer
    that the job now belongs to someone else.

    The returned event is set in that case. Nothing currently acts on it beyond
    logging: the ingest is already in flight and cancelling it is stage 12.3.
    """
    lost = asyncio.Event()
    interval = settings.lease_seconds / 3

    async def beat() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                async with session_scope(database.session_factory) as session:
                    alive = await DocumentRepository(session).renew_lease(
                        claimed.job_id,
                        claimed.lease_token,
                        lease_seconds=settings.lease_seconds,
                    )
                    await session.commit()
            except Exception:
                logger.exception(
                    "could not renew the lease for job_id=%s; will try again",
                    claimed.job_id,
                )
                continue

            if not alive:
                logger.warning(
                    "lost the lease for job_id=%s while still working on it — "
                    "a reaper gave it to someone else. The lease may be too "
                    "short for this workload.",
                    claimed.job_id,
                )
                lost.set()
                return

    task = asyncio.create_task(beat())
    try:
        yield lost
    finally:
        task.cancel()
        # Awaiting the cancelled task is what makes this deterministic: without
        # it the beat can outlive the block and renew a lease for a job that
        # has already finished.
        with suppress(asyncio.CancelledError):
            await task


async def reap(database: Database, settings: Settings) -> ReapResult:
    """Reclaim jobs whose worker stopped renewing.

    Its own session and transaction, so a failure here cannot poison the claim
    that follows — a reaper that cannot run is a degraded system, not a broken
    one, and the worker should carry on ingesting.
    """
    async with session_scope(database.session_factory) as session:
        result = await DocumentRepository(session).reap_expired_leases(
            max_attempts=settings.max_attempts
        )
        await session.commit()
    return result


async def process_one(
    database: Database,
    settings: Settings,
    agent: AgentClient = agent_client,
) -> bool:
    """Claim one job and run it. Returns whether there was anything to do.

    ── Two sessions, and that is the interesting part ──────────────────────────

    The claim and the work happen in **separate transactions on separate
    sessions**, which is a deliberate choice with two consequences:

    1. **A crash after the claim leaves a `processing` row.** If both were one
       transaction, a crash would roll the claim back too and the job would
       return to `queued` — which sounds better and is exactly what stage 2.1
       is for. Doing it accidentally here would quietly pre-solve 2.1 and
       destroy its trigger.

    2. **The database connection is released during the ingest.** The claim's
       session closes before the agent is called, so a 45-second ingest does
       not occupy a pool slot for 45 seconds. With `db_pool_size = 5`, holding
       one would mean five concurrent workers could starve the API of
       connections while doing no database work at all.

    The second reason is the one that would bite in production, and it is
    invisible until something is slow.
    """
    async with session_scope(database.session_factory) as session:
        claimed = await DocumentRepository(session).claim_next_queued_job(
            lease_seconds=settings.lease_seconds
        )
        if claimed is None:
            return False
        # Publish the claim before doing any work. After this commit the row
        # says `processing` to every other process, and the row lock is gone.
        await session.commit()

    logger.info(
        "claimed job_id=%s document_id=%s attempt=%d",
        claimed.job_id,
        claimed.document_id,
        claimed.attempts,
    )

    async with _heartbeat(database, claimed, settings):
        async with session_scope(database.session_factory) as session:
            repository = DocumentRepository(session)
            service = IngestionService(session, repository, agent)
            await service.process_job(
                claimed,
                RetryPolicy(
                    max_attempts=settings.max_attempts,
                    base_seconds=settings.retry_base_seconds,
                    max_delay_seconds=settings.max_delay_seconds,
                ),
            )

    return True


async def run(
    database: Database,
    settings: Settings,
    stop: asyncio.Event,
    agent: AgentClient = agent_client,
) -> None:
    """Drain the queue until asked to stop.

    **Loops immediately after doing work and waits only when idle.** A fixed
    sleep between every job would cap throughput at one job per interval
    regardless of how fast the jobs are, which is a throughput limit imposed by
    a constant nobody chose for that purpose.

    ── Why an unexpected exception does not kill the loop ──────────────────────

    `process_job` already turns every *expected* failure — a rejected PDF, an
    unreachable agent — into a `failed` job. An exception escaping it means
    something unforeseen: a bug, or the database going away mid-statement.

    The loop logs it and carries on, because one unprocessable job must not
    stop every other job in the queue. What it does **not** do is mark that job
    failed: it does not know how far the work got, and claiming knowledge it
    does not have is worse than leaving the row visibly stuck. So the row stays
    `processing` — 2.1's problem, created honestly.

    It backs off after an error for the same reason it backs off when idle: if
    the database is down, every iteration raises instantly, and a tight loop
    would turn one outage into a second one.

    `BaseException` is **not** caught. `KeyboardInterrupt` and `SystemExit`
    must end the process, and a real `kill -9` offers no choice anyway.
    """
    logger.info(
        "worker started poll_interval=%.1fs agent=%s",
        settings.worker_poll_seconds,
        settings.agent_base_url,
    )

    while not stop.is_set():
        try:
            # Before claiming, give back anything a dead worker was holding.
            # Running it here rather than in its own process means it is
            # redundant across however many workers exist, and that no extra
            # thing has to be deployed and watched for this one to keep
            # working.
            reclaimed = await reap(database, settings)
            if reclaimed.total:
                # `warning`, not `info`: reclaiming always means something
                # died. It is the system recovering, and it is still evidence.
                logger.warning(
                    "reclaimed %d abandoned job(s): %d requeued, %d given up on",
                    reclaimed.total,
                    reclaimed.requeued,
                    reclaimed.abandoned,
                )

            did_work = await process_one(database, settings, agent)
        except Exception:
            # `exception()` rather than `error()`: the traceback is the only
            # thing that makes an unforeseen failure diagnosable, and there is
            # no request to attach it to.
            logger.exception("worker iteration failed; the job is left in place")
            await _wait(stop, settings.worker_poll_seconds)
            continue

        if not did_work:
            await _wait(stop, settings.worker_poll_seconds)

    logger.info("worker stopped")


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake immediately if asked to stop.

    `asyncio.sleep(seconds)` would make shutdown take up to a full interval,
    which is the difference between a container stopping in milliseconds and
    Docker eventually sending it `SIGKILL`.
    """
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Ask the loop to finish its current job and exit.

    ── The Windows caveat, handled rather than discovered ──────────────────────

    `loop.add_signal_handler` is the correct asyncio API and it raises
    `NotImplementedError` on Windows' `ProactorEventLoop`. The fallback is the
    plain `signal.signal`, which on Windows supports `SIGINT` (Ctrl-C) and
    treats `SIGTERM` as a best-effort.

    `call_soon_threadsafe` in the fallback is not paranoia: a `signal.signal`
    handler interrupts whatever the interpreter is doing, and touching an
    `asyncio.Event` from there is only safe by going through the loop.

    **Either way this is cooperative.** The worker finishes the job it is
    holding before exiting, so a clean stop never creates a stuck row. An
    unclean stop — `kill -9`, a power cut, Docker losing patience — does, and
    that is the gap stage 2.1 fills.
    """
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def main() -> None:
    """Wire up, verify, run, dispose.

    Mirrors the API's `lifespan` on purpose: the same `create_database`, the
    same `SELECT 1` before accepting any work. A worker that starts against a
    dead database and discovers it on the first job looks like a job problem
    rather than an infrastructure one.
    """
    # Without this the worker prints nothing at all.
    #
    # Python's root logger has no handler, so `logging.lastResort` passes only
    # WARNING and above — the same reason every `logger.info` in this codebase
    # has been silently discarded. For the API that is merely unhelpful; for a
    # process whose entire observable behaviour is its log, it makes the thing
    # unusable.
    #
    # This is a floor, not a design. Structured JSON logs with a `request_id`
    # threaded from the API are stage 2.4, and they replace this line.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    settings = get_settings()
    database = create_database(settings)

    try:
        await verify_connectivity(database.engine)
    except Exception as exc:
        logger.error(
            "Cannot reach the database. Is Postgres running? "
            "`docker compose up -d` from the repository root. (%s)",
            exc,
        )
        await database.engine.dispose()
        raise

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    try:
        await run(database, settings, stop)
    finally:
        await database.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
