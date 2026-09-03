"""Chat route — POST /api/chat.

This is the whole read-path for now: take the user's message, remember it,
ask the model, remember the reply, send it back. No documents, no retrieval.

Conversation history is kept in a plain in-memory dict. It is ephemeral — it
resets every time the server restarts, and it is not shared across processes.
Real persistence (a database) is a later slice; this is enough to make
multi-turn chat work today.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from app.services import agent_client

router = APIRouter(prefix="/api", tags=["chat"])

# { conversationId: [ {"role": "user"|"assistant", "content": str}, ... ] }
_conversations: dict[str, list[dict[str, str]]] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    history = _conversations.setdefault(req.conversationId, [])
    history.append({"role": "user", "content": req.content})

    try:
        reply_text = await agent_client.generate_reply(history)
    except Exception as exc:
        # Roll back the user turn so a retry does not double-append it.
        # (Broad catch for this first slice — we'll add typed error handling later.)
        history.pop()
        raise HTTPException(
            status_code=502, detail=f"Agent request failed: {exc}"
        ) from exc

    history.append({"role": "assistant", "content": reply_text})

    return ChatResponse(
        message=ChatMessage(
            id=str(uuid4()),
            role="assistant",
            content=reply_text,
            citations=[],
            createdAt=datetime.now(timezone.utc).isoformat(),
        )
    )
