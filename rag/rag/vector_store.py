"""The vector store.

Every Qdrant call in the system is in this file. It owns three things: making
sure the collection exists and is the right shape, writing chunks with their
provenance, and searching.

**Embedded mode.** Qdrant runs as a library writing to a local folder
(`QDRANT_PATH`), so stage 1.1 needs no Docker — Docker arrives at 1.2 because
Postgres needs it. The constraint that comes with it: **only one process may
hold that folder open.** That is fine while the agent is the only writer. It
stops being fine at stage 1.3, when a separate worker process appears, and that
is a real trigger rather than a design flaw — set `QDRANT_URL` at that point and
this file needs no other change.

**`qdrant_client` is imported inside functions, not at module scope.** That is
unusual enough to need a reason: the vendor library pulls in gRPC, which ships
a large compiled binary, and importing it at module level makes `import rag`
depend on that binary loading successfully. Anything that touches `rag` at all
— the chunking unit tests, the extraction unit tests, the evaluation harness at
stage 3.1 — then fails for a reason that has nothing to do with vectors.

Deferring the import means the dependency is paid for only by the code that
genuinely needs a vector store, and the failure, when it comes, names the
operation that caused it. It is the same pattern `agent/app/providers/base.py`
already uses for chat providers.

**Point ids were random** (decision D3), and stage 2.2 made them
deterministic — see `_point_id`. The randomness was deliberate and it paid off:
by the time this changed there was a real doubly-indexed document in the store
to measure, with each `chunk_index` present twice under two different ids. A
stage whose trigger you have quietly prevented is a stage you cannot learn
from, and the evidence is in `docs/experiments/0002-stage-2-2-baseline-audit.md`.
"""

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING

from rag.config import get_settings
from rag.errors import VectorStoreError
from rag.models import Chunk, RetrievedChunk

if TYPE_CHECKING:
    # Type-checking only: this branch never runs, so the annotations below cost
    # nothing at import time.
    from qdrant_client import QdrantClient

# Points per upsert call. Large enough that a 300-page document is a handful of
# round trips, small enough that one failure does not lose everything.
_UPSERT_BATCH = 256

# Points per scroll page. Smaller than the upsert batch because each page is
# held in memory while its payloads are counted, and nothing here benefits from
# fewer, larger round trips.
_SCROLL_BATCH = 256

_POINT_NAMESPACE = uuid.UUID("0ccb9ba8-58c7-4d5e-9367-101281c98bea")
"""The namespace every point id is derived in. Generated once; never changes.

Changing this value orphans every point already written, because nothing would
compute the old ids again. It is therefore as sticky as `EMBEDDING_DIM` and
belongs in the source rather than in configuration, where it could be changed
by someone who did not know that.
"""


def _point_id(document_id: str, chunk_index: int) -> str:
    """The id for one chunk of one document. Same inputs, same id, forever.

    ── Why this is the whole of stage 2.2's engine half ───────────────────────

    `uuid.uuid4()` was here before, so a second ingestion of the same document
    wrote a second, disjoint set of points: the same text, the same page, new
    ids, nothing overwritten. At-least-once delivery arrived at 2.1 and turned
    that into a measured corruption — one document holding six points where
    three belong, with each `chunk_index` present twice.

    A deterministic id makes a re-ingestion an **overwrite** rather than an
    append, which is what `upsert` already meant and could not do without it.

    ── Why a fixed namespace and the id in the name ──────────────────────────

    The obvious spelling is `uuid5(uuid.UUID(document_id), str(chunk_index))`,
    making each document its own namespace. It crashes: `document_id` is a
    `str` and has never been required to be a UUID. `rag/tests/test_pipeline.py`
    passes `"doc-1"`, and the module docstring in `pipeline.py` is explicit
    that identity belongs to whoever owns the durable record — not to this
    library.

    Tightening that contract to "must be a parseable UUID" so the id scheme
    could be prettier would be the engine taking back a decision it
    deliberately delegated. So the namespace is a constant and the document id
    is part of the name.

    ── Why `:` is a safe separator ──────────────────────────────────────────

    `f"{document_id}:{chunk_index}"` must not be ambiguous — two different
    (document, index) pairs producing one string would silently collide and
    one chunk would overwrite another. Since `chunk_index` is always an
    integer, the final `:` is unambiguous no matter what the document id
    contains: everything after the last colon is the index, everything before
    it is the id.
    """
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{document_id}:{chunk_index}"))


