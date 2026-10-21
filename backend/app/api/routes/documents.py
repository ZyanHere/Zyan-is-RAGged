"""POST /documents — accept an upload and hand it to the agent.

**No longer a pass-through.** At stage 1.1 this route validated, forwarded and
returned, storing nothing because there was nothing to store it in.

Stage 1.2 is where that stopped being true. The route now records the attempt
before any work starts, so a timed-out or crashed upload leaves a visible row
rather than an unknowable state.

Stage 1.3 finished the job: it returns `202` with a queued record and does
not block. The result arrives later, through `GET /documents/{id}`, and the
only thing this handler does with the agent is not call it.

Routes raise domain errors; `main.py` maps them to status codes. Same shape as
the agent.
"""

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import DocumentRepositoryDep, SessionDep
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
    record = await service.accept_upload(
        filename=file.filename or "upload.pdf",
        content=content,
        content_type=file.content_type,
    )

    # `Location` points at where the outcome will appear. That is what makes
    # this a well-formed 202 rather than a 200 with a different number: the
    # response tells the client where to look instead of asking it to
    # reconstruct the URL from an id in the body.
    #
    # `JSONResponse` rather than returning the model, because a custom header
    # needs the response object. The `response_model` on the decorator still
    # documents the shape in the OpenAPI schema.
    return JSONResponse(
        status_code=HTTPStatus.ACCEPTED,
        content=record.model_dump(mode="json"),
        headers={"Location": f"/documents/{record.document_id}"},
    )

@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    repository: DocumentRepositoryDep,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, gt=0, le=MAX_PAGE_SIZE),
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
    """
    rows = await repository.list_documents_with_latest_job(limit=limit)
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
