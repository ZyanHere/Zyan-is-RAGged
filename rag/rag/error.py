"""Everything `rag` can raise.

One hierarchy, in one file, for two reasons.

**Callers catch categories, not modules.** The agent should be able to say "any
ingestion failure caused by the uploaded file is a 4xx" without importing from
extraction, chunking and indexing separately, and without knowing which of them
happened to raise.

**The HTTP mapping becomes a table.** The agent's route layer translates these
into status codes, and that translation is easier to get right — and to review —
when the full set is visible at once:

    InvalidDocumentError   →  400  the upload is not something we can read
    NoTextExtractedError   →  422  readable file, nothing in it to index
    EmbeddingError         →  502  an upstream provider failed us
    VectorStoreError       →  500  our own storage failed

Note what is *not* here: no retry logic, no transient/permanent classification,
no error codes. Stage 2.3 introduces that distinction when the dead-letter queue
needs it — driven by failures you have actually observed. Adding it now would be
guessing at which errors are worth retrying before anything has retried.
"""


class RagError(Exception):
    """Base class for every failure raised by this package.

    Catching this catches everything from the engine and nothing from anywhere
    else — so a caller can distinguish "the engine failed" from "our own code
    has a bug" without a bare `except Exception`.
    """


# ── Ingestion ─────────────────────────────────────────────────────────────────


class IngestionError(RagError):
    """A document could not be turned into indexed chunks."""


class InvalidDocumentError(IngestionError):
    """The uploaded bytes are not a PDF we can open.

    Covers an empty upload, a file that is not a PDF at all, a truncated or
    corrupt PDF, and a password-protected one. All four are the caller's
    problem, not ours, which is why they share a type and a 400.

    The message must name which of those it was. "Invalid document" tells the
    person uploading nothing; "file is password-protected" tells them what to
    do next.
    """


class NoTextExtractedError(IngestionError):
    """The PDF opened cleanly and yielded no usable text.

    Almost always a scanned document: pages of images with no text layer. The
    file is perfectly valid, so this is not a 400 — but indexing it would store
    nothing while reporting success, which is the single worst outcome at this
    stage. Stage 4.0 puts it plainly: silent garbage is the enemy.

    OCR is the eventual fix and it arrives at stage 16.2. Until then the correct
    behaviour is to refuse loudly and say why.
    """


# ── Providers ─────────────────────────────────────────────────────────────────


class EmbeddingError(RagError):
    """An embedding provider could not produce vectors.

    Vendor exceptions are translated into this inside `providers/`, so nothing
    outside that package imports an SDK's error classes — the same rule the
    agent's `ProviderError` already follows for chat models.

    Today this covers everything: a dead key, a rate limit, a timeout, a network
    failure. They demand different responses, and telling them apart is what
    stages 7.1 and 7.2 are for. Splitting the type before then would be writing
    the retry policy before observing a single retry.
    """


# ── Storage ───────────────────────────────────────────────────────────────────


class VectorStoreError(RagError):
    """The vector store could not be reached, written to, or read from.

    Named `VectorStoreError` rather than anything shorter because `IndexError`
    is a Python builtin, and shadowing it inside this package would make
    ordinary list-bounds bugs catchable by code meant to handle storage
    failures — a genuinely nasty class of silent bug.

    This is a 500, not a 502: Qdrant is *our* infrastructure, not a third party.
    The distinction matters when you start reading error rates and asking whose
    fault an outage was.
    """