"""Server-Sent Events formatting.

Mirrors the agent's helper. Kept separate rather than shared because the two
services are deployable independently — a shared module would couple them at
the source level, which is exactly what the HTTP boundary exists to avoid.
"""

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format one named SSE event with a JSON payload."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
