"""Batched query embedding. Stage 3.1.

**What this stage is actually about, and it is not performance.** Gemini's free
tier counts *requests*, not texts. Stage 2.5 recorded the refusal verbatim:

    sample 1:  3482.0 ms (100 vectors)
    sample 2:  FAILED - 429 RESOURCE_EXHAUSTED
               "Embed content requests per minute limit exceeded on Free Tier"

A hundred vectors went through in one accepted request, and the next request -
whatever its size - did not. `_embed` in `gemini.py` has always batched a
hundred texts per round trip; only `embed_documents` had a door to it, so the
evaluation harness's thirty to fifty questions cost thirty to fifty requests
against a corpus that indexes in about twenty.

So `test_fifty_questions_cost_one_request` is the headline, and on its own it
is not trustworthy: a stub that records a single call would satisfy it whatever
the code did. `test_a_hundred_and_one_questions_cost_two_requests` exists to
make the recorder prove it can count past one.

── No network, and the first test in this repo to touch `gemini.py` ──────────

`conftest.py`'s rule holds - nothing here touches the network, an API key, or a
vector store. `genai.Client` is replaced before the model is constructed, so no
real client is ever built, and the stub records what was asked for.
"""

from types import SimpleNamespace

import pytest

from rag import pipeline
from rag.models import Chunk, RetrievedChunk
from rag.providers import gemini as gemini_module
from rag.providers.fake import FakeEmbeddingModel

# Small on purpose. These tests assert about request *shape*, never about
# vector content, and 768 zeros per stubbed embedding would be noise.
GEMINI_DIMENSIONS = 8

# The fake provider's real width, because `retrieve_many`'s tests use the real
# fake rather than a hand-rolled one - see `_RecordingEmbedder`.
FAKE_DIMENSIONS = 768


# ── A stubbed Gemini client ──────────────────────────────────────────────────
#
# Shaped exactly like the part of the SDK `gemini.py` touches and no more:
# `client.models.embed_content(...)` returning an object with `.embeddings`,
# each with `.values`.


class _StubEmbedding:
    def __init__(self, values: list[float]) -> None:
        self.values = values


class _StubResponse:
    def __init__(self, embeddings: list[_StubEmbedding]) -> None:
        self.embeddings = embeddings


class _StubModels:
    """Records every request, and answers with the right number of vectors."""

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions
        self.calls: list[dict] = []

    def embed_content(self, *, model: str, contents: list[str], config: object):
        texts = list(contents)

        self.calls.append(
            {
                "model": model,
                "contents": texts,
                # The asymmetry the seam exists to protect. Read off the real
                # `types.EmbedContentConfig` the provider built, not off a
                # value this test passed in.
                "task_type": config.task_type,
                "dimensions": config.output_dimensionality,
            }
        )

        # One vector per input, correct width, so `_embed`'s own alignment and
        # dimension checks pass and cannot be what these tests are measuring.
        return _StubResponse(
            [
                _StubEmbedding([1.0] + [0.0] * (self._dimensions - 1))
                for _ in texts
            ]
        )


class _StubClient:
    def __init__(self, dimensions: int) -> None:
        self.models = _StubModels(dimensions)


@pytest.fixture
def gemini(monkeypatch) -> tuple[gemini_module.GeminiEmbeddingModel, _StubModels]:
    """A real `GeminiEmbeddingModel` over a stubbed client."""
    client = _StubClient(GEMINI_DIMENSIONS)

    # Patched before construction, so `genai.Client(api_key=...)` in
    # `__init__` never runs. The key below is never sent anywhere.
    monkeypatch.setattr(gemini_module.genai, "Client", lambda api_key: client)

    model = gemini_module.GeminiEmbeddingModel(
        api_key="not-a-real-key",
        model="gemini-embedding-001",
        dimensions=GEMINI_DIMENSIONS,
    )

    return model, client.models


# ── The requests a question costs ────────────────────────────────────────────


