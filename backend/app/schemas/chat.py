"""Chat API request/response models.

These mirror the TypeScript types in `frontend/src/types/index.ts` exactly,
so the field names are camelCase (conversationId, createdAt, ...) rather than
the usual Python snake_case. Keeping the shapes identical on both sides means
the frontend and backend agree on the contract with zero translation layer.
"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Body the frontend POSTs to /api/chat."""

    conversationId: str
    content: str


class Citation(BaseModel):
    """A source reference. Unused for now (no RAG yet), but the shape exists so
    the frontend's citation UI keeps working once retrieval is added."""

    id: str
    documentId: str
    documentTitle: str
    excerpt: str
    pageNumber: int | None = None
    chunkIndex: int | None = None


class ChatMessage(BaseModel):
    """A single assistant message returned to the frontend."""

    id: str
    role: str
    content: str
    citations: list[Citation] = []
    createdAt: str


class ChatResponse(BaseModel):
    """What /api/chat returns: { message: ... }."""

    message: ChatMessage
