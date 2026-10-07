"""POST /documents — accept an upload and hand it to the agent.

**This route is honestly a pass-through**, and saying so is more useful than
dressing it up. At stage 1.1 the backend validates, forwards, and returns. It
stores nothing, because there is nothing to store it in.

That is precisely the point. Stage 1.2 puts Postgres behind this route, so a
timed-out upload leaves a visible record instead of an unknowable state. Stage
1.3 makes it return `202` and a job id. The boundary exists now so those changes
land in one place — and so the extra network hop is present when the 300-page
PDF times out, which is what makes 1.1's "next problem" real rather than
theoretical.

Routes raise domain errors; `main.py` maps them to status codes. Same shape as
the agent.
"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.errors import BackendError, UploadTooLargeError
from app.services.agent_client import ingest_document

router = APIRouter()


@router.post("/documents")
async def upload_document(file: UploadFile = File(...)) -> JSONResponse:
    """Forward a PDF to the agent for indexing."""
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
        raise BackendError("The uploaded file is empty.")

    status_code, body = await ingest_document(
        filename=file.filename or "upload.pdf",
        content=content,
        content_type=file.content_type,
    )

    return JSONResponse(status_code=status_code, content=body)