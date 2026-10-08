"""Shared fixtures.

The documents here are deliberately small and plain. Their job is to let a test
assert *which page a fact is on*, which is the one property the whole pipeline
exists to preserve and the one that cannot be retrofitted.

Nothing in this directory touches the network, an API key, or a vector store.
Those are integration concerns and the curriculum puts them at stage 1.2, when
there is a real database for the pieces to agree across.
"""

import pytest

from rag.models import Page
from tests.fixtures.pdf_builder import build_pdf, build_pdf_without_text

# A three-page document with exactly one checkable fact per page. The facts are
# distinctive strings that appear nowhere else, so "which page is this on?" has
# a single right answer that the test can state up front.
ZEPHYR_PAGES: list[list[str]] = [
    [
        "myRAG Test Document",
        "",
        "Section 1 - Project origin",
        "",
        "The Zephyr project was approved on 14 March 2021 by the",
        "steering committee. The initial budget was 4.2 million euros,",
        "allocated across three financial years.",
        "",
        "The approval followed an eighteen-month feasibility study which",
        "concluded that the existing telemetry infrastructure could not",
        "support the projected data volumes beyond 2024.",
    ],
    [
        "Section 2 - People and technology",
        "",
        "Dr. Imogen Hartley was appointed technical lead in June 2021,",
        "having previously led the Northwind migration. The reference",
        "implementation is written in Rust.",
        "",
        "The team grew to eleven engineers by the end of the first year,",
        "organised into three streams: ingestion, storage and query.",
    ],
    [
        "Section 3 - Diagnostics and delivery",
        "",
        "Error code X-4021 indicates a checksum mismatch in the telemetry",
        "stream. It is almost always caused by a truncated upload rather",
        "than by corruption at rest.",
        "",
        "Final delivery slipped to 9 November 2023, eleven months behind",
        "the original schedule.",
    ],
]

# fact -> the page it is on, counting from 1 as a human does.
ZEPHYR_FACTS: dict[str, int] = {
    "4.2 million euros": 1,
    "Imogen Hartley": 2,
    "X-4021": 3,
}


@pytest.fixture
def zephyr_pdf() -> bytes:
    """A readable three-page PDF with a known fact on each page."""
    return build_pdf(ZEPHYR_PAGES)


@pytest.fixture
def scanned_pdf() -> bytes:
    """A valid two-page PDF with no extractable text."""
    return build_pdf_without_text(page_count=2)


@pytest.fixture
def pages() -> list[Page]:
    """Pages built directly, bypassing extraction.

    Chunking tests use these rather than running a PDF through the extractor,
    so that a chunking failure cannot be caused by an extraction bug. One
    assertion, one possible cause.
    """
    return [
        Page(number=1, text="alpha " * 100),
        Page(number=2, text="beta " * 100),
        Page(number=3, text="gamma " * 100),
    ]
