"""POST /documents — accept an upload and hand it to the agent.

**No longer a pass-through.** At stage 1.1 this route validated, forwarded and
returned, storing nothing because there was nothing to store it in.

Stage 1.2 is where that stopped being true. The route now records the attempt
before any work starts, so a timed-out or crashed upload leaves a visible row
rather than an unknowable state.

Stage 1.3 finished the job: it returns `202` with a queued record and does
not block. The result arrives later, through `GET /documents/{id}`, and the
only thing this handler does with the agent is not call it.

Stage 2.2 made `202` conditional. An upload of bytes the system already has
indexed enqueues nothing, so it answers `200` — see the handler.

Stage 2.3 adds the operator's two: `GET /documents?status=failed` is the
dead-letter queue, and `POST /documents/{id}/retry` is the only thing to do
about an entry in it.

Routes raise domain errors; `main.py` maps them to status codes. Same shape as
the agent.
"""

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import DocumentRepositoryDep, SessionDep
from app.db.models import IngestionStatus
from app.core.config import get_settings
from app.errors import BadUploadError, NotFoundError, UploadTooLargeError
from app.schemas.documents import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    DocumentListResponse,
    DocumentRead,
)
from app.services.ingestion import IngestionService

router = APIRouter()


@router.post(
    "/documents",
    response_model=DocumentRead,
    status_code=HTTPStatus.ACCEPTED,
)
async def upload_document(
    session: SessionDep,
    repository: DocumentRepositoryDep,
    file: UploadFile = File(...),
) -> JSONResponse:
    """Accept a PDF, record that it needs indexing, and return immediately.

    **`202 Accepted`, not `200 OK`**, and the distinction is the stage. 200
    would mean "here is the indexed document"; 202 means "this is a valid
    request, it has been recorded, and it has not happened yet". The body
    carries the document with `status: "queued"` and every count `null`,
    because at this instant that is the whole truth.

    ── Both codes, from stage 2.2 ─────────────────────────────────────────────

    `202` is now conditional on something actually being enqueued:

        202   a new document, or another attempt at one whose last attempt
              failed. Work is queued; the outcome arrives later at `Location`.
        200   these exact bytes are already indexed or already in flight.
              Nothing was created and nothing was queued.

    Both are successes, and that is the point — the request was "make sure this
    document is indexed", and in the second case it already is. A `409
    Conflict` would report a failure for an upload that worked, which is
    exactly what a browser retrying a timed-out `POST` would receive.

    The two codes are also the *only* signal a client gets, because both carry
    the same body. The frontend reads the status to tell the user whether it is
    watching a new ingestion or looking at a document it already had.

    **The handler does not make this decision**, it only reports it:
    `UploadOutcome.queued` comes from the service, where the rest of the
    ingestion policy lives. Deciding it here would put a product rule in the
    HTTP layer and leave the worker's half of the service unable to see it.

    **No `AgentClientDep`.** The route no longer talks to the agent at all, and
    dropping the dependency is the honest signal — a parameter it never used
    would leave the impression that it might.

    The route still parses the upload and checks what can be checked cheaply.
    Everything else is `IngestionService.accept_upload`, which is three writes
    and a commit.
    """
    settings = get_settings()

    # One byte past the limit, so an oversized upload is rejected before it has
    # been fully buffered rather than after.
    content = await file.read(settings.max_upload_bytes + 1)

    if len(content) > settings.max_upload_bytes:
        raise UploadTooLargeError(
            f"'{file.filename}' exceeds the maximum upload size of "
            f"{settings.max_upload_bytes // (1024 * 1024)} MB."
        )

    if not content:
        # The engine checks this too. This one saves a pointless round trip for
        # the most common bad upload.
        raise BadUploadError(f"'{file.filename}' is empty (0 bytes).")

    service = IngestionService(session, repository)
    outcome = await service.accept_upload(
        filename=file.filename or "upload.pdf",
        content=content,
        content_type=file.content_type,
    )

    # `Location` points at where the outcome will appear, and it is sent with
    # both codes. On a `202` it is what makes the response well formed — the
    # server tells the client where to look instead of asking it to
    # reconstruct the URL from an id in the body. On a `200` it names the
    # document the request turned out to be about, which is the one thing the
    # client did not know.
    #
    # `JSONResponse` rather than returning the model, because both a custom
    # header and a conditional status code need the response object. The
    # `response_model` on the decorator still documents the shape in the
    # OpenAPI schema, and the shape is the same either way.
    return JSONResponse(
        status_code=(
            HTTPStatus.ACCEPTED if outcome.queued else HTTPStatus.OK
        ),
        content=outcome.document.model_dump(mode="json"),
        headers={"Location": f"/documents/{outcome.document.document_id}"},
    )

