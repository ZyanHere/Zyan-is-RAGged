"""Ingesting a document, durably — in two halves.

Stage 1.2 built this as one method: record the attempt, commit, do the work,
record the outcome. Stage 1.3 cuts it in two at the commit, and the cut is the
whole stage:

    accept_upload()     record the attempt, store the bytes, COMMIT, return
                        ← this is all a request does now

    process_job()       fetch the bytes, call the agent, record the outcome
                        ← this runs in a worker, some time later

── Why cutting there ───────────────────────────────────────────────────────────

Because that commit was already the boundary between "we know about this
document" and "we are working on it". Stage 1.2 put it in the right place for a
reason it could not yet collect on; 1.3 collects.

The 1.2 invariant is not weakened by the split, it is strengthened. The commit
still precedes any work — and now the work is not even in the same process, so
there is no way for a future edit to accidentally reorder them.

── Why the halves cannot be run back-to-back ───────────────────────────────────

They can, and that is exactly what the system did until this layer. What
changed is that `accept_upload` now writes a **`queued`** job with no
`started_at`, and `process_job` expects an already-claimed `processing` one.
The transition between them belongs to `claim_next_queued_job`, which is also
what makes it safe for two workers to run at once.

So the sequence is three steps, not two, and the middle one is the queue:

    accept_upload  →  COMMIT  ···  claim  →  COMMIT  ···  process_job  →  COMMIT

Each `···` is an arbitrary amount of time, possibly a process restart.

── What the later stages added to this sequence ────────────────────────────────

**Stage 2.1** made a claim provisional. A job whose worker dies used to stay
`processing` forever; now the claim carries a lease and a token, the worker
renews the lease while it works, and any worker reaps expired leases before
claiming. Every write that finishes a job carries the token, so a worker that
was reaped affects zero rows rather than overwriting whoever holds the job now.

**Stage 2.2** made re-processing safe, which is what 2.1's retries required:
point ids are derived from `(document_id, chunk_index)` and an ingestion prunes
everything else belonging to that document, so running a job once or five times
leaves the same index.

**Stage 2.3** made the retry policy two policies. A failure is classified from
the agent's status code — 4xx permanent, 5xx and no-response transient, with
429 carved out — so a document that can never be indexed stops at attempt one
while a document caught by an outage gets minutes. See `classify`.

**Stage 2.4** made all of it visible. Both processes configure the same
logging, so the `logger.info` calls below — the accept, the dedupe decision,
the retry request — reach a handler for the first time; before it, every one of
them was discarded in the API process while working fine in the worker. Each
also carries the `request_id` of the request that caused the work, put there by
a filter rather than by any call site here.

── What this still deliberately does not fix ───────────────────────────────────

**Nothing aggregates.** `GET /stats` answers "how is the pipeline doing?" when
someone asks, and there is no history, no rate and no alert when the answer
gets worse. A snapshot is a thing you have to think to look at.

That is stage 10.1's trigger, and the gap is deliberate: a rate is only worth
emitting once something stores and graphs it.

── `IngestOutcome` is gone ─────────────────────────────────────────────────────

Stage 1.2 introduced it so a failed ingestion could keep the agent's status
code — 400 for "not a PDF", 422 for "nothing to index" — instead of returning
HTTP 200 with the failure buried in the body, which the frontend would have
rendered as silent success.

The route no longer learns an outcome at all. It returns `202 Accepted` before
any work happens, so there is no status code to carry and nothing to decide.
The failure reaches the user through the document's `error` field, which the
client has displayed since 1.2 — so the problem that type solved has moved
rather than returned.
"""

import hashlib
import logging
import random
from http import HTTPStatus
from uuid import UUID
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    FailureKind,
    IngestionJob,
    IngestionStatus,
)
from app.core.logging import request_id_var
from app.errors import AgentUnavailableError, ConflictError, NotFoundError
from app.repositories.documents import ClaimedJob, DocumentRepository
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


UNKNOWN_ERROR = "unknown"
"""Stored when a failure arrives with no message.

`ck_ingestion_jobs_failed_requires_error` forbids a failed job with a null
error, so the code cannot quietly record nothing. Saying "unknown" is at least
honest, and stage 2.3 will want to know how often it happens when it starts
classifying failures as transient or permanent.
"""

