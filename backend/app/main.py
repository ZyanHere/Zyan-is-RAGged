"""The backend service.

    frontend :3000  ──HTTP──▶  backend :8000  ──HTTP──▶  agent :8001

The only service the browser talks to, which is why it is the only one with
CORS. It holds no model keys, no prompts and no engine imports.

At stage 1.1 it forwards and little else. Modules 1.2 through 9 fill it in:
Postgres, jobs, retries, quotas, rate limiting, caching. The shape is here so
those land in a place that already exists.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import documents, health, query
from app.core.config import get_settings
from app.db.session import create_database, verify_connectivity
from app.errors import (
    AgentUnavailableError,
    BackendError,
    BadUploadError,
    ConflictError,
    NotFoundError,
    UploadTooLargeError,
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the database connection pool, and dispose of it on shutdown.

    The engine is built here rather than at module import for two reasons.

    An async engine binds its pooled connections to the event loop that opened
    them, and this module is imported by uvicorn, by pytest and (indirectly) by
    Alembic — each running its own loop. A module-level engine eventually hands
    a connection made on one loop to code running on another, and the error
    says "attached to a different loop" without naming anything that caused it.

    And a pool created at import has no shutdown. Every `uvicorn --reload`
    would abandon its open connections, and after enough reloads Postgres
    starts answering "sorry, too many clients already" to a process that is
    barely doing anything.

    The `SELECT 1` turns a stopped database into a refusal to start, with a
    sentence that says so — instead of an opaque 500 on the first upload, with
    a stack trace about connection pools.
    """
    settings = get_settings()
    database = create_database(settings)

    try:
        await verify_connectivity(database.engine)
    except Exception as exc:
        logger.error(
            "Cannot reach the database. Is Postgres running? "
            "`docker compose up -d` from the repository root. (%s)",
            exc,
        )
        await database.engine.dispose()
        raise

    app.state.database = database
    logger.info("database pool ready")

    try:
        yield
    finally:
        # Runs on normal shutdown and on a failed startup alike, so a crash
        # does not leave connections held open against the server.
        await database.engine.dispose()
        logger.info("database pool disposed")


app = FastAPI(
    title="myRAG backend",
    description="The reliability layer. Owns durability, not intelligence.",
    version="0.1.0",
    lifespan=lifespan,
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
#   NotFoundError          404
#   UploadTooLargeError    413
#   ConflictError          409   well formed, but not against this state
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


@app.exception_handler(NotFoundError)
async def _not_found(request: Request, exc: NotFoundError):
    return _error(404, str(exc))


@app.exception_handler(UploadTooLargeError)
async def _upload_too_large(request: Request, exc: UploadTooLargeError):
    return _error(413, str(exc))


@app.exception_handler(ConflictError)
async def _conflict(request: Request, exc: ConflictError):
    return _error(409, str(exc))


@app.exception_handler(AgentUnavailableError)
async def _agent_unavailable(request: Request, exc: AgentUnavailableError):
    logger.warning("agent unavailable: %s", exc)
    return _error(503, str(exc))


@app.exception_handler(BackendError)
async def _backend_failed(request: Request, exc: BackendError):
    logger.error("backend failed: %s", exc)
    return _error(500, str(exc))