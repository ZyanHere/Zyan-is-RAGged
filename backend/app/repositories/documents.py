"""Reading and writing documents and their ingestion attempts.

Every query against `documents` and `ingestion_jobs` lives here. Routes and
services talk to this class; nothing above it writes SQL or imports `select`.

── The rule that shapes this file: repositories do not commit ───────────────

Each method stages work on the session and returns. The caller decides when the
transaction ends.

That sounds like ceremony until you look at what stage 1.2 is for:

    record intent  →  COMMIT  →  call the agent  →  record outcome

The commit in the middle is the entire stage. If `create_document_with_job`
committed on your behalf, the ordering would be a property of this file rather
than of the service that performs it, and the next method someone adds would
commit too — at which point "when did this become durable?" stops having an
answer you can read.

So: this file stages, the service commits, and the ordering is visible at the
place where it matters.
"""

from collections.abc import Sequence
from typing import NamedTuple
from uuid import UUID

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import (
    Document,
    DocumentUpload,
    IngestionJob,
    IngestionStatus,
)

DocumentWithJob = tuple[Document, IngestionJob | None]


def _db_now_plus(seconds: float):
    """`now() + N seconds`, computed by the **database** clock. Stage 2.1.

    Not `datetime.now(timezone.utc) + timedelta(...)`, and the difference
    matters more here than anywhere else in this file. A lease is a comparison
    between a stored deadline and `now()` — made by a reaper that may be
    running on a different machine. If the deadline were written using one
    process's clock and compared against another's, a few seconds of skew would
    reap live workers or ignore dead ones, and the bug would appear only under
    load and never reproduce.

    `make_interval` takes positional `(years, months, weeks, days, hours, mins,
    secs)`, hence the six zeroes. Postgres has no `now() + :n * interval '1
    second'` that binds cleanly through SQLAlchemy, and string-concatenating an
    interval literal would be an injection site for a number.
    """
    return func.now() + func.make_interval(0, 0, 0, 0, 0, 0, seconds)


class ReapResult(NamedTuple):
    """What one pass of the reaper did. Stage 2.1.

    Two numbers rather than one, because they mean opposite things to whoever
    is reading the logs: `requeued` is the system recovering, `abandoned` is
    the system giving up. A single total would hide the second inside the
    first.
    """

    requeued: int
    abandoned: int

    @property
    def total(self) -> int:
        return self.requeued + self.abandoned


class ClaimedJob(NamedTuple):
    """What a worker gets when it successfully claims a job. Stage 1.3.

    **Two ids and nothing else, deliberately.** The claim is an `UPDATE …
    RETURNING`, so these values come back from the statement that performed it
    and are true by construction. Returning the whole `IngestionJob` entity
    would hand back an object the bulk UPDATE has already made stale — the 1.2
    lesson that cost an afternoon — and the worker would be reading a `status`
    of `queued` from a row the database now calls `processing`.

    Everything the worker needs to do its job is here: the `job_id` to record
    the outcome against, and the `document_id` to fetch the bytes and to pass
    down into `rag.ingest`.
    """

    job_id: UUID
    document_id: UUID

    lease_token: UUID
    """Proof that this claim, specifically, owns the job. Stage 2.1.

    Every write that finishes the job carries it, so a worker whose lease was
    reaped affects zero rows instead of overwriting whoever has it now.
    """

    attempts: int
    """How many times this job has now been claimed, including this one.

    The worker uses it to decide whether a failure is worth retrying, which is
    why it is on the claim rather than fetched later — the decision happens at
    the moment of failure, when another query would be one more thing to fail.
    """


