"""LLM service — what the routes call.

Thin by design. It supplies the generation settings from config and delegates
to whichever provider is configured. It imports no vendor SDK: that lives
behind `app.providers`.

When RAG arrives, retrieved document chunks get injected into the messages
here, before the provider call. The backend never has to know.
"""

from typing import AsyncIterator

from app.core.config import settings
from app.providers.base import Chunk, get_chat_model


def _settings_kwargs() -> dict[str, object]:
    """Generation settings, in one place so both paths cannot drift apart."""
    return {
        "system": settings.chat_system_prompt,
        "max_tokens": settings.chat_max_tokens,
        "temperature": settings.chat_temperature,
    }


async def generate_reply(messages: list[dict[str, str]]) -> str:
    """Send the conversation to the model and return the whole reply.

    `messages` is a list of {"role": "user"|"assistant", "content": str},
    oldest message first. Chat APIs are stateless, so the caller resends the
    whole conversation every time — that is how the model "remembers" earlier
    turns.

    Raises ProviderError if the model cannot produce a reply.
    """
    model = get_chat_model()
    return await model.complete(messages=messages, **_settings_kwargs())


async def stream_reply(messages: list[dict[str, str]]) -> AsyncIterator[Chunk]:
    """Same as generate_reply, but yields Chunks as they are produced.

    Raises ProviderError — possibly partway through, after some text has
    already been yielded. Callers must handle a failure that arrives late.
    """
    model = get_chat_model()
    async for piece in model.stream(messages=messages, **_settings_kwargs()):
        yield piece
