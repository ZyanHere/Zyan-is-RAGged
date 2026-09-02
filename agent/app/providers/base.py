from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class ChatModel(Protocol):
    """What every provider must be able to do.

    A Protocol is structural: a class satisfies this by having a matching
    `complete` method. It never needs to inherit from ChatModel, and this file
    never needs to import the providers that implement it.
    """

    def complete(
        self,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send a conversation to the model and return the reply text."""
        ...


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a reply.

    The route layer converts this into a 502. Vendor-specific exceptions are
    translated here so callers never import an SDK's error classes.
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