@lru_cache
def get_client() -> "QdrantClient":
    """Open the vector store once and reuse it.

    Cached because in embedded mode the client holds a lock on the storage
    folder — opening a second one in the same process fails outright.
    """
    from qdrant_client import QdrantClient

    settings = get_settings()
    try:
        if settings.qdrant_url:
            return QdrantClient(url=settings.qdrant_url)

        settings.qdrant_path.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(settings.qdrant_path))
    except Exception as exc:
        raise VectorStoreError(
            f"Could not open the vector store at "
            f"{settings.qdrant_url or settings.qdrant_path}: {exc}. In embedded "
            f"mode this usually means another process already has the folder "
            f"open."
        ) from exc


def ensure_collection() -> None:
    """Create the collection if missing, and verify its shape if present.

    The dimension check is the important half. Change EMBEDDING_MODEL or
    EMBEDDING_DIM against an existing index and every search either errors or —
    worse, if the dimensions happen to match — returns confident nonsense,
    because the stored vectors came from a different model and share no
    coordinate system with the new ones.

    Decision 0002 calls this the stickiest decision in the system: changing it
    is a migration, not a config edit. This is the check that makes the mistake
    loud instead of silent.
    """
    from qdrant_client import models as qmodels

    settings = get_settings()
    client = get_client()

    try:
        if not client.collection_exists(settings.qdrant_collection):
            client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(
                    size=settings.embedding_dim,
                    # Cosine: compares direction, ignores magnitude. The right
                    # choice for text embeddings, where "how long is the
                    # vector" carries no meaning.
                    distance=qmodels.Distance.COSINE,
                ),
            )
            return

        info = client.get_collection(settings.qdrant_collection)
        vectors_config = info.config.params.vectors
    except VectorStoreError:
        raise
    except Exception as exc:
        raise VectorStoreError(
            f"Could not inspect collection '{settings.qdrant_collection}': {exc}"
        ) from exc

    if not isinstance(vectors_config, qmodels.VectorParams):
        raise VectorStoreError(
            f"Collection '{settings.qdrant_collection}' uses named vectors, "
            f"which this engine does not. Delete it or point "
            f"QDRANT_COLLECTION at a different name."
        )

    if vectors_config.size != settings.embedding_dim:
        raise VectorStoreError(
            f"Collection '{settings.qdrant_collection}' stores "
            f"{vectors_config.size}-dimension vectors but EMBEDDING_DIM is "
            f"{settings.embedding_dim}. These vectors were produced by a "
            f"different model and cannot be compared. Either restore the "
            f"previous setting, or delete the collection and re-ingest every "
            f"document. See docs/decisions/0002-embedding-provider.md."
        )


