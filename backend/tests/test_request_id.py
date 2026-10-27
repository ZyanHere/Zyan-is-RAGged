"""The id that crosses the process boundary. Stage 2.4.

`X-Request-ID` on the way in and on the way out, and the value stored on the
job the request created. Driven over HTTP, because a middleware is only a
middleware when something runs through it.

── The inbound header is attacker-controlled ───────────────────────────────────

That is the part of this file worth reading. The id is written into **every log
line for the request** and into a database column, so an unvalidated header is
a log-forgery primitive: a newline closes the current line and whatever follows
is indistinguishable from something this service emitted.

A stage about making the system observable that lets a caller write the
observations would be worse than the blindness it replaces.
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FailureKind
from app.repositories.documents import DocumentRepository

PDF = b"%PDF-1.4 a document for the request-id tests"


def upload(content: bytes, filename: str = "corr.pdf") -> dict:
    return {"files": {"file": (filename, content, "application/pdf")}}


# ── Every response carries one ───────────────────────────────────────────────


async def test_every_response_carries_a_request_id(client) -> None:
    """Including the ones that do nothing interesting.

    `/health` is the cheapest possible request, and it still gets an id. A
    correlation scheme with holes in it is one you stop trusting the first
    time the line you need is in the hole.
    """
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


async def test_two_requests_get_different_ids(client) -> None:
    """Otherwise the id correlates nothing.

    Cheap, and it catches the mistake of generating the id once at import —
    which would look perfectly correct in every single-request test.
    """
    first = (await client.get("/health")).headers["X-Request-ID"]
    second = (await client.get("/health")).headers["X-Request-ID"]

    assert first != second


async def test_an_inbound_id_is_honoured(client) -> None:
    """A gateway's id wins, so correlation does not stop at our front door.

    Nothing upstream sets this today. Accepting it costs one regex, and the
    day something does set it, nothing here has to change — whereas always
    generating our own would mean the id in our logs is unrelated to the id in
    theirs, which is the one place correlation is most often needed.
    """
    response = await client.get(
        "/health", headers={"X-Request-ID": "gateway-abc123"}
    )

    assert response.headers["X-Request-ID"] == "gateway-abc123"


# ── The guard ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hostile", "why"),
    [
        ("abc\ndef", "a newline forges a second log line"),
        ("abc\r\nERROR fake entry", "CRLF, the same attack spelled properly"),
        ("x" * 65, "longer than the column and every log line"),
        ("", "empty is not an id"),
        ('{"json": "injection"}', "would be a nested object in a JSON log"),
        ("../../etc/passwd", "no reason to let a path through"),
    ],
)
async def test_a_hostile_inbound_id_is_replaced_not_echoed(
    client, hostile: str, why: str
) -> None:
    """**The security assertion in this stage.**

    The id goes into every log line and into a database column. Echoing an
    arbitrary header into both is how a caller writes your logs for you.

    Replaced rather than rejected: a malformed correlation header is not a
    reason to refuse to index someone's document. The request succeeds with an
    id of our own.
    """
    response = await client.get("/health", headers={"X-Request-ID": hostile})

    assert response.status_code == 200, "a bad id must not break the request"

    issued = response.headers["X-Request-ID"]
    assert issued != hostile, why
    assert "\n" not in issued and "\r" not in issued
    assert 0 < len(issued) <= 64


async def test_a_plausible_inbound_id_is_kept(client) -> None:
    """The guard must not be so strict that it rejects real ids.

    A test that only checks hostile input passes trivially if the regex
    rejects everything. These are the shapes real tracing systems emit.
    """
    for good in ("abc123", "req-7f3a1c", "a_b-C9", "x" * 64):
        response = await client.get("/health", headers={"X-Request-ID": good})
        assert response.headers["X-Request-ID"] == good, good


# ── It reaches the row ───────────────────────────────────────────────────────


async def test_the_upload_stores_the_id_of_the_request_that_made_it(
    client, session: AsyncSession
) -> None:
    """The point of the whole layer: the id survives the response.

    The API returns and the request is gone. A worker picks the job up later,
    possibly after a restart. The row is the only thing both of them can see —
    which is true because stage 1.3 made the queue a table.
    """
    response = await client.post(
        "/documents",
        headers={"X-Request-ID": "req-upload-9"},
        **upload(PDF + b" stored"),
    )
    document_id = response.json()["document_id"]

    stored = (
        await session.execute(
            text(
                "SELECT request_id FROM ingestion_jobs WHERE document_id = :d"
            ),
            {"d": document_id},
        )
    ).scalar_one()

    assert stored == "req-upload-9"


async def test_a_replay_records_the_replay_request(
    client, session: AsyncSession
) -> None:
    """Two attempts, two requests, and the row says which was which.

    This is what `request_id` being on the **job** rather than the document
    buys. The operator asking "why did attempt two run?" gets the request that
    asked for it, not the upload from last week.
    """
    created = await client.post(
        "/documents",
        headers={"X-Request-ID": "req-first"},
        **upload(PDF + b" replayed"),
    )
    document_id = created.json()["document_id"]

    # Drive the first attempt to a terminal state. `/retry` refuses a document
    # that is still `queued` with a 409 — stage 2.3's rule against handing the
    # same bytes to two workers — so a replay test has to get past it honestly
    # rather than by relaxing the rule.
    repo = DocumentRepository(session)
    claimed = await repo.claim_next_queued_job(lease_seconds=60.0)
    assert claimed is not None
    assert await repo.mark_job_failed(
        claimed.job_id,
        claimed.lease_token,
        error="the agent did not respond",
        failure_kind=FailureKind.TRANSIENT,
    )
    await session.commit()

    replayed = await client.post(
        f"/documents/{document_id}/retry", headers={"X-Request-ID": "req-second"}
    )
    assert replayed.status_code == 202

    ids = [
        row[0]
        for row in (
            await session.execute(
                text(
                    "SELECT request_id FROM ingestion_jobs "
                    " WHERE document_id = :d ORDER BY queued_at, id"
                ),
                {"d": document_id},
            )
        ).all()
    ]

    assert ids == ["req-first", "req-second"]


async def test_a_duplicate_upload_queues_nothing_and_records_nothing(
    client, session: AsyncSession
) -> None:
    """A `200` writes no job, so there is no second id to record.

    Worth pinning because the dedupe path is the one that *looks* like it
    should create something. If it quietly did, the duplicate would show up as
    a second attempt in every trace.
    """
    content = PDF + b" duplicate"
    await client.post(
        "/documents", headers={"X-Request-ID": "req-one"}, **upload(content)
    )
    second = await client.post(
        "/documents", headers={"X-Request-ID": "req-two"}, **upload(content)
    )

    assert second.status_code == 200

    ids = [
        row[0]
        for row in (
            await session.execute(text("SELECT request_id FROM ingestion_jobs"))
        ).all()
    ]
    assert ids == ["req-one"]


# ── It reaches the logs ──────────────────────────────────────────────────────


async def test_the_id_is_on_the_log_lines_the_request_produced(
    client, caplog: pytest.LogCaptureFixture
) -> None:
    """The filter puts it on the record without any call site knowing.

    `caplog` is adequate *here* — unlike in `test_logging.py`, this is not
    asking whether a handler exists, only whether the record carries the
    attribute. The filter runs on our handler, so the test configures logging
    and reads the record it produced.
    """
    from app.core.logging import RequestIdFilter

    caplog.handler.addFilter(RequestIdFilter())

    with caplog.at_level("INFO", logger="app.services.ingestion"):
        await client.post(
            "/documents",
            headers={"X-Request-ID": "req-logged"},
            **upload(PDF + b" logged"),
        )

    queued = [r for r in caplog.records if "ingestion queued" in r.getMessage()]
    assert queued, "the accept line should have been emitted"
    assert getattr(queued[0], "request_id", None) == "req-logged"


async def test_the_id_does_not_leak_between_requests(client) -> None:
    """The `ContextVar` is reset, and this is why that matters.

    anyio reuses the task that runs the middleware. Without the reset, a
    finished request could leave its id visible to whatever runs next — so a
    log line would carry a correlation id belonging to an unrelated request,
    which is worse than carrying none at all. A wrong id sends whoever is
    debugging to the wrong story.
    """
    from app.core.logging import request_id_var

    await client.get("/health", headers={"X-Request-ID": "req-leaky"})

    assert request_id_var.get() is None


async def test_the_json_formatter_carries_it(client) -> None:
    """End to end, in the shape a log collector actually receives."""
    import io
    import logging

    from app.core.logging import configure_logging

    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        configure_logging(json_output=True)
        buffer = io.StringIO()
        root.handlers[0].setStream(buffer)  # type: ignore[attr-defined]

        await client.post(
            "/documents",
            headers={"X-Request-ID": "req-json"},
            **upload(PDF + b" json"),
        )

        lines = [
            json.loads(line)
            for line in buffer.getvalue().splitlines()
            if line.strip().startswith("{")
        ]
    finally:
        root.handlers[:] = saved

    accepted = [p for p in lines if "ingestion queued" in p.get("message", "")]
    assert accepted, "no accept line reached the JSON handler"
    assert accepted[0]["request_id"] == "req-json"


# ── The browser has to be allowed to read it ─────────────────────────────────


async def test_the_header_is_exposed_through_cors(client) -> None:
    """**The silent failure this stage exists to stop, in its own mechanism.**

    CORS hides every response header except a short safelist. Without
    `expose_headers`, `X-Request-ID` is set on the wire and reading it from
    JavaScript returns `null` — no error, no warning, nothing in any console.
    The server looks correct, the browser sees nothing, and the only symptom
    is a feature that quietly does not work.

    This test was written because a mutation survived: emptying
    `expose_headers` broke nothing. Every other claim in this file had a test;
    the one that fails most quietly did not.

    An `Origin` header is required — Starlette's CORS middleware only adds
    these on a cross-origin response, so without it the assertion would pass
    against any configuration by testing nothing.

    `Location` is checked alongside, because the `202` from an upload points
    at the document with it and a client that cannot read it has to
    reconstruct the URL from the body.
    """
    response = await client.get(
        "/health", headers={"Origin": "http://localhost:3000"}
    )

    exposed = response.headers.get("access-control-expose-headers", "")
    allowed = {h.strip().lower() for h in exposed.split(",")}

    assert "x-request-id" in allowed, (
        "the header is set but invisible to the browser — JavaScript reading "
        "it gets null, with no error anywhere"
    )
    assert "location" in allowed
