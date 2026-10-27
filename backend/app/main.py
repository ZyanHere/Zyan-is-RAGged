"""The backend service.

    frontend :3000  ──HTTP──▶  backend :8000  ──HTTP──▶  agent :8001

The only service the browser talks to, which is why it is the only one with
CORS. It holds no model keys, no prompts and no engine imports.

At stage 1.1 it forwards and little else. Modules 1.2 through 9 fill it in:
Postgres, jobs, retries, quotas, rate limiting, caching. The shape is here so
those land in a place that already exists.
"""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import documents, health, query, stats
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.db.session import create_database, verify_connectivity
from app.errors import (
    AgentUnavailableError,
    BackendError,
    BadUploadError,
    ConflictError,
    NotFoundError,
    UploadTooLargeError,
)

# At import, not in `lifespan`.
#
# uvicorn imports this module and only then starts the server, so configuring
# here means the very first line this process emits is already handled —
# including anything that fails during `lifespan` itself. Doing it inside
# `lifespan` would leave the window where a startup failure is reported
# through `logging.lastResort`, which is the one moment it matters most.
#
# It is also why this is safe to do at import where the database engine is
# deliberately not: logging has no event loop to bind to and nothing to
# dispose.
configure_logging()

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

REQUEST_ID_HEADER = "X-Request-ID"

SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""What an inbound request id is allowed to look like.

**This is a log-injection guard, not tidiness.** The id is written into every
log line for the request and into a database column, so an unvalidated header
lets a caller write our observations for us.

── What this actually protects against, checked rather than assumed ──────────

**Length and charset.** A 200-character inbound id is replaced with a generated
one; verified live. Nothing else bounds it — `String(64)` would truncate or
raise at the database, which is far too late to be the first line of defence.

**Not, primarily, newlines.** The obvious threat is a value containing CRLF,
closing the current log line and forging a convincing `ERROR` of its own. Over
HTTP/1.1 that does not reach us: h11 parses `X-Request-ID: evil

X-Injected:
yes` as *two headers*, so the application sees `evil`. Tested with a raw
socket.

The pattern still refuses newlines, because the guard should not depend on
which parser happens to be in front of it — but claiming CRLF is what it is
*for* would overstate it. Length and charset are what it uniquely buys.

Anything that does not match is ignored and a fresh id is generated. Rejecting
the request instead would be worse: a malformed correlation header is not a
reason to refuse to index someone's document.
"""


@app.middleware("http")
async def attach_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Give every request an id, and put it where the logs can find it.

    ── Why an inbound header is honoured at all ──────────────────────────────

    So that a gateway, a load balancer or a calling service that already
    assigned an id wins. If this always generated its own, the id in our logs
    would be unrelated to the id in theirs, and correlation would stop at our
    front door — which is the one place it is most often needed.

    Nothing upstream sets it today. Accepting it costs one regex and means the
    day something does, nothing has to change here.

    ── Why the id is set on a `ContextVar` and not passed down ───────────────

    A logging filter reads it, so no call site mentions it. `services/` and
    `repositories/` have no idea a request id exists, which is the point: a
    value threaded by hand through every signature goes missing from exactly
    the line you needed.

    ── Why the token is reset ────────────────────────────────────────────────

    `ContextVar` values are per-context, and anyio reuses the task that runs
    this. Without the reset, a request that finished could leave its id
    visible to whatever runs next on that task — so a log line would carry a
    correlation id for an unrelated request, which is worse than carrying
    none.
    """
    inbound = request.headers.get(REQUEST_ID_HEADER)
    request_id = (
        inbound
        if inbound and SAFE_REQUEST_ID.match(inbound)
        # Twelve hex characters, not a full UUID. It is read by humans in log
        # lines and typed into `grep`; 48 bits is ample to separate the
        # requests alive at one moment, which is all correlation needs.
        else uuid.uuid4().hex[:12]
    )

    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)

    # On the response so a caller can quote it in a bug report, and so the
    # frontend can show it. See `expose_headers` below — without that, a
    # browser can read this header only on a same-origin response.
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the header above is set and **invisible to the browser**.
    # CORS hides every response header except a short safelist, so JavaScript
    # reading `X-Request-ID` would get `null` with no error anywhere — the
    # same shape of silent failure this whole stage is about.
    expose_headers=[REQUEST_ID_HEADER, "Location"],
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(stats.router)


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