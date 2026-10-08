"""Chunking: pages in, chunks out.

Pure function, no configuration, no I/O — which is exactly why these tests are
cheap and why `chunk_pages` takes its parameters explicitly instead of reading
settings. Stage 4.1 replaces this strategy with a structure-aware one as a
measured experiment; these tests describe the invariants that must survive any
such replacement, not the particular algorithm.
"""

import pytest

from rag.chunking import chunk_pages
from rag.models import Page

KWARGS = {"document_id": "doc-1", "filename": "zephyr.pdf"}


def test_returns_chunks_from_every_page(pages: list[Page]) -> None:
    """Regression: `return chunks` indented inside the page loop.

    Returning from inside the loop meant only the first page was ever chunked —
    and when every page was empty, the loop fell off the end and the function
    returned None, which surfaced as `len(None)` far away from the cause.

    Two symptoms, one indentation error, both caught here.
    """
    chunks = chunk_pages(pages, chunk_size=200, chunk_overlap=40, **KWARGS)

    assert chunks is not None, "chunk_pages must always return a list"
    assert {chunk.page for chunk in chunks} == {1, 2, 3}


def test_every_chunk_carries_a_page(pages: list[Page]) -> None:
    chunks = chunk_pages(pages, chunk_size=200, chunk_overlap=40, **KWARGS)
    assert all(isinstance(chunk.page, int) and chunk.page >= 1 for chunk in chunks)


def test_a_chunk_never_spans_a_page_break() -> None:
    """The invariant that keeps `page` a single integer.

    If a chunk could straddle a boundary its page would be a range, citations
    would become approximate, and the stage 3.1 recall calculation — "was a
    chunk from the gold page retrieved?" — would stop being an equality check.
    """
    pages = [Page(number=1, text="A" * 500), Page(number=2, text="B" * 500)]
    chunks = chunk_pages(pages, chunk_size=400, chunk_overlap=50, **KWARGS)

    for chunk in chunks:
        expected = "A" if chunk.page == 1 else "B"
        assert set(chunk.text) == {expected}, "chunk mixes text from two pages"


def test_no_chunk_exceeds_the_size_limit(pages: list[Page]) -> None:
    chunks = chunk_pages(pages, chunk_size=150, chunk_overlap=30, **KWARGS)
    assert all(len(chunk.text) <= 150 for chunk in chunks)


def test_chunk_index_is_sequential_across_the_whole_document(
    pages: list[Page],
) -> None:
    """Numbered per document, not restarted per page.

    Stage 2.2 derives deterministic point ids from `(document_id, chunk_index)`,
    so a repeat would collide and silently overwrite a different chunk.
    """
    chunks = chunk_pages(pages, chunk_size=200, chunk_overlap=40, **KWARGS)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_on_a_page_overlap() -> None:
    """Overlap exists so a fact on a window boundary survives whole somewhere.

    It is not free — it inflates the index by roughly overlap/size — and stage
    4.1 tunes that tradeoff with evidence. This test only asserts it happens.
    """
    pages = [Page(number=1, text="".join(str(i % 10) for i in range(1000)))]
    chunks = chunk_pages(pages, chunk_size=300, chunk_overlap=100, **KWARGS)

    assert len(chunks) > 1
    first, second = chunks[0], chunks[1]
    assert first.text[-100:] == second.text[:100]


def test_a_page_shorter_than_the_chunk_size_yields_one_chunk() -> None:
    pages = [Page(number=1, text="short")]
    chunks = chunk_pages(pages, chunk_size=1200, chunk_overlap=180, **KWARGS)

    assert len(chunks) == 1
    assert chunks[0].text == "short"
    assert chunks[0].page == 1


def test_blank_pages_are_skipped_without_producing_empty_chunks() -> None:
    """A blank page is normal — a cover sheet, a full-page image.

    Storing a whitespace-only chunk would mean paying to embed "" and holding a
    vector that can never usefully match anything.
    """
    pages = [
        Page(number=1, text="real content here"),
        Page(number=2, text="   \n\n  "),
        Page(number=3, text="more real content"),
    ]
    chunks = chunk_pages(pages, chunk_size=100, chunk_overlap=20, **KWARGS)

    assert {chunk.page for chunk in chunks} == {1, 3}
    assert all(chunk.text.strip() for chunk in chunks)


def test_no_pages_yields_no_chunks() -> None:
    assert chunk_pages([], chunk_size=100, chunk_overlap=20, **KWARGS) == []


def test_overlap_not_smaller_than_size_is_refused() -> None:
    """Each window would start at or before the previous one — an infinite loop.

    Refusing is much better than hanging: a hung upload gives you no
    information at all about what went wrong.
    """
    with pytest.raises(ValueError, match="smaller than chunk_size"):
        chunk_pages(
            [Page(number=1, text="x" * 100)],
            chunk_size=100,
            chunk_overlap=100,
            **KWARGS,
        )


@pytest.mark.parametrize("bad_size", [0, -1])
def test_non_positive_chunk_size_is_refused(bad_size: int) -> None:
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        chunk_pages(
            [Page(number=1, text="x")],
            chunk_size=bad_size,
            chunk_overlap=0,
            **KWARGS,
        )
