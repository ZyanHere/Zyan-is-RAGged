"""Gemini embeddings.

The only file in `rag` that imports a vendor SDK. Vendor exceptions are
translated to `EmbeddingError` here, so nothing outside this module ever
imports `google.genai`.

See docs/decisions/0002-embedding-provider.md for why Gemini at 768 dimensions.
"""

import math

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from rag.errors import EmbeddingError

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

    def embed_query(self, text: str) -> list[float]:
        """Embed a question for searching."""
        return self._embed([text], task_type="RETRIEVAL_QUERY")[0]

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
                vectors.append(_l2_normalise(values))

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


def _l2_normalise(vector: list[float]) -> list[float]:
    """Scale a vector to unit length.

    **Not optional at 768 dimensions.** `gemini-embedding-001` returns
    unit-length vectors only at its native 3072 dimensions. Ask for a truncated
    output — which decision 0002 does, for a 4x smaller and faster index — and
    the result is no longer normalised, because chopping off dimensions removes
    part of the length.

    Cosine similarity divides by both vectors' magnitudes, so in principle it
    tolerates that. In practice Qdrant normalises once at insertion for speed
    and assumes what it stored was sensible, and inconsistent magnitudes across
    the corpus distort scores in ways that are invisible — no error, just
    quietly worse ranking. Normalising here, at the seam, means every vector
    that reaches the index is unit length regardless of provider.

    The zero guard is for defence, not realism: a zero-length vector has no
    direction to preserve, and dividing by zero would poison the index with NaN.
    """
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0.0:
        return vector
    return [value / magnitude for value in vector]