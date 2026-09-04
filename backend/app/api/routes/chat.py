"""Chat route — POST /api/chat.

Takes the user's message, remembers it, asks the agent, streams the reply back
token by token, and records the finished reply. No documents, no retrieval.

Conversation history is kept in a plain in-memory dict. It is ephemeral — it
resets every time the server restarts, and it is not shared across processes.
Real persistence (a database) is the next slice; this is enough to make
multi-turn chat work today.
"""

import json
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.sse import SSE_HEADERS, sse_event
from app.schemas.chat import ChatRequest
from app.services import agent_client

router = APIRouter(prefix="/api", tags=["chat"])

# { conversationId: [ {"role": "user"|"assistant", "content": str}, ... ] }
_conversations: dict[str, list[dict[str, str]]] = {}


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Stream an assistant reply as SSE.

    Always responds 200 — see the agent's generate_stream for why a streamed
    endpoint reports failure as an `error` event rather than an HTTP status.

    Events forwarded from the agent (start / token / error / done) pass through
    untouched. This route adds `message_id` to `start` so the client can
    identify the message it is building, and guarantees an `error` event if the
    agent itself is unreachable.
    """
    history = _conversations.setdefault(req.conversationId, [])
    history.append({"role": "user", "content": req.content})

    message_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    async def event_stream() -> AsyncIterator[str]:
        # Accumulated so the completed reply can be stored once the stream ends.
        parts: list[str] = []
        completed = False

        yield sse_event(
            "start",
            {"messageId": message_id, "createdAt": created_at},
        )

        current_event: str | None = None
        skip_block = False

        try:
            async for line in agent_client.stream_reply(history):
                # Observe token events to build the reply, but forward every
                # line unchanged — we do not own the agent's event schema.
                if line.startswith("event: "):
                    current_event = line[len("event: ") :].strip()
                    # We emit our own `start` (carrying messageId), so the
                    # agent's is dropped. The whole block must go, not just
                    # this line, or its `data:` arrives orphaned and malformed.
                    skip_block = current_event == "start"
                    if current_event == "done":
                        completed = True
                elif line.startswith("data: ") and current_event == "token":
                    # Observe tokens to rebuild the reply for storage. Every
                    # line is still forwarded verbatim: we do not own the
                    # agent's event schema, we only read the part we need.
                    try:
                        payload = json.loads(line[len("data: ") :])
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                        parts.append(payload["text"])

                if skip_block:
                    if line == "":
                        skip_block = False
                    continue

                yield f"{line}\n" if line else "\n"

        except httpx.HTTPError as exc:
            yield sse_event(
                "error",
                {"message": f"Agent request failed: {exc}", "retryable": True},
            )
        finally:
            # Runs on success, on error, and on client disconnect. Whatever was
            # generated is kept: the tokens were paid for, and a user who
            # pressed Stop still expects to see what arrived.
            text = "".join(parts)
            if text:
                history.append({"role": "assistant", "content": text})
            elif not completed:
                # Nothing usable came back, so drop the user turn too. Without
                # this, a retry would append the same question twice.
                if history and history[-1]["role"] == "user":
                    history.pop()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
