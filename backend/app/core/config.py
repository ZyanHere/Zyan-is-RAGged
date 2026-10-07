"""Backend configuration.

The backend holds no model keys and no engine settings. It knows where the
agent is, how long to wait for it, who may call it, and how large an upload it
will accept. That is the whole list, and it is short on purpose — the day it
grows an LLM setting is the day the layering has broken.

No module-level instance, for the same reason as the agent: importing a module
should not require a configured environment.
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

    agent_base_url: str = "http://localhost:8001"

    # Generous because stage 1.1 ingestion is synchronous and a large PDF
    # genuinely takes minutes. This number is a placeholder for a missing
    # queue, and stage 1.3 is where it stops being needed.
    agent_timeout: float = Field(default=120.0, gt=0)

    # The outermost boundary, and the one that matters most: this is where an
    # oversized upload would otherwise be buffered in memory before being
    # forwarded. The agent enforces its own limit independently.
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)

    # Comma-separated for multiple origins.
    frontend_origin: str = "http://localhost:3000"

    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.frontend_origin.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()