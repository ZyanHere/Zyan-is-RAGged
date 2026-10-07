"""The engine's two public operations.

    ingest(bytes)  →  extract  →  chunk  →  embed  →  store
    retrieve(text) →  embed    →  search

Everything above this file is orchestration; everything below is mechanism.

**`retrieve` deliberately does not generate an answer** (decision D2). It
returns evidence. Building a prompt and calling a chat model is the agent's job,
which is what keeps `rag` free of any chat-model dependency — and what lets the
stage 3.1 harness import this module and measure retrieval with no LLM anywhere
in the measurement path.

**`ingest` does not mint the document id.** Identity belongs to whoever owns the
durable record of the document, and that is not this library. At stage 1.1 the
agent generates a uuid4 and passes it down; at stage 1.2 Postgres creates the
`documents` row first — precisely so a timed-out upload leaves a visible record
— and passes that row's id down instead. Nothing in this file changes when that
happens, which is the entire point of taking it as an argument.
"""

from rag.chunking import chunk_pages
from rag.config import get_settings
from rag.errors import NoTextExtractedError
from rag.extraction import extract_pages
from rag.models import IngestResult, RetrievedChunk
from rag.providers.base import get_embedding_model
from rag.vector_store import ensure_collection, search, upsert_chunks


def ingest(data: bytes, *, document_id: str, filename: str) -> IngestResult:
    """Index one document under the caller's id, and report what happened.

    Synchronous and unbounded by design. A 300-page PDF will block this call for
    minutes — that is stage 1.1's known defect and the observed trigger for the
    async pipeline in 1.3. Do not pre-empt it.

    Args:
        data: The raw file bytes.
        document_id: Supplied by the caller, which owns the document's identity.
        filename: Original name, carried onto every chunk for citations.

    Raises:
        InvalidDocumentError: the upload is not a readable PDF.
        NoTextExtractedError: readable PDF, no text to index.
        EmbeddingError: the provider failed.
        VectorStoreError: storage failed.
    """
    settings = get_settings()

    pages = extract_pages(data, filename=filename)

    pages_with_text = sum(1 for page in pages if page.text.strip())
    characters_extracted = sum(len(page.text) for page in pages)

    # The loud failure. A scanned PDF opens perfectly and yields no text, so
    # without this check ingestion would report success having stored nothing —
    # and nobody would find out until a question about it came back empty.
    # Stage 16.2 adds OCR; until then, refusing is the honest behaviour.
    if pages_with_text == 0:
        raise NoTextExtractedError(
            f"'{filename}' has {len(pages)} pages and no extractable text. It "
            f"is almost certainly a scanned document — images of text, with no "
            f"text layer. OCR is not supported yet, so nothing was indexed."
        )

    chunks = chunk_pages(
        pages,
        document_id=document_id,
        filename=filename,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    if not chunks:
        raise NoTextExtractedError(
            f"'{filename}' produced {characters_extracted} characters across "
            f"{pages_with_text} pages but no usable chunks. Nothing was indexed."
        )

    # Before spending any embedding quota. A dimension mismatch discovered after
    # embedding 4,000 chunks costs real money and real free-tier allowance.
    ensure_collection()

    model = get_embedding_model()
    vectors = model.embed_documents([chunk.text for chunk in chunks])

    upsert_chunks(
        chunks,
        vectors,
        embedding_model=model.model_name,
        embedding_dim=model.dimensions,
    )

    return IngestResult(
        document_id=document_id,
        filename=filename,
        page_count=len(pages),
        pages_with_text=pages_with_text,
        characters_extracted=characters_extracted,
        chunk_count=len(chunks),
    )


def retrieve(question: str, *, top_k: int | None = None) -> list[RetrievedChunk]:
    """Find the chunks most similar to a question, best first.

    Returns evidence, not an answer. An empty list means either nothing is
    indexed or nothing matched — call `count_chunks()` to tell those apart, and
    only when you need to.
    """
    settings = get_settings()

    cleaned = question.strip()
    if not cleaned:
        raise ValueError("Cannot retrieve for an empty question.")

    ensure_collection()

    vector = get_embedding_model().embed_query(cleaned)
    return search(vector, top_k=top_k or settings.top_k)