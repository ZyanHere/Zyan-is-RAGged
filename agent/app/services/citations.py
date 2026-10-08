"""Citation markers: assign, render, resolve.

The three functions here are one concern, not three. `build_context` assigns a
marker to each chunk; `extract_citations` resolves the markers the model wrote
back to documents and pages; `to_sources` exposes the same numbering to the
client. **They must agree, and keeping them in one file is what enforces that.**
If marker assignment lived next to the prompt and resolution lived next to the
HTTP response, a change to one would compile perfectly while making every
citation in the system point at the wrong page — a failure that looks entirely
plausible from the outside.

This is also the module stages 17.2 (verifying a cited span actually supports
its claim) and 17.5 (surfacing contradictions between sources) grow into.
"""

import logging
import re

from app.prompts.answer import EXCERPT_TEMPLATE
from app.schemas.query import Citation, SourceChunk
from rag import RetrievedChunk

logger = logging.getLogger(__name__)

# Matches [1], [12] — the markers the prompt asks the model to write.
_MARKER = re.compile(r"\[(\d+)\]")


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Number the chunks and format them for the prompt.

    Markers are 1-based because that is how the model is asked to write them,
    and because a human reading `[0]` in an answer will assume it is a bug.

    Order is retrieval order — best match first. Stage 4.6 revisits that:
    models attend less well to the middle of a long context, so "strongest
    evidence first *and last*" turns out to beat plain descending order. That is
    a measured change and it needs the evaluation harness first.
    """
    return "\n\n".join(
        EXCERPT_TEMPLATE.format(
            marker=marker,
            filename=retrieved.chunk.filename,
            page=retrieved.chunk.page,
            text=retrieved.chunk.text,
        )
        for marker, retrieved in enumerate(chunks, start=1)
    )


def extract_citations(answer: str, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Resolve the `[n]` markers in an answer back to documents and pages.

    Only markers that exist are returned. A model can write `[9]` when it was
    given four excerpts, and turning that into a citation would fabricate a
    source — the exact failure this whole design exists to prevent.

    Out-of-range markers are logged rather than dropped silently: in a system
    whose entire premise is provenance, a model inventing citations is a signal
    worth seeing, even before stage 17.2 turns it into a measured metric.

    Returned in order of first appearance, deduplicated, so the list reads in
    the same order as the answer.
    """
    citations: list[Citation] = []
    seen: set[int] = set()

    for match in _MARKER.finditer(answer):
        marker = int(match.group(1))
        if marker in seen:
            continue
        seen.add(marker)

        if not 1 <= marker <= len(chunks):
            logger.warning(
                "model cited [%d] but only %d excerpts were supplied; dropping",
                marker,
                len(chunks),
            )
            continue

        chunk = chunks[marker - 1].chunk
        citations.append(
            Citation(
                marker=marker,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page=chunk.page,
            )
        )

    return citations


def to_sources(chunks: list[RetrievedChunk]) -> list[SourceChunk]:
    """Everything that was shown to the model, cited or not.

    Same numbering as `build_context`, which is why it belongs in this file.
    """
    return [
        SourceChunk(
            marker=marker,
            document_id=retrieved.chunk.document_id,
            filename=retrieved.chunk.filename,
            page=retrieved.chunk.page,
            # The score lives on the wrapper, not the chunk: it describes this
            # *retrieval*, not the chunk itself. The same chunk retrieved for a
            # different question scores differently.
            score=retrieved.score,
            text=retrieved.chunk.text,
        )
        for marker, retrieved in enumerate(chunks, start=1)
    ]