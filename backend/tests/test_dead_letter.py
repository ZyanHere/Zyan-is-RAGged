"""The operator's view of what died, and the one thing to do about it. Stage 2.3.

`GET /documents?status=failed` and `POST /documents/{id}/retry`, driven over
HTTP, because both are about status codes and a status code cannot be tested
below the route.

── What a dead-letter queue is here ────────────────────────────────────────────

A filter, not a table. The roadmap called for moving exhausted jobs into a
separate table; a `WHERE` clause does everything that would have, because dead
jobs already cannot clog the queue (`failed` is terminal and unclaimable) and
replay already exists (`create_job_for_document`, built at 2.2).

So these tests are mostly about the two things a filter can get wrong — showing
a document that is no longer dead, and hiding one that is — plus the single
refusal the retry endpoint makes.
"""

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, IngestionStatus
from app.repositories.documents import DocumentRepository
from app.services.ingestion import IngestionService, RetryPolicy

PDF = b"%PDF-1.4 a document for the dead-letter tests"

# One attempt, no waiting: these tests are about what happens *after* the
# retries run out, so spending real backoff to get there would be slow and
# would test stage 2.1 again.
IMMEDIATE = RetryPolicy(max_attempts=1, base_seconds=0.0)
LEASE = 60.0


class GoodAgent:
    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        return 201, {
            "document_id": kwargs["document_id"],
            "filename": kwargs["filename"],
            "page_count": 1,
            "pages_with_text": 1,
            "characters_extracted": 40,
            "chunk_count": 1,
        }


class RejectingAgent:
    """A 4xx — permanent. The file is the problem."""

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        return 400, {"detail": "'broken.pdf' is not a valid PDF."}


class UnavailableAgent:
    """A 5xx — transient. The system is the problem."""

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        return 503, {"detail": "The embedding provider is unreachable."}


def upload(content: bytes, filename: str = "doc.pdf") -> dict:
    return {"files": {"file": (filename, content, "application/pdf")}}


async def drive_to_failure(
    client, session: AsyncSession, repo: DocumentRepository, agent, filename: str
) -> str:
    """Upload a document and run it to a terminal failure through the real path.

    Through the system rather than by writing a `failed` row directly, so the
    state these tests read was produced the way production produces it —
    including the `failure_kind` the classifier chose.
    """
    content = PDF + b" " + filename.encode()
    response = await client.post("/documents", **upload(content, filename))
    document_id = response.json()["document_id"]

    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None
    await session.commit()
    await IngestionService(session, repo, agent).process_job(claimed, IMMEDIATE)

    return document_id


# ── The list ─────────────────────────────────────────────────────────────────


async def test_the_failed_filter_returns_only_failed_documents(
    client, session: AsyncSession
) -> None:
    """The dead list, against a mixed set.

    A healthy document is uploaded too, so the filter has something to exclude
    — a test where everything matches cannot tell a filter from a missing
    filter.
    """
    repo = DocumentRepository(session)

    dead = await drive_to_failure(
        client, session, repo, RejectingAgent(), "broken.pdf"
    )

    alive = (await client.post("/documents", **upload(PDF + b" ok", "fine.pdf"))).json()[
        "document_id"
    ]
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None
    await session.commit()
    await IngestionService(session, repo, GoodAgent()).process_job(claimed, IMMEDIATE)

    response = await client.get("/documents", params={"status": "failed"})

    assert response.status_code == 200
    ids = [item["document_id"] for item in response.json()["items"]]
    assert ids == [dead]
    assert alive not in ids

    everything = await client.get("/documents")
    assert len(everything.json()["items"]) == 2, "the unfiltered list is unchanged"


async def test_the_dead_list_says_why_each_one_died(
    client, session: AsyncSession
) -> None:
    """`failure_kind` is on the wire, and it is what makes the list actionable.

    Two entries that look identical without it — both `failed`, both with a
    string — and that need opposite responses from whoever is reading.
    """
    repo = DocumentRepository(session)

    await drive_to_failure(client, session, repo, RejectingAgent(), "broken.pdf")
    await drive_to_failure(client, session, repo, UnavailableAgent(), "unlucky.pdf")

    items = (
        await client.get("/documents", params={"status": "failed"})
    ).json()["items"]

    kinds = {item["filename"]: item["failure_kind"] for item in items}
    assert kinds == {"broken.pdf": "permanent", "unlucky.pdf": "transient"}


async def test_an_unknown_status_is_rejected_rather_than_ignored(client) -> None:
    """`?status=ded` must be a 422, not an empty list.

    This is the assertion that earns the typed query parameter. An unknown
    value silently returning `{"items": []}` reads as *"nothing has failed"* —
    the most dangerous possible answer to the question this endpoint exists to
    answer, and indistinguishable from good news.
    """
    response = await client.get("/documents", params={"status": "ded"})

    assert response.status_code == 422


