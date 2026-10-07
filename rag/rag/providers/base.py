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

from functools import lru_cache
from typing import Protocol


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
    Stage 2.4's fake embedder — a local function returning a deterministic
    vector after a configurable sleep — plugs in here as one more branch, and no
    caller changes.
    """
    # Imported inside the function so adding a provider never costs an import
    # for the providers you are not using.
    from rag.config import get_settings
    from rag.providers.gemini import GeminiEmbeddingModel

    settings = get_settings()
    return GeminiEmbeddingModel(
        api_key=settings.google_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
    )