def upsert_chunks(
    chunks: list[Chunk],
    vectors: list[list[float]],
    *,
    embedding_model: str,
    embedding_dim: int,
) -> list[str]:
    """Write chunks and their vectors to the collection.

    `strict=True` on the zip is deliberate: a length mismatch between chunks and
    vectors would pair each chunk with the wrong vector from that point on,
    producing an index that looks fine and retrieves nonsense. Crashing is very
    much the better outcome.

    **Idempotent since stage 2.2.** The ids come from `_point_id`, so calling
    this twice with the same document writes the same points twice rather than
    twice as many points. "Upsert" finally means what it says.

    It is only *half* of replacement, though. Overwriting the ids it writes
    leaves behind anything the document previously had under *other* ids —
    chunks from a longer run, or chunks from before the ids were derived at
    all. **Returns the ids it wrote**, so `delete_chunks_except` can remove
    exactly the rest; the pipeline calls them as a pair.
    """
    if not chunks:
        return []

    from qdrant_client import models as qmodels

    settings = get_settings()
    client = get_client()

    points = [
        qmodels.PointStruct(
            # Deterministic since stage 2.2: re-ingesting this document
            # overwrites these exact points instead of adding a second copy.
            id=_point_id(chunk.document_id, chunk.chunk_index),
            vector=vector,
            payload={
                # ── provenance ────────────────────────────────────────────────
                # Everything needed to say where this text came from. Lost here
                # means lost forever.
                "document_id": chunk.document_id,
                "filename": chunk.filename,
                "page": chunk.page,
                "chunk_index": chunk.chunk_index,
                # ── content ──────────────────────────────────────────────────
                # The text itself lives in the payload because there is no other
                # store yet. Stage 1.2 gives it a proper home.
                "text": chunk.text,
                # ── which model produced this vector ─────────────────────────
                # Required by decision 0002 so a model mismatch is detectable
                # per chunk, not just per collection — which is what you need
                # if a partial re-embed ever leaves a collection mixed.
                "embedding_model": embedding_model,
                "embedding_dim": embedding_dim,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    try:
        for offset in range(0, len(points), _UPSERT_BATCH):
            client.upsert(
                collection_name=settings.qdrant_collection,
                points=points[offset : offset + _UPSERT_BATCH],
                # Block until the write is durable. Slower, and at stage 1.1
                # "the upload said it worked" must actually mean it worked.
                wait=True,
            )
    except Exception as exc:
        raise VectorStoreError(
            f"Failed writing {len(points)} chunks to "
            f"'{settings.qdrant_collection}': {exc}"
        ) from exc

    return [str(point.id) for point in points]


def delete_chunks_except(document_id: str, *, keep_ids: list[str]) -> None:
    """Remove every point of this document that is not one of `keep_ids`.

    The second half of replacing a document, and it makes one claim true
    without conditions: **after a successful ingestion the store holds exactly
    the chunks that ingestion wrote** for that document.

    ── Why this is not a tail delete, which is what it was first ─────────────

    The first version deleted `chunk_index >= n`, on the reasoning that
    `upsert_chunks` overwrites `0 … n-1` and only a *shrinking* re-ingest
    leaves anything behind. The stage's own measure disproved it on the first
    run:

        before   6 points, chunk_index [0, 0, 1, 1, 2, 2]
        after    9 points, chunk_index [0, 0, 0, 1, 1, 1, 2, 2, 2]

    Those six were written by `uuid.uuid4()` before this stage. The new
    ingestion wrote three points under *derived* ids, which match none of
    them, and the tail delete reached none of them either — because they carry
    chunk indices 0, 1 and 2, not 3 and above.

    The lesson is general and worth keeping: **points written under a different
    id scheme are identifiable only by `document_id`, never by index.** A tail
    delete repairs nothing that predates the scheme, so it could make future
    ingestions idempotent while leaving every existing duplicate in place. That
    is a fix that passes its unit tests and fixes nothing.

    Identifying the survivors by *what they are not* covers both cases at once:
    a shrinking re-ingest, and any point from any earlier scheme.

    **`keep_ids=[]` deletes every chunk of the document**, which is the one
    thing a caller outside the pipeline needs: `tools/qdrant_orphans.py` uses
    it to remove the vectors of documents that no longer exist in Postgres,
    because `ON DELETE CASCADE` does not reach across into the vector store.

    ── Why still after the upsert, never before ──────────────────────────────

    Deleting first would leave the document unsearchable until the write
    landed — and if embedding then failed, permanently absent. Pruning
    afterwards means every point that is about to exist already does before
    anything is removed. Duplicate chunks are a bad outcome; silently losing a
    working document is a worse one.

    ── What this costs, and the trigger for doing it differently ─────────────

    `keep_ids` goes into the filter, so the request grows with the document:
    a 1,000-chunk book is roughly 36 KB of ids. Qdrant evaluates it only
    against that document's points, so the work is bounded, but the payload is
    not constant.

    The constant-size alternative is a **generation stamp**: put an
    `ingest_id` on every chunk's payload and delete
    `document_id = X AND ingest_id != current`, which is two conditions however
    large the document. It is how index swaps are normally done, and it costs a
    payload field plus a new concept in `Chunk`.

    Not now, because nothing here is measured as slow and the id list is
    exactly expressive. **The trigger:** a document large enough that the
    filter payload shows up in a measurement — or the moment anything else
    needs to reason about "which run wrote this", which is likely to be 2.4's
    `request_id` threading.
    """
    from qdrant_client import models as qmodels

    settings = get_settings()
    client = get_client()

    # An empty `keep_ids` means "keep nothing", so the whole document goes.
    # Expressed by omitting the clause rather than by passing an empty
    # `has_id`: "not in the empty set" is trivially true and would mean the
    # same thing, but it relies on how the vendor validates an empty list
    # where this relies on nothing. It is a real use — `tools/qdrant_orphans.py`
    # deletes documents that no longer exist in Postgres — not a degenerate
    # case to tolerate.
    must_not = (
        [qmodels.HasIdCondition(has_id=list(keep_ids))] if keep_ids else None
    )

    try:
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )
                    ],
                    # "belonging to this document, but not one of these" —
                    # which is the whole semantics in one clause.
                    must_not=must_not,
                )
            ),
            # Same reason as the upsert: the caller is about to report success,
            # so the write needs to be durable before it does.
            wait=True,
        )
    except Exception as exc:
        raise VectorStoreError(
            f"Could not prune the old chunks of document {document_id} in "
            f"'{settings.qdrant_collection}': {exc}"
        ) from exc


