"""`GET /documents` and `GET /documents/{id}`.

These are the endpoints that make stage 1.2's record *readable*. Writing a row
nobody can query would be bookkeeping; being able to ask "what happened to that
upload?" is what turns it into durability.

Driven over HTTP rather than against the repository, because the repository is
already covered in `test_repositories.py`. What is untested until now is the
wiring — routing, validation, the response model, the 404 — and that only
exists at the HTTP layer.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, IngestionStatus
from app.repositories.documents import DocumentRepository
from app.services.ingestion import IngestionService, RetryPolicy

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


# These tests are about the flow, not about expiry. A long lease keeps
# the reaper out of them; its own tests use a deliberately short one.
LEASE = 60.0

# Incidental when the seeded job succeeds. Where a test wants a *terminal*
# failure to display, it passes `NO_RETRY` — otherwise stage 2.1 requeues the
# job and the row is `queued`, not `failed`, which is correct and not what
# those tests are about.
RETRY = RetryPolicy(max_attempts=5, base_seconds=0.0)
NO_RETRY = RetryPolicy(max_attempts=1, base_seconds=0.0)


class FakeAgent:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self.body = body if body is not None else {
            "page_count": 3,
            "pages_with_text": 3,
            "characters_extracted": 1269,
            "chunk_count": 3,
        }

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        return self.status_code, self.body


@pytest.fixture
def repo(session: AsyncSession) -> DocumentRepository:
    return DocumentRepository(session)


async def seed(
    session,
    repo,
    filename: str,
    agent: FakeAgent | None = None,
    retry: RetryPolicy = RETRY,
):
    """Put one document through the real ingestion path, end to end.

    Three steps now, with their commits: accept, claim, process. The claim is
    required rather than decorative — `process_job` expects a job that is
    already `processing`, and completing a `queued` one violates
    `ck_ingestion_jobs_started_at_matches_status`.

    Use `seed_queued` for a document that has been accepted and not yet picked
    up, which is the state these endpoints must now also be able to report.
    """
    service = IngestionService(session, repo, agent or FakeAgent())
    accepted = (
        await service.accept_upload(
            filename=filename,
            content=_unique(PDF),
            content_type="application/pdf",
        )
    ).document

    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None and claimed.document_id == accepted.document_id
    await session.commit()

    await service.process_job(claimed, retry)
    return accepted


async def seed_queued(session, repo, filename: str):
    """A document accepted but not yet claimed — the new intermediate state.

    This is what every upload looks like for however long the queue is deep,
    so an endpoint that cannot describe it is an endpoint that lies during
    normal operation.
    """
    service = IngestionService(session, repo, FakeAgent())
    return (
        await service.accept_upload(
            filename=filename,
            content=_unique(PDF),
            content_type="application/pdf",
        )
    ).document


# ── The list ─────────────────────────────────────────────────────────────────


async def test_an_empty_list_is_an_envelope_not_null(client) -> None:
    """`{"items": []}`, never `null` and never a bare `[]`.

    The envelope is what lets `total` or `next_cursor` be added later without
    breaking a client that already iterates the response. Wrapping a bare array
    after the fact is not backward compatible; adding a key to an object is.
    """
    response = await client.get("/documents")

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_the_list_shows_each_document_with_its_outcome(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    await seed(session, repo, "good.pdf")
    await seed(
        session,
        repo,
        "bad.txt",
        FakeAgent(status_code=400, body={"detail": "not a PDF"}),
        # Terminal, so the list has a `failed` row to show. With retries on
        # this would be `queued` — see the next test.
        retry=NO_RETRY,
    )

    body = (await client.get("/documents")).json()
    by_name = {item["filename"]: item for item in body["items"]}

    assert by_name["good.pdf"]["status"] == "done"
    assert by_name["good.pdf"]["chunk_count"] == 3
    assert by_name["good.pdf"]["error"] is None

    assert by_name["bad.txt"]["status"] == "failed"
    assert by_name["bad.txt"]["error"] == "not a PDF"
    assert by_name["bad.txt"]["chunk_count"] is None


async def test_the_list_is_newest_first(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    """Ordering is `created_at DESC, id DESC`.

    The tiebreaker is not decoration. Postgres's `now()` is
    `transaction_timestamp()`, so documents created in one transaction share an
    identical `created_at` — and these tests run entirely inside one. Without a
    unique second key the order would be whatever the planner felt like, and
    this assertion would be a coin toss.

    `id` works because it is a UUIDv7: unique, and time-ordered, so it breaks
    ties in creation order rather than arbitrarily.
    """
    await seed(session, repo, "first.pdf")
    await seed(session, repo, "second.pdf")
    await seed(session, repo, "third.pdf")

    body = (await client.get("/documents")).json()
    assert [item["filename"] for item in body["items"]] == [
        "third.pdf",
        "second.pdf",
        "first.pdf",
    ]


async def test_limit_caps_the_response(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    for n in range(3):
        await seed(session, repo, f"doc-{n}.pdf")

    body = (await client.get("/documents?limit=2")).json()
    assert len(body["items"]) == 2


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_an_out_of_range_limit_is_rejected(client, limit: int) -> None:
    """Bounded server-side, not trusted from the client.

    An unbounded client-supplied limit is a request to build an arbitrarily
    large response in memory — a denial of service with a polite query string.
    422 rather than silently clamping, so a client asking for 10,000 learns
    that it cannot rather than quietly receiving 200.
    """
    assert (await client.get(f"/documents?limit={limit}")).status_code == 422


# ── One document ─────────────────────────────────────────────────────────────


async def test_fetching_one_document(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    created = await seed(session, repo, "zephyr-test.pdf")

    body = (await client.get(f"/documents/{created.document_id}")).json()

    assert body["document_id"] == str(created.document_id)
    assert body["filename"] == "zephyr-test.pdf"
    assert body["status"] == "done"
    assert body["pages_with_text"] == 3
    assert body["finished_at"] is not None


async def test_an_unknown_id_is_a_404(client) -> None:
    response = await client.get(f"/documents/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "No document with id" in response.json()["detail"]


async def test_a_malformed_id_is_a_422_not_a_404(client) -> None:
    """Different answers to different questions.

    "That is not a UUID" and "I have no such document" are distinct problems,
    and typing the path parameter as `UUID` means validation rejects the first
    before any query runs. Collapsing both into 404 would make a client-side
    bug look like missing data.
    """
    assert (await client.get("/documents/not-a-uuid")).status_code == 422


# ── What the record is for ───────────────────────────────────────────────────


async def test_an_interrupted_ingest_is_visible_through_the_api(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    """**Stage 1.2's whole point, read back over HTTP.**

    The agent call dies with a `BaseException` the service does not catch —
    standing in for the process being killed. Before this stage that left
    chunks in Qdrant and nothing else, so "partially indexed" and "never
    uploaded" were indistinguishable.

    Now the upload is a row, and the row is reachable: `status: processing`
    with `finished_at: null`, which
    `ck_ingestion_jobs_finished_at_matches_status` guarantees can only mean
    *started, never finished*.

    Nothing retries it. That is correct — the measure is **detectable**, not
    recovered. Leases and a reaper are stage 2.1, and they are only buildable
    once there is a stuck row to find.
    """

    class CrashingAgent:
        async def ingest_document(self, **kwargs):
            raise KeyboardInterrupt("simulated process interruption")

    with pytest.raises(KeyboardInterrupt):
        await seed(session, repo, "interrupted.pdf", CrashingAgent())

    body = (await client.get("/documents")).json()
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["filename"] == "interrupted.pdf"
    assert item["status"] == IngestionStatus.PROCESSING.value
    assert item["finished_at"] is None
    assert item["error"] is None


# ── The queued state, over HTTP (stage 1.3) ──────────────────────────────────


async def test_a_queued_document_is_reported_as_queued(
    client, session, repo: DocumentRepository
) -> None:
    """**The state the client polls on.**

    Between the `202` and a worker picking the job up, this is what every
    upload looks like — and for however long the queue is deep, it is what the
    user is staring at. An endpoint that could not describe it would be lying
    during normal operation.

    Every result field is `null`, and that is the honest answer rather than a
    gap: nothing has been attempted, so there is nothing to report. `null` is
    distinguishable from `0`, which would wrongly claim a document with no
    pages.
    """
    accepted = await seed_queued(session, repo, "waiting.pdf")
    await session.commit()

    response = await client.get(f"/documents/{accepted.document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["finished_at"] is None
    assert body["error"] is None
    assert body["page_count"] is None
    assert body["chunk_count"] is None


async def test_the_list_distinguishes_queued_from_processing_from_done(
    client, session, repo: DocumentRepository
) -> None:
    """Three documents, three states, one request.

    This is the query the sidebar makes, and the reason `queued` had to be a
    separate status rather than reusing `processing`: "nobody has started this"
    and "a worker is working on it right now" look identical to a user
    otherwise, and only one of them is a reason to worry when it lasts.
    """
    await seed(session, repo, "finished.pdf")

    accepted = await seed_queued(session, repo, "running.pdf")
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None and claimed.document_id == accepted.document_id

    await seed_queued(session, repo, "waiting.pdf")
    await session.commit()

    items = (await client.get("/documents")).json()["items"]
    by_name = {item["filename"]: item["status"] for item in items}

    assert by_name == {
        "finished.pdf": "done",
        "running.pdf": "processing",
        "waiting.pdf": "queued",
    }


async def test_a_document_waiting_to_retry_is_queued_and_says_why(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    """**A state that did not exist before stage 2.1.**

    A failure is no longer terminal on the first try, so between attempts a
    document sits at `queued` — the same status as a fresh upload — while
    carrying the reason it is waiting.

    That pairing is deliberate. `failed_requires_error` does not apply to a
    `queued` row, so the repository could have cleared the error on requeue
    and did not: without it, a document being retried after a provider outage
    would look identical to one nobody has touched yet, and the user would have
    no idea anything had gone wrong.
    """
    await seed(
        session,
        repo,
        "flaky.pdf",
        FakeAgent(status_code=502, body={"detail": "the embedding provider failed"}),
        retry=RETRY,
    )
    await session.commit()

    items = (await client.get("/documents")).json()["items"]
    row = next(item for item in items if item["filename"] == "flaky.pdf")

    assert row["status"] == "queued", (
        "a job awaiting a retry is back on the queue, not failed"
    )
    assert row["error"] == "the embedding provider failed", (
        "and it still says why it is waiting"
    )
    assert row["finished_at"] is None
    assert row["chunk_count"] is None


async def test_a_retrying_document_is_distinguishable_from_a_fresh_one(
    client, session: AsyncSession, repo: DocumentRepository
) -> None:
    """**The gap stage 2.1 left until this layer.**

    Both of these documents are `status: "queued"`. Without `attempts` they
    are identical over the wire, so the client would show the same badge for
    "nobody has started this yet" and "this has failed twice and is waiting to
    try again" — hiding a repeated failure behind a patient-looking label.
    """
    # Order matters: `seed` claims the *oldest* queued job, so the document
    # meant to fail has to be enqueued first. Seeding the fresh one first made
    # this test claim and fail the wrong document — a reminder that the queue
    # is FIFO and the helpers are not independent of each other.
    await seed(
        session,
        repo,
        "flaky.pdf",
        FakeAgent(status_code=502, body={"detail": "the provider failed"}),
        retry=RETRY,
    )
    await seed_queued(session, repo, "fresh.pdf")
    await session.commit()

    items = (await client.get("/documents")).json()["items"]
    by_name = {item["filename"]: item for item in items}

    fresh, flaky = by_name["fresh.pdf"], by_name["flaky.pdf"]

    assert fresh["status"] == flaky["status"] == "queued", (
        "both are queued — which is exactly why `attempts` has to be sent"
    )
    assert fresh["attempts"] == 0
    assert fresh["error"] is None
    assert fresh["next_attempt_at"] is None, "nothing is holding it back"

    assert flaky["attempts"] == 1
    assert flaky["error"] == "the provider failed"
    assert flaky["next_attempt_at"] is not None, (
        "a job waiting out its backoff should say when it will be tried again"
    )


async def test_attempts_is_zero_for_a_document_with_no_job(
    client, session: AsyncSession
) -> None:
    """`0`, not `null`.

    A document with no ingestion job should be impossible — both rows are
    written in one transaction — but the read path tolerates it so the
    inconsistency is visible rather than hidden. In that case "how many times
    has this been attempted" has a true answer, and it is zero.
    """
    document = Document(
        filename="orphan.pdf", byte_size=10, content_type="application/pdf"
    )
    session.add(document)
    await session.commit()

    body = (await client.get(f"/documents/{document.id}")).json()

    assert body["status"] is None
    assert body["attempts"] == 0