MISSING_UPLOAD_ERROR = (
    "The stored upload for this document is missing, so there is nothing to "
    "ingest. The job cannot be retried without re-uploading the file."
)
"""Recorded when a claimed job's bytes are not there.

**This should be unreachable.** The document, its job and its upload are
written in one transaction, and the foreign key cascades, so a job without an
upload would mean someone deleted the bytes while leaving the job behind.

It is handled rather than asserted because the honest response to "the input
vanished" is a failed job with a readable reason — something an operator can
see in the list — not a stack trace in a log nobody is reading. A worker is not
a request; there is no caller to hand an exception to.
"""


def classify(status_code: int | None) -> FailureKind:
    """Could this failure have succeeded, given another try? Stage 2.3.

    ── The whole classification is a status code, and that is the finding ────

    The backend never imports `rag` — it learns what happened to a document
    from the agent's HTTP response and nothing else. That boundary turns out
    to already carry this distinction, because `agent/app/main.py` maps the
    engine's error hierarchy onto status codes:

        InvalidDocumentError  400   not a PDF, corrupt, encrypted
        UploadTooLargeError   413   too big, and will stay too big
        NoTextExtractedError  422   scanned; OCR is stage 16.2
        EmbeddingError        502   rate limit, timeout, dead key
        ProviderError         502
        VectorStoreError      500   our own storage
        AgentError            500
        (no response)          —    the agent is down or did not answer

    **4xx means the request can never succeed; 5xx means the system failed
    you.** That is the HTTP specification's own semantics, and permanent and
    transient map onto it without inventing anything.

    `rag/errors.py` says its hierarchy is where this distinction belongs when
    2.3 needs it. It turns out the backend does not need the hierarchy at all,
    only the mapping the agent already performs — which is better, because it
    keeps the backend ignorant of the engine, and that ignorance is what made
    the 1.3 worker split possible.

    ── The one carve-out, and why it is spelled out ─────────────────────────

    `429 Too Many Requests` is 4xx and **transient**. It is the exception that
    proves the rule is about *who can fix it* rather than about the number: a
    rate limit is the server asking you to wait, not telling you the request
    was wrong.

    Nothing emits a 429 today. A provider will, and the next person to read
    this should not have to rediscover it from an incident.

    ── Why `None` rather than a sentinel code ───────────────────────────────

    `None` means there was no response at all — `AgentUnavailableError`, which
    the backend raises itself. Mapping that onto 503 and passing a number
    would be inventing a response the agent never sent, and the caller already
    knows the difference because it catches the exception.
    """
    if status_code is None:
        return FailureKind.TRANSIENT
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return FailureKind.TRANSIENT
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return FailureKind.TRANSIENT
    return FailureKind.PERMANENT