async def test_a_document_that_recovered_leaves_the_dead_list(
    client, session: AsyncSession
) -> None:
    """The failure mode the repository's filter is shaped to avoid.

    A document that failed and was then retried successfully still has a
    `failed` job in its history. If the list showed it, every fixed document
    would stay on the operator's list forever, and the list would become the
    thing nobody reads.
    """
    repo = DocumentRepository(session)
    document_id = await drive_to_failure(
        client, session, repo, UnavailableAgent(), "unlucky.pdf"
    )

    assert (
        await client.get("/documents", params={"status": "failed"})
    ).json()["items"], "it is dead before the retry"

    await client.post(f"/documents/{document_id}/retry")
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None
    await session.commit()
    await IngestionService(session, repo, GoodAgent()).process_job(claimed, IMMEDIATE)

    after = (await client.get("/documents", params={"status": "failed"})).json()
    assert after["items"] == [], "a recovered document is not dead"


# ── The retry ────────────────────────────────────────────────────────────────


async def test_retrying_a_dead_document_queues_a_fresh_attempt(
    client, session: AsyncSession
) -> None:
    """`202`, the same document, a new job that starts clean.

    `attempts: 0` is the load-bearing assertion. Carrying the dead job's count
    forward would mean a deliberate replay began with its budget already
    spent — and a document that exhausted its retries could never be
    re-driven at all, which is precisely the document on this list.
    """
    repo = DocumentRepository(session)
    document_id = await drive_to_failure(
        client, session, repo, UnavailableAgent(), "unlucky.pdf"
    )

    response = await client.post(f"/documents/{document_id}/retry")

    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == document_id, "same document, new attempt"
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["error"] is None, "the new attempt has not failed yet"
    assert body["failure_kind"] is None
    assert response.headers["Location"] == f"/documents/{document_id}"

    counts = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM documents) AS documents, "
                "       (SELECT count(*) FROM document_uploads) AS uploads, "
                "       (SELECT count(*) FROM ingestion_jobs) AS jobs"
            )
        )
    ).one()
    assert (counts.documents, counts.uploads, counts.jobs) == (1, 1, 2), (
        "one document, one blob, two attempts — no second copy of anything"
    )


async def test_a_permanently_failed_document_may_still_be_retried(
    client, session: AsyncSession
) -> None:
    """It reads wrong, and it is right.

    The server decided this file could never be indexed — and what it actually
    knows is that the file was not a PDF *when it last looked*. It cannot
    observe whether OCR has since been installed or a limit raised. Refusing
    would be the server asserting the outside world has not changed.

    The cost of being wrong is one claim and one 4xx: `classify` still stops
    it at attempt one.
    """
    repo = DocumentRepository(session)
    document_id = await drive_to_failure(
        client, session, repo, RejectingAgent(), "broken.pdf"
    )

    assert (
        await client.get(f"/documents/{document_id}")
    ).json()["failure_kind"] == "permanent"

    assert (await client.post(f"/documents/{document_id}/retry")).status_code == 202


async def test_retrying_an_unknown_document_is_a_404(client) -> None:
    """A 404, not a 500, and the message names only the id.

    At stage 5.1 "not found" and "not yours" must be indistinguishable from
    outside, or the 404 itself reveals which ids exist.
    """
    missing = "01a00000-0000-7000-8000-000000000000"

    response = await client.post(f"/documents/{missing}/retry")

    assert response.status_code == 404


async def test_a_malformed_id_is_a_422_not_a_404(client) -> None:
    """An unparseable id and an unknown id are different answers.

    Rejected by validation before any query runs, which is also why it cannot
    be mistaken for "we looked and it is not there".
    """
    assert (await client.post("/documents/not-a-uuid/retry")).status_code == 422


@pytest.mark.parametrize("in_flight", ["queued", "processing"])
async def test_retrying_a_document_already_in_flight_is_refused(
    client, session: AsyncSession, in_flight: str
) -> None:
    """**The only refusal, and the only one the server can actually know.**

    Queueing beside a live attempt would hand the same bytes to two workers at
    once — the duplicate-chunk corruption stage 2.2 removed, arriving by a new
    route. A `409` rather than a `400`: the request is well formed and will be
    fine once the current attempt finishes.
    """
    repo = DocumentRepository(session)
    response = await client.post("/documents", **upload(PDF + b" live", "live.pdf"))
    document_id = response.json()["document_id"]

    if in_flight == "processing":
        claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
        assert claimed is not None
        await session.commit()

    refused = await client.post(f"/documents/{document_id}/retry")

    assert refused.status_code == 409
    assert in_flight in refused.json()["detail"]

    jobs = (
        await session.execute(text("SELECT count(*) FROM ingestion_jobs"))
    ).scalar_one()
    assert jobs == 1, "the refusal must not have queued anything"


async def test_a_document_with_no_job_at_all_can_be_retried(
    client, session: AsyncSession
) -> None:
    """The state that should be impossible, and the one action that fixes it.

    Both rows are written in one transaction, so a job-less document should
    not exist. It is representable, the list reports it rather than hiding it,
    and the honest response to seeing one is to queue the attempt that is
    missing — not to refuse because there is nothing to compare against.
    """
    document = Document(
        filename="jobless.pdf",
        byte_size=4,
        content_type="application/pdf",
        content_hash=hashlib.sha256(b"jobless").hexdigest(),
    )
    session.add(document)
    await session.commit()

    response = await client.post(f"/documents/{document.id}/retry")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
