"""Client for talking to the agent service.

The backend never calls a model itself — it sends the conversation to the agent
over HTTP and gets back the reply. This module is that boundary.

The backend deliberately knows nothing about what the agent does internally —
whether it retrieves documents, reasons in a graph, or calls a model directly.

The agent runs as a separate service (default http://localhost:8001). Its
address comes from AGENT_BASE_URL so the two can live on different hosts/ports
in any environment.
"""

from typing import AsyncIterator

import httpx

from app.core.config import settings


async def generate_reply(messages: list[dict[str, str]]) -> str:
    """Ask the agent for a complete reply.

    `messages` is a list of {"role": "user"|"assistant", "content": str},
    oldest first. Returns the assistant's reply text.
    """
    url = f"{settings.agent_base_url}/generate"

    async with httpx.AsyncClient(timeout=settings.agent_timeout) as client:
        response = await client.post(url, json={"messages": messages})
        response.raise_for_status()
        data = response.json()

    return data["text"]


async def stream_reply(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """Ask the agent for a streamed reply, yielding raw SSE lines.

    Lines are forwarded to our own caller **verbatim** rather than being parsed
    and re-serialised. Two reasons: it is cheaper, and it means the agent can
    add new event types without the backend needing to learn about them.

    The caller still parses `token` events in order to accumulate the reply for
    persistence — observing the stream, without owning its schema.
    """
    url = f"{settings.agent_base_url}/generate/stream"

    async with httpx.AsyncClient(timeout=settings.agent_timeout) as client:
        async with client.stream(
            "POST", url, json={"messages": messages}
        ) as response:
            if response.status_code >= 400:
                # On a streaming response the body has not been read yet, so
                # raise_for_status() alone would give a message with no detail.
                body = (await response.aread()).decode(errors="replace")
                raise httpx.HTTPStatusError(
                    f"Agent returned {response.status_code}: {body[:500]}",
                    request=response.request,
                    response=response,
                )
            # aiter_lines handles the chunk-splitting problem for us on this
            # hop; the browser side has to solve it by hand (see lib/sse.ts).
            async for line in response.aiter_lines():
                yield line
