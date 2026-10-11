"""FastAPI dependencies.

The seam between the framework and everything else. Routes declare what they
need; this module knows where it comes from.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database, session_scope
from app.repositories.documents import DocumentRepository
from app.services import agent_client
from app.services.ingestion import AgentClient


def get_database(request: Request) -> Database:
    """The engine and session factory, created once in `lifespan`.

    Read from `app.state` rather than a module-level global, which is what lets
    the engine be created and disposed with the application rather than with
    the import.
    """
    return request.app.state.database


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """A session for one request.

    Lifetime only. It does not commit — see `session_scope`. A route that
    writes commits explicitly, because *when* the commit happens is the
    substance of stage 1.2 rather than a detail to hide in a dependency.
    """
    async with session_scope(database.session_factory) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_document_repository(session: SessionDep) -> DocumentRepository:
    """A repository bound to this request's session.

    Routes depend on this rather than constructing it, so a test can override
    the dependency with a fake and never touch a database.
    """
    return DocumentRepository(session)


DocumentRepositoryDep = Annotated[
    DocumentRepository, Depends(get_document_repository)
]
"""Written as an `Annotated` alias so a route signature reads

    async def upload(repo: DocumentRepositoryDep) -> ...

rather than repeating `Depends(...)` at every call site. One place to change if
the wiring ever does.
"""


def get_agent_client() -> AgentClient:
    """The module that talks to the agent service.

    A dependency rather than a direct import inside the route, for one concrete
    reason: a test that wants to observe what the backend records when the
    agent fails must be able to make it fail *deterministically*.

    Without this, the only way to test "the agent is down" was for the agent to
    actually be down — so the test passed on a machine where nothing was
    running and failed the moment `docker compose up` started one. A test whose
    result depends on what else happens to be running is not a test.
    """
    return agent_client


AgentClientDep = Annotated[AgentClient, Depends(get_agent_client)]
