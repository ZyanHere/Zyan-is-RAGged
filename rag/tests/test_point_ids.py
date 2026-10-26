"""Point ids. Stage 2.2.

The engine's half of idempotency is one function: the id a chunk is stored
under. Before this stage it was `uuid.uuid4()`, so a second ingestion of a
document could not overwrite the first and wrote a disjoint copy instead.

── What is testable here and what is not ──────────────────────────────────────

`_point_id` is a pure function, so every property that matters about it —
determinism, distinctness, independence from anything ambient — is checkable
with no vector store, no network and no API key, which is this suite's rule.

What is *not* testable here is that the store honours the ids and the delete
filter. That needs real Qdrant and is the stage's end-to-end measure:
re-ingest the doubly-indexed document found in the baseline audit and watch its
point count go from 6 to 3.

The last test in this file is the one that joins the two halves. A perfect pure
function nobody calls would pass every test above it.
"""

import uuid

import pytest

from rag.models import Chunk
from rag.vector_store import _POINT_NAMESPACE, _point_id


def chunk(document_id: str = "doc-1", chunk_index: int = 0) -> Chunk:
    return Chunk(
        document_id=document_id,
        filename="zephyr.pdf",
        page=1,
        chunk_index=chunk_index,
        text="the Zephyr project was approved on 14 March 2021",
    )


# ── Determinism ──────────────────────────────────────────────────────────────


def test_the_same_chunk_always_gets_the_same_id() -> None:
    """The entire point of the stage, stated as plainly as it can be.

    With `uuid4` this was false by construction, and the consequence was a
    measured one: a document holding six points where three belong, each
    `chunk_index` present twice under two different ids.
    """
    assert _point_id("doc-1", 0) == _point_id("doc-1", 0)


def test_ids_survive_a_process_boundary() -> None:
    """Derived, not remembered.

    A cache or a counter would make the ids stable within one process and
    useless across the two that matter — the worker that ingested a document
    yesterday is not the worker retrying it today. Recomputing the expected
    value from the primitives here proves nothing is being held in memory.
    """
    expected = str(uuid.uuid5(_POINT_NAMESPACE, "doc-1:7"))

    assert _point_id("doc-1", 7) == expected


def test_the_namespace_is_pinned() -> None:
    """A regression guard on a value that must never change.

    Changing `_POINT_NAMESPACE` orphans every point ever written, because
    nothing would compute the old ids again — the same class of mistake as
    changing `EMBEDDING_DIM` against a populated collection, and silent in the
    same way. Writing the constant down in a test makes an accidental edit
    fail here rather than in production six months later.
    """
    assert str(_POINT_NAMESPACE) == "0ccb9ba8-58c7-4d5e-9367-101281c98bea"


# ── Distinctness ─────────────────────────────────────────────────────────────


def test_different_chunks_of_one_document_get_different_ids() -> None:
    """Otherwise a document would collapse to a single stored chunk.

    This is the failure mode a deterministic scheme risks and a random one
    could not have: get the derivation wrong and every chunk overwrites the
    last, leaving one point per document and a silently gutted index.
    """
    ids = {_point_id("doc-1", index) for index in range(50)}

    assert len(ids) == 50


def test_the_same_chunk_index_in_different_documents_differs() -> None:
    """The other collapse: two documents sharing one set of ids.

    Every document has a chunk 0, so a scheme keyed on the index alone would
    make each upload overwrite the previous one's chunks.
    """
    assert _point_id("doc-1", 0) != _point_id("doc-2", 0)


def test_ids_are_valid_uuids() -> None:
    """Qdrant accepts a UUID or an unsigned integer and nothing else.

    A string that merely looked unique would be rejected at write time, which
    is the one failure in this file that no amount of reasoning catches
    earlier.
    """
    parsed = uuid.UUID(_point_id("doc-1", 3))

    assert parsed.version == 5


# ── The separator, which is where a clever scheme would break ────────────────


