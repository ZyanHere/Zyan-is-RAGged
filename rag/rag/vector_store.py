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

**Point ids are random** (decision D3). Stage 2.2 replaces them with
`uuid5(document_id, chunk_index)`. Doing it now would pre-fix the duplicate-chunk
corruption that 2.2 exists to make you reproduce, and a stage whose trigger you
have quietly prevented is a stage you cannot learn from.
"""

import uuid
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client import models as qmodels

from rag.config import get_settings
from rag.errors import VectorStoreError
from rag.models import Chunk, RetrievedChunk

# Points per upsert call. Large enough that a 300-page document is a handful of
# round trips, small enough that one failure does not lose everything.
_UPSERT_BATCH = 256


@lru_cache
def get_client() -> QdrantClient:
    """Open the vector store once and reuse it.

    Cached because in embedded mode the client holds a lock on the storage
    folder — opening a second one in the same process fails outright.
    """
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
) -> None:
    """Write chunks and their vectors to the collection.

    `strict=True` on the zip is deliberate: a length mismatch between chunks and
    vectors would pair each chunk with the wrong vector from that point on,
    producing an index that looks fine and retrieves nonsense. Crashing is very
    much the better outcome.
    """
    if not chunks:
        return

    settings = get_settings()
    client = get_client()

    points = [
        qmodels.PointStruct(
            id=str(uuid.uuid4()),
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