def test_fifty_questions_cost_one_request(gemini) -> None:
    """**The reason this stage exists.** Fifty questions, one request.

    The rate limit counts requests, so this is not an optimisation around the
    limit - it is exactly the unit the limit measures. Before `embed_queries`,
    the only public query path was `embed_query`, and an eval run cost fifty.
    """
    model, models = gemini

    vectors = model.embed_queries([f"question {n}" for n in range(50)])

    assert len(models.calls) == 1
    assert len(models.calls[0]["contents"]) == 50
    assert len(vectors) == 50


def test_a_hundred_and_one_questions_cost_two_requests(gemini) -> None:
    """The recorder can count past one, and the batch boundary is real.

    Without this, the test above would pass against a stub that recorded a
    single call no matter what, and against an implementation that silently
    dropped everything after the first batch. Both would look like success.
    """
    model, models = gemini
    count = gemini_module._MAX_BATCH + 1

    vectors = model.embed_queries([f"question {n}" for n in range(count)])

    assert len(models.calls) == 2
    assert len(models.calls[0]["contents"]) == gemini_module._MAX_BATCH
    assert len(models.calls[1]["contents"]) == 1
    assert len(vectors) == count


def test_queries_and_documents_use_different_task_types(gemini) -> None:
    """The asymmetry survives the new method.

    `gemini-embedding-001` produces different vectors depending on whether it
    is told it is embedding a document to be found or a question doing the
    finding. Getting it wrong degrades retrieval and errors nothing - so the
    distinction is carried by the method name, and this is the test that says
    the names still mean what they claim.
    """
    model, models = gemini

    model.embed_queries(["a question"])
    model.embed_documents(["a chunk of a document"])

    assert models.calls[0]["task_type"] == "RETRIEVAL_QUERY"
    assert models.calls[1]["task_type"] == "RETRIEVAL_DOCUMENT"


def test_embed_query_sends_one_text_as_a_query(gemini) -> None:
    """The singular path is unchanged in cost and in task type.

    `embed_query` now delegates to `embed_queries`, and a delegation that
    quietly sent a batch, or sent it under the document task type, would be
    invisible to every other test here.
    """
    model, models = gemini

    model.embed_query("a question")

    assert len(models.calls) == 1
    assert models.calls[0]["contents"] == ["a question"]
    assert models.calls[0]["task_type"] == "RETRIEVAL_QUERY"


def test_the_fake_provider_batches_queries_like_the_real_one() -> None:
    """The fake still satisfies the protocol, and is still symmetric.

    The fake exists to be a *drop-in* substitute. A widened protocol it does
    not satisfy is a measurement apparatus that cannot be swapped in - and the
    failure would not appear until something asked it for a batch, which today
    is only the harness.
    """
    model = FakeEmbeddingModel(dimensions=FAKE_DIMENSIONS, delay_ms=0)
    texts = ["alpha", "beta", "gamma"]

    batched = model.embed_queries(texts)

    assert batched == [model.embed_query(text) for text in texts]
    assert batched == model.embed_documents(texts)


# ── retrieve_many ────────────────────────────────────────────────────────────


class _RecordingEmbedder:
    """The real fake provider, recording which texts were asked for together.

    Wrapping the real `FakeEmbeddingModel` rather than inventing a stub, so
    these tests also exercise the `embed_queries` just added to it.
    """

    def __init__(self) -> None:
        self._inner = FakeEmbeddingModel(dimensions=FAKE_DIMENSIONS, delay_ms=0)
        self.model_name = self._inner.model_name
        self.dimensions = self._inner.dimensions
        self.batches: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return self._inner.embed_queries(texts)

    def embed_query(self, text: str) -> list[float]:
        self.batches.append([text])
        return self._inner.embed_query(text)