class DocumentRepository:
    """Persistence for documents and their ingestion attempts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create_document_with_job(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None,
        content_hash: str,
    ) -> tuple[Document, IngestionJob]:
        """Record that a document exists and that we are about to index it.

        Both rows in one transaction: a document with no attempt attached is a
        half-truth, and the pair is a single logical fact — *this arrived and
        we started work on it*.

        Returns both objects with their ids populated. `flush()` sends the
        INSERTs and gets the server-side defaults back **without committing**,
        so the caller still owns the transaction boundary.

        **Three rows now, not two** — the upload joins them at stage 1.3.

        `byte_size` is no longer a parameter: it is `len(content)`, and taking
        both invited them to disagree. A caller that passed a stale size would
        have produced a document whose recorded size did not match its stored
        bytes, with nothing to catch it.

        **All three in one transaction, which is the point.** A job with no
        upload is a job a worker cannot run; an upload with no job is bytes
        nobody will ever look at. The pair being atomic is what lets the worker
        treat "I claimed a job" as "its input exists".

        **The job starts `queued` with no `started_at`.** Until stage 1.3 it
        started `processing`, because the request that created it was about to
        do the work itself — there was no interval during which "waiting" was
        a true description.

        Now there is, and `started_at IS NULL` is what says so. A worker stamps
        it when it claims the job, so the gap between `queued_at` and
        `started_at` is the queue's wait time, measurable per job.

        Nothing in this call starts any work. That is the point: after it
        returns and the caller commits, the only thing that exists is a
        promise.

        **`content_hash` is required, not optional — stage 2.2.** It is computed
        by the caller, which already holds the bytes, and it is what makes this
        INSERT capable of *failing*: `uq_documents_content_hash` refuses a
        second document with the same hash.

        That failure is a feature and the caller has to be ready for it. This
        method does not catch it, for the same reason it does not commit: the
        decision about what a duplicate upload means is a product decision and
        belongs where the rest of them are. See `IngestionService.accept_upload`.

        It has no default. A default of `None` would let a caller silently opt
        out of deduplication, and the one place that writes documents would be
        the one place able to bypass the rule the whole stage is about.
        """
        document = Document(
            filename=filename,
            byte_size=len(content),
            content_type=content_type,
            content_hash=content_hash,
        )
        job = IngestionJob(
            document=document,
            status=IngestionStatus.QUEUED,
            # Explicit, and it has to be: the column has no server default, and
            # SQLAlchemy would otherwise omit it from the INSERT. Passing None
            # is what writes NULL — see the column's docstring.
            started_at=None,
        )
        upload = DocumentUpload(document=document, content=content)

        self._session.add(document)
        self._session.add(job)
        self._session.add(upload)
        await self._session.flush()

        return document, job

    async def create_job_for_document(
        self, document_id: UUID
    ) -> IngestionJob:
        """Queue another attempt at a document that already exists. Stage 2.2.

        One row. No new document, no second copy of the bytes, no new identity.

        ── This is the two-table split finally paying out ──────────────────────

        `models.py` argues for separating identity from attempts, and the
        argument has been theoretical since 1.2 — every document had exactly one
        job, written in the same transaction. This is the first caller that
        needs the other shape.

        It exists because of a specific case. Someone uploads a PDF, ingestion
        fails, they upload the same file again to make it work. The bytes are
        identical, so `uq_documents_content_hash` says it is the same document —
        and it *is* the same document. What is new is the attempt.

        If identity and attempts shared a table, there would be no way to say
        that: you would either reject the re-upload (and strand the user with a
        document they cannot fix) or create a second document (and pay for the
        same file twice, which is what this stage removes).

        ── Why it does not check the document exists ──────────────────────────

        The foreign key does. A bad `document_id` raises `IntegrityError` on
        flush, which is the same answer one query earlier and one round trip
        cheaper. The caller in `accept_upload` has just read the document
        anyway, so a check here would re-read a row it already has.

        ── The new job's state, and why every field is explicit ──────────────

        `queued`, `started_at = None`, `attempts = 0`, no lease, no
        `next_attempt_at`. A *fresh* attempt, not a continuation: the previous
        job keeps its own `attempts` and its own error, so the history of what
        was tried survives, which is exactly what a second table is for.

        `attempts = 0` is deliberate rather than inherited. Carrying the failed
        job's count forward would mean a re-upload started life halfway through
        its retry budget, and a document that had exhausted it could never be
        retried at all — a user's deliberate second attempt silently refused
        because of what happened to the first.
        """
        job = IngestionJob(
            document_id=document_id,
            status=IngestionStatus.QUEUED,
            # Explicit for the same reason as in `create_document_with_job`:
            # the column has no server default, so SQLAlchemy omits it from the
            # INSERT unless told, and `queued` with a `started_at` violates
            # `ck_ingestion_jobs_started_at_matches_status`.
            started_at=None,
        )
        self._session.add(job)
        await self._session.flush()

        return job

    async def claim_next_queued_job(
        self, *, lease_seconds: float
    ) -> ClaimedJob | None:
        """Take the oldest queued job, or return `None` if there is nothing.

        **This is the mechanism the whole stage turns on.** Two workers polling
        the same table must never take the same job: the document would be
        ingested twice, embedded twice — real money — and chunked twice, so the
        same fact would be cited twice from the same page.

        ── The SQL, and why it is one statement ────────────────────────────────

            UPDATE ingestion_jobs
               SET status = 'processing', started_at = now()
             WHERE id = (SELECT id FROM ingestion_jobs
                          WHERE status = 'queued'
                          ORDER BY queued_at, id
                          LIMIT 1
                          FOR UPDATE SKIP LOCKED)
            RETURNING id, document_id

        `FOR UPDATE` locks the chosen row until this transaction ends.
        **`SKIP LOCKED` is the part that matters**: without it a second worker
        *blocks* on the row the first is holding, so ten workers process one
        job at a time and the queue is correct but pointless. With it, a locked
        row is treated as though it were not there and the second worker takes
        the next one. No collisions and no waiting.

        ── Why not two statements ─────────────────────────────────────────────

        The obvious shape is `SELECT … FOR UPDATE SKIP LOCKED`, then `UPDATE`.
        It is correct, and it was the first version here. One statement is
        better for two reasons:

        * **one round trip instead of two**, which matters when the loop does
          nothing else;
        * **no stale object.** A separate bulk UPDATE leaves the entity the
          SELECT returned describing a row that no longer exists in that
          state — the bug stage 1.2 spent an afternoon on. `RETURNING` hands
          back values produced by the statement that wrote them.

        ── What this deliberately does not do ─────────────────────────────────

        **No lease, no heartbeat, no expiry.** A worker that dies after
        claiming leaves the job at `processing` forever and nothing reclaims
        it. That is stage 2.1, and it is only buildable once there is a stuck
        row to observe — so this method creates the problem on purpose.

        The caller commits. The lock is released at that commit, by which point
        the row is `processing` and no longer matches the `queued` filter, so
        nobody else can select it regardless.
        """
        next_queued = (
            select(IngestionJob.id)
            .where(
                IngestionJob.status == IngestionStatus.QUEUED,
                # The backoff, honoured here rather than slept on. A worker
                # that waited in Python would hold a process doing nothing and
                # would forget the delay entirely on restart; a timestamp
                # survives both, and any worker can respect it.
                #
                # NULL means "no delay was ever set", which is every job that
                # has not failed yet — hence the OR rather than a default.
                or_(
                    IngestionJob.next_attempt_at.is_(None),
                    IngestionJob.next_attempt_at <= func.now(),
                ),
            )
            # Oldest first, with `id` as a tiebreaker because `queued_at` is
            # `transaction_timestamp()` and a batch upload shares one value.
            # Without it the order within a batch is whatever the planner
            # chooses, which is not wrong but is not FIFO either.
            .order_by(IngestionJob.queued_at, IngestionJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )

        claimed = (
            await self._session.execute(
                update(IngestionJob)
                .where(IngestionJob.id == next_queued)
                # Same reason as `mark_job_done`: this is a bulk UPDATE and the
                # ORM must not try to reconcile it against the identity map.
                .execution_options(synchronize_session=False)
                .values(
                    status=IngestionStatus.PROCESSING,
                    started_at=func.now(),
                    # ── The lease ────────────────────────────────────────────
                    #
                    # A fresh token per claim, not per worker. If it named the
                    # worker, a worker that lost a lease and later re-claimed
                    # the same job could not tell its two attempts apart —
                    # and the stale write from the first would be accepted by
                    # the second.
                    lease_token=uuid.uuid4(),
                    lease_expires_at=_db_now_plus(lease_seconds),
                    # Counts claims, not failures: a worker that died silently
                    # still used one up. The conservative reading, and what
                    # stops a job that crashes its worker from cycling forever.
                    attempts=IngestionJob.attempts + 1,
                    # This claim *is* the attempt that was being waited for.
                    next_attempt_at=None,
                )
                .returning(
                    IngestionJob.id,
                    IngestionJob.document_id,
                    IngestionJob.lease_token,
                    IngestionJob.attempts,
                )
            )
        ).one_or_none()

        if claimed is None:
            return None

        return ClaimedJob(
            job_id=claimed.id,
            document_id=claimed.document_id,
            lease_token=claimed.lease_token,
            attempts=claimed.attempts,
        )

    async def renew_lease(
        self, job_id: UUID, lease_token: UUID, *, lease_seconds: float
    ) -> bool:
        """Push this claim's deadline forward. `False` means it is gone.

        **The heartbeat.** You cannot ask a dead process whether it is dead, so
        the design inverts the question: staying alive is something a worker
        has to keep doing, and a worker that stops doing it is indistinguishable
        from one that died — which is the point.

        Returning `False` rather than raising, because losing a lease is not an
        error. It means a reaper decided this worker was gone and gave the job
        to someone else, which is the system working. The worker's job is to
        notice and stop, not to panic.
        """
        result = await self._session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.lease_token == lease_token,
            )
            .execution_options(synchronize_session=False)
            .values(lease_expires_at=_db_now_plus(lease_seconds))
        )
        return result.rowcount == 1

    async def get_upload_content(self, document_id: UUID) -> bytes | None:
        """The stored bytes for a document, or `None` if there are none.

        Selects the **column**, not the entity. Loading a `DocumentUpload`
        would put a 25 MB object in the session's identity map where it would
        stay until the session closed; this returns the bytes and keeps nothing.

        `None` means no upload row, which after stage 1.3 should be impossible
        for a job that exists — they are written in one transaction. The worker
        treats it as a failure rather than a crash, because a job whose input
        has vanished is a real state to record and a stack trace is not.
        """
        return (
            await self._session.execute(
                select(DocumentUpload.content).where(
                    DocumentUpload.document_id == document_id
                )
            )
        ).scalar_one_or_none()

    async def mark_job_done(
        self,
        job_id: UUID,
        lease_token: UUID,
        *,
        page_count: int,
        pages_with_text: int,
        characters_extracted: int,
        chunk_count: int,
    ) -> None:
        """Record a successful attempt and its numbers.

        `status` and `finished_at` are set in **one** UPDATE, and that is not a
        style preference — `ck_ingestion_jobs_finished_at_matches_status`
        requires a job to be `processing` exactly while `finished_at` is NULL.
        Setting them in two statements fails on the first one.

        A good example of a constraint shaping code rather than merely
        validating it.

        `func.now()` rather than a Python timestamp keeps the database clock
        authoritative, which matters once there is more than one API instance.

        ── The ownership check, added at stage 2.1 ─────────────────────────────

        `AND lease_token = :lease_token` is what makes a reaper safe to have.
        Without it the sequence below silently corrupts, and nothing anywhere
        reports a problem:

            worker A claims job 7
            A pauses — GC, a VM suspend, a laptop lid
            the lease expires; a reaper requeues job 7
            worker B claims it, indexes it, marks it done
            A wakes up and marks job 7 done
                → overwrites B's counts with A's
                → and the document is now indexed twice

        **Returns whether it applied.** `False` is not an error — it means a
        reaper decided this worker was gone, which is the system working. The
        worker's job is to notice and stop.

        The lease is cleared in the same statement, because
        `ck_ingestion_jobs_lease_matches_status` forbids a `done` job from
        still holding one. A lease outliving its work would let a *later* stale
        write succeed.
        """
        result = await self._session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.lease_token == lease_token,
            )
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.DONE,
                finished_at=func.now(),
                lease_token=None,
                lease_expires_at=None,
                page_count=page_count,
                pages_with_text=pages_with_text,
                characters_extracted=characters_extracted,
                chunk_count=chunk_count,
            )
        )
        return result.rowcount == 1

    async def mark_job_failed(
        self, job_id: UUID, lease_token: UUID, *, error: str
    ) -> bool:
        """Record a failed attempt and why.

        `error` is required by `ck_ingestion_jobs_failed_requires_error`: a
        failure with no explanation is one nobody can diagnose. If the cause is
        genuinely unknown, the caller must say `"unknown"` — which is at least
        honest, and which stage 2.3 will want when it starts classifying
        failures as transient or permanent.

        Carries the same ownership check as `mark_job_done`, for the same
        reason: a stale worker must not be able to mark someone else's
        in-progress job as failed. That would be worse than the success case —
        it destroys work that was going fine.
        """
        result = await self._session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.lease_token == lease_token,
            )
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.FAILED,
                finished_at=func.now(),
                lease_token=None,
                lease_expires_at=None,
                error=error,
            )
        )
        return result.rowcount == 1

    async def requeue_job(
        self,
        job_id: UUID,
        lease_token: UUID,
        *,
        error: str,
        delay_seconds: float,
    ) -> bool:
        """Put a failed job back on the queue, to be retried after a delay.

        Stage 2.1's answer to the defect that an agent restart used to destroy
        every in-flight document: a failure stops being terminal.

        ── What has to move together ───────────────────────────────────────────

        Four columns, and three of them are forced by constraints rather than
        chosen:

            status      → queued        the job is claimable again
            started_at  → NULL          `started_at_matches_status` requires it:
                                        a queued job has no current attempt
            lease_*     → NULL          `lease_matches_status` requires it
            next_attempt_at → now()+d   the backoff

        `started_at` being cleared looks like information loss and is not. It
        means "when the *current* attempt began", and a requeued job has no
        current attempt. The history is in `attempts`.

        ── Why the error is kept ───────────────────────────────────────────────

        `failed_requires_error` does not apply to a `queued` row, so this could
        clear it. It deliberately does not: a job waiting to retry should still
        say why it is waiting, and the client renders exactly that — "retrying
        after: the agent did not respond". Clearing it would make a retrying
        job indistinguishable from a fresh upload.
        """
        result = await self._session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.lease_token == lease_token,
            )
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.QUEUED,
                started_at=None,
                lease_token=None,
                lease_expires_at=None,
                next_attempt_at=_db_now_plus(delay_seconds),
                error=error,
            )
        )
        return result.rowcount == 1

    async def reap_expired_leases(self, *, max_attempts: int) -> ReapResult:
        """Reclaim jobs whose worker stopped renewing. Stage 2.1.

        **This is the thing that makes a stuck row temporary.** Before it, a
        worker that died left a job `processing` forever and nothing in the
        system would ever look at it again.

        ── Two statements, not one with a CASE ────────────────────────────────

        They answer different questions and the order matters:

        1. **Exhausted** — expired *and* already tried `max_attempts` times.
           Giving up is the right answer: a job that reliably kills its worker
           would otherwise cycle forever, and each cycle costs a claim, an
           ingest attempt and possibly embedding quota. This is the bound on
           the poison-message problem that stage 2.3 will handle properly.

        2. **Recoverable** — everything else that expired. Straight back to
           `queued`.

        Exhausted first, because the second statement's filter would otherwise
        sweep those rows up and requeue them.

        ── No backoff on a reaped job ─────────────────────────────────────────

        `next_attempt_at` is left alone here, deliberately. A crashed worker is
        not a failing job — the work never got a verdict — so making the
        document wait is punishing it for someone else's crash. Recovery should
        be prompt; the bound against cycling is `attempts`, not delay.

        ── Why no `SKIP LOCKED` ───────────────────────────────────────────────

        Every worker runs this, so two reapers can collide on the same row.
        They do not need to be kept apart: both are writing the same thing, and
        the second one's UPDATE simply matches nothing because the first
        already changed the status. Reaping is idempotent in a way claiming is
        not.
        """
        expired = IngestionJob.lease_expires_at < func.now()

        abandoned = await self._session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.status == IngestionStatus.PROCESSING,
                expired,
                IngestionJob.attempts >= max_attempts,
            )
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.FAILED,
                finished_at=func.now(),
                lease_token=None,
                lease_expires_at=None,
                error=(
                    "Abandoned: the worker holding this job stopped responding, "
                    f"and it has already been attempted {max_attempts} times."
                ),
            )
        )

        requeued = await self._session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.status == IngestionStatus.PROCESSING,
                expired,
            )
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.QUEUED,
                started_at=None,
                lease_token=None,
                lease_expires_at=None,
            )
        )

        return ReapResult(
            requeued=requeued.rowcount, abandoned=abandoned.rowcount
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    def _latest_job_subquery(self):
        """One row per document: its most recent attempt.

        `DISTINCT ON (document_id)` with `ORDER BY document_id, started_at
        DESC` is Postgres's way of saying "first row per group". The ORDER BY's
        leading column **must** match the DISTINCT ON column or Postgres
        rejects it — the ordering is what decides which row survives.

        Alternatives, and why not:

          ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY started_at DESC)
              portable to any SQL database, several lines longer, and sorts
              every row rather than stopping at the first per group.

          LATERAL subquery
              what you need for "the latest N per document". Overkill for one.

        Portability is not a concern here: `SELECT ... FOR UPDATE SKIP LOCKED`
        at stage 2.1 already ties this project to Postgres.

        **An index worth adding later, not now:** this would prefer
        `(document_id, started_at DESC)`, where today only `(document_id)`
        exists. With a handful of rows the planner will seq-scan regardless, so
        adding it now would be an index justified by a guess. Stage 11.3's rule
        is indexes justified by `EXPLAIN ANALYZE` — revisit when the table has
        enough rows for the plan to mean anything.

        **Ordered by `queued_at`, not `started_at` — stage 1.3.** `started_at`
        became nullable when `queued` arrived, and it is NULL for exactly the
        newest job. Ordering by it would decide "latest" using a column the
        latest row does not have, and where that row lands then depends on the
        database's NULLS default rather than on anything intended.

        `id DESC` is a tiebreaker for the same reason it appears in
        `list_documents_with_latest_job`: `now()` is `transaction_timestamp()`,
        so two jobs written in one transaction share an identical `queued_at`.
        With `DISTINCT ON` that is worse than an unstable sort — the tie
        decides *which row survives*, so without the tiebreaker the endpoint
        can report a different job's status on different days.
        """
        return (
            select(IngestionJob)
            .ext(distinct_on(IngestionJob.document_id))
            .order_by(
                IngestionJob.document_id,
                IngestionJob.queued_at.desc(),
                IngestionJob.id.desc(),
            )
            .subquery()
        )

    async def list_documents_with_latest_job(
        self, *, limit: int = 50
    ) -> Sequence[DocumentWithJob]:
        """Every document with the state of its most recent attempt.

        An **outer** join: a document with no job is wrong but not impossible,
        and silently hiding such a row would conceal exactly the kind of
        inconsistency this stage exists to make visible.
        """
        latest = self._latest_job_subquery()
        job = aliased(IngestionJob, latest)

        result = await self._session.execute(
            select(Document, job)
            .outerjoin(job, job.document_id == Document.id)
            .execution_options(populate_existing=True)
            # A unique tiebreaker, not decoration.
            #
            # `created_at` is not unique: Postgres's `now()` is
            # `transaction_timestamp()`, so every row written in one
            # transaction shares an identical value. Ordering by it alone
            # leaves the planner free to return those rows in any order, and
            # it will return a different one on a different day.
            #
            # `id` is a UUIDv7, which is time-ordered, so it is both a unique
            # tiebreaker and the right one — it breaks ties in creation order.
            #
            # This becomes correctness rather than tidiness at stage 19.1,
            # where keyset pagination over a non-unique sort key silently skips
            # and repeats rows across pages.
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
        )
        return [(document, j) for document, j in result.all()]

    async def get_document_with_latest_job(
        self, document_id: UUID
    ) -> DocumentWithJob | None:
        """One document and its most recent attempt, or `None` if unknown."""
        latest = self._latest_job_subquery()
        job = aliased(IngestionJob, latest)

        result = await self._session.execute(
            select(Document, job)
            .outerjoin(job, job.document_id == Document.id)
            .where(Document.id == document_id)
            .execution_options(populate_existing=True)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def get_by_content_hash(
        self, content_hash: str
    ) -> DocumentWithJob | None:
        """The document with these exact bytes, and its latest attempt. Stage 2.2.

        The read that makes an upload idempotent. `accept_upload` asks this
        first, and when it answers, nothing is written and nothing is queued.

        ── Why it returns the latest job and not just the document ────────────

        Because the caller's next decision depends on it. A duplicate of a
        document that is `done` is a no-op; a duplicate of one whose last
        attempt `failed` is a request to try again. One query answers both
        instead of the service fetching the document and then its job.

        It is the same `DISTINCT ON` shape as `get_document_with_latest_job` —
        deliberately, so "what is the state of this document?" has one
        implementation however you arrive at the row.

        ── Why the lookup cannot be trusted on its own ───────────────────────

        This is a read, so two concurrent uploads of the same bytes can both
        get `None` from it and both proceed to insert. The unique constraint is
        what resolves that, and the caller handles the loser's `IntegrityError`.

        Checking first is still worth it: it makes the ordinary duplicate — a
        user re-uploading deliberately — a single SELECT with no write
        attempted, and leaves the constraint to handle only the genuine race.

        ── No index needed, and that is not an oversight ─────────────────────

        `uq_documents_content_hash` is backed by a unique B-tree index, which
        this equality lookup uses. A unique constraint is an index; adding a
        second one on the same column would be dead weight.
        """
        latest = self._latest_job_subquery()
        job = aliased(IngestionJob, latest)

        result = await self._session.execute(
            select(Document, job)
            .outerjoin(job, job.document_id == Document.id)
            .where(Document.content_hash == content_hash)
            .execution_options(populate_existing=True)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def get_job(self, job_id: UUID) -> IngestionJob | None:
        """One attempt by id, as the database currently has it.

        `populate_existing=True` is load-bearing here, and the bug it prevents
        is subtle enough to be worth spelling out.

        `mark_job_done` and `mark_job_failed` issue bulk UPDATE statements.
        Those change rows in the database; they do not reliably update objects
        the session already holds. A plain `session.get()` returns the
        **cached instance from the identity map without querying at all**, so
        reading a job straight after marking it hands back the pre-update
        object — status possibly stale, `error` still `None`, while the row in
        Postgres says otherwise.

        It is a bad failure mode because it is half-right: some attributes look
        updated and some do not, so it reads like data corruption rather than a
        caching artifact.

        `populate_existing` forces the SELECT and overwrites the cached
        instance with what came back. The cost is one query where `get()` could
        sometimes have avoided it — a trade worth making for a method whose
        entire contract is "what does the database say?".
        """
        result = await self._session.execute(
            select(IngestionJob)
            .where(IngestionJob.id == job_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
