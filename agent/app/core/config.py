"""Agent configuration.

`rag` has its own `Settings` reading the same `.env` file. That is not
duplication — they are different values owned by different layers, and both
declare `extra="ignore"` so neither rejects the file for containing the other's
keys. The agent has no business knowing what EMBEDDING_DIM is; `rag` has no
business knowing an OpenRouter key exists.

**No module-level `settings` instance.** Building one at import time would mean
that importing *any* agent module executes configuration — so a unit test for a
pure string function could not run without an OpenRouter key in the
environment. Callers use `get_settings()`, which is cached, so the cost is one
function call and the gain is a package that can be imported without a
configured world.

**`top_k` is not here.** How many chunks retrieval returns is the engine's
concern and `rag` owns that default. The agent passes the caller's `top_k`
through — `None` included — rather than holding a second opinion about the same
environment variable.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── OpenRouter (chat) ─────────────────────────────────────────────────────
    openrouter_api_key: str
    openrouter_model: str = "deepseek/deepseek-chat-v3-0324:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "myRAG"

    # ── Generation ────────────────────────────────────────────────────────────
    chat_max_tokens: int = Field(default=4096, gt=0)
    # Low by default: this system quotes documents. Creativity is a defect here.
    chat_temperature: float = Field(default=0.3, ge=0.0, le=2.0)

    # ── Uploads ───────────────────────────────────────────────────────────────
    # Enforced here as well as at the backend. The agent must not assume it is
    # only ever called by our own backend — the same reason the request body is
    # validated at both boundaries.
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8001


@lru_cache
def get_settings() -> Settings:
    """Build the settings once and reuse them.

    `get_settings.cache_clear()` is the escape hatch a test uses after setting
    different environment variables.
    """
    return Settings()