def _result_for(vector: list[float]) -> list[RetrievedChunk]:
    """A one-chunk result that identifies the vector it was searched with."""
    return [
        RetrievedChunk(
            chunk=Chunk(
                document_id="doc",
                filename="doc.pdf",
                page=1,
                chunk_index=0,
                text=f"{vector[0]:.9f}",
            ),
            score=1.0,
        )
    ]


@pytest.fixture
def retrieval(monkeypatch) -> tuple[_RecordingEmbedder, list[tuple]]:
    """`pipeline` with its store and its embedder replaced.

    `get_settings` is stubbed too: building real `Settings` would require a
    `GOOGLE_API_KEY`, and a test that passes or fails depending on a
    developer's `.env` is worse than no test.
    """
    embedder = _RecordingEmbedder()
    searches: list[tuple] = []

    def fake_search(vector: list[float], *, top_k: int) -> list[RetrievedChunk]:
        searches.append((tuple(vector), top_k))
        return _result_for(vector)

    monkeypatch.setattr(pipeline, "ensure_collection", lambda: None)
    monkeypatch.setattr(pipeline, "get_embedding_model", lambda: embedder)
    monkeypatch.setattr(pipeline, "search", fake_search)
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(top_k=5))

    return embedder, searches


def test_retrieve_many_preserves_question_order(retrieval) -> None:
    """Order is the contract, and a duplicate must not collapse into one.

    Deduplicating is the obvious optimisation and the likeliest way to break
    this: a caller computing recall over `zip(questions, results)` would
    attribute every metric after the collapsed duplicate to the wrong
    question, with no error and a plausible number at the end.

    "alpha" appears twice on purpose. Four questions must mean four searches,
    in the order given.
    """
    embedder, searches = retrieval
    questions = ["alpha", "beta", "alpha", "gamma"]

    results = pipeline.retrieve_many(questions, top_k=3)

    reference = FakeEmbeddingModel(dimensions=FAKE_DIMENSIONS, delay_ms=0)
    expected = [tuple(reference.embed_query(question)) for question in questions]

    # One request for the whole batch - the point of the function.
    assert embedder.batches == [questions]

    # The searches, in question order, duplicate included.
    assert [vector for vector, _ in searches] == expected

    # And the *returned* lists in that order too, not merely the searches.
    assert len(results) == len(questions)
    assert [result[0].chunk.text for result in results] == [
        f"{vector[0]:.9f}" for vector in expected
    ]


def test_retrieve_many_refuses_the_whole_batch_for_one_blank_question(
    retrieval,
) -> None:
    """All-or-nothing, and refused before a single request is spent.

    Two separate claims, and the second is the one that is easy to lose: the
    validation has to happen *before* the embedder is touched, or a caller's
    mistake costs a request against a per-minute quota.

    Skipping the bad question instead would return three results for four
    questions, and every metric computed from the pair would be attributed to
    the wrong question from that point on.
    """
    embedder, searches = retrieval

    with pytest.raises(ValueError, match="index"):
        pipeline.retrieve_many(["alpha", "   ", "gamma"], top_k=3)

    assert embedder.batches == []
    assert searches == []


def test_an_empty_batch_is_not_an_empty_question(retrieval) -> None:
    """No questions is no work; a blank question is a refusal.

    The two must not collapse, which is why the early return sits after the
    validation rather than before it.
    """
    embedder, searches = retrieval

    assert pipeline.retrieve_many([]) == []
    assert embedder.batches == []
    assert searches == []


def test_retrieve_many_matches_retrieve_for_a_single_question(retrieval) -> None:
    """The two public entry points agree, including on the default top_k.

    A harness that measured through `retrieve_many` while everything else used
    `retrieve` would be measuring a different system from the one that runs -
    the exact failure the fake provider's whole design is organised against.
    """
    embedder, searches = retrieval

    singular = pipeline.retrieve("the Zephyr project")
    batched = pipeline.retrieve_many(["the Zephyr project"])

    assert batched == [singular]

    # Both resolved the configured default rather than one of them inventing
    # its own.
    assert [top_k for _, top_k in searches] == [5, 5]
