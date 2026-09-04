"""OpenRouter chat model.

The only file in the agent that imports a vendor SDK. OpenRouter speaks the
OpenAI wire protocol, so the OpenAI client works unchanged — it is just pointed
at a different base_url.

Vendor exceptions are translated to ProviderError here so that nothing outside
this module ever imports `openai`.
"""

from typing import AsyncIterator

import openai

from app.providers.base import Chunk, ProviderError


class OpenRouterChatModel:
    """Satisfies the ChatModel protocol in base.py.

    Note it does not inherit from ChatModel — having matching methods is the
    whole contract (structural typing).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        site_url: str = "",
        app_name: str = "",
    ) -> None:
        self.model = model

        # OpenRouter uses these for its public leaderboards. Both are optional,
        # so only send the ones that are actually configured.
        default_headers: dict[str, str] = {}
        if site_url:
            default_headers["HTTP-Referer"] = site_url
        if app_name:
            default_headers["X-Title"] = app_name

        # Async client: a blocking HTTP call inside an async route would stall
        # the event loop and serialise every concurrent request.
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or None,
        )

    def _payload(self, messages: list[dict[str, str]], system: str) -> list[dict[str, str]]:
        """Prepend the system prompt.

        The OpenAI format carries the system prompt as the first message,
        unlike Anthropic's top-level `system` parameter.
        """
        return [{"role": "system", "content": system}, *messages]

    def _translate(self, exc: Exception) -> ProviderError:
        """Turn a vendor exception into our own, with an actionable message."""
        if isinstance(exc, openai.AuthenticationError):
            return ProviderError(
                "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in "
                f"agent/.env. Provider said: {exc}"
            )
        if isinstance(exc, openai.NotFoundError):
            return ProviderError(
                f"Model '{self.model}' was not found. Free model ids change — "
                f"verify it at https://openrouter.ai/models. Provider said: {exc}"
            )
        if isinstance(exc, openai.RateLimitError):
            return ProviderError(
                "OpenRouter rate limited this request. This can mean the "
                "per-minute cap, the daily free-tier quota, or the model being "
                f"at upstream capacity. Provider said: {exc}"
            )
        return ProviderError(f"OpenRouter request failed: {exc}")

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send the conversation and return the whole reply at once."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=self._payload(messages, system),
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except openai.APIError as exc:
            raise self._translate(exc) from exc

        # A provider can return a response with no choices (content filtered,
        # upstream model error). Treat that as a failure rather than "".
        if not response.choices:
            raise ProviderError("OpenRouter returned no choices.")

        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[Chunk]:
        """Send the conversation and yield Chunks as they are generated.

        Failures can happen in two places: when opening the stream, and partway
        through it. Both are translated to ProviderError — the caller decides
        whether that becomes a 502 or a mid-stream `error` event.
        """
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=self._payload(messages, system),
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
        except openai.APIError as exc:
            raise self._translate(exc) from exc

        try:
            async for chunk in stream:
                # Some chunks carry no choices at all (keepalives, usage-only
                # final frames). Skip rather than index into an empty list.
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # Reasoning models stream their chain of thought here first and
                # leave `content` empty until they are done thinking. Reading
                # only `content` makes them look like a hung connection.
                reasoning = getattr(delta, "reasoning", None)
                if reasoning:
                    yield Chunk("reasoning", reasoning)

                if delta.content:
                    yield Chunk("content", delta.content)
        except openai.APIError as exc:
            raise self._translate(exc) from exc
        finally:
            # If the caller stops consuming (client disconnected), close the
            # upstream connection so we stop paying for tokens nobody reads.
            await stream.close()
