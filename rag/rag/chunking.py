"""Pages → chunks.

Fixed-size character windows with overlap. This is the naive baseline that
stage 4.1 replaces with structure-aware chunking — and replacing it is a
*measured experiment*, so the baseline has to exist first and its numbers have
to be recorded.

Two properties this module guarantees, both of which later stages depend on:

**A chunk never spans a page break.** Splitting per page keeps `page` a single
integer rather than a range, which keeps citations exact and keeps the stage 3.1
recall calculation ("was a chunk from the gold page retrieved?") a simple
equality check.

**It takes its parameters explicitly.** No `get_settings()` call anywhere in
here. That is what lets the whole module be tested with no environment, no API
key and no vector store — which is exactly the kind of test you want to be able
to run a hundred times a second.
"""

from rag.models import Chunk, Page

def chunk_pages(
    pages: list[Page],
    *,
    chunk_size: int,
    chunk_overlap: int,
    document_id: str,
    filename: str,
) -> list[Chunk]:
    """Split pages into overlapping fixed-size chunks.

    Args:
        pages: Extracted pages, in document order.
        document_id: Identity assigned at ingestion.
        filename: Carried onto every chunk because at stage 1.1 the vector
            store is the only record a document exists. Stage 1.2 moves it.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Characters each chunk repeats from the previous one.
            Overlap exists so a fact sitting on a window boundary still appears
            whole in at least one chunk. It is not free — it inflates the index
            by roughly overlap/size — and stage 4.1 tunes the tradeoff with
            evidence rather than intuition.

    Returns:
        Chunks in document order, `chunk_index` numbered from 0 across the
        whole document (not restarted per page).

    Raises:
        ValueError: if the window cannot advance, which would loop forever.
    """

    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}.")
    if chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be non-negative, got {chunk_overlap}.")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be smaller than "
            f"chunk_size ({chunk_size}); otherwise chunking cannot advance."
        )

    chunks: list[Chunk] = []
    chunk_index = 0

    for page in pages:
        text = page.text.strip()
        if not text:
            continue

        length = len(text)
        start = 0

        while start < length:
            end = min(start + chunk_size, length)
            piece = text[start:end].strip()

            if piece:
                chunks.append(
                    Chunk(
                        document_id=document_id,
                        filename=filename,
                        page=page.number,
                        chunk_index=chunk_index,
                        text=piece,
                    )
                )
                chunk_index += 1

            if end == length:
                break

            # Step back by the overlap. Guaranteed to advance by at least one
            # character because overlap < size was checked above.
            start = end - chunk_overlap

        return chunks