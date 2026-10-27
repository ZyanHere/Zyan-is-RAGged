"""The embedding seam.

`get_embedding_model()` is the only way anything in `rag` obtains something
that can turn text into vectors. Callers receive an `EmbeddingModel` and never
learn which vendor is behind it.

**Why this lives in `rag` and not in `agent`** (decision D1): stage 3.1 requires
an evaluation harness that calls retrieval directly, with no chatbot in the
loop. Retrieval has to embed the question. If the embedder lived in the agent,
the harness would have to boot the agent to measure retrieval — and `rag`
importing `agent` is a forbidden direction anyway. The rule: a seam lives in the
lowest layer that needs it.

**Why this is synchronous** while the agent's chat seam is async. Embedded
Qdrant is a synchronous library, and the evaluation harness is a plain script
where async buys nothing. Rather than make `rag` async to suit one caller,
`rag` stays sync and the agent moves the call off the event loop with
`run_in_threadpool` — which FastAPI does automatically for a `def` route. The
cost is a bounded thread pool, and that bound is a genuine future trigger.

**Why two embedding methods.** `gemini-embedding-001` is an *asymmetric* model:
it is told whether it is embedding a document to be found, or a question doing
the finding, and it produces different vectors accordingly. Embedding both sides
the same way measurably degrades retrieval, and the mistake is invisible —
nothing errors, results are just quietly worse. Encoding the distinction in the
interface makes it impossible to get wrong by accident.
"""

import logging
from functools import lru_cache
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingModel(Protocol):
    """What every embedding provider must be able to do.

    A Protocol is structural: a class satisfies it by having matching members.
    It never inherits from this, and this file never imports the providers that
    implement it.
    """

    model_name: str
    """Provider's model id. Written into every chunk payload so a later model
    change is detectable rather than silently returning nonsense."""

    dimensions: int
    """Length of the vectors this model produces. Must match the Qdrant
    collection exactly, or every search fails."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed chunks for storage. Returns one vector per input, in order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a question for searching."""
        ...


@lru_cache
def get_embedding_model() -> EmbeddingModel:
    """Build the configured embedding model once and reuse it.

    Provider selection is driven by config, not by an import at the call site.

    **This function is where stage 2.5 collected on the seam.** For four
    stages it returned Gemini unconditionally — a seam in shape only — and
    the claim was that adding a second provider would change this function
    and nothing else. It did: the branch below is the entire diff outside
    the new provider's own file. No caller, no route, no test of the
    pipeline had to know.

    ── Why the warning is here and not in a startup hook ─────────────────

    `lru_cache` means this body runs exactly once per process, which is
    precisely the shape a startup announcement needs — and it needs no
    `lifespan`. The agent does not have one (see
    `docs/architecture/current.md`), and adding one sideways to carry a
    warning is how an unrelated concern gets attached to a stage.

    The cost of that choice is stated rather than hidden: the warning fires
    on first *use*, not at boot, so a process configured with the fake
    provider that never embeds anything never announces itself. Acceptable,
    because a process that never embeds cannot write a fake vector either.
    """
    # Imported inside the function so adding a provider never costs an import
    # for the providers you are not using. That is load-bearing now rather than
    # tidy: a top-level import of `gemini` would pull the Google SDK into every
    # process that only wants the fake one.
    from rag.config import get_settings

    settings = get_settings()

    if settings.embedding_provider == "fake":
        from rag.providers.fake import FakeEmbeddingModel

        # `warning`, not `info`, and the reason is a fact about this codebase
        # rather than a style preference. Stage 2.4 gave the backend and the
        # worker a root log handler; **the agent still has none**, so
        # `logging.lastResort` is what carries this line — and lastResort
        # passes WARNING and above only. An `info` would be invisible in
        # exactly the process that most needs to announce itself.
        logger.warning(
            "EMBEDDING_PROVIDER=fake \u2014 vectors are hashes of the text and "
            "carry no meaning. Retrieval results are nonsense by design. "
            "collection=%s delay=%dms per batch",
            settings.qdrant_collection,
            settings.fake_embed_delay_ms,
        )

        return FakeEmbeddingModel(
            dimensions=settings.embedding_dim,
            delay_ms=settings.fake_embed_delay_ms,
        )

    from rag.providers.gemini import GeminiEmbeddingModel

    # `google_api_key` is `str | None` since 2.5, and this is the only place
    # that could dereference a `None`. It cannot be one: `Settings` refuses to
    # build without a key when the provider is Gemini, so reaching this line
    # means one exists. The assertion is for the type checker, not the program.
    assert settings.google_api_key is not None

    return GeminiEmbeddingModel(
        api_key=settings.google_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
    )