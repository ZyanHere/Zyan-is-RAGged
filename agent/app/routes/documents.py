"""POST /documents — index one PDF, synchronously.

**This handler is `def`, not `async def`, and that is deliberate.**

`rag.ingest` is synchronous and slow: it reads a PDF, calls an embedding API
several times, and writes to disk. Calling it inside an `async def` handler
would block the event loop for the entire duration — every other request to this
process, including `/health`, would sit and wait behind it.

FastAPI runs a plain `def` handler in a worker thread instead, so the event loop
stays free. That thread pool is bounded (40 by default), which is a real limit
and a real future trigger: enough concurrent uploads will exhaust it, and that
observation is part of what earns the queue at stage 1.3.
"""

from fastapi import APIRouter, File, UploadFile

from app.core.config import get_settings
from app.errors import UploadTooLargeError
from app.schemas.documents import IngestResponse
from app.services.ingestion import ingest_upload

router = APIRouter()


@router.post("/documents", response_model=IngestResponse)
def ingest_document(file: UploadFile = File(...)) -> IngestResponse:
    """Extract, chunk, embed and index one PDF.

    Blocks until the whole document is indexed. A 300-page PDF will hold this
    request open for minutes and time out the browser — the known defect of
    stage 1.1, and the trigger for 1.2 and 1.3. It is left in place on purpose.

    Failures are translated to status codes by the exception handlers in
    `main.py`, so there is no try/except here.
    """
    settings = get_settings()

    # `file.file` is the underlying synchronous file object — in an `async def`
    # handler you would `await file.read()`.
    #
    # Reading one byte past the limit is how the limit actually protects
    # anything: read the whole file first and then measure it, and a 2 GB upload
    # has already cost 2 GB of memory by the time you reject it.
    data = file.file.read(settings.max_upload_bytes + 1)

    if len(data) > settings.max_upload_bytes:
        raise UploadTooLargeError(
            f"'{file.filename}' exceeds the maximum upload size of "
            f"{settings.max_upload_bytes // (1024 * 1024)} MB."
        )

    return ingest_upload(data, filename=file.filename or "upload.pdf")