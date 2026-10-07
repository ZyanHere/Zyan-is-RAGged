"""Turning retrieved evidence into a cited answer.

Orchestration only. Marker assignment and resolution live in `citations.py`;
the prompt text lives in `prompts/answer.py`. What remains here is the sequence
and the two decisions about when *not* to call a model at all.

Generation settings arrive as arguments rather than being read from config
here. A service that reaches for global configuration cannot be tested without
one, and the route already knows the settings — passing them down costs two
parameters and keeps this function callable with anything.
"""

from app.providers.base import ChatModel
from app.prompts.answer import SYSTEM_PROMPT, USER_TEMPLATE
from app.schemas.query import QueryResponse
from app.services.citations import build_context, extract_citations, to_sources
from rag import RetrievedChunk

NO_EVIDENCE_ANSWER = (
    "I could not find anything in the indexed documents that answers this "
    "question."
)

EMPTY_INDEX_ANSWER = (
    "No documents have been indexed yet, so there is nothing to answer from. "
    "Upload a PDF first."
)


async def answer_question(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    model: ChatModel,
    index_is_empty: bool,
    max_tokens: int,
    temperature: float,
) -> QueryResponse:
    """Generate a cited answer from retrieved evidence.

    Two cases never reach the model. Both save a pointless call, and more
    importantly both are the honest answer: with no evidence there is nothing to
    ground an answer in, and a model asked to answer from an empty context will
    often oblige from its own training data — which is precisely the failure
    this system exists to prevent.
    """
    if index_is_empty:
        return QueryResponse(answer=EMPTY_INDEX_ANSWER, citations=[], sources=[])

    if not chunks:
        return QueryResponse(answer=NO_EVIDENCE_ANSWER, citations=[], sources=[])

    user_message = USER_TEMPLATE.format(
        context=build_context(chunks),
        question=question,
    )

    answer = await model.complete(
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    return QueryResponse(
        answer=answer,
        citations=extract_citations(answer, chunks),
        sources=to_sources(chunks),
    )