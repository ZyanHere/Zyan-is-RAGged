import openai

from app.providers.base import ProviderError


class OpenRouterChatModel:
    """Satisfies the ChatModel protocol in base.py.

    Note it does not inherit from ChatModel — having a matching `complete`
    method is the whole contract (structural typing).
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

        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or None,
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send the conversation to the model and return the reply text.

        `messages` is [{"role": "user"|"assistant", "content": str}], oldest
        first. The system prompt is prepended as its own message — the OpenAI
        format carries it in the messages array, unlike Anthropic's top-level
        `system` parameter.
        """
        payload = [{"role": "system", "content": system}, *messages]

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in agent/.env."
            ) from exc
        except openai.NotFoundError as exc:
            raise ProviderError(
                f"Model '{self.model}' was not found. Free model ids change — "
                "verify it at https://openrouter.ai/models."
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(
                "OpenRouter rate limit hit. The free tier allows only a few "
                "requests per minute — wait and retry."
            ) from exc
        except openai.APIError as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc

        # A provider can return a response with no choices (content filtered,
        # upstream model error). Treat that as a failure rather than "".
        if not response.choices:
            raise ProviderError("OpenRouter returned no choices.")

        return response.choices[0].message.content or ""