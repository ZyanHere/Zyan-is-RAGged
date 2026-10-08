"""The shapes that move through the engine.

The pipeline is a sequence of transformations between these four types:

    bytes  ──extract──▶  list[Page]
           ──chunk────▶  list[Chunk]
           ──embed────▶  vectors, handed to the index
                         ▲
    question ──embed──▶  ┘ ──search──▶  list[RetrievedChunk]

**Every one of these carries its page.** That is not decoration. A page number
discarded during extraction cannot be recovered afterwards — the same sentence
may appear on several pages, whitespace and hyphenation have already been
normalised, and a chunk may straddle a boundary. Citations, the evaluation
harness in stage 3.1 (which scores retrieval against gold *pages*), and failure
attribution in 3.2 all depend on this surviving.

**Why dataclasses and not pydantic models.** Pydantic earns its cost at a trust
boundary, where untrusted input has to be validated. These types never cross
one: they are produced by this package, from data already validated at the
agent's HTTP layer. Inside the library they are plain records, and using a
dataclass says so.

All four are frozen — immutable once built. A pipeline stage returns new objects
rather than editing the ones it was handed, so a bug can never be "something
downstream changed the page number".
"""


from dataclasses import dataclass
# @dataclass automatically generates common class methods like __init__, __repr__, and __eq__ from the fields you define.

@dataclass(frozen=True, slots=True)
class Page:
    """One page of a document, as extracted.

    number:
        **1-based**, matching what a human sees when they open the PDF.
        pypdf indexes pages from 0; the conversion happens once, inside
        `extraction.py`, and nothing downstream ever adjusts it again. An
        off-by-one here makes every citation in the system quietly wrong.

    text:
        The page's text, possibly empty. An empty page is normal — a cover
        sheet, a full-page image — and is not an error on its own. It becomes
        one only when *every* page is empty, which `IngestResult` makes visible.
    """

    number: int
    text: str

@dataclass(frozen=True, slots=True)
class Chunk:
    """A slice of one page, sized for embedding.

    A chunk never spans a page break. Splitting within a page is what keeps
    `page` a single unambiguous integer for the life of the chunk, and at stage
    1.1 it costs nothing.

    document_id:
        Assigned at ingestion. Stable for this document.

    filename:
        Carried here **because there is nowhere else to put it yet.** At stage
        1.1 the vector store is the only durable record that a document exists,
        so the chunk payload has to answer "which file is this?" for a citation
        to be readable. That duplication is a real cost — the same string on
        every chunk — and it is exactly the problem stage 1.2 solves by
        introducing Postgres. Leave it visible rather than pretending otherwise.

    chunk_index:
        Position within the document, from 0. Ordering and debugging today;
        stage 2.2 uses it to build deterministic point ids.

    text:
        The chunk's own text. No vector: the embedding is *derived* from a
        chunk, it is not part of one. Keeping them apart is what lets chunking
        be tested with no embedding provider anywhere in sight.
    """

    document_id: str
    filename: str
    page: int
    chunk_index: int
    text: str

@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk returned by a search, with its similarity score.

    Composition rather than a flat copy of `Chunk`'s fields, so a chunk's shape
    is defined in exactly one place. When stage 5.1 adds `tenant_id` and stage
    4.4 adds a reranker score, each lands on the type that owns it instead of
    being duplicated across both.

    `score` belongs to the wrapper, not the chunk: it describes this
    *retrieval*. The same chunk retrieved for a different question scores
    differently, so it is not a property of the chunk at all.

    score:
        Qdrant's cosine similarity, roughly 0..1, higher is better. Only
        comparable *within* one search — it is not a confidence value and must
        not be shown to a user as one. Stage 17.3 turns scores into an
        abstention decision; until then they are for debugging.
    """

    chunk: Chunk
    score: float

@dataclass(frozen=True, slots=True)
class IngestResult:
    """What ingestion reports back to the caller.

    This is the object the agent turns into its HTTP response, and therefore
    what the backend learns about a document. It answers "what happened?" with
    numbers rather than a boolean, because at stage 1.1 the most dangerous
    outcome is not a crash — it is a scanned PDF that indexes nothing and
    reports success.

    page_count vs pages_with_text:
        The gap between these two is the diagnosis. 10 pages, 0 with text means
        a scanned document; ingestion must refuse rather than quietly index
        nothing. Stage 4.0 names this explicitly: silent garbage is the enemy.

    characters_extracted:
        Total across all pages. The crude smoke test for "did extraction
        actually work", and the baseline you compare against when a better
        extractor arrives at 4.0.
    """

    document_id: str
    filename: str
    page_count: int
    pages_with_text: int
    characters_extracted: int
    chunk_count: int