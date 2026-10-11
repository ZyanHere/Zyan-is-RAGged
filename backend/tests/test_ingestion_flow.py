"""The ordering invariant, tested.

Stage 1.2's measure is **interrupted ingests that are detectable: 0% → 100%**,
and these tests are where that number comes from. The question each one asks is
not "did the upload work" but "**what survives if it does not**".

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


async def ingest(svc: IngestionService, filename: str = "zephyr-test.pdf"):
    """The response body. Use `ingest_outcome` when the status code matters."""
    outcome = await ingest_outcome(svc, filename)
    return outcome.response


async def ingest_outcome(svc: IngestionService, filename: str = "zephyr-test.pdf"):
    return await svc.ingest(
        filename=filename, content=PDF, content_type="application/pdf"
    )


# ── Success ──────────────────────────────────────────────────────────────────


async def test_a_successful_ingest_is_recorded_as_done(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    agent = FakeAgent()
    response = await ingest(service(session, repo, agent))

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
    response = await ingest(service(session, repo, agent))

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

    response = await ingest(service(session, repo, agent), filename="notes.txt")

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
    response = await ingest(service(session, repo, agent))

    assert response.status is IngestionStatus.FAILED
    assert response.error == "unknown"


async def test_an_unreachable_agent_is_recorded_as_a_failed_attempt(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """No response at all is still an attempt, and still worth a row.

    Before this stage, an agent that was simply not running meant an upload
    that left no trace whatsoever.
    """
    response = await ingest(service(session, repo, UnreachableAgent()))

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
    svc = service(session, repo, CrashingAgent())

    with pytest.raises(KeyboardInterrupt):
        await ingest(svc)

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
        await ingest(service(session, repo, CrashingAgent()), filename="stuck.pdf")

    await ingest(service(session, repo, FakeAgent()), filename="fine.pdf")

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


async def test_the_row_is_durable_before_the_agent_is_called(
    test_database_url: str,
) -> None:
    """The invariant, proved from outside the transaction.

    Every other test in this file shares the service's session, so it would see
    the row whether or not it had been committed — an uncommitted INSERT is
    perfectly visible to the transaction that made it. Asserting durability
    from inside is asserting nothing.

    So this test runs the service on its own connection and has the fake agent,
    **at the moment it is called**, open a *second* connection and look for the
    row. A second connection can only see committed data.

    If someone later moves the commit to after the agent call, every other test
    here still passes and this one fails.

    It opts out of the shared-transaction fixtures and cleans up after itself,
    which is the price of being the one test that needs real commits.
    """
    engine = create_async_engine(test_database_url)
    probe_engine = create_async_engine(test_database_url)
    seen: dict[str, int] = {}

    class ProbingAgent:
        async def ingest_document(self, *, document_id: str, **kwargs):
            async with probe_engine.connect() as other:
                count = (
                    await other.execute(
                        text("SELECT count(*) FROM documents WHERE id = :id"),
                        {"id": uuid.UUID(document_id)},
                    )
                ).scalar_one()
                seen["rows"] = count
            return 200, {
                "page_count": 1,
                "pages_with_text": 1,
                "characters_extracted": 10,
                "chunk_count": 1,
            }

    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    document_id = None
    try:
        async with factory() as s:
            svc = IngestionService(s, DocumentRepository(s), ProbingAgent())
            outcome = await svc.ingest(
                filename="durable.pdf", content=PDF, content_type="application/pdf"
            )
            document_id = outcome.response.document_id

        assert seen.get("rows") == 1, (
            "a separate connection could not see the document when the agent "
            "was called — the commit is not happening before the work starts"
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


# ── HTTP status codes ────────────────────────────────────────────────────────


async def test_a_rejected_document_keeps_the_agent_status_code(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """A failed ingestion is not an HTTP 200.

    The attempt is recorded either way — that is the stage's point — but the
    caller asked for a document to be indexed and it was not. Returning 200
    with `status: "failed"` in the body means every client has to remember to
    look, and the frontend does not: it shows an error only when the response
    is not ok. A rejected PDF would render as a silent success.
    """
    agent = FakeAgent(status_code=400, body={"detail": "not a PDF"})
    outcome = await ingest_outcome(service(session, repo, agent))

    assert outcome.http_status == 400
    assert outcome.response.status is IngestionStatus.FAILED


async def test_an_unreachable_agent_is_a_503(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    """503, not 500: nothing is wrong with *this* service.

    The distinction is what lets an error rate later answer "whose fault was
    the outage?" without reading logs.
    """
    outcome = await ingest_outcome(service(session, repo, UnreachableAgent()))
    assert outcome.http_status == 503


async def test_success_is_a_200(
    session: AsyncSession, repo: DocumentRepository
) -> None:
    outcome = await ingest_outcome(service(session, repo, FakeAgent()))
    assert outcome.http_status == 200


async def test_the_route_records_an_upload_when_the_agent_is_down(
    app, client, session: AsyncSession, repo: DocumentRepository
) -> None:
    """The whole path, over HTTP, through the real app.

    Everything else in this file calls the service directly. This one goes
    through routing, dependency injection, multipart parsing, the response
    model and the exception handlers — the wiring service-level tests cannot
    see.

    **The agent is overridden rather than simply absent.** The first version of
    this test relied on no agent happening to be running, which passed on a
    laptop with nothing started and failed the instant `docker compose up`
    started one. A test whose result depends on what else is running is not a
    test — so the failure is injected here, deterministically, and the test
    gives the same answer either way.
    """
    from app.api.deps import get_agent_client

    app.dependency_overrides[get_agent_client] = lambda: UnreachableAgent()

    response = await client.post(
        "/documents",
        files={"file": ("zephyr-test.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "failed"
    assert "Could not reach the agent" in body["detail"]

    document_id = body["document_id"]
    found = await repo.get_document_with_latest_job(uuid.UUID(document_id))
    assert found is not None, "the upload must be recorded even when the agent is down"
    document, job = found
    assert document.filename == "zephyr-test.pdf"
    assert job is not None
    assert job.status is IngestionStatus.FAILED


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
