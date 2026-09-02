"""LLM service — what the route calls.

Thin by design. It supplies the generation settings from config and delegates
to whichever provider is configured. It imports no vendor SDK: that lives
behind `app.providers`.

When RAG arrives, retrieved document chunks get injected into the messages
here, before the provider call. The backend never has to know.
"""

from app.core.config import settings
from app.providers.base import get_chat_model

def generate_reply(messages: list[dict[str, str]]) -> str:
    """Send the conversation to the model and return the reply text.

    `messages` is a list of {"role": "user"|"assistant", "content": str},
    oldest message first. Chat APIs are stateless, so the caller resends the
    whole conversation every time — that is how the model "remembers" earlier
    turns.

    Raises ProviderError if the model cannot produce a reply; the route turns
    that into a 502.
    """

    model = get_chat_model()
    return model.complete(
        messages=messages,
        system=settings.chat_system_prompt,
        max_tokens=settings.chat_max_tokens,
        temperature=settings.chat_temperature,
    )