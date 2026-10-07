"""The agent service.

    frontend :3000  →  backend :8000  →  agent :8001  →  OpenRouter / Gemini
                                              │
                                              └── imports ──▶ rag

Holds the exception-to-status-code table for both vocabularies — the agent's
own failures and the engine's. Putting it here rather than in try/except blocks
inside each route means a new route gets correct error handling for free, and
there is exactly one place to look when a failure comes back with the wrong
status.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import documents, health, query
from app.errors import AgentError, ProviderError, UploadTooLargeError
from rag import (
    EmbeddingError,
    InvalidDocumentError,
    NoTextExtractedError,
    RagError,
    VectorStoreError,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="myRAG agent",
    description="The AI layer. Owns prompts, models and RAG orchestration.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(query.router)


# ── Failures ──────────────────────────────────────────────────────────────────
#
#   from rag                              from the agent
#   ─────────────────────────────         ──────────────────────────────
#   InvalidDocumentError  400             UploadTooLargeError   413
#   NoTextExtractedError  422             ProviderError         502
#   EmbeddingError        502             AgentError            500
#   VectorStoreError      500
#   RagError              500
#
# The two base classes are registered last: FastAPI picks the most specific
# handler for the exception's type, so `RagError` and `AgentError` only catch
# what nothing above them named.
#
# No CORS here: the browser never talks to this service. The backend is the only
# thing that calls it, and adding CORS would quietly make a direct browser call
# work — hiding a layering violation instead of failing it.


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


@app.exception_handler(InvalidDocumentError)
async def _invalid_document(request: Request, exc: InvalidDocumentError):
    return _error(400, str(exc))


@app.exception_handler(NoTextExtractedError)
async def _no_text(request: Request, exc: NoTextExtractedError):
    return _error(422, str(exc))


@app.exception_handler(UploadTooLargeError)
async def _upload_too_large(request: Request, exc: UploadTooLargeError):
    return _error(413, str(exc))


@app.exception_handler(EmbeddingError)
async def _embedding_failed(request: Request, exc: EmbeddingError):
    logger.warning("embedding provider failed: %s", exc)
    return _error(502, str(exc))


@app.exception_handler(ProviderError)
async def _chat_failed(request: Request, exc: ProviderError):
    logger.warning("chat provider failed: %s", exc)
    return _error(502, str(exc))


@app.exception_handler(VectorStoreError)
async def _vector_store_failed(request: Request, exc: VectorStoreError):
    logger.error("vector store failed: %s", exc)
    return _error(500, str(exc))


@app.exception_handler(RagError)
async def _engine_failed(request: Request, exc: RagError):
    logger.error("engine failed: %s", exc)
    return _error(500, str(exc))


@app.exception_handler(AgentError)
async def _agent_failed(request: Request, exc: AgentError):
    logger.error("agent failed: %s", exc)
    return _error(500, str(exc))