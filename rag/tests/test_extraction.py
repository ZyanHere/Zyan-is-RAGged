"""Extraction: PDF bytes in, pages out.

The assertions that matter here are about *page numbers*, not about text
quality. Extraction quality is stage 4.0's subject and needs the evaluation
harness to judge it. What stage 1.1 must guarantee is that the page a piece of
text came from survives, because that is the one thing no later stage can
reconstruct.
"""

import pytest

from rag.errors import InvalidDocumentError
from rag.extraction import extract_pages
from tests.conftest import ZEPHYR_FACTS


def test_page_count_matches_the_document(zephyr_pdf: bytes) -> None:
    pages = extract_pages(zephyr_pdf, filename="zephyr.pdf")
    assert len(pages) == 3


def test_page_numbers_are_one_based_and_sequential(zephyr_pdf: bytes) -> None:
    """The single most consequential line in the module.

    pypdf counts pages from 0; a human opening the PDF counts from 1. If the
    conversion is wrong, every citation in the system is off by one and every
    one of them looks entirely plausible.
    """
    pages = extract_pages(zephyr_pdf, filename="zephyr.pdf")
    assert [page.number for page in pages] == [1, 2, 3]


@pytest.mark.parametrize(("fact", "expected_page"), sorted(ZEPHYR_FACTS.items()))
def test_each_fact_is_extracted_onto_its_own_page(
    zephyr_pdf: bytes, fact: str, expected_page: int
) -> None:
    """Provenance, end to end through extraction."""
    pages = extract_pages(zephyr_pdf, filename="zephyr.pdf")
    pages_containing = [page.number for page in pages if fact in page.text]
    assert pages_containing == [expected_page]


def test_pages_with_text_are_not_silently_empty(zephyr_pdf: bytes) -> None:
    """Regression: the `pdf_pagees` typo.

    A misspelled loop variable raised NameError on every page, and the broad
    `except Exception` turned that programming bug into "this page has no
    text". Every page came back empty, ingestion reported success, and nothing
    anywhere complained.

    This test fails loudly on any future recurrence — including a different
    exception being swallowed by the same handler.
    """
    pages = extract_pages(zephyr_pdf, filename="zephyr.pdf")
    assert all(page.text.strip() for page in pages), (
        "every page of this document has text; an empty one means extraction "
        "failed silently"
    )


def test_a_pdf_without_text_yields_empty_pages_rather_than_raising(
    scanned_pdf: bytes,
) -> None:
    """Extraction reports; the pipeline decides.

    A scanned document is not malformed, so extraction has nothing to complain
    about. Whether "no text anywhere" is an error is a policy question, and
    policy lives in `pipeline.ingest`. Keeping the split means a future OCR
    fallback at stage 16.2 slots in at the pipeline without touching this file.
    """
    pages = extract_pages(scanned_pdf, filename="scanned.pdf")
    assert len(pages) == 2
    assert all(page.text == "" for page in pages)


def test_rejects_empty_bytes() -> None:
    with pytest.raises(InvalidDocumentError, match="empty"):
        extract_pages(b"", filename="nothing.pdf")


def test_rejects_a_file_that_is_not_a_pdf() -> None:
    """The message must name the real problem.

    "Invalid document" tells the person uploading nothing. Naming the bytes
    found tells them they uploaded the wrong file.
    """
    with pytest.raises(InvalidDocumentError, match="not a PDF"):
        extract_pages(b"just some notes, not a pdf", filename="notes.txt")


def test_rejects_a_truncated_pdf(zephyr_pdf: bytes) -> None:
    """Correct header, damaged body — the extension and magic bytes both lie."""
    with pytest.raises(InvalidDocumentError):
        extract_pages(zephyr_pdf[:200], filename="truncated.pdf")


def test_normalisation_removes_trailing_space_and_blank_line_runs() -> None:
    """Whitespace only — never content.

    Collapsing blank lines saves chunk budget and makes chunk text readable
    when you are debugging a bad citation. Removing headers or boilerplate
    would be a content decision, and that belongs to stage 4.0 where the
    evaluation harness can say whether it helped.
    """
    from rag.extraction import _normalise

    assert _normalise("a   \nb\n\n\n\nc\n   ") == "a\nb\n\nc"
