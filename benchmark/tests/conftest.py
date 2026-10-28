"""Fixtures for the harness's own tests. Stage 3.1.

A temporary corpus of real PDFs with known page counts, built with `rag`'s own
`pdf_builder`. Reusing it rather than committing fixture PDFs means the page
counts these tests assert against are produced by the same `pypdf` the loader
reads them with — so a `pypdf` upgrade that changed page counting would fail
here rather than silently shift the loader's bounds check.

The `sys.path` insertion is the pattern `tools/capacity_probe.py` already
uses to reach the same module. It is ugly and it is the established way in
this repository to borrow a test fixture across packages.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "rag"))

from tests.fixtures.pdf_builder import build_pdf  # noqa: E402

# Page counts the loader's bounds check is asserted against.
SHORT_PAGES = 3
LONG_PAGES = 5

SHORT = "short.pdf"
LONG = "long.pdf"


@pytest.fixture
def corpus(tmp_path: pathlib.Path) -> pathlib.Path:
    """A documents directory holding two PDFs of known length."""
    documents = tmp_path / "documents"
    documents.mkdir()

    (documents / SHORT).write_bytes(
        build_pdf([[f"short page {n}"] for n in range(1, SHORT_PAGES + 1)])
    )
    (documents / LONG).write_bytes(
        build_pdf([[f"long page {n}"] for n in range(1, LONG_PAGES + 1)])
    )

    return documents


@pytest.fixture
def write_questions(tmp_path: pathlib.Path):
    """Write a question CSV from rows, returning its path.

    Rows are given as whole lines so a test can write a *malformed* file —
    which is most of what the loader's tests are about, and which a
    dict-of-fields helper would quietly correct.
    """
    from benchmark.loader import COLUMNS

    def write(*lines: str, header: str | None = None) -> pathlib.Path:
        path = tmp_path / "questions.csv"
        body = "\n".join([header if header is not None else ",".join(COLUMNS), *lines])
        path.write_text(body + "\n", encoding="utf-8")
        return path

    return write