def document_chunk_counts() -> dict[str, int]:
    """How many points the store holds for each document.

    ── Why this is part of the public surface and not a script's helper ──────

    It answers the one question nothing else can: **does the vector store agree
    with the database?** Postgres records a `chunk_count` per successful job;
    this is the other side of that comparison, and without it a disagreement
    between the two is undetectable from inside the system.

    That disagreement is not hypothetical. The audit that opened stage 2.2
    found one document holding twice its chunks, and 39 points belonging to
    documents that no longer exist at all — `ON DELETE CASCADE` stops at the
    edge of Postgres, so deleting a document leaves its vectors behind.

    ── Why scroll and not count-per-document ────────────────────────────────

    One pass over the collection answers for every document at once. A
    `count` call filtered per document would be one round trip each, and the
    caller does not know which ids to ask about — finding the *unexpected* ones
    is the whole point.

    `with_payload=["document_id"]` keeps the text and the vectors out of the
    response, so the cost is one small field per point rather than the whole
    store.

    **This is a full scan**, and it is honest about that: it is for audits and
    diagnostics, not for a request path. At the size where it stops being
    cheap, the right answer is a counter maintained at write time, which is
    stage 2.4's metrics work.
    """
    settings = get_settings()
    client = get_client()

    counts: dict[str, int] = {}
    offset = None

    try:
        while True:
            points, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                limit=_SCROLL_BATCH,
                offset=offset,
                with_payload=["document_id"],
                with_vectors=False,
            )
            for point in points:
                document_id = (point.payload or {}).get("document_id")
                if document_id is None:
                    # Provenance is the one thing this pipeline must never
                    # lose, so a point without it is a finding rather than a
                    # row to skip quietly. `search` raises on the same
                    # condition; here the caller is an audit, and an audit that
                    # hid the broken points would be worse than useless.
                    raise VectorStoreError(
                        f"Point {point.id} has no document_id in its payload. "
                        f"It cannot be attributed to any document, and nothing "
                        f"in this system can have written it that way."
                    )
                counts[str(document_id)] = counts.get(str(document_id), 0) + 1

            # Qdrant returns the next page's offset, or None when done.
            if offset is None:
                return counts
    except VectorStoreError:
        raise
    except Exception as exc:
        raise VectorStoreError(
            f"Could not scroll '{settings.qdrant_collection}': {exc}"
        ) from exc


def search(vector: list[float], *, top_k: int) -> list[RetrievedChunk]:
    """Return the `top_k` chunks closest to `vector`, best first."""
    settings = get_settings()
    client = get_client()

    try:
        response = client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
    except Exception as exc:
        raise VectorStoreError(
            f"Search against '{settings.qdrant_collection}' failed: {exc}"
        ) from exc

    results: list[RetrievedChunk] = []
    for point in response.points:
        payload = point.payload or {}

        # A payload missing its page means provenance was lost on the way in.
        # That is the one failure this whole design exists to prevent, so it
        # must be loud — a citation silently defaulting to page 0 would be far
        # worse than an error.
        missing = [
            key
            for key in ("document_id", "filename", "page", "chunk_index", "text")
            if key not in payload
        ]
        if missing:
            raise VectorStoreError(
                f"Point {point.id} is missing payload fields {missing}. It was "
                f"written by an older or different version of this pipeline; "
                f"re-ingest the document."
            )

        # Rebuilding the Chunk from the payload, then wrapping it with the
        # score. The payload holds exactly a Chunk's fields — which is the
        # check above — so the reconstruction is total rather than lossy.
        results.append(
            RetrievedChunk(
                chunk=Chunk(
                    document_id=payload["document_id"],
                    filename=payload["filename"],
                    page=payload["page"],
                    chunk_index=payload["chunk_index"],
                    text=payload["text"],
                ),
                score=point.score,
            )
        )

    return results


def count_chunks() -> int:
    """How many chunks are indexed.

    Used by the caller to tell "nothing has been uploaded yet" apart from
    "nothing matched your question" — two situations that need very different
    answers and that an empty result list cannot distinguish.

    Deliberately *not* called by `retrieve()`. Searching an empty collection
    already returns an empty list, so a guard there would cost an extra round
    trip on every successful query to save one on the rare empty-index case.
    The caller pays only when it actually needs the distinction.
    """
    settings = get_settings()
    client = get_client()
    try:
        return client.count(
            collection_name=settings.qdrant_collection, exact=True
        ).count
    except Exception as exc:
        raise VectorStoreError(
            f"Could not count '{settings.qdrant_collection}': {exc}"
        ) from exc