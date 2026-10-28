"""Gemini embeddings.

The only file in `rag` that imports a vendor SDK. Vendor exceptions are
translated to `EmbeddingError` here, so nothing outside this module ever
imports `google.genai`.

**`l2_normalise` used to live here** and moved to `_vectors.py` at stage 2.5,
when a second provider needed it. Having the fake import it from this module
would have dragged the Google SDK into a provider that exists to avoid
touching Google at all — see that module's docstring.

**`embed_queries` arrived at stage 3.1**, and `_embed` needed no change to
support it. The free tier's limit counts requests rather than texts — stage
2.5 recorded the refusal, *"Embed content requests per minute limit exceeded
on Free Tier"*, one request after a hundred vectors had been accepted — and
the batching that makes a document cheap had no equivalent on the query side.
A question went out alone, so the evaluation harness's thirty to fifty
questions cost thirty to fifty requests. They now cost one.

See docs/decisions/0002-embedding-provider.md for why Gemini at 768 dimensions.
"""

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from rag.errors import EmbeddingError
from rag.providers._vectors import l2_normalise

# Gemini accepts a limited number of inputs per embed call. Batching keeps a
# 300-page document from becoming one enormous request that times out, while
# still being far cheaper than one call per chunk.
_MAX_BATCH = 100


class GeminiEmbeddingModel:
    """Satisfies the EmbeddingModel protocol in base.py.

    Note it does not inherit from it — having matching members is the whole
    contract (structural typing).
    """

    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self.model_name = model
        self.dimensions = dimensions
        self._client = genai.Client(api_key=api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed chunks for storage."""
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed several questions in one request. Stage 3.1.

        The same batching as `embed_documents` — up to `_MAX_BATCH` texts per
        round trip — and the same ordering contract: `result[i]` belongs to
        `texts[i]`, which `_embed` enforces per batch.
        """
        return self._embed(texts, task_type="RETRIEVAL_QUERY")

    def embed_query(self, text: str) -> list[float]:
        """Embed a question for searching."""
        return self.embed_queries([text])[0]

    def _embed(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        """Embed a list of strings, in batches, preserving order.

        `task_type` is what makes this model asymmetric — the same sentence
        embeds differently as a stored document than as a query, and telling
        the model which role it is playing measurably improves retrieval.
        """
        if not texts:
            return []

        vectors: list[list[float]] = []

        for offset in range(0, len(texts), _MAX_BATCH):
            batch = texts[offset : offset + _MAX_BATCH]

            try:
                response = self._client.models.embed_content(
                    model=self.model_name,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type=task_type,
                        output_dimensionality=self.dimensions,
                    ),
                )
            except genai_errors.APIError as exc:
                raise self._translate(exc) from exc
            except Exception as exc:
                raise EmbeddingError(
                    f"Gemini embedding request failed: {exc}"
                ) from exc

            embeddings = response.embeddings or []

            # Order is the entire contract — vectors[i] must belong to texts[i].
            # A short or reordered response would silently attach every chunk's
            # vector to the wrong text, producing an index that looks healthy
            # and retrieves nonsense. Refuse instead.
            if len(embeddings) != len(batch):
                raise EmbeddingError(
                    f"Gemini returned {len(embeddings)} embeddings for "
                    f"{len(batch)} inputs. Refusing to store a misaligned batch."
                )

            for embedding in embeddings:
                values = list(embedding.values or [])
                if len(values) != self.dimensions:
                    raise EmbeddingError(
                        f"Gemini returned a {len(values)}-dimension vector but "
                        f"EMBEDDING_DIM is {self.dimensions}. Every stored "
                        f"vector must match the collection exactly."
                    )
                vectors.append(l2_normalise(values))

        return vectors

    def _translate(self, exc: genai_errors.APIError) -> EmbeddingError:
        """Turn a vendor exception into ours, with an actionable message."""
        code = getattr(exc, "code", None)

        if code in (401, 403):
            return EmbeddingError(
                "Google rejected the API key. Check GOOGLE_API_KEY in "
                f"agent/.env — get one free at https://aistudio.google.com/apikey. "
                f"Provider said: {exc}"
            )
        if code == 429:
            return EmbeddingError(
                "Google rate limited this request. The free embedding tier has "
                "both a per-minute and a per-day cap, and a large document can "
                f"exhaust the per-minute one in a single ingest. Provider said: {exc}"
            )
        if code == 404:
            return EmbeddingError(
                f"Embedding model '{self.model_name}' was not found. Check "
                f"EMBEDDING_MODEL in agent/.env. Provider said: {exc}"
            )
        return EmbeddingError(f"Gemini embedding request failed: {exc}")
