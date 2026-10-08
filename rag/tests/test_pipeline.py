"""Pipeline: the parts that can be tested without a network.

`ingest` ends in an embedding call and a vector write, so the happy path is an
integration test and belongs at stage 1.2 when there is a real datastore for
the pieces to agree across. What is unit-testable now is everything the
pipeline decides *before* it reaches a provider — and that turns out to be
where today's subtlest bug lived.
"""

import pytest

from rag import pipeline
from rag.errors import InvalidDocumentError, NoTextExtractedError


def _explode() -> None:
    raise AssertionError(
        "configuration was read before the input had been validated"
    )


def test_a_non_pdf_is_rejected_before_configuration_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: `ingest` called `get_settings()` on its first line.

    A missing GOOGLE_API_KEY therefore raised a pydantic ValidationError before
    extraction ever ran, so *every* bad-input error came back as an opaque 500
    about configuration. "This is not a PDF" was unreachable whenever the
    embedding config was incomplete.

    The two concerns are genuinely independent: judging the input is not the
    embedder's business. Replacing `get_settings` with something that raises
    proves the ordering directly, with no environment manipulation.
    """
    monkeypatch.setattr(pipeline, "get_settings", _explode)

    with pytest.raises(InvalidDocumentError, match="not a PDF"):
        pipeline.ingest(
            b"just some notes", document_id="doc-1", filename="notes.txt"
        )


def test_an_empty_upload_is_rejected_before_configuration_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "get_settings", _explode)

    with pytest.raises(InvalidDocumentError, match="empty"):
        pipeline.ingest(b"", document_id="doc-1", filename="nothing.pdf")


def test_a_scanned_pdf_is_refused_before_configuration_is_read(
    monkeypatch: pytest.MonkeyPatch, scanned_pdf: bytes
) -> None:
    """The loud failure, and it must not depend on a working embedder either.

    A scanned PDF opens cleanly and yields nothing. Without this refusal,
    ingestion would report success having stored nothing, and nobody would find
    out until a question about the document came back empty. OCR arrives at
    stage 16.2; until then refusing is the honest behaviour.
    """
    monkeypatch.setattr(pipeline, "get_settings", _explode)

    with pytest.raises(NoTextExtractedError, match="no extractable text"):
        pipeline.ingest(
            scanned_pdf, document_id="doc-1", filename="scanned.pdf"
        )


def test_retrieve_refuses_an_empty_question() -> None:
    """Caught before anything is spent.

    An empty question would otherwise cost an embedding call to learn nothing,
    and on a free tier that quota is finite.
    """
    with pytest.raises(ValueError, match="empty question"):
        pipeline.retrieve("   ")
