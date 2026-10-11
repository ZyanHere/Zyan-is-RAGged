"""Document ingestion, agent-side.

Thin on purpose. It owns three things the engine should not: minting the
document id, choosing what the HTTP response says, and being the place where
stage 1.2's "record the attempt before starting" and 1.3's "hand this to a
queue" will land without touching a route or the engine.

── Who owns the document id (stage 1.2) ────────────────────────────────────

The caller supplies it, and the agent mints one only when nobody did.

That inversion is forced by the ordering the backend has to guarantee:

    create the document row  →  COMMIT  →  call the agent  →  record the outcome

The commit happens *before* this function runs, so the id has to exist before
this function runs. If the agent minted it, the backend would have no id to
commit, and the whole point of the stage — a durable record written before the
work starts — would be impossible.

The fallback is kept so the agent remains testable on its own. `curl -F
file=@x.pdf localhost:8001/documents` still works with no backend involved,
which is how you tell an agent problem from a backend one.
"""

import uuid

import rag
from app.schemas.documents import IngestResponse


def ingest_upload(
    data: bytes, *, filename: str, document_id: str | None = None
) -> IngestResponse:
    """Index an uploaded file and describe what happened.

    Args:
        document_id: The caller's id, already durable on their side. When
            absent the agent mints one — see the module docstring for why that
            is a fallback rather than the normal path.
    """
    result = rag.ingest(
        data,
        document_id=document_id or str(uuid.uuid4()),
        filename=filename,
    )

    return IngestResponse(
        document_id=result.document_id,
        filename=result.filename,
        page_count=result.page_count,
        pages_with_text=result.pages_with_text,
        characters_extracted=result.characters_extracted,
        chunk_count=result.chunk_count,
    )