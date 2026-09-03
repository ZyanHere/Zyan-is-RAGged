from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "myRAG Agent"
    app_version: str = "0.1.0"
    app_env: str = Field(default="development", alias="APP_ENV")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8001, alias="PORT")

    # ── OpenRouter ────────────────────────────────────────────────────────────
    # The agent owns every LLM concern: the key, the model, the prompt.
    # Leave the key blank here and put it in agent/.env (never commit it).
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="deepseek/deepseek-chat-v3-0324:free", alias="OPENROUTER_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    # Optional attribution headers OpenRouter uses for its leaderboards.
    openrouter_site_url: str = Field(default="", alias="OPENROUTER_SITE_URL")
    openrouter_app_name: str = Field(default="myRAG", alias="OPENROUTER_APP_NAME")

    # ── Generation ────────────────────────────────────────────────────────────
    chat_max_tokens: int = Field(default=4096, alias="CHAT_MAX_TOKENS")
    chat_temperature: float = Field(default=0.3, alias="CHAT_TEMPERATURE")
    chat_system_prompt: str = Field(
        default=(
            "You are myRAG, a helpful assistant. Answer clearly and concisely. "
            # "You do not yet have access to the user's uploaded documents — "
            # "document retrieval will be added later — so answer from general "
            # "knowledge and say so if a question would require their documents."
        ),
        alias="CHAT_SYSTEM_PROMPT",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()