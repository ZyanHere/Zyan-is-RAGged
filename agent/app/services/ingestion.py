"""Document ingestion, agent-side.

Thin on purpose. It owns three things the engine should not: minting the
document id, choosing what the HTTP response says, and being the place where
stage 1.2's "record the attempt before starting" and 1.3's "hand this to a
queue" will land without touching a route or the engine.

The id is generated here because at stage 1.1 the agent is the outermost thing
that knows a document exists. At 1.2 the backend will create a Postgres row
first and pass its id in, and this function becomes a pass-through for it —
which is exactly why `rag.ingest` takes the id as an argument.
"""

import uuid

import rag
from app.schemas.documents import IngestResponse


def ingest_upload(data: bytes, *, filename: str) -> IngestResponse:
    """Index an uploaded file and describe what happened."""
    document_id = str(uuid.uuid4())

    result = rag.ingest(data, document_id=document_id, filename=filename)

    return IngestResponse(
        document_id=result.document_id,
        filename=result.filename,
        page_count=result.page_count,
        pages_with_text=result.pages_with_text,
        characters_extracted=result.characters_extracted,
        chunk_count=result.chunk_count,
    )