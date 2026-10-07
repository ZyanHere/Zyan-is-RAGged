"""HTTP shapes for POST /documents.

Deliberately not `rag`'s dataclasses. Those are internal records; these are a
contract with the backend. Keeping them apart means adding a field to a `Chunk`
for debugging does not silently change the public API.

The cost is a mapping step. It lives in `services/ingestion.py`, not here and
not in the route — a schema that imports the engine's types to map itself would
give back exactly the coupling this separation buys.
"""

from pydantic import BaseModel


class IngestResponse(BaseModel):
    """What POST /documents returns.

    Numbers rather than a boolean, because at stage 1.1 the dangerous outcome
    is not a crash — it is a document that reports success having indexed
    nothing. The gap between `page_count` and `pages_with_text` is the tell.
    """

    document_id: str
    filename: str
    page_count: int
    pages_with_text: int
    characters_extracted: int
    chunk_count: int