"""Shared fixtures. **The agent's first tests, at stage 3.1.**

`requirements.txt` has listed `pytest` and `httpx` since stage 1.1 and nothing
ever used them. That is recorded rather than quietly fixed: the agent has been
the least-tested layer in this project for five stages, and the route this
directory was created for is one the evaluation harness depends on.

── Why `TestClient` and not the backend's `ASGITransport` ─────────────────────

`backend/tests/conftest.py` builds an `httpx.AsyncClient` over an
`httpx.ASGITransport` and runs async tests through `pytest-asyncio`. That is
the right shape *there*, because the backend's routes are `async def` and its
tests need async database access.

Neither applies here. `pytest_asyncio` is not installed in the agent's
virtualenv, `POST /retrieve` is a plain `def`, and `starlette.testclient`
arrives for free with FastAPI. So the divergence is a decision, not drift, and
the trigger to revisit it is the agent's first genuinely async route needing a
test.

── Nothing here needs configuration ──────────────────────────────────────────

`app/core/config.py` deliberately has no module-level `settings` instance, so
importing the application executes no configuration and these tests do not
need an OpenRouter key, a Google key, or an `agent/.env`. A test that passes or
fails depending on a developer's local environment is worse than no test.

Nothing here touches the network, a model provider, or a vector store either.
`rag.retrieve_many` is replaced; what is being exercised is routing,
validation, serialisation and `main.py`'s error table.
"""

import pytest
from fastapi.testclient import TestClient

import rag
from app.main import app
from rag.models import Chunk, RetrievedChunk


def chunk(text: str, *, page: int = 1, index: int = 0) -> RetrievedChunk:
    """One retrieved chunk, shaped like the real thing."""
    return RetrievedChunk(
        chunk=Chunk(
            document_id="doc-1",
            filename="doc.pdf",
            page=page,
            chunk_index=index,
            text=text,
        ),
        score=0.75,
    )


@pytest.fixture
def client() -> TestClient:
    """The real application, in process.

    Requests go through real routing, validation, dependency handling and the
    exception handlers in `main.py` — which is the part worth testing.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def retrieval(monkeypatch) -> list[dict]:
    """Replace `rag.retrieve_many`, and record what the route asked it for.

    Patched on the `rag` module itself, which is what `routes/retrieve.py`
    imports and what it looks the function up on at call time.

    The stand-in answers with one chunk per question whose text *is* the
    question, so a test can tell which result belongs to which question
    without depending on any vector arithmetic.
    """
    calls: list[dict] = []

    def fake_retrieve_many(questions, *, top_k=None):
        calls.append({"questions": list(questions), "top_k": top_k})
        return [[chunk(question)] for question in questions]

    monkeypatch.setattr(rag, "retrieve_many", fake_retrieve_many)
    return calls


@pytest.fixture
def no_chat_model(monkeypatch) -> None:
    """Make constructing a chat model an error.

    A guard against generation creeping into the measurement path. See
    `test_no_chat_model_is_constructed`.
    """
    import app.providers.base as provider_base

    def explode():
        raise AssertionError(
            "A chat model was constructed while serving POST /retrieve. That "
            "route exists to measure retrieval with no language model in the "
            "path at all."
        )

    monkeypatch.setattr(provider_base, "get_chat_model", explode)
