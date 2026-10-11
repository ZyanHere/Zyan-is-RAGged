"""Ingesting a document, durably.

This module exists for one line of code, and everything else here is in service
of making that line obvious:

    await session.commit()        # before the agent is called, not after

── Why that ordering is the whole of stage 1.2 ──────────────────────────────

Before this stage, the only evidence a document existed was its chunks in
Qdrant. That is a *result*, not a record of intent. Kill the process halfway
through a 300-page PDF and you are left with some chunks and no way to tell
whether the document was half-indexed, fully indexed, or never uploaded at all.
"Partially indexed" and "never happened" looked identical.

Committing the intent *first* separates them. After the commit there is a row
saying **this arrived and we started work on it**, and it survives anything
that happens next — a crash, a timeout, a power cut, a rate limit from the
embedding provider halfway through.

If the two commits were one — if the row were written in the same transaction
as the result — a crash would roll back both and the system would be exactly as
blind as before the database existed. The database would be decoration.

── What this deliberately does not fix ──────────────────────────────────────

A job whose process dies stays `processing` forever. Nothing retries it,
nothing reclaims it, nothing notices.

That is correct for now. Stage 1.2's measure is *interrupted ingests that are
detectable: 0% → 100%* — detectable, not recovered. The lease, the heartbeat
and the reaper that requeues abandoned work are stage 2.1, and they are only
buildable once there is a stuck row to observe. Leave it broken; make it
visible.
"""

import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AgentUnavailableError
from app.repositories.documents import DocumentRepository
from app.schemas.documents import DocumentRead
from app.services import agent_client

logger = logging.getLogger(__name__)

