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
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Document, IngestionJob, IngestionStatus

DocumentWithJob = tuple[Document, IngestionJob | None]


class DocumentRepository:
    """Persistence for documents and their ingestion attempts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create_document_with_job(
        self,
        *,
        filename: str,
        byte_size: int,
        content_type: str | None,
    ) -> tuple[Document, IngestionJob]:
        """Record that a document exists and that we are about to index it.

        Both rows in one transaction: a document with no attempt attached is a
        half-truth, and the pair is a single logical fact — *this arrived and
        we started work on it*.

        Returns both objects with their ids populated. `flush()` sends the
        INSERTs and gets the server-side defaults back **without committing**,
        so the caller still owns the transaction boundary.

        The job starts as `processing` rather than `queued`. Nothing queues
        anything yet — ingestion is synchronous, so a `queued` state would last
        microseconds. It becomes meaningful at stage 1.3.
        """
        document = Document(
            filename=filename,
            byte_size=byte_size,
            content_type=content_type,
        )
        job = IngestionJob(
            document=document,
            status=IngestionStatus.PROCESSING,
        )

        self._session.add(document)
        self._session.add(job)
        await self._session.flush()

        return document, job

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
        """
        return (
            select(IngestionJob)
            .ext(distinct_on(IngestionJob.document_id))
            .order_by(
                IngestionJob.document_id, IngestionJob.started_at.desc()
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
