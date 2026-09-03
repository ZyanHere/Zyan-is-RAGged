from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "myRAG Backend"
    app_version: str = "0.1.0"
    app_env: str = Field(default="development", alias="APP_ENV")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    frontend_origin: str = Field(
        default="http://localhost:3000", alias="FRONTEND_ORIGIN"
    )

    # ── Agent service ─────────────────────────────────────────────────────────
    # The backend calls the agent over HTTP. All model config — API key,
    # model, prompt — lives in the agent, not here.
    agent_base_url: str = Field(
        default="http://localhost:8001", alias="AGENT_BASE_URL"
    )
    agent_timeout: float = Field(default=120.0, alias="AGENT_TIMEOUT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
