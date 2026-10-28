"""POST /retrieve — find evidence, and stop there. Stage 3.1.

**Retrieval without an answer**, which is the whole point. `POST /query`
retrieves and then calls a chat model; this route returns the chunks and
nothing else. No prompt is built, no model is constructed, nothing is
generated.

── Why this route exists at all ───────────────────────────────────────────────

The stage 3.1 evaluation harness has to measure retrieval, and it cannot read
the index. Qdrant runs embedded — a library holding an **exclusive lock** on a
storage folder — and that folder is a named Docker volume inside this
container. `docker-compose.yml` has said so since 1.3:

    "this is a different index from the one in ./agent/qdrant_data ... anything
     on the host — the stage 3.1 evaluation harness, for instance — cannot read
     it directly"

Worse than inaccessible, it is *silently* inaccessible: `get_client()` calls
`qdrant_path.mkdir(parents=True, exist_ok=True)`, so a host script does not
fail — it creates or opens a different folder and reports plausible numbers
against an empty or stale index.

This process already holds the lock and already imports `rag`. Three options
were weighed (running the harness inside this container, and adding a Qdrant
server with `QDRANT_URL`); this one needs no new infrastructure, and 3.2's
failure attribution will reuse the same endpoint.

**It is not a chatbot in the loop.** The curriculum's requirement — *"a runner
that calls retrieval directly, no chatbot in the loop"* — is about answer
generation confounding the measurement. Nothing here generates.

── Why `def` and not `async def` ──────────────────────────────────────────────

`rag.retrieve_many` is synchronous and blocks twice: on one embedding request
to Gemini, and on one Qdrant search per question. A plain `def` means FastAPI
runs it on the worker threadpool, which is stage 2.5's rule and both halves of
it — *a route that blocks belongs on a thread; a route that does no I/O belongs
on the loop.*

Fifty questions hold one of forty threads for several seconds. That is
affordable, and `/health` cannot be starved by it: 2.5 made that route
`async def` after measuring it go from 8 ms to 3508 ms behind exactly this kind
of work.

── Why there is no try/except ─────────────────────────────────────────────────

`main.py`'s docstring claims that putting the exception-to-status table there
rather than in each route means "a new route gets correct error handling for
free". This route is the test of that claim, and it collects:

    EmbeddingError   502   the provider refused us — a 429 included
    VectorStoreError 500   our own storage failed
    RagError         500   anything else from the engine

A `ValueError` from `retrieve_many`'s own blank-question check would *not* be
covered, which is why `RetrieveRequest` refuses blanks at the boundary before
the engine is reached.
"""

from fastapi import APIRouter

import rag
from app.schemas.retrieve import (
    QuestionResult,
    RetrievedChunkOut,
    RetrieveRequest,
    RetrieveResponse,
)

router = APIRouter()


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    """Find the chunks most similar to each question. One embedding request."""
    # `top_k` goes through untouched, None included: the engine owns that
    # default, and a second opinion here would be a second source of truth.
    results = rag.retrieve_many(request.questions, top_k=request.top_k)

    return RetrieveResponse(
        results=[
            QuestionResult(
                question=question,
                chunks=[
                    RetrievedChunkOut(
                        document_id=found.chunk.document_id,
                        filename=found.chunk.filename,
                        page=found.chunk.page,
                        chunk_index=found.chunk.chunk_index,
                        score=found.score,
                        text=found.chunk.text,
                    )
                    for found in chunks
                ],
            )
            # `strict=True` is the point of this line rather than an
            # afterthought. If `retrieve_many` ever returned a different number
            # of results than it was given questions, a lenient zip would
            # silently truncate to the shorter one — producing a response that
            # is correctly *shaped*, shorter than the request, and wrong about
            # which question each result belongs to. `upsert_chunks` uses
            # `strict=True` for the same reason on the way in.
            for question, chunks in zip(request.questions, results, strict=True)
        ]
    )
