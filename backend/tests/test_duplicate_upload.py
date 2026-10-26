"""Uploading the same bytes twice. Stage 2.2.

**This is the file that proves the upload is idempotent**, and it is also the
first test anywhere that drives `POST /documents` over HTTP. That was a gap
worth closing on its own: the status code is the *only* thing distinguishing a
new ingestion from a no-op, and a status code cannot be tested below the route.

── Two halves, two techniques ──────────────────────────────────────────────────

The deliberate duplicate — someone re-uploading a file — is sequential, and the
ordinary `client` fixture tests it end to end through real routing, validation
and the exception handlers.

The *race* cannot use that fixture. `session` wraps every test in one
transaction and rolls it back, so two "concurrent" callers would share a single
transaction and could never contend for the unique index. Those tests open
their own engines and commit for real, the same trade
`test_claim_concurrency.py` makes for the same reason.

── What the race is about, and why a SELECT is not enough ──────────────────────

`accept_upload` looks the hash up before inserting. Two requests carrying the
same bytes can both read "nothing" before either writes, so the lookup is a
fast path, not a guarantee. `uq_documents_content_hash` is the guarantee, and
the loser's `IntegrityError` is caught on a SAVEPOINT so it can re-read and
answer with the winner's document instead of failing.
"""

import asyncio
import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.repositories.documents import DocumentRepository
from app.services.ingestion import IngestionService, RetryPolicy

# Not a real PDF. Nothing here reaches `rag.extraction` — the fake agent below
# answers for the engine, and these tests are about identity, not parsing.
PDF = b"%PDF-1.4 the same bytes, uploaded more than once"

RETRY = RetryPolicy(max_attempts=5, base_seconds=0.0)
LEASE = 60.0


