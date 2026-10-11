"""Test database setup.

These are the project's first **integration** tests. The curriculum's testing
thread puts them exactly here — "do the pieces agree across a real DB?" — and
that question cannot be answered against a fake.

── Why a real Postgres and not SQLite ───────────────────────────────────────

SQLite would make these tests faster and completely worthless. The things being
tested are CHECK constraints, a foreign key with ON DELETE CASCADE, and column
types that SQLite either implements differently or ignores. A green suite
against SQLite would tell you nothing about the database you actually run — and
at stage 2.1 the `SELECT ... FOR UPDATE SKIP LOCKED` that the whole job queue
depends on does not exist in SQLite at all.

The rule: **test against the database you deploy.**

── Isolation ────────────────────────────────────────────────────────────────

A separate database, `myrag_test`, dropped and recreated once per session, then
migrated with Alembic — the same migrations that run in development, so the
tests also prove the migrations produce the schema the models expect.

Each test then runs inside a transaction that is rolled back afterwards. That
is faster than truncating tables between tests, and it lets a test call
`session.commit()` and observe the result without leaking anything into the
next one.
"""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

TEST_DB_SUFFIX = "_test"


def _test_database_url() -> str:
    """The development DSN, pointed at a database named `<name>_test`.

    Derived rather than configured separately so there is still one place the
    host, port and credentials are written down.
    """
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}{TEST_DB_SUFFIX}").render_as_string(
        hide_password=False
    )


def _guard(url_str: str) -> str:
    """Refuse to touch a database that is not obviously a test database.

    This fixture drops the database it points at. If `DATABASE_URL` were ever
    misconfigured — a stray environment variable, a copied `.env`, a cloud DSN
    pasted in for a one-off check — the fixture would destroy real data, and
    the mistake would be unrecoverable and completely silent.

    One `if` prevents the worst thing in this file from happening.
    """
    name = make_url(url_str).database or ""
    if not name.endswith(TEST_DB_SUFFIX):
        raise RuntimeError(
            f"Refusing to run: the test database is '{name}', which does not "
            f"end in '{TEST_DB_SUFFIX}'. This fixture DROPS that database."
        )
    return url_str


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _guard(_test_database_url())


@pytest.fixture(scope="session", autouse=True)
def _create_test_database(test_database_url: str) -> AsyncIterator[None]:
    """Drop, create and migrate `myrag_test` once for the whole session.

    Two details worth knowing:

    **`CREATE DATABASE` cannot run inside a transaction**, so this connects
    with asyncpg directly rather than through SQLAlchemy, which wraps work in
    one by default.

    **It connects to the `postgres` maintenance database** — you cannot drop a
    database you are connected to.

    Alembic is then run against the fresh database rather than
    `Base.metadata.create_all()`. `create_all` would be faster and would skip
    the migrations entirely, which means the tests would never notice a
    migration that does not reproduce the models. Running them here makes every
    test run a migration test.
    """
    url = make_url(test_database_url)
    db_name = url.database
    admin_dsn = url.set(database="postgres", drivername="postgresql").render_as_string(
        hide_password=False
    )

    async def recreate() -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            # Disconnect anything still attached, or the DROP blocks forever.
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                db_name,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            await conn.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await conn.close()

    asyncio.run(recreate())

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.upgrade(config, "head")

    yield


@pytest_asyncio.fixture
async def connection(test_database_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection with an open transaction that is always rolled back.

    The engine is created per test rather than once per session because each
    test gets its own event loop, and a pooled asyncpg connection belongs to
    the loop that opened it. Sharing one across loops produces
    "attached to a different loop" errors far from their cause.
    """
    engine = create_async_engine(test_database_url, poolclass=None)
    conn = await engine.connect()
    transaction = await conn.begin()
    try:
        yield conn
    finally:
        # Unconditional: a test that committed, failed, or raised all leave the
        # database exactly as they found it.
        await transaction.rollback()
        await conn.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session bound to the test's transaction.

    `join_transaction_mode="create_savepoint"` is what makes
    `await session.commit()` safe here: instead of committing the outer
    transaction, the session commits a SAVEPOINT inside it. The test sees
    committed behaviour — constraints fire, data is visible to subsequent
    queries on the same connection — and the outer rollback still discards
    everything.

    Without it, a `commit()` inside a test would end the outer transaction and
    the rollback in `connection` would have nothing left to undo.
    """
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as s:
        yield s