class UploadOutcome(NamedTuple):
    """What an upload did, and what the HTTP layer should say about it.

    ── Why a second field and not just the document ────────────────────────────

    Before stage 2.2 an accepted upload always queued work, so `202 Accepted`
    was the only honest answer and the route needed nothing but the record.
    Deduplication adds an outcome where **nothing was written**: the bytes were
    already indexed. `202` means *recorded, not yet done*, which would be false
    for a document that is already done.

    `queued` is the one bit the route cannot work out for itself. It cannot be
    inferred from `document.status`, and the near-miss is worth naming: a
    `queued` status is the state of both a brand-new upload and a duplicate of
    something already waiting in the queue, so reading the status would answer
    `202` for both — correct for the first and a lie about the second.

    A `NamedTuple` rather than a dataclass, matching `ClaimedJob` and
    `ReapResult` in the repository: these are results being carried one level
    up, not entities with behaviour.

    **Not an enum of three cases.** `created`, `retried` and `duplicate` are
    genuinely three things, and the HTTP layer treats the first two
    identically — both are "work is now queued, look here later". Adding a
    distinction the only consumer collapses would be carrying a shape for a
    caller that does not exist. The three cases are distinguished in the logs,
    where they are actually read.
    """

    document: DocumentRead
    queued: bool
    """True when this request caused work to be enqueued.

    `False` means the response is a report on a document that was already
    here, and the route answers `200` instead of `202`.
    """


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times to try, and how long to wait between tries. Stage 2.1.

    **Passed in rather than read from `get_settings()`**, for the same reason
    the agent is injected: a test that wants to exercise exhaustion should not
    have to construct a whole `Settings` or monkeypatch a global. It is three
    numbers and a function over them.

    ── The failure this exists to fix ──────────────────────────────────────────

    Until now `_record_failure` set `status = 'failed'`, which no code path
    ever left. A three-second `docker compose restart agent` therefore
    destroyed every document being processed at that moment, permanently, and
    the only recovery was a human noticing and re-uploading.

    A failure is now provisional until the attempts run out.
    """

    max_attempts: int
    base_seconds: float
    max_delay_seconds: float = 60.0
    """The longest any single wait may be. Stage 2.3.

    Defaulted rather than required, so the many existing tests that construct
    a policy with two numbers keep working and keep meaning what they meant.
    Production passes it explicitly from `Settings`.
    """

    def delay_for(self, attempt: int) -> float:
        """How long to wait before attempt number `attempt + 1`.

        **Exponential backoff with full jitter.** Two separate ideas, and the
        second is the one people leave out:

            ceiling = base * 2 ** (attempt - 1)   → 2, 4, 8, 16, 32
            delay   = uniform(0, ceiling)         → somewhere in that window

        *Backoff* is because retrying a broken thing immediately does not help
        and costs it capacity it needs to recover.

        *Jitter* is because of what happens without it. Fifty workers that all
        failed against the same outage compute the same ceiling, wait the same
        number of seconds, and come back **in the same instant** — so the
        service that was recovering gets the entire backlog at once and falls
        over again. The retry storm is caused by the retry policy being
        correct and identical everywhere.

        Full jitter — uniform across the whole window rather than a small
        wobble around the ceiling — is the simplest form that actually spreads
        them, and it is what AWS's own guidance settled on after measuring the
        alternatives.

        The randomness means this is deliberately **not** deterministic, which
        is why the tests assert on bounds rather than on a value.

        ── The cap, added at stage 2.3 ────────────────────────────────────────

        Doubling has no natural end, and five attempts never reached a ceiling
        worth capping — the largest was 16 seconds. At eight the last would be
        128, and the budget's shape would be set by one long sleep rather than
        by several spread-out tries.

        **Capping is what makes more attempts buy coverage instead of
        latency.** Without it, raising `max_attempts` mostly means a document
        sits non-terminal for longer, which is the opposite of the intent.

        Capped exponential backoff with full jitter is the standard form; this
        code had the jitter and not the cap, which is the easier half to
        remember.
        """
        ceiling = min(
            self.base_seconds * 2 ** max(0, attempt - 1),
            self.max_delay_seconds,
        )
        return random.uniform(0, ceiling)


class IngestionService:
    """Accepts uploads, and processes claimed jobs.

    Takes the session *and* the repository. The repository stages writes; the
    session owns transaction boundaries, and this class is the only place that
    decides where those boundaries fall. That split is why neither the
    dependency nor the repository commits on anyone's behalf — if they did, the
    ordering this module exists to guarantee would be a property of some other
    file.

    **One class, two callers, and they use different halves.** The route calls
    `accept_upload` and never touches the agent; the worker calls `process_job`
    and never accepts anything. They are together because they share the
    session-and-repository wiring and because reading them side by side is how
    the cut between them stays obvious.

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

    # ── The request's half ────────────────────────────────────────────────────

    async def accept_upload(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> UploadOutcome:
        """Record that a document arrived, and that it needs indexing.

        Everything a request does. Bounded work whose duration depends on the
        size of the upload and nothing else: no agent call, no embedding, no
        vector store.

        ── Three outcomes, not one — stage 2.2 ────────────────────────────────

        Until now there was one: a new document, queued. The content hash makes
        two more possible, and the difference between them is a product
        decision rather than an implementation detail:

            these bytes are new                 create, queue, 202
            these bytes are here and the last
              attempt failed                    queue another attempt, 202
            these bytes are here and fine       return it; 202 would be a lie,
                                                so 200

        The caller reads `UploadOutcome.queued` to choose the status code.

        **Why the third case is a success and not a `409`.** The request is
        "make sure this document is indexed", and it is. A browser retrying a
        timed-out upload is the common cause, and `409 Conflict` would report a
        failure for an upload that actually worked — the exact outcome
        idempotency exists to prevent. Nothing is created, nothing is queued,
        and `200` rather than `202` is what says so.

        **Why the second case queues a job rather than returning the failure.**
        The bytes are identical, so it is the same document — but someone
        re-uploading a file that failed is asking for another attempt, not for
        the bad news again. One document, many jobs: that is what 1.2's
        two-table split was for, and this is its first real caller. Refuse the
        re-upload and a document whose retries were exhausted could never be
        re-driven from the UI at all.

        ── Why the hash is computed here and not passed in ────────────────────

        `content_hash` is `sha256(content)` and this method already has
        `content`, so taking the hash as a parameter would mean two arguments
        that can contradict each other. The repository makes the same argument
        about `byte_size`, which stopped being a parameter for exactly this
        reason: a caller passing a stale value would produce a document whose
        recorded size did not match its stored bytes, with nothing to catch it.

        A hash that does not match its bytes is worse than a wrong size. It
        does not look broken — it is still 64 valid hex characters — and the
        damage is silent: that document never deduplicates against another
        upload of the same file, and may dedupe against an unrelated one.

        Deriving it here makes that unrepresentable rather than merely unlikely.
        """
        content_hash = hashlib.sha256(content).hexdigest()

        # The fast path. Someone re-uploading deliberately is the ordinary
        # duplicate, and this makes it one SELECT with nothing written.
        existing = await self._repository.get_by_content_hash(content_hash)
        if existing is not None:
            return await self._resolve_duplicate(*existing, filename=filename)

        # ── The race the SELECT above cannot close ───────────────────────────
        #
        # Two requests carrying the same bytes can both read `None` before
        # either writes. Only `uq_documents_content_hash` can refuse the
        # second, so the INSERT is allowed to fail and the failure is handled
        # rather than prevented.
        #
        # **Why a savepoint.** In Postgres a failed statement aborts the whole
        # transaction: after the IntegrityError nothing further can run on this
        # session until something rolls back, and an outer rollback would
        # discard the lookup that has to come next. `begin_nested()` issues a
        # SAVEPOINT, so only the failed INSERT is undone and the session stays
        # usable.
        #
        # The alternative is `INSERT ... ON CONFLICT DO NOTHING`, which never
        # raises and so needs no savepoint. It would also mean writing the
        # three rows as Core inserts with explicit foreign keys, giving up the
        # relationship cascade that writes document, job and upload in a
        # single flush — a larger change, to avoid an exception on a rare path.
        try:
            async with self._session.begin_nested():
                document, job = await self._repository.create_document_with_job(
                    filename=filename,
                    content=content,
                    content_type=content_type,
                    content_hash=content_hash,
                    # Read here rather than taken as a parameter: the id
                    # belongs to the request, and the request is ambient. A
                    # parameter would put it in the signature of every method
                    # between the route and the row.
                    request_id=request_id_var.get(),
                )
        except IntegrityError:
            # Re-read rather than inspect the exception. If the hash is present
            # now, we lost the race and the winner's document is the answer; if
            # it is absent, this was a *different* constraint and the error is
            # not ours to swallow.
            #
            # Discriminating on the data rather than on a constraint name in an
            # error message means this keeps working if the constraint is
            # renamed, and it cannot mistake one violation for another.
            existing = await self._repository.get_by_content_hash(content_hash)
            if existing is None:
                raise

            logger.info(
                "upload lost the race for content_hash=%s; returning the "
                "document the winner created",
                content_hash[:12],
            )
            return await self._resolve_duplicate(*existing, filename=filename)

        # The invariant, inherited from 1.2 and now load-bearing for a second
        # reason: a worker in another process can only see committed rows, so
        # this commit is also what *publishes* the job to the queue.
        await self._session.commit()

        logger.info(
            "ingestion queued document_id=%s job_id=%s filename=%s bytes=%d",
            document.id,
            job.id,
            filename,
            len(content),
        )

        return UploadOutcome(DocumentRead.from_rows(document, job), queued=True)

    async def _resolve_duplicate(
        self,
        document: Document,
        job: IngestionJob | None,
        *,
        filename: str,
    ) -> UploadOutcome:
        """These bytes are already here. Decide whether to attempt them again.

        `filename` is taken only for the log line. The stored document keeps
        the name it was first uploaded under: the bytes are the identity, and
        renaming a document because someone re-uploaded it under a different
        name would rewrite a record on the strength of something this stage has
        just decided is not identifying.

        **A document with no job at all takes the retry branch**, not the no-op
        one. That state should be impossible — both rows are written in one
        transaction — but it is representable, and a re-upload is the one
        action that would fix it. The alternative is answering `200` for a
        document that nothing will ever index.

        **`processing` and `queued` are deliberately no-ops.** The document is
        mid-flight; queueing a second attempt would have two workers ingest the
        same bytes concurrently, which is the duplicate-chunk problem this
        stage exists to remove, arriving by a new route.
        """
        if job is not None and job.status is not IngestionStatus.FAILED:
            logger.info(
                "duplicate upload of filename=%s matched document_id=%s "
                "(status=%s); nothing queued",
                filename,
                document.id,
                job.status,
            )
            return UploadOutcome(
                DocumentRead.from_rows(document, job), queued=False
            )

        retry = await self._repository.create_job_for_document(
            document.id, request_id=request_id_var.get()
        )
        await self._session.commit()

        logger.info(
            "re-upload of filename=%s queued a new attempt for document_id=%s "
            "job_id=%s (previous attempt: %s)",
            filename,
            document.id,
            retry.id,
            job.status if job else "none",
        )
        return UploadOutcome(
            DocumentRead.from_rows(document, retry), queued=True
        )

    async def retry_document(self, document_id: UUID) -> DocumentRead:
        """Queue a fresh attempt at a document that is already here. Stage 2.3.

        The operator's half of the dead-letter queue. The list says what died;
        this is the only thing to *do* about it.

        ── It is `create_job_for_document`, and that is the point ─────────────

        Stage 2.2 built that method so a re-upload of a failed document would
        queue another attempt rather than create a second document. Replaying
        from the dead-letter list is the same operation reached a different
        way, so it is the same code: one document, many jobs.

        The difference is what the operator needs — the *file* is required for
        a re-upload and they usually do not have it. The bytes are already in
        `document_uploads`; only a row is missing.

        ── Why a permanent failure is still retryable ────────────────────────

        It reads wrong at first: the server decided this document can never
        succeed, and now it will try again on request.

        But what the server knows is that the file was not a PDF *when it last
        looked*. It does not know whether OCR has since been installed, the
        size limit raised, or the upload replaced. Refusing would be the
        server asserting the outside world has not changed, which is not
        something it can observe. Retrying a genuinely broken document costs
        one claim and one 4xx — `_classify` still stops it at attempt one.

        ── The one case that *is* refused ────────────────────────────────────

        A document whose latest job is `queued` or `processing`. That is
        knowable, and queueing beside it would hand the same bytes to two
        workers at once — the duplicate-chunk corruption stage 2.2 removed,
        arriving by a new route. `IngestionStatus.is_terminal` is the test,
        so the rule stays spelled one way.
        """
        found = await self._repository.get_document_with_latest_job(document_id)
        if found is None:
            raise NotFoundError(f"No document with id {document_id}.")

        document, job = found

        if job is not None and not job.status.is_terminal:
            raise ConflictError(
                f"Document {document_id} is already {job.status} — a second "
                f"attempt would index the same bytes twice. Wait for the "
                f"current one to finish."
            )

        retry = await self._repository.create_job_for_document(
            document.id, request_id=request_id_var.get()
        )
        await self._session.commit()

        logger.info(
            "retry requested for document_id=%s job_id=%s "
            "(previous attempt: %s, %s)",
            document.id,
            retry.id,
            job.status if job else "none",
            job.failure_kind if job and job.failure_kind else "n/a",
        )

        return DocumentRead.from_rows(document, retry)

    # ── The worker's half ─────────────────────────────────────────────────────

    async def process_job(
        self, claimed: ClaimedJob, retry: RetryPolicy
    ) -> None:
        """Run one already-claimed job to a terminal state.

        **Takes a `ClaimedJob`, not a job id**, and that is a contract rather
        than a convenience: the job must already be `processing` with a
        `started_at`, because `mark_job_done` on a `queued` row would violate
        `ck_ingestion_jobs_started_at_matches_status`. The type makes it
        impossible to call this on something nobody claimed.

        Returns nothing. There is no caller waiting for a result — the outcome's
        only destination is the database, and the client reads it by polling.
        Any exception that escapes here reaches the worker loop, which is where
        the decision about retrying lives (and at this stage, does not).
        """
        found = await self._repository.get_document_with_latest_job(
            claimed.document_id
        )
        if found is None:
            # The foreign key makes this impossible, so treat it as a failure
            # rather than crashing the worker on an invariant violation.
            #
            # **Permanent since stage 2.3.** Nothing in this system ever
            # re-creates a deleted upload row, so retrying is spending the
            # budget on an outcome that is already decided. `_record_failure`'s
            # docstring used to argue for retrying it anyway — *"carving out
            # exceptions one at a time is how a rule stops being a rule"* —
            # and that argument held exactly as long as there was no rule to
            # carve it out of.
            await self._record_failure(
                claimed, MISSING_UPLOAD_ERROR, FailureKind.PERMANENT, retry
            )
            return

        document, _ = found

        content = await self._repository.get_upload_content(claimed.document_id)
        if content is None:
            await self._record_failure(
                claimed, MISSING_UPLOAD_ERROR, FailureKind.PERMANENT, retry
            )
            return

        # Unbounded, and no longer a problem for anyone waiting. The agent
        # timeout still applies — it is the worker that now absorbs it, and
        # `AGENT_TIMEOUT` stops being a guess about a user's patience and
        # becomes a measured decision at stage 7.1.
        try:
            status_code, body = await self._agent.ingest_document(
                document_id=str(claimed.document_id),
                filename=document.filename,
                content=content,
                content_type=document.content_type,
            )
        except AgentUnavailableError as exc:
            # No response at all — the agent is down, or did not answer in
            # time. Transient by definition: nothing was judged about this
            # document, so nothing is known to be wrong with it.
            #
            # `None` rather than a stand-in status code, because inventing a
            # 503 the agent never sent would put a fiction in the one place
            # the classification reads from.
            await self._record_failure(
                claimed, str(exc), classify(None), retry
            )
            return

        if status_code >= 400:
            detail = body.get("detail")
            message = detail if isinstance(detail, str) and detail else UNKNOWN_ERROR
            await self._record_failure(
                claimed, message, classify(status_code), retry
            )
            return

        await self._record_success(claimed, body)

    async def _record_success(self, claimed: ClaimedJob, body: dict) -> None:
        """Mark the attempt done and store its numbers.

        The counts are read from the agent's body with `.get(..., 0)` rather
        than indexed. A missing field here would be a contract mismatch between
        two services, and failing the whole job over it — *after* the document
        has already been indexed in Qdrant — would turn a cosmetic problem into
        a lost document.
        """
        applied = await self._repository.mark_job_done(
            claimed.job_id,
            claimed.lease_token,
            page_count=int(body.get("page_count", 0)),
            pages_with_text=int(body.get("pages_with_text", 0)),
            characters_extracted=int(body.get("characters_extracted", 0)),
            chunk_count=int(body.get("chunk_count", 0)),
        )
        await self._session.commit()

        if not applied:
            # A reaper decided this worker was gone and the job was given to
            # someone else. Not an error — the system working. Logged at
            # warning because it also means the lease is too short for the real
            # workload, which is a tuning signal.
            logger.warning(
                "lost the lease before finishing job_id=%s; another worker owns "
                "it now and this result was discarded",
                claimed.job_id,
            )
            return

        logger.info("ingestion done job_id=%s", claimed.job_id)

    async def _record_failure(
        self,
        claimed: ClaimedJob,
        error: str,
        kind: FailureKind,
        retry: RetryPolicy,
    ) -> None:
        """Record this attempt's failure — and decide whether to try again.

        **The decision that stage 2.1 exists for.** Until now this method ended
        the job: `status = 'failed'`, which nothing ever left. An agent restart
        of a few seconds therefore destroyed every document in flight, and the
        only recovery was a human noticing and re-uploading the file.

        Now a failure is provisional. The job goes back on the queue with a
        delay, and only stops being retried when it has used its attempts.

        ── The classification decides, not just the count — stage 2.3 ─────────

        A **permanent** failure gives up on the first attempt. A **transient**
        one gets the full budget. Until this stage both got the same five
        attempts, and the measurements that ended that are worth keeping:

            a corrupt PDF      5 attempts over 14.6s — 4 of them could never
                               have succeeded
            a valid document   permanently failed after 22s of downtime, when
                               another minute would have indexed it

        The second is the expensive one, and it is the reason the budget grew
        rather than shrank. Retrying a broken file costs four pointless claims
        and no embedding — extraction fails before a provider is touched.
        *Not* retrying a good document costs the document.

        ── Where `kind` comes from ────────────────────────────────────────────

        `classify`, over the status code the agent returned, computed by the
        caller at the point of failure rather than here. This method decides
        what to *do* about a classification; deciding what the classification
        *is* belongs with the response that carries the evidence.

        ── The rule that was carved out, and why that was always the plan ────

        Stage 2.1's version of this docstring argued for retrying *everything*,
        including `MISSING_UPLOAD_ERROR`, which genuinely cannot succeed:
        *"carving out exceptions one at a time is how a rule stops being a
        rule"*. That held exactly as long as there was no rule to carve them
        out of. There is one now, so the exception is not an exception — it is
        `FailureKind.PERMANENT`, decided by the same function that decides
        every other case.

        ── Why the lease token is still required ──────────────────────────────

        Both branches go through a conditional write. A worker that has lost
        its lease must not be able to requeue a job someone else is running,
        any more than it may complete one — that would reset a healthy
        in-progress attempt back to `queued` and have it done twice.
        """
        # Permanent failures short-circuit the budget entirely. The attempt
        # count is not consulted, because no number of attempts changes what a
        # file is.
        give_up = (
            kind is FailureKind.PERMANENT
            or claimed.attempts >= retry.max_attempts
        )

        if give_up:
            # The suffix only earns its place when retries actually happened.
            # On a single-attempt failure "gave up after 1 attempts" is noise
            # *and* bad grammar, and it would make the message the user sees
            # differ from the engine's own words for no reason.
            retried = claimed.attempts > 1
            applied = await self._repository.mark_job_failed(
                claimed.job_id,
                claimed.lease_token,
                error=(
                    f"{error} (gave up after {claimed.attempts} attempts)"
                    if retried
                    else error
                ),
                failure_kind=kind,
            )
        else:
            delay = retry.delay_for(claimed.attempts)
            applied = await self._repository.requeue_job(
                claimed.job_id,
                claimed.lease_token,
                error=error,
                failure_kind=kind,
                delay_seconds=delay,
            )

        await self._session.commit()

        if not applied:
            logger.warning(
                "lost the lease before recording a failure for job_id=%s; "
                "another worker owns it now",
                claimed.job_id,
            )
            return

        if give_up:
            logger.warning(
                "ingestion failed permanently job_id=%s kind=%s attempts=%d "
                "error=%s",
                claimed.job_id,
                kind,
                claimed.attempts,
                error,
            )
        else:
            logger.warning(
                "ingestion failed job_id=%s kind=%s attempt=%d of %d; "
                "retrying in %.1fs error=%s",
                claimed.job_id,
                kind,
                claimed.attempts,
                retry.max_attempts,
                delay,
                error,
            )
