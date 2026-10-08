"""PDF bytes → pages of text.

The single rule of this module: it returns `list[Page]`, never one joined
string. Joining is where page numbers die, and they cannot be recovered
afterwards — see the module docstring in `models.py`.

Extraction here is deliberately naive. pypdf emits text in the order the PDF
draws it, which for a two-column layout interleaves the columns into nonsense.
That is a known defect, it is stage 4.0's problem, and fixing it now would mean
tuning an extractor before the evaluation harness exists to say whether the
tuning helped. What this module *must* do today is fail loudly rather than
silently returning garbage.
"""

import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from rag.errors import InvalidDocumentError
from rag.models import Page

# Every PDF begins with these bytes. Checking them is cheap and catches the
# common case — a .png or .docx renamed to .pdf — with a message that names the
# actual problem, instead of a pypdf stack trace.


_PDF_MAGIC = b"%PDF-"   #Checks the first bytes of the uploaded file.

_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def extract_pages(data:bytes, *, filename:str) -> list[Page ]:
    """Read a PDF and return its pages, numbered from 1.

    Takes bytes rather than a path on purpose: the agent receives an upload in
    memory, and a library that insists on a filesystem forces every caller —
    including every test — to write a temp file first.

    Raises:
        InvalidDocumentError: empty, not a PDF, corrupt, or password-protected.
    """
    if not data:
        raise InvalidDocumentError(f"'{filename}' is empty (0 bytes).")

    if not data.startswith(_PDF_MAGIC):
        raise InvalidDocumentError(
            f"'{filename}' is not a PDF. It starts with {data[:8]!r}, and every "
            f"PDF must start with {_PDF_MAGIC!r}. Only PDF uploads are "
            f"supported at this stage."
        )

    try:
        reader = PdfReader(BytesIO(data))
    except PdfReadError as exc:
        raise InvalidDocumentError(
            f"'{filename}' is not a valid PDF: {exc}. It may be truncated, "
            f"corrupt, or password-protected. Only valid PDFs are supported at "
            f"this stage."
        ) from exc
    except Exception as exc:
        # pypdf raises a wide and undocumented range of exceptions on malformed
        # input. Catching broadly here is deliberate: the caller's contract is
        # "bad file gives InvalidDocumentError", and letting a raw
        # struct.error or KeyError escape would break that contract for no gain.
        raise InvalidDocumentError(
            f"'{filename}' could not be read as a PDF: {exc}"
        ) from exc

    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except Exception as exc:
            raise InvalidDocumentError(
                f"'{filename}' is password-protected and cannot be opened: {exc}"
            ) from exc
        if not opened:
            raise InvalidDocumentError(
                f"'{filename}' is password-protected. Remove the password and "
                f"upload it again."
            )

    pages: list[Page] = []
    for zero_based_index, pdf_page in enumerate(reader.pages):
        try: 
            raw = pdf_page.extract_text() or ""
        except Exception :
            # One unreadable page must not lose the other 299. Record it as
            # empty; `pages_with_text` in IngestResult makes the loss visible.
            raw = ""
        pages.append(
            Page(
                # +1 is the whole conversion. pypdf counts from 0; a human
                # opening the PDF counts from 1. Doing this once, here, is why
                # nothing downstream ever has to think about it again.
                number=zero_based_index + 1,
                text=_normalise(raw),
            )
        )

    if not pages:
        raise InvalidDocumentError(f"'{filename}' opened but contains no pages.")

    return pages


def _normalise(text: str) -> str:
    """Tidy extracted text without changing what it says.

    Only whitespace: pypdf scatters trailing spaces and long runs of blank
    lines through its output, which waste chunk budget and make chunk text
    unpleasant to read when you are debugging a bad citation.

    Nothing here removes headers, footers or repeated boilerplate — that is a
    content decision, it belongs to stage 4.0, and it should be driven by
    failures the evaluation harness actually attributes to extraction.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("\n", text)
    text = _EXCESS_BLANK_LINES.sub("\n\n", text)
    return text.strip()