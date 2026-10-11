"""The engine and the session factory.

Infrastructure only: how a connection is obtained and how long it lives.
Nothing here knows what a document is.

── Why these are factories, not module-level objects ────────────────────────

`create_async_engine` looks harmless at module scope, and it is the most common
way to get this wrong. An async engine's pool binds its connections to the
event loop that opened them, and this module is imported by three things that
each run their own loop: uvicorn, pytest, and Alembic. A shared module-level
engine hands a connection created on one loop to code running on another, and
the error — "attached to a different loop" — names nothing that points at the
cause.

Building the engine inside `lifespan` also gives it a *shutdown*. Without
`dispose()`, every `uvicorn --reload` abandons a pool of open connections, and
after enough reloads Postgres answers "sorry, too many clients already" to a
process that is doing almost nothing.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


@dataclass(slots=True)
class Database:
    """An engine and the factory that makes sessions on it.

    Held on `app.state` for the lifetime of the process. Bundled into one
    object so the lifespan has a single thing to create and a single thing to
    tear down.
    """

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def create_database(settings: Settings) -> Database:
    """Build the engine and session factory from configuration."""
    engine = create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=settings.db_pool_pre_ping,
    )

    session_factory = async_sessionmaker(
        bind=engine,
        # Keep attributes readable after `commit()`.
        #
        # By default SQLAlchemy expires every object on commit, so the next
        # attribute access re-fetches it from the database. In async code that
        # re-fetch is a lazy load, which raises `MissingGreenlet` — so the
        # common pattern of committing and then reading `document.id` would
        # blow up for reasons that have nothing to do with ids.
        #
        # The trade is that an object held across commits can go stale. At this
        # scale nothing holds one that long.
        expire_on_commit=False,
    )

    return Database(engine=engine, session_factory=session_factory)


async def verify_connectivity(engine: AsyncEngine) -> None:
    """One `SELECT 1`, at startup, so a dead database fails loudly here.

    Without this, a stopped Postgres surfaces as an opaque 500 on the first
    upload — the "mysteriously at 3am" failure that stage 15.1 warns about,
    with a stack trace about connection pools rather than a sentence saying the
    database is not running.

    **This is not the same as `/health` checking the database.** Starting is a
    one-time event; liveness is continuous. A liveness probe that fails because
    a dependency is down invites a restart that cannot possibly help. At stage
    12.1, when a load balancer starts reading these answers, the distinction
    becomes `/health` (am I alive?) and `/readyz` (can I serve?).

    The cost, stated plainly: the service now refuses to start when Postgres is
    down, rather than starting and failing per request. For a backend whose
    entire job is durability, refusing is the honest behaviour.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A session with a managed lifetime and *unmanaged* transactions.

    It closes the session, and rolls back if the block raises. It does **not**
    commit — and that omission is deliberate rather than an oversight.

    The usual FastAPI recipe commits automatically at the end of the request.
    It would quietly destroy stage 1.2, whose entire point is this ordering:

        record intent  →  COMMIT  →  call the agent  →  record outcome

    An automatic commit at the end makes it natural to do all of that in one
    transaction. A crash during the agent call then loses the intent record
    along with everything else, and the system is exactly as blind as it was
    before the database existed.

    So commits are explicit, at the call site, where the ordering is visible
    and reviewable.
    """
    async with factory() as session:
        try:
            yield session
        except Exception:
            # The session would roll back on close anyway. Doing it here makes
            # the rollback part of the failure path rather than a side effect
            # of garbage collection.
            await session.rollback()
            raise
