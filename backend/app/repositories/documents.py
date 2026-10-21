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

from sqlalchemy import func, select, update
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
        """
        document = Document(
            filename=filename,
            byte_size=len(content),
            content_type=content_type,
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

    async def claim_next_queued_job(self) -> ClaimedJob | None:
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
            .where(IngestionJob.status == IngestionStatus.QUEUED)
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
                )
                .returning(IngestionJob.id, IngestionJob.document_id)
            )
        ).one_or_none()

        if claimed is None:
            return None

        return ClaimedJob(job_id=claimed.id, document_id=claimed.document_id)

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
        """
        await self._session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.DONE,
                finished_at=func.now(),
                page_count=page_count,
                pages_with_text=pages_with_text,
                characters_extracted=characters_extracted,
                chunk_count=chunk_count,
            )
        )

    async def mark_job_failed(self, job_id: UUID, *, error: str) -> None:
        """Record a failed attempt and why.

        `error` is required by `ck_ingestion_jobs_failed_requires_error`: a
        failure with no explanation is one nobody can diagnose. If the cause is
        genuinely unknown, the caller must say `"unknown"` — which is at least
        honest, and which stage 2.3 will want when it starts classifying
        failures as transient or permanent.
        """
        await self._session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .execution_options(synchronize_session=False)
            .values(
                status=IngestionStatus.FAILED,
                finished_at=func.now(),
                error=error,
            )
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
