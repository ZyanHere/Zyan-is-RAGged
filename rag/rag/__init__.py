"""myRAG's retrieval engine.

A library, not a service. Imported by the agent, and — from stage 3.1 — by the
evaluation harness directly, with no web server and no chat model in the path.

Public surface:

    ingest(data, document_id=..., filename=...)   index one document
    retrieve(question, top_k=...)                 find supporting chunks
    count_chunks()                                how many chunks exist

Everything else is internal. `from rag import ...` is the supported import;
reaching into `rag.vector_store` or `rag.providers` from outside this package
means the surface is missing something, and the fix is to widen it here
deliberately.
"""

from rag.errors import (
    EmbeddingError,
    IngestionError,
    InvalidDocumentError,
    NoTextExtractedError,
    RagError,
    VectorStoreError,
)
from rag.models import Chunk, IngestResult, Page, RetrievedChunk
from rag.pipeline import ingest, retrieve
from rag.vector_store import count_chunks

__all__ = [
    # operations
    "ingest",
    "retrieve",
    "count_chunks",
    # data shapes
    "Page",
    "Chunk",
    "RetrievedChunk",
    "IngestResult",
    # failures — the agent maps these to HTTP status codes
    "RagError",
    "IngestionError",
    "InvalidDocumentError",
    "NoTextExtractedError",
    "EmbeddingError",
    "VectorStoreError",
]