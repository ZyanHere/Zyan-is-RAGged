"""POST /retrieve. Stage 3.1.

The route the evaluation harness measures through, because it cannot read the
index itself — embedded Qdrant holds an exclusive lock inside this container's
named volume.

What these tests cover is the boundary: ordering across serialisation,
validation of a bad batch, and whether `main.py`'s exception table reaches a
route that was written without a single `try`. Retrieval itself is stubbed;
`rag`'s own suite owns that.
"""

import pytest

import rag
from app.schemas.retrieve import MAX_QUESTIONS
from rag.errors import EmbeddingError, VectorStoreError


def test_the_response_echoes_each_question_in_order(client, retrieval) -> None:
    """**The reason the response carries the question at all.**

    `retrieve_many` guarantees ordering by construction — a comprehension over
    the vectors. Serialisation and an HTTP hop are a new place for it to break,
    and a misaligned result would make the harness attribute every later metric
    to the wrong question with no error and a plausible number at the end.

    "alpha" appears twice deliberately: four questions must come back as four
    results, in order, with the duplicate intact rather than collapsed.

    **And the list must not be a palindrome.** The first version of this test
    used `["alpha", "beta", "alpha"]`, which reads as a reasonable "three
    questions with a duplicate" — and a mutation that reversed the result list
    *survived it*, because reversing a palindrome changes nothing. The
    duplicate that was supposed to make the test stronger was the thing hiding
    the defect. Hence "gamma".
    """
    questions = ["alpha", "beta", "gamma", "alpha"]

    response = client.post("/retrieve", json={"questions": questions})

    assert response.status_code == 200
    results = response.json()["results"]

    assert [result["question"] for result in results] == questions

    # The stub answers with the question as the chunk text, so this checks the
    # *payload* travelled with the right question — not merely that the
    # questions came back in order.
    assert [result["chunks"][0]["text"] for result in results] == questions


def test_a_chunk_carries_where_it_came_from(client, retrieval) -> None:
    """Including `chunk_index`, which 3.1 does not use and 3.2 will.

    Page is what 3.1 matches gold against. `chunk_index` is here so that
    attributing a failure to a chunk rather than a page at 3.2 does not require
    re-running the baseline to get a field that was always available.
    """
    response = client.post("/retrieve", json={"questions": ["alpha"]})

    chunk = response.json()["results"][0]["chunks"][0]
    assert set(chunk) == {
        "document_id",
        "filename",
        "page",
        "chunk_index",
        "score",
        "text",
    }
    assert chunk["page"] == 1
    assert chunk["chunk_index"] == 0


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_question_is_refused_by_the_schema(
    client, retrieval, blank: str
) -> None:
    """A 422, not a 500 — and the engine is never reached.

    `min_length=1` catches `""` and not `"   "`. Without the validator, a
    whitespace question would reach `retrieve_many`, which refuses the batch
    with a `ValueError` — and `main.py` has no handler for `ValueError`, so a
    plainly bad request would come back as an opaque server error.

    The second assertion is the one that matters: refusing after the batch had
    already been embedded would have spent a request against a per-minute
    quota to learn something the schema knew.
    """
    response = client.post("/retrieve", json={"questions": ["alpha", blank]})

    assert response.status_code == 422
    assert retrieval == []


def test_an_empty_question_list_is_refused(client, retrieval) -> None:
    """Zero questions must not be able to look like a successful run.

    The harness has its own completeness contract. This is the same rule one
    layer down, where it costs a `min_length`.
    """
    response = client.post("/retrieve", json={"questions": []})

    assert response.status_code == 422
    assert retrieval == []


def test_more_than_a_hundred_questions_is_refused(client, retrieval) -> None:
    """One HTTP request stays one embedding request.

    `MAX_QUESTIONS` mirrors `_MAX_BATCH` in `gemini.py`. Accepting 101 would
    silently make this call cost two requests against the limit that counts
    requests — which is the entire thing stage 3.1's batching was for.
    """
    at_the_limit = [f"q{n}" for n in range(MAX_QUESTIONS)]
    one_too_many = [f"q{n}" for n in range(MAX_QUESTIONS + 1)]

    assert client.post("/retrieve", json={"questions": at_the_limit}).status_code == 200
    assert client.post("/retrieve", json={"questions": one_too_many}).status_code == 422


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (EmbeddingError("the provider refused us"), 502),
        (VectorStoreError("our own storage failed"), 500),
    ],
)
def test_an_engine_failure_gets_the_status_main_py_assigned_it(
    client, monkeypatch, error: Exception, status: int
) -> None:
    """**The test of `main.py`'s claim**, which this route is the first to rely on.

    That module's docstring says putting the exception-to-status table there
    rather than in try/except blocks inside each route means "a new route gets
    correct error handling for free". `routes/retrieve.py` contains no `try`
    at all, so either the claim holds or every provider failure reaching this
    route is an unlabelled 500.

    Two codes rather than one, because a single handler catching everything
    would pass a one-case test: 502 says an upstream provider failed us, 500
    says our own storage did, and the distinction is what makes an error rate
    attributable.
    """

    def fail(questions, *, top_k=None):
        raise error

    monkeypatch.setattr(rag, "retrieve_many", fail)

    response = client.post("/retrieve", json={"questions": ["alpha"]})

    assert response.status_code == status
    assert str(error) in response.json()["detail"]


def test_a_short_result_list_from_the_engine_fails_loudly(
    client, monkeypatch
) -> None:
    """`strict=True` on the zip, which is the point of that line.

    If `retrieve_many` ever returned fewer results than it was given questions,
    a lenient `zip` would truncate to the shorter one — producing a response
    that is correctly *shaped*, shorter than the request, and wrong about which
    question each result belongs to. The harness checks the length it receives,
    but a silent truncation here would mean the agent itself had already lost
    the pairing.

    A 500 is the right answer: this is an internal invariant violation, not a
    bad request, and loud is the whole point.
    """

    def one_result_for_two_questions(questions, *, top_k=None):
        return [[]]

    monkeypatch.setattr(rag, "retrieve_many", one_result_for_two_questions)

    with pytest.raises(ValueError, match="argument 2 is shorter"):
        client.post("/retrieve", json={"questions": ["alpha", "beta"]})


def test_top_k_passes_through_untouched_including_none(client, retrieval) -> None:
    """The agent holds no default. `rag` owns what `top_k` means.

    `None` must arrive as `None` rather than being resolved here, or there
    would be two sources of truth for one environment variable — and the
    harness could measure a `top_k` the running system does not use.
    """
    client.post("/retrieve", json={"questions": ["alpha"]})
    client.post("/retrieve", json={"questions": ["alpha"], "top_k": 3})

    assert [call["top_k"] for call in retrieval] == [None, 3]


def test_no_chat_model_is_constructed(client, retrieval, no_chat_model) -> None:
    """Nothing generates. Asserted, not assumed.

    Stage 3.1 requires a runner that measures retrieval *"with no chatbot in
    the loop"*. `routes/retrieve.py` imports no provider today, so this test
    passes trivially — and that is exactly why it is worth having: it is a
    guard against someone later adding a summary, a rerank through an LLM, or
    an "while we're here" answer to this route, which would silently put
    generation back into the measurement path.
    """
    response = client.post("/retrieve", json={"questions": ["alpha"]})

    assert response.status_code == 200
