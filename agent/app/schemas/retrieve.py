"""HTTP shapes for POST /retrieve. Stage 3.1.

**Why this is not `schemas/query.py`'s `SourceChunk`.** That type carries
`marker: int` — the number the model wrote in its answer text, so a client can
turn `[1]` into a link. A retrieval-only response has no answer and therefore
no markers, and borrowing the field would mean inventing a value for it. The
two shapes look similar because they describe the same chunk; they differ
because one has been through a language model and the other has not.

**Why the response echoes each question.** `rag.retrieve_many` guarantees that
`results[i]` belongs to `questions[i]` — it is a list comprehension over the
vectors, so the ordering holds by construction. JSON serialisation and an HTTP
hop are a *new* place for that to break, and a misaligned result is precisely
the failure the evaluation harness exists to not have: a caller computing
recall over `zip(questions, results)` would attribute every later metric to the
wrong question, with no error and a plausible number at the end.

Echoing costs one string per question and turns the ordering contract into
something the harness can **assert** rather than assume.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

MAX_QUESTIONS = 100
"""Questions per request.

Mirrors `_MAX_BATCH` in `rag/rag/providers/gemini.py`, so one HTTP request is
one embedding request. That is the unit the free tier's rate limit counts —
stage 2.5 recorded the refusal as *"Embed content requests per minute limit
exceeded"* — and a cap anywhere else would quietly turn one call into two.
"""

Question = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
"""One question. Same 2000-character ceiling as `QueryRequest.question`.

**No `strip_whitespace`.** Stripping here would be tempting — it would make
`"   "` fail `min_length` for free — and it would break the echo: the response
would carry a *different* string from the one the caller sent, so asserting
alignment would compare a stripped question against an unstripped one and fail
for a reason that has nothing to do with ordering. The blank case is handled
explicitly below instead.
"""


class RetrieveRequest(BaseModel):
    """A batch of questions to find evidence for."""

    questions: list[Question] = Field(min_length=1, max_length=MAX_QUESTIONS)
    """At least one.

    An empty list is refused rather than answered with an empty result,
    because a run of zero questions must not be able to look like a
    successful one. The harness has its own completeness contract; this is the
    same rule applied one layer down, where it is cheap.
    """

    top_k: int | None = Field(default=None, gt=0, le=50)
    """None means "let the engine decide", exactly as in `QueryRequest`.

    The agent holds no default of its own — `rag` owns what `top_k` means, and
    a second opinion here would be a second source of truth.
    """

    @field_validator("questions")
    @classmethod
    def _refuse_blank_questions(cls, questions: list[str]) -> list[str]:
        """A whitespace-only question is a 422, not a 500.

        `min_length=1` does not catch `"   "`. Without this, such a question
        would reach `rag.retrieve_many`, which refuses the batch with a
        `ValueError` — and `main.py` has no handler for `ValueError`, so the
        caller would get an opaque 500 for what is plainly a bad request.

        **This duplicates a check `retrieve_many` already performs, and the
        duplication is deliberate.** They are two different contracts: this one
        says what this HTTP boundary accepts, the other is a library invariant
        that holds for every caller including ones that never speak HTTP.
        Removing either would leave a real gap.
        """
        blank = [index for index, question in enumerate(questions) if not question.strip()]
        if blank:
            raise ValueError(
                f"questions at index {blank} are empty or whitespace. The "
                f"whole batch is refused rather than skipped, so that a "
                f"result list can never be shorter than its question list."
            )
        return questions


class RetrievedChunkOut(BaseModel):
    """One chunk retrieval found, with where it came from."""

    document_id: str
    filename: str
    page: int
    chunk_index: int
    """Which chunk of the document, numbered from 0 across the whole document.

    Not needed by stage 3.1, which matches gold *pages*. Included because 3.2
    attributes failures per chunk — "the gold span was in a chunk that was
    never retrieved" is a different diagnosis from "the page was retrieved but
    the wrong part of it" — and adding the field later would mean re-running
    the baseline to get it.
    """

    score: float
    text: str


class QuestionResult(BaseModel):
    """What one question found."""

    question: str
    """The question as received, echoed back verbatim. See the module docstring."""

    chunks: list[RetrievedChunkOut]
    """Best first. Empty means nothing matched, or nothing is indexed."""


class RetrieveResponse(BaseModel):
    results: list[QuestionResult]
    """One entry per question, in the order the questions were given."""
