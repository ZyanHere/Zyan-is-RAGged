"""The backend's one connection to the agent.

Every call from backend to agent goes through this module. That is what makes
`backend → agent` a boundary you can find, instrument and later put a retry
policy behind, rather than a scattering of httpx calls.

**The backend never imports `rag`.** It learns what happened to a document from
the agent's HTTP response and nothing else. That rule is what keeps stage 1.3's
worker split possible at all.

At stage 1.1 this client is a pass-through: no retries, no circuit breaker, no
timeouts beyond a blunt overall one. Those arrive in module 7, each earned by an
observed failure. Adding them now would be guessing.
"""

import httpx

from app.core.config import get_settings
from app.errors import AgentUnavailableError


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.agent_base_url,
        timeout=settings.agent_timeout,
    )


async def ingest_document(
    *, filename: str, content: bytes, content_type: str | None
) -> tuple[int, dict]:
    """Forward an upload to the agent.

    Returns the agent's status code alongside its JSON body so the route can
    pass both through unchanged. Translating the agent's errors here would mean
    inventing a second error vocabulary for no benefit — at stage 1.1 the agent
    is the authority on what went wrong with a document.
    """
    settings = get_settings()
    files = {"file": (filename, content, content_type or "application/pdf")}

    try:
        async with _client() as client:
            response = await client.post("/documents", files=files)
    except httpx.TimeoutException as exc:
        raise AgentUnavailableError(
            f"The agent did not respond within {settings.agent_timeout:.0f}s. "
            f"Ingestion is synchronous at this stage, so a large PDF can exceed "
            f"it — the document may still be indexing."
        ) from exc
    except httpx.HTTPError as exc:
        raise AgentUnavailableError(
            f"Could not reach the agent at {settings.agent_base_url}: {exc}. "
            f"Is it running on port 8001?"
        ) from exc

    return response.status_code, _json_of(response)


async def query(*, question: str, top_k: int | None) -> tuple[int, dict]:
    """Forward a question to the agent."""
    settings = get_settings()

    payload: dict[str, object] = {"question": question}
    if top_k is not None:
        payload["top_k"] = top_k

    try:
        async with _client() as client:
            response = await client.post("/query", json=payload)
    except httpx.TimeoutException as exc:
        raise AgentUnavailableError(
            f"The agent did not respond within {settings.agent_timeout:.0f}s."
        ) from exc
    except httpx.HTTPError as exc:
        raise AgentUnavailableError(
            f"Could not reach the agent at {settings.agent_base_url}: {exc}. "
            f"Is it running on port 8001?"
        ) from exc

    return response.status_code, _json_of(response)


def _json_of(response: httpx.Response) -> dict:
    """Decode a response body, tolerating one that is not JSON.

    An upstream crash or a proxy error page arrives as HTML with a 5xx. Letting
    the decode error escape would replace a useful upstream status with a
    confusing local one.
    """
    try:
        body = response.json()
    except ValueError:
        return {
            "detail": (
                f"The agent returned a non-JSON response "
                f"({response.status_code}): {response.text[:200]}"
            )
        }
    return body if isinstance(body, dict) else {"detail": body}