class FakeAgent:
    """Succeeds, and counts how many times it was asked to.

    The count is the point in one test below: a duplicate upload that queues
    nothing must also cost nothing, and "did we embed this twice?" is a
    question about calls, not about rows.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        self.calls.append(kwargs)
        return 201, {
            "document_id": kwargs["document_id"],
            "filename": kwargs["filename"],
            "page_count": 3,
            "pages_with_text": 3,
            "characters_extracted": 1200,
            "chunk_count": 3,
        }


class BrokenAgent:
    """Rejects the document the way the engine rejects an unreadable file."""

    async def ingest_document(self, **kwargs) -> tuple[int, dict]:
        return 422, {"detail": "not a PDF"}


def upload(content: bytes = PDF, filename: str = "same.pdf") -> dict:
    """The multipart body `POST /documents` expects.

    The field name must be `file`: FastAPI resolves multipart fields by name,
    and renaming it produces a 422 about a missing field rather than anything
    to do with this test.
    """
    return {"files": {"file": (filename, content, "application/pdf")}}


# ── The deliberate duplicate, over HTTP ──────────────────────────────────────


async def test_a_first_upload_is_accepted_and_queued(client) -> None:
    """The baseline, so the next test's `200` means something.

    Asserted here rather than taken for granted because this is the first test
    of this route at all, and a `202` that was always a `200` would make every
    comparison below vacuous.
    """
    response = await client.post("/documents", **upload())

    assert response.status_code == 202
    assert response.headers["Location"] == (
        f"/documents/{response.json()['document_id']}"
    )
    assert response.json()["status"] == "queued"
    assert response.json()["chunk_count"] is None


async def test_the_same_bytes_again_are_a_200_and_queue_nothing(
    client, session: AsyncSession
) -> None:
    """The headline. Same bytes, same document, no second job, no second blob.

    `200` rather than `202` is the entire signal: the request was "make sure
    this document is indexed", and it already is. `202` would promise work
    that is not going to happen, and a client polling for it would wait
    forever for a state change that already occurred.
    """
    first = await client.post("/documents", **upload())
    assert first.status_code == 202

    second = await client.post("/documents", **upload())

    assert second.status_code == 200, "nothing was queued, so this is not a 202"
    assert second.json()["document_id"] == first.json()["document_id"]
    assert second.headers["Location"] == first.headers["Location"], (
        "the Location names the document the request turned out to be about"
    )

    counts = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM documents) AS documents, "
                "       (SELECT count(*) FROM document_uploads) AS uploads, "
                "       (SELECT count(*) FROM ingestion_jobs) AS jobs"
            )
        )
    ).one()
    assert (counts.documents, counts.uploads, counts.jobs) == (1, 1, 1), (
        "a duplicate must not create a document, a blob or a job"
    )


async def test_a_different_filename_does_not_make_a_different_document(
    client,
) -> None:
    """The bytes are the identity; the name is a label.

    And the stored document keeps its *original* name. Renaming it because
    someone re-uploaded the same file as `copy.pdf` would rewrite a record on
    the strength of the one attribute this stage has just decided is not
    identifying.
    """
    first = await client.post("/documents", **upload(filename="original.pdf"))
    second = await client.post("/documents", **upload(filename="copy.pdf"))

    assert second.status_code == 200
    assert second.json()["document_id"] == first.json()["document_id"]
    assert second.json()["filename"] == "original.pdf", (
        "a duplicate upload must not rename the document it matched"
    )


async def test_different_bytes_are_a_different_document(client) -> None:
    """The control. Without it, a dedupe that matched *everything* would pass
    every other test in this file."""
    first = await client.post("/documents", **upload(PDF))
    second = await client.post("/documents", **upload(PDF + b" and more"))

    assert second.status_code == 202
    assert second.json()["document_id"] != first.json()["document_id"]


async def test_re_uploading_a_failed_document_queues_another_attempt(
    client, session: AsyncSession
) -> None:
    """The case that makes this a product decision rather than a rule.

    The bytes are identical, so it is the same document — but someone
    re-uploading a file that failed is asking for another attempt, not for the
    bad news again.

    One document, many jobs. This is the first caller that needs the shape
    `models.py` has been arguing for since 1.2, and without it a document whose
    retries were exhausted could never be re-driven from the UI at all.
    """
    first = await client.post("/documents", **upload())
    document_id = first.json()["document_id"]

    # Drive it to a terminal failure through the real path, so the state this
    # test depends on was produced by the system rather than written by hand.
    repo = DocumentRepository(session)
    service = IngestionService(session, repo, BrokenAgent())
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None
    await session.commit()
    await service.process_job(claimed, RetryPolicy(max_attempts=1, base_seconds=0.0))

    failed = await client.get(f"/documents/{document_id}")
    assert failed.json()["status"] == "failed", "the setup must actually fail"

    second = await client.post("/documents", **upload())

    assert second.status_code == 202, "a re-upload after a failure queues work"
    assert second.json()["document_id"] == document_id, "same document"
    assert second.json()["status"] == "queued"
    assert second.json()["attempts"] == 0, (
        "a fresh attempt starts at zero — inheriting the failed job's count "
        "would mean a deliberate re-upload began halfway through its budget"
    )
    assert second.json()["error"] is None, "the new attempt has not failed yet"

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
        "one document, one blob, two attempts"
    )


async def test_a_duplicate_of_a_queued_document_queues_nothing(
    client, session: AsyncSession
) -> None:
    """`queued` and `processing` are deliberately no-ops, not retries.

    The document is mid-flight. Queueing a second attempt would hand the same
    bytes to two workers at once — which is the duplicate-chunk corruption this
    stage exists to remove, arriving by a new route.

    Only `failed` means "this needs another go".
    """
    first = await client.post("/documents", **upload())
    assert first.json()["status"] == "queued"

    second = await client.post("/documents", **upload())

    assert second.status_code == 200
    jobs = (
        await session.execute(text("SELECT count(*) FROM ingestion_jobs"))
    ).scalar_one()
    assert jobs == 1, "a document already waiting must not be queued twice"


async def test_a_duplicate_costs_no_embedding_call(
    client, session: AsyncSession
) -> None:
    """The cost claim, measured in calls rather than rows.

    Rows are cheap; embedding is the bill. Two uploads of one file must
    produce exactly one trip through the agent, and counting jobs alone would
    not prove it — a job that is queued and never claimed also costs nothing,
    for a different reason.
    """
    agent = FakeAgent()
    repo = DocumentRepository(session)
    service = IngestionService(session, repo, agent)

    await client.post("/documents", **upload())
    claimed = await repo.claim_next_queued_job(lease_seconds=LEASE)
    assert claimed is not None
    await session.commit()
    await service.process_job(claimed, RETRY)
    assert len(agent.calls) == 1

    duplicate = await client.post("/documents", **upload())
    assert duplicate.status_code == 200

    # Nothing claimable, so nothing to pay for.
    assert await repo.claim_next_queued_job(lease_seconds=LEASE) is None
    assert len(agent.calls) == 1, (
        "the duplicate must not have been embedded a second time"
    )


# ── The race, on real connections ────────────────────────────────────────────


async def test_two_simultaneous_uploads_of_the_same_bytes(
    test_database_url: str,
) -> None:
    """Two callers, neither of which can see the other's uncommitted row.

    Both run their lookup and find nothing, so both try to insert — which is
    precisely the window the fast-path SELECT cannot close. One commits; the
    other's INSERT violates the unique index, its SAVEPOINT rolls back, it
    re-reads and answers with the winner's document.

    **What a passing test looks like:** one document in the table, and *both*
    callers holding its id. A caller that received an error would be the bug —
    its upload really did succeed, just not because of anything it did.
    """
    content = PDF + b" race"
    content_hash = hashlib.sha256(content).hexdigest()

    engine_a = create_async_engine(test_database_url)
    engine_b = create_async_engine(test_database_url)
    factory_a = async_sessionmaker(bind=engine_a, expire_on_commit=False)
    factory_b = async_sessionmaker(bind=engine_b, expire_on_commit=False)

    async def accept(factory):
        async with factory() as session:
            repo = DocumentRepository(session)
            service = IngestionService(session, repo, FakeAgent())
            return await service.accept_upload(
                filename="racing.pdf",
                content=content,
                content_type="application/pdf",
            )

    try:
        # `gather` rather than sequential awaits: both coroutines reach their
        # INSERT before either has committed, which is the state being tested.
        outcome_a, outcome_b = await asyncio.gather(
            accept(factory_a), accept(factory_b)
        )

        assert outcome_a.document.document_id == outcome_b.document.document_id, (
            "both callers must end up pointing at the same document"
        )

        async with engine_a.connect() as conn:
            documents = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM documents WHERE content_hash = :h"
                    ),
                    {"h": content_hash},
                )
            ).scalar_one()
            jobs = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM ingestion_jobs j "
                        "  JOIN documents d ON d.id = j.document_id "
                        " WHERE d.content_hash = :h"
                    ),
                    {"h": content_hash},
                )
            ).scalar_one()

        assert documents == 1, "the unique index must have refused the second"
        assert jobs == 1, (
            "and the loser must not have queued a second attempt at a document "
            "that is already queued"
        )

        # Exactly one of them did the enqueueing. Which one is a race and must
        # not be asserted; that exactly one did is the invariant.
        assert [outcome_a.queued, outcome_b.queued].count(True) == 1, (
            "one caller created and queued; the other reported an existing "
            "document and queued nothing"
        )
    finally:
        async with engine_a.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE content_hash = :h"),
                {"h": content_hash},
            )
        await engine_a.dispose()
        await engine_b.dispose()


async def test_the_loser_of_the_race_recovers_instead_of_raising(
    test_database_url: str,
) -> None:
    """The SAVEPOINT, tested deterministically.

    ── Why the obvious version of this test does not work ─────────────────────

    The first attempt committed A's document and *then* called B's
    `accept_upload`, expecting B's INSERT to collide. It passed with the
    savepoint removed, which is how the mistake was found: by that point A's
    row was committed, so B's own fast-path lookup found it and B never
    attempted an INSERT at all. The test was exercising the fast path and
    claiming to exercise the recovery.

    The race window is specifically **"the lookup returned nothing, but by the
    time we insert, the row exists"**, and that window is inside one call. It
    cannot be hit from outside by ordering two calls.

    So the stale read is simulated: B's first lookup is forced to miss, which
    is exactly what a concurrent caller observes, and every later lookup is the
    real one. That makes the collision certain on every run rather than
    dependent on how the event loop interleaved.

    ── What fails without the savepoint ──────────────────────────────────────

    B's INSERT raises `IntegrityError`, which aborts B's entire transaction in
    Postgres. The recovery lookup then raises `PendingRollbackError` instead of
    returning the winner's row, and the caller receives a 500 for an upload
    that in fact succeeded. `begin_nested()` confines the damage to the failed
    INSERT.
    """
    content = PDF + b" forced collision"
    content_hash = hashlib.sha256(content).hexdigest()

    engine_a = create_async_engine(test_database_url)
    engine_b = create_async_engine(test_database_url)
    factory_a = async_sessionmaker(bind=engine_a, expire_on_commit=False)
    factory_b = async_sessionmaker(bind=engine_b, expire_on_commit=False)

    try:
        async with factory_a() as session_a, factory_b() as session_b:
            # A creates and commits the document first.
            service_a = IngestionService(
                session_a, DocumentRepository(session_a), FakeAgent()
            )
            winner = await service_a.accept_upload(
                filename="winner.pdf",
                content=content,
                content_type="application/pdf",
            )
            assert winner.queued is True

            # B's first lookup misses, as a concurrent caller's would. Nothing
            # else about the repository is faked: the INSERT is real, the
            # constraint is real, and the recovery lookup is the real one.
            repo_b = DocumentRepository(session_b)
            real_lookup = repo_b.get_by_content_hash
            calls = {"n": 0}

            async def stale_then_real(value: str):
                calls["n"] += 1
                if calls["n"] == 1:
                    return None
                return await real_lookup(value)

            repo_b.get_by_content_hash = stale_then_real  # type: ignore[method-assign]
            service_b = IngestionService(session_b, repo_b, FakeAgent())

            loser = await service_b.accept_upload(
                filename="loser.pdf",
                content=content,
                content_type="application/pdf",
            )

            assert calls["n"] == 2, (
                "the INSERT must have been attempted and recovered from — one "
                "lookup means B took the fast path and this test proved nothing"
            )

        assert loser.document.document_id == winner.document.document_id
        assert loser.queued is False, "the loser queued nothing"
        assert loser.document.filename == "winner.pdf", (
            "the losing caller gets the document that exists, under the name "
            "it was actually stored with"
        )
    finally:
        async with engine_a.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE content_hash = :h"),
                {"h": content_hash},
            )
        await engine_a.dispose()
        await engine_b.dispose()


async def test_an_unrelated_integrity_error_is_not_swallowed(
    session: AsyncSession,
) -> None:
    """The savepoint handler must not become a catch-all.

    `accept_upload` catches `IntegrityError` and decides what it meant by
    re-reading the hash. If the hash is absent the violation was something
    else, and the error has to propagate — otherwise any future constraint on
    `documents` would be silently converted into "this is a duplicate", and
    the response would describe a document that was never written.

    The violation used here is a `filename` that is NULL, which
    `documents.filename NOT NULL` refuses. It is not the duplicate path, so the
    service must let it through untouched.
    """
    service = IngestionService(session, DocumentRepository(session), FakeAgent())

    with pytest.raises(IntegrityError):
        await service.accept_upload(
            filename=None,  # type: ignore[arg-type]
            content=PDF + b" unrelated violation",
            content_type="application/pdf",
        )
