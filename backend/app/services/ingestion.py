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

── What this deliberately does not fix ─────────────────────────────────────────

A job whose worker dies stays `processing` forever. Nothing retries it, nothing
reclaims it, nothing notices — and now nobody is even waiting on a request to
find out, which makes it worse and more realistic.

That is correct for now. Stage 2.1's lease, heartbeat and reaper are only
buildable once there is a stuck row to observe. Leave it broken; make it
visible.

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

import logging
import random
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AgentUnavailableError
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
        """
        ceiling = self.base_seconds * 2 ** max(0, attempt - 1)
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
    ) -> DocumentRead:
        """Record that a document arrived, and that it needs indexing.

        Everything a request does. Two INSERTs, one blob, one COMMIT — bounded
        work whose duration depends on the size of the upload and nothing else.
        No agent call, no embedding, no vector store.

        Returns the document as it now stands: `status = "queued"`, every count
        `null`, because nothing has been attempted yet. The caller turns that
        into a `202`.
        """
        document, job = await self._repository.create_document_with_job(
            filename=filename,
            content=content,
            content_type=content_type,
        )

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

        return DocumentRead.from_rows(document, job)

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
            await self._record_failure(claimed, MISSING_UPLOAD_ERROR, retry)
            return

        document, _ = found

        content = await self._repository.get_upload_content(claimed.document_id)
        if content is None:
            await self._record_failure(claimed, MISSING_UPLOAD_ERROR, retry)
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
            # time. Still a failed attempt, and still worth recording.
            await self._record_failure(claimed, str(exc), retry)
            return

        if status_code >= 400:
            detail = body.get("detail")
            message = detail if isinstance(detail, str) and detail else UNKNOWN_ERROR
            await self._record_failure(claimed, message, retry)
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
        self, claimed: ClaimedJob, error: str, retry: RetryPolicy
    ) -> None:
        """Record this attempt's failure — and decide whether to try again.

        **The decision that stage 2.1 exists for.** Until now this method ended
        the job: `status = 'failed'`, which nothing ever left. An agent restart
        of a few seconds therefore destroyed every document in flight, and the
        only recovery was a human noticing and re-uploading the file.

        Now a failure is provisional. The job goes back on the queue with a
        delay, and only stops being retried when it has used its attempts.

        ── Everything retries, including things that obviously will not work ───

        There is no classification here: a corrupt PDF is retried exactly as a
        network blip is, which is deliberate and slightly uncomfortable.

        Classifying failures as transient or permanent is **stage 2.3's whole
        subject**, and its stated trigger is observing the waste — "a malformed
        PDF retries every 30s for a day". Pre-empting that here would mean
        arriving at 2.3 with the lesson half-learned and no evidence behind it.

        The waste is bounded and cheap in the meantime: a rejected PDF fails
        during extraction, before any embedding is paid for, so the cost of
        retrying one is five claims and a minute of backoff.

        The same uniformity applies to `MISSING_UPLOAD_ERROR`, which genuinely
        *cannot* succeed on a retry — nothing ever re-creates a deleted upload
        row. It is still retried, because carving out exceptions one at a time
        is how a rule stops being a rule, and because the case is supposed to
        be unreachable anyway.

        ── Why the lease token is still required ──────────────────────────────

        Both branches go through a conditional write. A worker that has lost
        its lease must not be able to requeue a job someone else is running,
        any more than it may complete one — that would reset a healthy
        in-progress attempt back to `queued` and have it done twice.
        """
        give_up = claimed.attempts >= retry.max_attempts

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
            )
        else:
            delay = retry.delay_for(claimed.attempts)
            applied = await self._repository.requeue_job(
                claimed.job_id,
                claimed.lease_token,
                error=error,
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
                "ingestion failed permanently job_id=%s attempts=%d error=%s",
                claimed.job_id,
                claimed.attempts,
                error,
            )
        else:
            logger.warning(
                "ingestion failed job_id=%s attempt=%d of %d; retrying in "
                "%.1fs error=%s",
                claimed.job_id,
                claimed.attempts,
                retry.max_attempts,
                delay,
                error,
            )
