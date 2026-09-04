"""Generate routes.

    POST /generate         whole reply, one JSON response
    POST /generate/stream  reply streamed as SSE tokens

Both are stateless — the backend owns conversation history and sessions. The
non-streaming route stays because it is the simpler thing to test and debug
with, and because the future RAG engine's `answer()` is non-streaming too.
"""

from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.sse import SSE_HEADERS, sse_event
from app.providers.base import ProviderError
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.services import llm

router = APIRouter(tags=["generate"])


def _to_dicts(req: GenerateRequest) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in req.messages]


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        text = await llm.generate_reply(_to_dicts(req))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return GenerateResponse(text=text)


@router.post("/generate/stream")
async def generate_stream(req: GenerateRequest) -> StreamingResponse:
    """Stream the reply as SSE.

    Always responds 200. Once a StreamingResponse is returned the status line
    has already been sent, so a failure — whether immediate or partway through
    generation — is reported as an `error` event rather than an HTTP status.
    Consumers must therefore treat `error` as a real outcome, not an edge case.

    Events emitted:
        start  {}                             sent immediately, before the model
                                              is even reached, so the client can
                                              show activity during the wait
        token      {"text": "..."}            answer text, zero or more
        reasoning  {"text": "..."}            chain of thought, zero or more,
                                              only from reasoning models
        error  {"message", "retryable"}       terminal
        done   {"stopReason": "end_turn"}     terminal
    """
    messages = _to_dicts(req)

    async def event_stream() -> AsyncIterator[str]:
        # Flush something immediately. Time-to-first-token can be seconds, and
        # this is what lets the UI distinguish "working" from "hung".
        yield sse_event("start", {})

        try:
            async for chunk in llm.stream_reply(messages):
                # Two event names, so the UI can show answer text and "thinking"
                # differently without inspecting the payload.
                name = "token" if chunk.kind == "content" else "reasoning"
                yield sse_event(name, {"text": chunk.text})
        except ProviderError as exc:
            yield sse_event("error", {"message": str(exc), "retryable": True})
            return
        except Exception as exc:  # noqa: BLE001 - last resort, must not hang the stream
            yield sse_event(
                "error",
                {"message": f"Unexpected agent error: {exc}", "retryable": False},
            )
            return

        yield sse_event("done", {"stopReason": "end_turn"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