@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    repository: DocumentRepositoryDep,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, gt=0, le=MAX_PAGE_SIZE),
    status: IngestionStatus | None = Query(default=None),
) -> DocumentListResponse:
    """Every document, newest first, with the state of its latest attempt.

    **This is the endpoint the frontend has been waiting for.** Its upload
    mutation already declares `invalidatesTags: ["Document"]`, written at a
    point when nothing provided that tag — a no-op against an empty cache. Once
    the frontend's list query declares `providesTags: ["Document"]`, those two
    halves connect and refetch-after-upload starts working with no new code.
    That is the concrete payoff of the architecture, and it is one line on each
    side.

    One query, not one per document: the repository joins the latest job in a
    single `DISTINCT ON`. With `lazy="raise"` on the relationship, an
    accidental N+1 would raise rather than quietly issue fifty round trips.

    `limit` is bounded server-side. An unbounded client-supplied limit is a
    request to build an arbitrarily large response in memory.

    ── `?status=failed` is the dead-letter queue — stage 2.3 ─────────────────

    Not a separate endpoint, and not a separate table. The question *"what has
    died?"* is the same question this endpoint already answers, narrowed — so
    it gets a filter rather than a parallel route with its own response model
    and its own pagination to keep in step.

    **Typed as `IngestionStatus`**, which is what makes an unknown value a
    `422` from validation rather than a silently empty list. `?status=ded`
    returning `{"items": []}` would read as "nothing has failed", which is the
    most dangerous possible answer to that question.

    It filters on the document's **latest** job. A document that failed once
    and has since succeeded is not in the dead list — see the repository,
    where that distinction is one word and the whole correctness of this
    feature.
    """
    rows = await repository.list_documents_with_latest_job(
        limit=limit, status=status
    )
    return DocumentListResponse(
        items=[DocumentRead.from_rows(document, job) for document, job in rows]
    )


@router.get("/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID,
    repository: DocumentRepositoryDep,
) -> DocumentRead:
    """One document and the state of its latest attempt.

    `document_id` is typed as `UUID`, so a malformed id is rejected by
    validation as a 422 before any query runs — a missing document and an
    unparseable id are different answers and should not share a code path.

    The 404 message says only that the id is unknown. At stage 5.1, when
    documents belong to tenants, "not found" and "not yours" must be
    indistinguishable from outside — otherwise the 404 itself reveals which
    ids exist.
    """
    found = await repository.get_document_with_latest_job(document_id)
    if found is None:
        raise NotFoundError(f"No document with id {document_id}.")

    document, job = found
    return DocumentRead.from_rows(document, job)


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentRead,
    status_code=HTTPStatus.ACCEPTED,
)
async def retry_document(
    document_id: UUID,
    session: SessionDep,
    repository: DocumentRepositoryDep,
) -> JSONResponse:
    """Queue another attempt at a document that is already here. Stage 2.3.

    The operator's half of the dead-letter queue, and the reason the list is
    worth having: without a way to act on an entry, a dead-letter view is a
    list of regrets.

    **`202`, like an upload**, because it means the same thing — work has been
    recorded and has not happened yet, and the outcome appears at `Location`.
    No `200` variant here: unlike `POST /documents`, this call *always*
    enqueues something or fails, so there is no "nothing to do" outcome to
    distinguish.

    **`POST`, not `PUT`**, because it is not idempotent: calling it twice
    queues two attempts. That is also why the conflict below matters — the
    non-idempotence is bounded by refusing while one is already in flight.

    ── The status codes, and what each one knows ─────────────────────────────

        202   queued. The document exists and nothing was running.
        404   no such document.
        409   its latest attempt is `queued` or `processing`.

    The `409` is the only refusal, and it is refused because the server can
    *know* it: two workers on the same bytes is the duplicate-chunk corruption
    stage 2.2 removed.

    A permanently failed document is **not** refused. The server knows the
    file was not a PDF when it last looked; it does not know whether OCR has
    since been installed or the file replaced, and refusing would assert
    something it cannot observe. See `IngestionService.retry_document`.

    ── Why the body is a `DocumentRead` and not an empty 202 ────────────────

    So the client can render the row immediately — `status: "queued"`,
    `attempts: 0`, `error: null` — instead of waiting a poll interval to find
    out whether anything happened. The same reason the upload route returns
    one.
    """
    service = IngestionService(session, repository)
    record = await service.retry_document(document_id)

    return JSONResponse(
        status_code=HTTPStatus.ACCEPTED,
        content=record.model_dump(mode="json"),
        headers={"Location": f"/documents/{record.document_id}"},
    )
