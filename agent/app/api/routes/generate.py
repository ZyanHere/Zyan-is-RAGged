"""Generate route — POST /generate.

The agent's whole job for now: take a conversation, ask the model, return the
reply text. Stateless — the backend owns conversation history and sessions.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services import llm

router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    try:
        text = llm.generate_reply(messages)
    except Exception as exc:
        # Broad catch for this first slice — typed error handling comes later.
        raise HTTPException(
            status_code=502, detail=f"LLM request failed: {exc}"
        ) from exc

    return GenerateResponse(text=text)
