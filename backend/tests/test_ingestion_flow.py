"""The ordering invariant, tested — now across three transactions.

Stage 1.2's measure is **interrupted ingests that are detectable: 0% → 100%**,
and these tests are where that number comes from. The question each one asks is
not "did the upload work" but "**what survives if it does not**".

Stage 1.3 split the work, so the sequence under test is now:

    accept_upload  →  COMMIT      what a request does
    claim          →  COMMIT      what a worker does to take ownership
    process_job    →  COMMIT      what a worker does with it

The `ingest` helper below runs all three with their commits, because that is
the only faithful way to test the parts. A test that skipped the claim would be
testing a sequence the system never performs — and would fail anyway, since
completing a `queued` job violates a constraint.

── The fake agent ───────────────────────────────────────────────────────────

Every test here substitutes the agent with a stub. That is not only for speed.
Testing "does the backend record a failure when the agent fails?" against a
real agent means breaking a real agent on purpose — slow, unreliable, and it
exercises the wrong system. The backend's job is to record whatever the agent
says, so a stub that says it is exactly the right instrument.

It also means this suite needs no agent process, no API keys and no network.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models import IngestionStatus
from app.errors import AgentUnavailableError
from app.repositories.documents import DocumentRepository
from app.schemas.documents import DocumentRead
from app.services.ingestion import IngestionService

PDF = b"%PDF-1.4 pretend this is a real document"


class FakeAgent:
    """Stands in for `app.services.agent_client`.

    Records what it was called with, so a test can assert that the backend's
    own document id was the one sent downstream.
    """

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
    """An agent that never answers at all."""

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        raise AgentUnavailableError(
            "Could not reach the agent at http://localhost:8001. "
            "Is it running on port 8001?"
        )


class CrashingAgent:
    """An agent call that dies in a way nothing catches.

    Simulates the process being killed mid-ingest: a `BaseException` that the
    service does not handle and must not handle, because a real `kill -9`
    offers no opportunity to handle anything.
    """

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        raise KeyboardInterrupt("simulated process interruption")


@pytest.fixture
def repo(session: AsyncSession) -> DocumentRepository:
    return DocumentRepository(session)


def service(session, repo, agent) -> IngestionService:
    return IngestionService(session, repo, agent)


async def accept(svc: IngestionService, filename: str = "zephyr-test.pdf"):
    """Only the request's half: record it, store the bytes, commit."""
    return await svc.accept_upload(
        filename=filename, content=PDF, content_type="application/pdf"
    )


async def ingest(
    session: AsyncSession,
    repo: DocumentRepository,
    agent,
    filename: str = "zephyr-test.pdf",
):
    """Accept, claim, process — and commit between each, as the system does.

    **The claim is not optional scaffolding.** `process_job` requires a job
    that is already `processing` with a `started_at`, because completing a
    `queued` row would violate
    `ck_ingestion_jobs_started_at_matches_status`. Skipping it would be testing
    a sequence that cannot happen.

    Returns the document as the database holds it afterwards — re-read, not
    assembled from what was sent, so a write that silently failed to apply
    shows up here rather than being papered over.
    """
    svc = IngestionService(session, repo, agent)

    accepted = await accept(svc, filename)

    claimed = await repo.claim_next_queued_job()
    assert claimed is not None, "the job just accepted should be claimable"
    assert claimed.job_id is not None
    # The worker commits the claim before starting work, so that a crash
    # leaves a `processing` row rather than rolling the claim back.
    await session.commit()

    await svc.process_job(claimed)

    found = await repo.get_document_with_latest_job(accepted.document_id)
    assert found is not None
    document, job = found
    return DocumentRead.from_rows(document, job)


# ── Success ──────────────────────────────────────────────────────────────────


