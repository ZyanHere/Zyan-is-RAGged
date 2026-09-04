"""The provider seam.

`get_chat_model()` is the only way the rest of the agent obtains something that
can talk to an LLM. Callers receive a `ChatModel` and never learn which vendor
is behind it.

Adding a paid provider later means: write one module next to this one, add a
branch to the factory, and change one env var. No caller changes.
"""

from functools import lru_cache
from typing import AsyncIterator, Literal, NamedTuple, Protocol

from app.core.config import settings


class Chunk(NamedTuple):
    """One piece of a streamed reply.

    Reasoning models emit their chain of thought before any answer text, on a
    separate channel. A client that reads only the answer sees nothing at all
    for many seconds and looks hung, so the two kinds travel together and the
    UI decides what to do with each.

    kind:
        "content"   text belonging to the answer
        "reasoning" the model thinking out loud, not part of the answer
    """

    kind: Literal["content", "reasoning"]
    text: str


class ChatModel(Protocol):
    """What every provider must be able to do.

    A Protocol is structural: a class satisfies this by having matching methods.
    It never needs to inherit from ChatModel, and this file never needs to
    import the providers that implement it.

    Both methods are async because a blocking call inside an async route stalls
    the whole event loop — every other request waits behind it.
    """

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send a conversation to the model and return the whole reply."""
        ...

    def stream(
        self,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[Chunk]:
        """Send a conversation and yield Chunks as they are generated.

        Not `async def` — an async generator function is called, not awaited,
        so its declared return type is the iterator itself.
        """
        ...


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a reply.

    The route layer converts this into a 502, or into an SSE `error` event when
    the failure happens mid-stream. Vendor-specific exceptions are translated
    here so callers never import an SDK's error classes.
    """


@lru_cache
def get_chat_model() -> ChatModel:
    """Build the configured chat model once and reuse it.

    Provider selection is driven by config, not by imports at the call site.
    """
    # Imported inside the function so that adding a provider never costs an
    # import for the providers you are not using.
    from app.providers.openrouter import OpenRouterChatModel

    return OpenRouterChatModel(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        site_url=settings.openrouter_site_url,
        app_name=settings.openrouter_app_name,
    )
