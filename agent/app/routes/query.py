"""POST /query — retrieve evidence, then answer from it.

**This handler is `async def`, unlike the documents route.** It has to be: the
chat model is async, and `await` is only legal inside an async function.

That leaves the synchronous half — `rag.retrieve`, which embeds the question and
searches Qdrant — needing somewhere to run that is not the event loop.
`run_in_threadpool` is the explicit version of what FastAPI does automatically
for a `def` handler.

The two routes make the rule visible: sync work goes in a thread, either
implicitly by declaring `def`, or explicitly with `run_in_threadpool` when the
handler also has to await something.
"""

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

import rag
from app.core.config import get_settings
from app.providers.base import get_chat_model
from app.schemas.query import QueryRequest, QueryResponse
from app.services.answer import answer_question

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """Answer a question from the indexed documents, with page citations."""
    settings = get_settings()

    # `top_k` goes through untouched, None included: the engine owns that
    # default, and a second opinion here would be a second source of truth.
    chunks = await run_in_threadpool(
        rag.retrieve, request.question, top_k=request.top_k
    )

    # Only asked when it matters. An empty result means either nothing is
    # indexed or nothing matched, and those deserve different answers — but
    # counting on every successful query to learn something we only need on
    # failure is a round trip for nothing.
    index_is_empty = (
        await run_in_threadpool(rag.count_chunks) == 0 if not chunks else False
    )

    return await answer_question(
        request.question,
        chunks,
        model=get_chat_model(),
        index_is_empty=index_is_empty,
        max_tokens=settings.chat_max_tokens,
        temperature=settings.chat_temperature,
    )