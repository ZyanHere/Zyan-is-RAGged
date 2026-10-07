"""Configuration for the rag engine.

Every tunable value in this package is declared here and read from the
environment exactly once. No other module in `rag` touches `os.environ`, so
this file is the complete list of things that can be configured.

Two deliberate differences from `agent/app/core/config.py`:

1. **There is no module-level `settings` object.** The agent builds one at
   import time, which is fine for a service that cannot run without its config
   anyway. `rag` is a library: importing it must never require a Google API
   key. Chunking tests have no business failing because an embedding key is
   missing. So settings are built lazily, on first use, by `get_settings()`.

2. **Only the outer layers read settings.** `pipeline.py`, `index.py` and the
   providers call `get_settings()`. The pure functions — extraction, chunking —
   take their parameters explicitly, which is what makes them testable without
   an environment at all.
"""

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything `rag` can be configured with.

    Field names map to environment variables case-insensitively:
    `chunk_size` is read from `CHUNK_SIZE`.
    """

    model_config = SettingsConfigDict(
        # Resolved relative to the working directory of whatever process
        # imported us. Running the agent from `agent/` therefore picks up
        # `agent/.env`. The evaluation harness in stage 3.1 will run from its
        # own directory and supply its own file — which is the point of not
        # hard-coding a path here.
        env_file=".env",
        env_file_encoding="utf-8",
        # `agent/.env` also holds OpenRouter keys, ports and generation
        # settings. None of those are rag's business, and without this pydantic
        # would reject the file for containing fields it does not recognise.
        extra="ignore",
    )

    # ── Embeddings ────────────────────────────────────────────────────────────
    # No default: a missing key must fail immediately with a named field,
    # rather than surfacing as a confusing 401 from Google on first upload.
    google_api_key: str

    # Changing either of these invalidates every vector already stored and
    # forces a full re-ingest. Both are written into every chunk's payload so a
    # mismatch is detectable instead of silently returning nonsense.
    # See docs/decisions/0002-embedding-provider.md.
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = Field(default=768, gt=0)

    # ── Vector store ──────────────────────────────────────────────────────────
    # Embedded mode: Qdrant is a library writing to a local folder, no Docker.
    # Resolved to an absolute path below, so the same command run from two
    # different directories cannot quietly create two different indexes.
    qdrant_path: Path = Path("./qdrant_data")

    # Set this to point at a real Qdrant server instead. When present it wins
    # and `qdrant_path` is ignored.
    qdrant_url: str | None = None

    qdrant_collection: str = "documents"

    # ── Chunking ──────────────────────────────────────────────────────────────
    chunk_size: int = Field(default=1200, gt=0)
    chunk_overlap: int = Field(default=180, ge=0)

    # ── Retrieval ─────────────────────────────────────────────────────────────
    # How many chunks retrieval returns. Lives in config rather than as a
    # function default because stage 4.6 tunes it as a measured experiment.
    top_k: int = Field(default=5, gt=0)

    @model_validator(mode="after")
    def _check_chunk_geometry(self) -> Self:
        """Reject a chunk size and overlap that cannot produce progress.

        If the overlap is not smaller than the chunk size, each chunk starts at
        or before the previous one, and the chunker never reaches the end of the
        text. That is an infinite loop, and it is far better to refuse at
        startup than to discover it as a hung upload.
        """
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) must be smaller than "
                f"CHUNK_SIZE ({self.chunk_size}); otherwise chunking cannot "
                f"advance through the text."
            )
        return self

    @property
    def uses_embedded_qdrant(self) -> bool:
        """True when Qdrant runs as a local folder rather than a server."""
        return self.qdrant_url is None

    @model_validator(mode="after")
    def _resolve_qdrant_path(self) -> Self:
        """Make the storage path absolute, pinned to the current directory.

        A relative path is interpreted against the working directory, so
        launching the agent from `agent/` and a script from the repo root would
        create two separate indexes with the same name and no warning. Fixing
        it at load time makes the location explicit and loggable.
        """
        self.qdrant_path = self.qdrant_path.resolve()
        return self


@lru_cache
def get_settings() -> Settings:
    """Build the settings once and reuse them.

    `lru_cache` means the environment is read on first call and never again, so
    every module sees the same values for the lifetime of the process — and a
    test can reset them with `get_settings.cache_clear()`.
    """
    return Settings()