"""Backend configuration.

The backend holds no model keys and no engine settings. It knows where the
agent is, how long to wait for it, who may call it, how large an upload it will
accept, and — from stage 1.2 — where its database is. It still holds nothing
about prompts, models or embeddings: the day it grows an LLM setting is the day
the layering has broken.

No module-level instance, for the same reason as the agent: importing a module
should not require a configured environment.
"""

from functools import lru_cache

from pydantic import Field, field_validator
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

    # ── Database (stage 1.2) ──────────────────────────────────────────────────

    # One DSN rather than separate host/port/user/password fields.
    #
    # Twelve-factor, and it is the shape every managed provider hands you — AWS
    # RDS, Neon, Railway and Fly all give a single connection string. Assembling
    # one from five variables means five places for an environment to be half
    # configured, and a URL that exists nowhere you can paste into psql.
    #
    # The default points at the local Compose service. That is a deliberate
    # exception to "no secrets in defaults": these credentials are for a
    # throwaway container reachable only from this machine, they are written in
    # `docker-compose.yml` in this same repository, and anything resembling a
    # real deployment overrides the whole DSN. Stage 15.3 is where secret
    # handling becomes a real subject.
    #
    # Note the duplication: this default and the defaults in
    # `docker-compose.yml` must agree, and nothing enforces that. Change one and
    # you get a connection refused with no explanation of why.
    database_url: str = (
        "postgresql+asyncpg://myrag:myrag_dev_password@localhost:5432/myrag"
    )

    # Log every SQL statement the ORM generates.
    #
    # On in development on purpose. Stage 1.2's stated subject is relational
    # modelling, transactions and indexes, and an ORM's whole job is to hide the
    # SQL those are made of. Reading what SQLAlchemy actually emits — including
    # the BEGIN and COMMIT around each unit of work — is most of the lesson.
    #
    # It is noisy and it belongs off anywhere that matters, which is why it is a
    # setting rather than a hard-coded `True`.
    db_echo: bool = False

    # ── Connection pool ───────────────────────────────────────────────────────
    #
    # These are SQLAlchemy's own defaults, written out rather than inherited.
    # Pool sizing is one of stage 1.2's stated subjects and it is invisible
    # while it is implicit — and the arithmetic that matters is not obvious:
    #
    #     worker processes x (pool_size + max_overflow)  <=  Postgres max_connections
    #
    # Postgres defaults to 100. Four uvicorn workers at 5+10 each is 60, which
    # fits; eight workers is 120, which does not — and the failure is
    # "FATAL: sorry, too many clients already" at peak load, not at startup.
    #
    # Stage 8.3 is where these stop being guesses and become measured numbers.
    db_pool_size: int = Field(default=5, gt=0)
    """Connections kept open permanently."""

    db_max_overflow: int = Field(default=10, ge=0)
    """Extra connections opened under load, then closed again."""

    # ── Worker (stage 1.3) ────────────────────────────────────────────────────

    worker_poll_seconds: float = Field(default=1.0, gt=0)
    """How long the worker waits before asking for work again, when idle.

    **Polling, not notification.** Postgres has `LISTEN`/`NOTIFY`, which would
    wake the worker the instant a job is enqueued instead of up to a second
    later. It is not used, for a reason worth stating rather than defaulting
    into: `NOTIFY` is fire-and-forget, so a worker that is restarting when the
    notification fires misses it permanently and the job waits forever. Any
    correct design still needs the poll as a backstop — at which point the
    notification is a latency optimisation on top, not the mechanism.

    So the poll is the mechanism, and this number is the worst-case delay
    before a queued job is noticed. One second costs one query per idle worker
    per second against a local Postgres, which is nothing; `NOTIFY` becomes
    worth adding when the idle cost or the added latency is measured and
    matters.

    `gt=0` because zero would be a busy loop that pins a core and hammers the
    database for no benefit.
    """

    db_pool_pre_ping: bool = True
    """Check a pooled connection is alive before handing it out.

    Costs a round trip per checkout and prevents the most annoying class of
    error in development: Postgres restarts inside Docker, every pooled
    connection is now dead, and the next request fails with a broken-pipe error
    that has nothing to do with the code being written.
    """

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """Upgrade a bare `postgresql://` DSN to the asyncpg driver.

        SQLAlchemy picks its driver from the URL scheme, and `postgresql://`
        means psycopg2 — which is not installed here and would not work with an
        async engine if it were. The failure is a `ModuleNotFoundError` about a
        package nobody mentioned, several layers from the cause.

        This matters because the DSN a managed provider gives you at stage 15.3
        will say `postgresql://`, and pasting it in verbatim is the obvious
        thing to do. Normalising here means that works.
        """
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

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