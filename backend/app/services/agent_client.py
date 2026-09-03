"""Client for talking to the agent service.

The backend never calls a model itself — it sends the conversation to the agent
over HTTP and gets back the reply text. This module is that boundary.

The backend deliberately knows nothing about what the agent does internally —
whether it retrieves documents, reasons in a graph, or calls a model directly.

The agent runs as a separate service (default http://localhost:8001). Its
address comes from AGENT_BASE_URL so the two can live on different hosts/ports
in any environment.
"""

import httpx

from app.core.config import settings


async def generate_reply(messages: list[dict[str, str]]) -> str:
    """Ask the agent to generate a reply for this conversation.

    `messages` is a list of {"role": "user"|"assistant", "content": str},
    oldest first. Returns the assistant's reply text.
    """
    url = f"{settings.agent_base_url}/generate"

    async with httpx.AsyncClient(timeout=settings.agent_timeout) as client:
        response = await client.post(url, json={"messages": messages})
        response.raise_for_status()
        data = response.json()

    return data["text"]
