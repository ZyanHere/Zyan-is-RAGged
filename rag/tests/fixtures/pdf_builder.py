"""Build PDFs in memory, with no third-party dependency.

**Why generate rather than commit binary fixtures.** A committed PDF is opaque:
you cannot read a diff of it, you cannot see which page a fact is on without
opening it, and when a test fails you cannot tell whether the document or the
code changed. Generating from a list of strings means the fixture's content is
visible in the test that uses it, and the page a fact lives on is a fact about
the source code rather than about a blob.

It also avoids reportlab — a large dependency to add to a library that
otherwise needs only pypdf to read PDFs, not write them.

This produces deliberately plain documents: single column, no tables, no
headers, no images. That is correct for *unit tests*, which check that page
numbers survive the pipeline. It is emphatically not an evaluation corpus —
stage 3.1 needs real documents with real layout problems, and measuring
retrieval against synthetic text this clean would produce flattering numbers
that mean nothing.
"""


def _escape(text: str) -> str:
    """Escape the three characters that are syntax inside a PDF string."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    """Lay out one page's lines as PDF text-drawing operators.

    `BT`/`ET` open and close a text object, `Tf` picks the font and size, `TL`
    sets the line leading, `Td` positions the cursor, `Tj` draws a string and
    `T*` advances a line.
    """
    out = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
    for line in lines:
        out.append(f"({_escape(line)}) Tj")
        out.append("T*")
    out.append("ET")
    return "\n".join(out).encode("latin-1")


def _assemble(objects: list[bytes]) -> bytes:
    """Serialise objects and append a cross-reference table.

    The xref table maps each object number to its byte offset in the file, so
    it can only be written once every object's position is known — which is why
    this is a second pass rather than part of building the objects.
    """
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []

    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()

    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def build_pdf(pages: list[list[str]]) -> bytes:
    """A PDF whose pages contain exactly the lines given, in order.

    Args:
        pages: One list of lines per page.
    """
    # Objects 1 and 2 are the catalog and the page tree. They reference objects
    # created below, so they are reserved here and filled in at the end.
    objects: list[bytes] = [b"", b""]

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    content_numbers = []
    for lines in pages:
        stream = _content_stream(lines)
        content_numbers.append(
            add(
                b"<< /Length "
                + str(len(stream)).encode()
                + b" >>\nstream\n"
                + stream
                + b"\nendstream"
            )
        )

    font_number = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    page_numbers = [
        add(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
            + str(contents).encode()
            + b" 0 R /Resources << /Font << /F1 "
            + str(font_number).encode()
            + b" 0 R >> >> >>"
        )
        for contents in content_numbers
    ]

    kids = b" ".join(str(n).encode() + b" 0 R" for n in page_numbers)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids ["
        + kids
        + b"] /Count "
        + str(len(page_numbers)).encode()
        + b" >>"
    )

    return _assemble(objects)


def build_pdf_without_text(page_count: int = 2) -> bytes:
    """A structurally valid PDF whose pages have no text operators at all.

    This is what a scanned document looks like to a text extractor: it opens
    cleanly, reports the right page count, and yields nothing. The most
    dangerous input in the system, because every naive check passes.
    """
    objects: list[bytes] = [b"", b""]

    page_numbers = []
    for _ in range(page_count):
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>")
        page_numbers.append(len(objects))

    kids = b" ".join(str(n).encode() + b" 0 R" for n in page_numbers)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids ["
        + kids
        + b"] /Count "
        + str(page_count).encode()
        + b" >>"
    )

    return _assemble(objects)