def test_a_missing_separator_would_collide_and_does_not() -> None:
    """`("doc-1", 11)` and `("doc-11", 1)` must not share an id.

    Concatenated with no separator both become `doc-111`, so one chunk would
    silently overwrite a chunk of a *different document* — worse than the
    duplication this stage is fixing, because the lost text is simply gone and
    the index still looks healthy.

    ── On the case that is deliberately not here ─────────────────────────────

    A second pair was written alongside this one — `("doc:1", 2)` against
    `("doc", 12)`, meant to guard a document id that itself contains the
    separator. It was removed after the mutation run, because **no plausible
    wrong scheme makes it collide**: with no separator it gives `doc:12` and
    `doc12`; with the colon, `doc:1:2` and `doc:12`. It survived every
    mutation, including reverting to `uuid4`.

    A test that cannot fail is not a test, and this project has already been
    bitten twice by assertions that proved nothing. The property it was
    describing is real and holds for the reason stated below; it just does not
    need a test to say so.

    `f"{document_id}:{chunk_index}"` is unambiguous because `chunk_index` is
    always an integer: everything after the final colon is the index and
    everything before it is the document id, whatever the id contains.
    """
    assert _point_id("doc-1", 11) != _point_id("doc-11", 1)


def test_a_document_id_that_is_not_a_uuid_is_accepted() -> None:
    """`uuid5(uuid.UUID(document_id), ...)` is the obvious spelling and crashes.

    `document_id` is a `str` and has never been required to be a UUID —
    `test_pipeline.py` passes `"doc-1"`, and `pipeline.py` states that
    identity belongs to whoever owns the durable record of the document, not
    to this library. The agent happens to mint UUIDs; that is its choice, not
    a contract this function may rely on.

    Tightening the contract to make the id scheme prettier would be the engine
    taking back a decision it deliberately delegated, so this asserts the
    looser contract still holds.
    """
    assert _point_id("not-a-uuid-at-all", 0)
    assert _point_id("", 0), "even an empty id must produce something valid"


# ── The link between the pure function and the write ─────────────────────────


def test_upsert_uses_the_deterministic_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this, every test above could pass while nothing used the result.

    That is not a hypothetical failure mode in this project: at stage 2.1 a
    heartbeat test passed with the heartbeat removed, and the lesson was that a
    test of a mechanism has to touch the code path that uses it.

    So this one captures what `upsert_chunks` actually hands to Qdrant, and
    asserts the ids are the derived ones — twice, to show the second write
    targets the same points rather than new ones.

    The client is faked rather than real because this suite reaches no vector
    store; what is being checked is the id, which is decided before the client
    is involved at all.
    """
    from rag import vector_store

    written: list[list] = []

    class FakeClient:
        def upsert(self, *, collection_name, points, wait):
            written.append(points)
            return None

    class FakeSettings:
        qdrant_collection = "documents"

    # `get_settings` is patched as well as `get_client`, and the reason is
    # itself a finding worth keeping: without it this test fails with a
    # pydantic error about a missing GOOGLE_API_KEY. `upsert_chunks` reads the
    # settings object purely for the collection name, but the settings object
    # cannot be built at all without embedding configuration.
    #
    # It is the same coupling `test_pipeline.py` exists to guard against from
    # the other direction — "a missing GOOGLE_API_KEY masked every input
    # error" — and this suite's rule is that nothing here needs a key. Stage
    # 2.4's fake embedder is where that coupling gets addressed properly.
    monkeypatch.setattr(vector_store, "get_client", FakeClient)
    monkeypatch.setattr(vector_store, "get_settings", FakeSettings)

    chunks = [chunk(chunk_index=i) for i in range(3)]
    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]

    returned = [
        vector_store.upsert_chunks(
            chunks, vectors, embedding_model="fake", embedding_dim=2
        )
        for _ in range(2)
    ]

    assert len(written) == 2, "both calls must have reached the store"

    expected = [_point_id("doc-1", i) for i in range(3)]
    assert [point.id for point in written[0]] == expected
    assert [point.id for point in written[1]] == expected, (
        "the second write must target the same ids — that is what makes a "
        "retry an overwrite rather than a duplicate"
    )

    # The returned ids are what `delete_chunks_except` prunes around, so a
    # mismatch between "what was written" and "what was reported written"
    # would delete live chunks. Asserting they are the same list is cheap and
    # the failure it guards against is not recoverable.
    assert returned[0] == expected
    assert returned[1] == expected
