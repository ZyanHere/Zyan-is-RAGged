"""The backend service.

    frontend :3000  ──HTTP──▶  backend :8000  ──HTTP──▶  agent :8001

The only service the browser talks to, which is why it is the only one with
CORS. It holds no model keys, no prompts and no engine imports.

At stage 1.1 it forwards and little else. Modules 1.2 through 9 fill it in:
Postgres, jobs, retries, quotas, rate limiting, caching. The shape is here so
those land in a place that already exists.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import documents, health, query
from app.core.config import get_settings
from app.errors import (
    AgentUnavailableError,
    BackendError,
    BadUploadError,
    UploadTooLargeError,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="myRAG backend",
    description="The reliability layer. Owns durability, not intelligence.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(query.router)


# ── Failures ──────────────────────────────────────────────────────────────────
#
#   BadUploadError         400   the caller sent something unusable
#   UploadTooLargeError    413
#   AgentUnavailableError  503   our dependency is down, not us
#   BackendError           500   registered last; catches what nothing named
#
# Errors the agent *returns* are not handled here — they are forwarded with
# their own status code and body, because the agent is the authority on what
# went wrong inside it.


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


@app.exception_handler(BadUploadError)
async def _bad_upload(request: Request, exc: BadUploadError):
    return _error(400, str(exc))


@app.exception_handler(UploadTooLargeError)
async def _upload_too_large(request: Request, exc: UploadTooLargeError):
    return _error(413, str(exc))


@app.exception_handler(AgentUnavailableError)
async def _agent_unavailable(request: Request, exc: AgentUnavailableError):
    logger.warning("agent unavailable: %s", exc)
    return _error(503, str(exc))


@app.exception_handler(BackendError)
async def _backend_failed(request: Request, exc: BackendError):
    logger.error("backend failed: %s", exc)
    return _error(500, str(exc))