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

    lease_seconds: float = Field(default=60.0, gt=0)
    """How long a worker's claim on a job lasts before it lapses. Stage 2.1.

    **The number is a bet on two failure modes at once**, and it is wrong in a
    different way at each end:

        too short   a worker that is merely slow — a long ingest, a GC pause, a
                    stalled embedding call — gets its job taken away while it is
                    still working. The work is done twice and the first result
                    is thrown away.

        too long    a worker that genuinely died holds its job for that long
                    before anything notices. The document just sits there.

    60s against a heartbeat every 20s (a third of this) means two consecutive
    renewals can fail before anyone is declared dead, which absorbs a slow query
    or a brief network blip without a false reclaim.

    It is not a guess about how long ingestion takes — the heartbeat is what
    covers that, so a four-minute ingest is fine under a one-minute lease. It is
    a guess about how long a *renewal* can plausibly be delayed. Stage 11.2 is
    where it stops being a guess.
    """

    max_attempts: int = Field(default=15, gt=0)
    """How many times a **transient** failure may be retried before giving up.

    Counts claims, not errors, so a job that silently kills its worker burns
    attempts just as a job that fails loudly does. That is deliberate: the
    thing being bounded is "how much can one document cost us", and a crash
    costs the same as a timeout.

    ── Why this was five, and why five was wrong ──────────────────────────────

    The previous version of this docstring said five was *"large enough to ride
    out a provider outage of several minutes once the backoff is applied"*.
    That was a guess, and stage 2.3 measured it:

        a valid document, uploaded during an outage
        → permanently failed after 22 seconds

    Not several minutes. Twenty-two seconds — which `docker compose restart
    agent` fits comfortably inside, so an ordinary deploy destroyed every
    document in flight and the only recovery was a human re-uploading.

    **This is why a stage is not finished until it has produced a number.** The
    reasoning in the old docstring was plausible and the arithmetic was never
    done.

    ── Where fifteen comes from, and why it was eight first ──────────────────

    The target is **about five minutes** of outage survived. Eight attempts
    was the first answer and it was wrong, by a factor of three:

        8 attempts, cap 60   p10  55s    median  91s    p90 126s
        15 attempts, cap 60  p10 233s    median 302s    p90 369s

    (20,000 simulated runs of `delay_for`, which is cheap to do and was not
    done the first time.)

    **One document in ten gave up after 55 seconds** under the eight-attempt
    policy — barely better than the 22-second budget this stage exists to fix.
    Two live runs landed at 49.5s and 81.3s, both in that lower half, which is
    how the error was noticed at all.

    The mistake was reasoning about the *worst* case — the ceilings sum to
    182s, which sounds like "about three minutes" — when what a document
    actually experiences is the **sum of the draws**, and full jitter halves
    every one of them. The spread matters more than the mean here, because the
    documents that give up early are precisely the ones a short outage should
    have saved.

    Fifteen attempts with the 60-second cap gives ceilings of 2, 4, 8, 16, 32
    and then 60 nine times over: a median of ~5 minutes and a p10 of ~4.

    ── What fifteen attempts costs ──────────────────────────────────────────

    Up to fifteen claims per document, each a short transaction and one agent
    call that fails fast while the dependency is down. It is not fifteen
    embedding bills: a transient failure by definition did not get far enough
    to be charged for, and a **permanent** failure never reaches attempt two —
    see `_classify`.

    So the cost of patience is paid in cheap retries against a service that is
    already refusing connections, and the alternative is throwing away
    documents that would have succeeded.

    It is a budget, not a guarantee. A ten-minute incident still fails
    documents, and that is what the dead-letter list and `POST
    /documents/{id}/retry` are for: the system should recover from a restart on
    its own and ask for help with an outage.

    ── It no longer applies to every failure ────────────────────────────────

    A **permanent** failure gives up on the first attempt regardless of this
    number — a file that is not a PDF will not become one. See `_classify` in
    `services/ingestion.py`.
    """

    max_delay_seconds: float = Field(default=60.0, gt=0)
    """The longest any single wait between attempts may be. Stage 2.3.

    **Capped exponential backoff**, which is the standard form and which this
    system did not have. Uncapped, the ceiling doubles forever: at eight
    attempts the last wait would be up to 128 seconds and the budget's shape
    would be set by one long sleep rather than by several spread-out tries.

    The cap is what makes raising `max_attempts` buy *coverage* instead of
    *latency*. Without it, more attempts mostly means a document sits
    non-terminal for longer.

    Sixty seconds, because the thing being waited on is a service restarting
    or a rate-limit window closing, and both are measured in tens of seconds.
    A longer cap would make the tail of the budget indistinguishable from the
    system having forgotten about the document.
    """

    retry_base_seconds: float = Field(default=2.0, gt=0)
    """The first retry delay. Each subsequent attempt doubles the ceiling.

    With the default the ceilings run 2, 4, 8, 16, 32 and then flatten at
    `max_delay_seconds`. **How much outage that covers is not readable from
    this number** — it depends on `max_attempts` and on the cap, and the draws
    are random. The arithmetic lives with `max_attempts`, where it was once
    got wrong by a factor of three by reading a sequence like this one and
    reasoning about its sum.

    **The delay is a ceiling, not a value.** The service picks a random number
    between zero and it — full jitter. Without that, every worker that failed
    against the same outage waits the same number of seconds and returns *in
    the same instant*, which is how a recovering service gets knocked over by
    the clients that were waiting for it.
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