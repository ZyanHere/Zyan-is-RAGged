"""Server-Sent Events formatting.

SSE is a plain-text HTTP streaming format. One event looks like:

    event: token\n
    data: {"text": "Hello"}\n
    \n

The blank line terminates the event. That double newline is the only framing
there is, which is why a consumer must buffer across network chunks — a chunk
can arrive split anywhere, including in the middle of an event.

We use SSE rather than WebSockets because the traffic is one-directional
(server to client), it is ordinary HTTP so proxies and auth work unchanged, and
the browser needs no special protocol handling.
"""

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format one named SSE event with a JSON payload."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Streaming responses must not be buffered by anything between here and the
# browser, or the tokens arrive in one clump at the end and streaming is
# pointless. `X-Accel-Buffering` disables nginx buffering specifically.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