async def test_a_successful_ingest_is_recorded_as_done(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    agent = FakeAgent()
    response = await ingest(session, repo, agent)

    assert response.status is IngestionStatus.DONE
    assert response.chunk_count == 3
    assert response.pages_with_text == 3
    assert response.error is None
    assert response.finished_at is not None

    found = await repo.get_document_with_latest_job(response.document_id)
    assert found is not None
    document, job = found
    assert document.filename == "zephyr-test.pdf"
    assert document.byte_size == len(PDF)
    assert job is not None
    assert job.status is IngestionStatus.DONE


async def test_the_backend_sends_its_own_document_id_downstream(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """The id flows *down*, and that direction is the point.

    The backend commits a row, then tells the agent which document this is. The
    agent passes it to `rag.ingest` and into the Qdrant payload, so the vectors
    and the database row agree on an identifier that existed before either of
    them did.

    If the agent minted the id instead, the backend would have had nothing to
    commit before starting work — and the ordering this stage exists to
    establish would be impossible.
    """
    agent = FakeAgent()
    response = await ingest(session, repo, agent)

    assert len(agent.calls) == 1
    assert agent.calls[0]["document_id"] == str(response.document_id)


# ── Failure ──────────────────────────────────────────────────────────────────


async def test_an_agent_error_is_recorded_with_its_message(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """The engine's own words survive the request.

    "is not a PDF. It starts with b'just som'" was written in
    `rag/extraction.py` and travelled engine → agent → backend → this row. That
    chain is the whole of stage 1.1's fail-loudly design; stage 1.2 is where it
    stops being a response body nobody kept.
    """
    detail = "'notes.txt' is not a PDF. It starts with b'just som'."
    agent = FakeAgent(status_code=400, body={"detail": detail})

    response = await ingest(session, repo, agent, filename="notes.txt")

    assert response.status is IngestionStatus.FAILED
    assert response.error == detail
    assert response.finished_at is not None
    assert response.chunk_count is None

    found = await repo.get_document_with_latest_job(response.document_id)
    assert found is not None
    _, job = found
    assert job is not None
    assert job.status is IngestionStatus.FAILED
    assert job.error == detail


async def test_a_failure_with_no_detail_still_records_something(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """`ck_ingestion_jobs_failed_requires_error` forbids a silent failure.

    The code cannot store nothing, so it stores "unknown" — which is at least
    honest, and which stage 2.3 will want to count when it starts separating
    transient failures from permanent ones.
    """
    agent = FakeAgent(status_code=502, body={})
    response = await ingest(session, repo, agent)

    assert response.status is IngestionStatus.FAILED
    assert response.error == "unknown"


async def test_an_unreachable_agent_is_recorded_as_a_failed_attempt(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """No response at all is still an attempt, and still worth a row.

    Before this stage, an agent that was simply not running meant an upload
    that left no trace whatsoever.
    """
    response = await ingest(session, repo, UnreachableAgent())

    assert response.status is IngestionStatus.FAILED
    assert "Could not reach the agent" in (response.error or "")
    assert response.finished_at is not None


# ── Interruption — the measure ───────────────────────────────────────────────


async def test_an_interrupted_ingest_leaves_a_visible_row(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """**This is stage 1.2's 0% → 100%.**

    The agent call dies with `KeyboardInterrupt` — a `BaseException`, which the
    service does not catch and must not catch, because a real `kill -9` gives
    no opportunity to catch anything.

    Before this layer, that left chunks in Qdrant and nothing else: "partially
    indexed" and "never uploaded" were indistinguishable. Now the row is still
    there, and because `ck_ingestion_jobs_finished_at_matches_status` guarantees
    `processing` means `finished_at IS NULL`, the state means exactly one thing
    — **started, never finished**.

    Note what this does *not* do: nothing retries it, nothing reclaims it, and
    it will sit in `processing` forever. That is correct for now. The measure is
    *detectable*, not *recovered* — leases and a reaper are stage 2.1, and they
    are only buildable once there is a stuck row to look at.
    """
    with pytest.raises(KeyboardInterrupt):
        await ingest(session, repo, CrashingAgent())

    # The session is still usable: the crash happened after the commit, so
    # there is no failed transaction to clean up.
    rows = await repo.list_documents_with_latest_job()
    assert len(rows) == 1

    document, job = rows[0]
    assert document.filename == "zephyr-test.pdf"
    assert job is not None
    assert job.status is IngestionStatus.PROCESSING
    assert job.finished_at is None, "an unfinished job must have no finish time"
    assert job.error is None


async def test_stuck_jobs_can_be_found_by_query(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """The query an operator would actually run.

    "Which ingestions started and never finished?" is answerable now. It is
    also the query stage 2.1's reaper is built on — which is why making the
    state visible has to come first.
    """
    with pytest.raises(KeyboardInterrupt):
        await ingest(session, repo, CrashingAgent(), filename="stuck.pdf")

    await ingest(session, repo, FakeAgent(), filename="fine.pdf")

    stuck = (
        await session.execute(
            text(
                "SELECT d.filename FROM ingestion_jobs j "
                "JOIN documents d ON d.id = j.document_id "
                "WHERE j.status = 'processing' AND j.finished_at IS NULL"
            )
        )
    ).scalars().all()

    assert list(stuck) == ["stuck.pdf"]


# ── The commit really is before the call ─────────────────────────────────────


async def test_another_connection_can_see_the_job_the_instant_it_is_accepted(
    test_database_url: str,
) -> None:
    """**The invariant, and now also the proof that a queue is possible.**

    Every other test in this file shares one session, so it would see the row
    whether or not it had been committed — an uncommitted INSERT is perfectly
    visible to the transaction that made it. Asserting durability from inside
    is asserting nothing.

    So this test accepts an upload on its own connection and then looks for the
    job from a *second* connection, which can only see committed data.

    ── Why this replaced the stage-1.2 version ────────────────────────────────

    That version had the fake agent probe for the row at the moment it was
    called, proving the commit came first. After the split the agent is called
    by `process_job`, two commits later, so the probe would pass trivially and
    would no longer be testing the ordering at all.

    What matters now is stronger and simpler: **the moment `accept_upload`
    returns, another process can see the job.** That is not a detail of this
    service, it is the entire premise of handing work to a worker. If the
    commit moved after the response, the worker would be polling for rows that
    do not exist yet and the queue would silently lose uploads.
    """
    engine = create_async_engine(test_database_url)
    probe_engine = create_async_engine(test_database_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    document_id = None
    try:
        async with factory() as s:
            svc = IngestionService(s, DocumentRepository(s), FakeAgent())
            accepted = await accept(svc, "durable.pdf")
            document_id = accepted.document_id

            # Still inside the service's session, and deliberately *before*
            # anything else happens. A separate connection, no shared
            # transaction.
            async with probe_engine.connect() as other:
                row = (
                    await other.execute(
                        text(
                            "SELECT j.status, j.started_at IS NULL AS not_started, "
                            "       length(u.content) AS stored_bytes "
                            "  FROM ingestion_jobs j "
                            "  JOIN document_uploads u ON u.document_id = j.document_id "
                            " WHERE j.document_id = :id"
                        ),
                        {"id": document_id},
                    )
                ).one_or_none()

        assert row is not None, (
            "a separate connection could not see the job after accept_upload "
            "returned — the commit is not happening before the response, and a "
            "worker would never find this upload"
        )
        assert row.status == "queued"
        assert row.not_started is True, "a queued job has not started"
        assert row.stored_bytes == len(PDF), (
            "the bytes must be committed with the job, or the worker has "
            "nothing to ingest"
        )
    finally:
        if document_id is not None:
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    text("DELETE FROM documents WHERE id = :id"),
                    {"id": document_id},
                )
        await engine.dispose()
        await probe_engine.dispose()


# ── What the route says, and what it no longer knows ─────────────────────────
#
# Stage 1.2 had three tests here asserting that the service reported the
# agent's status code — 400 for a rejected PDF, 503 for an unreachable agent,
# 200 for success — so that the frontend could not render a failure as a silent
# success.
#
# **All three are gone, and nothing was lost.** The route cannot know any of
# those things any more: it answers before the work happens. The outcomes they
# protected are asserted directly against the recorded job by
# `test_an_agent_error_is_recorded_with_its_message` and
# `test_an_unreachable_agent_is_recorded_as_a_failed_attempt`, which is a
# better place for them — they are facts about the record, not about a
# response.
#
# What the route says instead is below.


async def test_the_route_returns_202_with_a_location_header(
    app, client, repo: DocumentRepository
) -> None:
    """`202 Accepted`, a queued record, and where to look for the outcome.

    202 is the whole contract of this stage. 200 would claim the document is
    indexed; 202 says the request was valid, has been recorded, and has not
    happened yet — and `Location` says where the answer will appear, so the
    client does not have to reconstruct the URL from an id.
    """
    response = await client.post(
        "/documents",
        files={"file": ("zephyr-test.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["finished_at"] is None
    assert body["chunk_count"] is None, "nothing has been attempted yet"
    assert response.headers["location"] == f"/documents/{body['document_id']}"

    found = await repo.get_document_with_latest_job(uuid.UUID(body["document_id"]))
    assert found is not None
    _document, job = found
    assert job is not None
    assert job.status is IngestionStatus.QUEUED
    assert job.started_at is None


async def test_the_route_accepts_an_upload_while_the_agent_is_down(
    app, client, repo: DocumentRepository
) -> None:
    """**A capability this stage creates**, not merely a behaviour it preserves.

    At stage 1.2 this test asserted a 503: the route called the agent inline,
    so an agent outage was an upload failure. The upload was *recorded*, which
    was the point of that stage, but the user still got an error and had to
    try again later.

    Now the route never touches the agent, so an outage is invisible at upload
    time. The document is accepted, queued, and sits there until a worker and
    a healthy agent exist — which is what a queue is for.

    The agent override is left in place deliberately even though nothing
    should call it. If the route ever starts talking to the agent again, this
    test fails, and it fails deterministically rather than depending on
    whether something happens to be running on port 8001 — a mistake the
    stage-1.2 version of this test actually made.
    """
    from app.api.deps import get_agent_client

    app.dependency_overrides[get_agent_client] = lambda: UnreachableAgent()

    response = await client.post(
        "/documents",
        files={"file": ("zephyr-test.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 202, (
        "an upload must not fail because the agent is unavailable"
    )
    body = response.json()
    assert body["status"] == "queued"
    assert body["error"] is None, "nothing has failed; nothing has been tried"

    found = await repo.get_document_with_latest_job(uuid.UUID(body["document_id"]))
    assert found is not None
    document, job = found
    assert document.filename == "zephyr-test.pdf"
    assert job is not None
    assert job.status is IngestionStatus.QUEUED


async def test_the_route_rejects_an_empty_upload_without_recording_it(
    app, client, repo: DocumentRepository
) -> None:
    """Rejected before anything is written.

    An empty file never reaches the service, so no document row is created. The
    record exists for attempts that *started*, not for requests that were
    refused at the door.

    The agent is overridden with one that raises if called — proving the
    rejection happens before the agent is involved at all, rather than
    happening to work because the agent rejected it too.
    """
    from app.api.deps import get_agent_client

    app.dependency_overrides[get_agent_client] = lambda: UnreachableAgent()

    response = await client.post(
        "/documents", files={"file": ("empty.pdf", b"", "application/pdf")}
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]
    assert await repo.list_documents_with_latest_job() == []
