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

**Measured at stage 2.5, and the prediction holds exactly.** With a calibrated
3.2-second embed delay:

    N=10   wall  5.56s   response p50 1.954s
    N=40   wall  4.02s   response p50 3.937s    one wave
    N=60   wall  7.98s   response p50 4.432s    p95 7.884s — two waves

The knee is at 40. The queue at 1.3 was built on this claim and nobody checked
it for four stages.

**What the same measurement found that this docstring did not predict:** "the
event loop stays free" is true and was not sufficient. `/health` is *also* a
plain `def`, so it shared this pool and went from 8 ms to 3508 ms under the
load — a liveness check starved by the thing it was supposed to report on. It
is `async def` now. See `docs/experiments/0006-…`.

This route stays `def`, and that is the other half of the rule: **a route that
blocks belongs on a thread; a route that does no I/O belongs on the loop.**
"""

from fastapi import APIRouter, File, Form, UploadFile

from app.core.config import get_settings
from app.errors import UploadTooLargeError
from app.schemas.documents import IngestResponse
from app.services.ingestion import ingest_upload

router = APIRouter()


@router.post("/documents", response_model=IngestResponse)
def ingest_document(
    file: UploadFile = File(...),
    document_id: str | None = Form(default=None),
) -> IngestResponse:
    """Extract, chunk, embed and index one PDF.

    Blocks until the whole document is indexed. A 300-page PDF will hold this
    request open for minutes and time out the browser — the known defect of
    stage 1.1, and the trigger for 1.2 and 1.3. It is left in place on purpose.

    Failures are translated to status codes by the exception handlers in
    `main.py`, so there is no try/except here.

    `document_id` is an optional multipart field, not a path or query
    parameter, because it travels with the file in the same request. The
    backend sends the id it has already committed; a direct `curl` omits it and
    the agent mints one, which keeps the agent independently testable.
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

    return ingest_upload(
        data,
        filename=file.filename or "upload.pdf",
        document_id=document_id,
    )