class AgentClient(Protocol):
    """What the ingestion service needs from the agent.

    A Protocol rather than the module itself, so the dependency is a *shape*
    and not an import. That is what lets a test supply a stub — and the stub is
    the right instrument, because "does the backend record a failure when the
    agent fails?" should not be answered by breaking a real agent.

    Structural, like the provider seams in `rag` and the agent: anything with a
    matching method satisfies it, with no inheritance and no registration.
    """

    async def ingest_document(
        self,
        *,
        document_id: str,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> tuple[int, dict]:
        ...


@dataclass(slots=True)
class IngestOutcome:
    """What happened, and what the HTTP layer should say about it.

    The status code travels with the response instead of being inferred from
    it, because the two answer different questions and only the route should
    decide the second.

    **Why a failed ingestion is not an HTTP 200.** The attempt is recorded
    either way — that is this stage's whole point — but the caller asked for a
    document to be indexed and it was not. Returning 200 with `status:
    "failed"` buried in the body means every client has to remember to look,
    and the one we have does not: the frontend shows an error only when the
    response is not ok. A rejected PDF would render as a success with no
    message at all.

    So the failure keeps the status code the agent gave it — 400 for "not a
    PDF", 422 for "nothing to index", 502 for a provider outage — and the body
    carries `detail` where every existing client already looks.

    At stage 1.3 this becomes `202 Accepted` plus a job id, and the outcome
    stops being known at response time at all.
    """

    http_status: int
    response: "DocumentRead"


UNKNOWN_ERROR = "unknown"
"""Stored when a failure arrives with no message.

`ck_ingestion_jobs_failed_requires_error` forbids a failed job with a null
error, so the code cannot quietly record nothing. Saying "unknown" is at least
honest, and stage 2.3 will want to know how often it happens when it starts
classifying failures as transient or permanent.
"""


class IngestionService:
    """Orchestrates one upload: record it, attempt it, record the outcome.

    Takes the session *and* the repository. The repository stages writes; the
    session owns transaction boundaries, and this class is the only place that
    decides where those boundaries fall. That split is why neither the
    dependency nor the repository commits on anyone's behalf — if they did, the
    ordering above would be a property of some other file.

    `agent` is injected so tests can supply a fake. That is not only for speed:
    testing "does the backend record a failure when the agent fails?" against a
    real agent would mean breaking a real agent on purpose, which is slow,
    unreliable, and tests the wrong system.
    """

    def __init__(
        self,
        session: AsyncSession,
        repository: DocumentRepository,
        agent: AgentClient = agent_client,
    ) -> None:
        self._session = session
        self._repository = repository
        self._agent = agent

    async def ingest(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> IngestOutcome:
        """Index one document, leaving a durable record either way."""

        # ── 1. Record the intent ──────────────────────────────────────────────
        document, job = await self._repository.create_document_with_job(
            filename=filename,
            byte_size=len(content),
            content_type=content_type,
        )

        # ── 2. Make it durable, before any work starts ───────────────────────
        #
        # Everything after this line can fail, hang or be killed. None of it can
        # erase the fact that this document was uploaded and an attempt began.
        await self._session.commit()

        document_id = document.id
        job_id = job.id
        logger.info(
            "ingestion started document_id=%s job_id=%s filename=%s bytes=%d",
            document_id,
            job_id,
            filename,
            len(content),
        )

        # ── 3. Do the work ───────────────────────────────────────────────────
        #
        # Synchronous and unbounded: a 300-page PDF holds this open for minutes
        # and may hit the agent timeout. That is stage 1.1's known defect and
        # the trigger for 1.3's `202 Accepted` and job polling. It is left in
        # place on purpose — but from now on, when it happens, there is a row
        # that says so.
        try:
            status_code, body = await self._agent.ingest_document(
                document_id=str(document_id),
                filename=filename,
                content=content,
                content_type=content_type,
            )
        except AgentUnavailableError as exc:
            # No response at all — the agent is down, or did not answer in
            # time. Still a failed attempt, and still worth recording.
            return await self._record_failure(
                document, job_id, str(exc), HTTPStatus.SERVICE_UNAVAILABLE
            )

        # ── 4. Record the outcome ────────────────────────────────────────────
        if status_code >= 400:
            detail = body.get("detail")
            message = detail if isinstance(detail, str) and detail else UNKNOWN_ERROR
            return await self._record_failure(
                document, job_id, message, status_code
            )

        return await self._record_success(document, job_id, body)

    async def _record_success(
        self, document: object, job_id: object, body: dict
    ) -> IngestOutcome:
        """Mark the attempt done and store its numbers.

        The counts are read from the agent's body with `.get(..., 0)` rather
        than indexed. A missing field here would be a contract mismatch between
        two services, and failing the whole upload over it — *after* the
        document has already been indexed in Qdrant — would turn a cosmetic
        problem into a lost document.
        """
        await self._repository.mark_job_done(
            job_id,
            page_count=int(body.get("page_count", 0)),
            pages_with_text=int(body.get("pages_with_text", 0)),
            characters_extracted=int(body.get("characters_extracted", 0)),
            chunk_count=int(body.get("chunk_count", 0)),
        )
        await self._session.commit()

        logger.info("ingestion done job_id=%s", job_id)
        return IngestOutcome(HTTPStatus.OK, await self._respond(document, job_id))

    async def _record_failure(
        self, document: object, job_id: object, error: str, http_status: int
    ) -> IngestOutcome:
        """Mark the attempt failed, with the reason the engine gave.

        `status` and `finished_at` move together in one UPDATE because
        `ck_ingestion_jobs_finished_at_matches_status` permits nothing else —
        the repository handles that, and the constraint is what guarantees a
        `processing` row genuinely means "still running".
        """
        await self._repository.mark_job_failed(job_id, error=error)
        await self._session.commit()

        logger.warning(
            "ingestion failed job_id=%s status=%s error=%s",
            job_id,
            http_status,
            error,
        )
        return IngestOutcome(http_status, await self._respond(document, job_id))

    async def _respond(self, document: object, job_id: object) -> DocumentRead:
        """Build the response from the database, not from what we just sent.

        One extra read, and it means the response cannot claim something the
        database does not hold. A write that silently failed to apply shows up
        here instead of being papered over by the values still in memory.
        """
        job = await self._repository.get_job(job_id)
        assert job is not None, "the job was committed moments ago"
        return DocumentRead.from_rows(document, job)
