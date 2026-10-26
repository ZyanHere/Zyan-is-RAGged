"""myRAG's retrieval engine.

A library, not a service. Imported by the agent, and — from stage 3.1 — by the
evaluation harness directly, with no web server and no chat model in the path.

Public surface:

    ingest(data, document_id=..., filename=...)   index one document
    retrieve(question, top_k=...)                 find supporting chunks
    count_chunks()                                how many chunks exist
    document_chunk_counts()                       how many, per document
    delete_chunks_except(document_id, ...)        prune a document's old chunks

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
from rag.vector_store import (
    count_chunks,
    delete_chunks_except,
    document_chunk_counts,
)

__all__ = [
    # operations
    "ingest",
    "retrieve",
    "count_chunks",
    # maintenance and audit - stage 2.2
    #
    # Exported rather than reached for, because the package docstring says
    # touching `rag.vector_store` from outside means the surface is missing
    # something. `tools/qdrant_orphans.py` is the caller: it compares what the
    # store holds against what Postgres records, and deletes what belongs to
    # no document at all.
    "document_chunk_counts",
    "delete_chunks_except",
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