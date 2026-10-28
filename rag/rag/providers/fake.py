"""A fake embedding provider, for load testing.

**This produces meaningless vectors.** Nothing it embeds can be retrieved by
relevance, because the numbers are a hash of the text and carry no semantics at
all. It exists to answer one question — *what does slow embedding do to the
shape of the system?* — and it answers that question honestly while answering
every question about retrieval quality wrongly.

── Why it exists, and why it exists twice ──────────────────────────────────────

Three questions have been deferred since stage 1.3, and none of them can be
answered against Gemini's free tier: a large ingest is rejected with a 429 in
about a second, so every load-test failure would be a quota artefact rather
than an observation about concurrency.

This file was written once during 1.3 preparation and **removed as out of
sequence** — it was being built to make a measurement that belonged to a later
stage. It arrives properly at 2.5. The design below is recovered rather than
reinvented: the modules were deleted but their bytecode survived in
`__pycache__`, and Python keeps docstrings as bytecode constants.

── What the delay models, and what it does not ─────────────────────────────────

One `time.sleep` per batch of 100 texts, mirroring `_MAX_BATCH` in `gemini.py`,
because the real provider costs one network round trip per batch. A per-text
delay would make duration scale linearly with chunk count, which is the wrong
model of a batching API.

`time.sleep` and not `asyncio.sleep`, for a load-bearing reason: this runs on a
thread from the agent's bounded threadpool, and `time.sleep` releases the GIL.
The thread is therefore parked exactly as it would be on a socket read, which
is the resource the capacity probe is trying to exhaust. A busy-wait would
measure GIL contention instead, and an `asyncio.sleep` could not run here at
all — the handler calling this is a plain `def`.

It models: wall-clock time a worker thread is blocked, and everything
downstream of that — threads held, sockets held, requests left open, timeouts
fired.

It does not model: latency *variance* (the delay is constant, so there is no
tail), rate limiting, retries and backoff, TLS handshakes, bandwidth, token
cost, or the provider's own CPU. **Any p95 measured against this provider is a
measure of queueing alone**, and the write-up has to say so rather than imply a
model of a real provider.

── Symmetric, unlike Gemini ────────────────────────────────────────────────────

`embed_documents` and `embed_query` return the *same* vector for the same text.
Gemini is asymmetric and told which role it is playing (`RETRIEVAL_DOCUMENT` vs
`RETRIEVAL_QUERY`), and that difference measurably matters for ranking.

Here it is dropped deliberately. This stage measures latency, not relevance,
and symmetry makes this provider useful for one more thing: a query embeds to
exactly its own chunk's vector, so a retrieval smoke test can assert *which*
chunk came back without any model in the loop.
"""

import hashlib
import logging
import time

from rag.providers._vectors import l2_normalise

logger = logging.getLogger(__name__)

# Mirrors `_MAX_BATCH` in `gemini.py`. The number itself does not matter here —
# what matters is that it is the *same* number, so the batch boundaries fall in
# the same places and a measurement taken against this provider describes the
# same request pattern as the real one.
_MAX_BATCH = 100

# A float is derived from four bytes of hash material, read as a uint32.
_BYTES_PER_FLOAT = 4

# blake2b's maximum. Larger digests mean fewer hashing rounds per vector; at
# 768 dimensions this is 3,072 bytes of material, so 48 rounds rather than 96.
_DIGEST_SIZE = 64

_UINT32_MAX = 4294967295


class FakeEmbeddingModel:
    """Satisfies the EmbeddingModel protocol in base.py.

    Like `GeminiEmbeddingModel`, it does not inherit from the protocol —
    matching members are the whole contract.
    """

    model_name = "fake-embedding"
    """Written into every chunk's payload, and the safeguard that outlives all
    the others.

    A vector produced here is identifiable in the index forever, through a
    field `search()` already carries and `upsert_chunks` already writes. If
    every other guard fails and fake vectors reach a real collection, this is
    what makes them findable afterwards rather than indistinguishable.
    """

    def __init__(self, *, dimensions: int, delay_ms: int) -> None:
        self.dimensions = dimensions
        self._delay_seconds = delay_ms / 1000.0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Stage 3.1. Symmetric with `embed_documents`, like everything here.

        The real provider gained this because its rate limit counts requests,
        so fifty questions had to become one. There is no limit to respect
        here, and this provider is symmetric anyway — so the method exists to
        keep the fake a *drop-in* substitute, which is the one property every
        decision in this file serves. A fake that no longer satisfies the
        protocol is a measurement apparatus that cannot be swapped in.
        """
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Hash each text, sleeping once per batch.

        The sleep is outside the per-text work and inside the per-batch loop,
        which is the whole point: it reproduces the cost structure of a
        batching API rather than of a per-item one.
        """
        if not texts:
            return []

        vectors: list[list[float]] = []

        for offset in range(0, len(texts), _MAX_BATCH):
            batch = texts[offset : offset + _MAX_BATCH]

            # Guarded, so a delay of zero costs nothing at all. The default is
            # zero: this provider is also useful as a *fast* fake, for tests
            # that want determinism without latency.
            if self._delay_seconds:
                time.sleep(self._delay_seconds)

            vectors.extend(_vector_for(text, self.dimensions) for text in batch)

        return vectors


def _vector_for(text: str, dimensions: int) -> list[float]:
    """Hash one string into a deterministic unit vector of `dimensions` floats.

    **`hashlib`, not the builtin `hash()`.** `hash()` is salted per process, so
    the same text would embed differently on every restart — which would make a
    stored index unusable after a restart and a retrieval assertion impossible
    to write. Cryptographic hashing is stable across processes, machines and
    Python versions.

    The output is normalised for the reason in `_vectors.py`: a provider whose
    vectors are not unit length is not a drop-in substitute for one whose
    vectors are, so a measurement taken against it would not be a measurement
    of the same system.
    """
    needed = dimensions * _BYTES_PER_FLOAT
    encoded = text.encode("utf-8")

    # One digest is 64 bytes and a 768-dimension vector needs 3,072, so the
    # material is extended until there is enough. The counter goes in blake2b's
    # **salt** rather than being appended to the text.
    #
    # The reason is unambiguity, not a measured defect — and the distinction
    # was found by mutating this line. Appending `str(counter)` makes the
    # inputs for `("x", round 10)` and `("x1", round 0)` identical, so the two
    # texts share about ten of their forty-eight digest blocks. Measured, that
    # produces **no correlation at all** between the vectors: the shared bytes
    # land at different offsets, so no two components align and the cosine
    # stays at zero.
    #
    # So concatenation is not wrong here *today*. It is wrong in the way that
    # becomes a bug later: the overlap depends on the digest size and the
    # dimension count, and someone changing either could align the blocks
    # without ever learning they had. `salt` is a parameter whose entire job is
    # to make digests of the same input disjoint, and using it means the
    # property holds by construction rather than by arithmetic that happens to
    # work out.
    material = bytearray()
    counter = 0
    while len(material) < needed:
        material += hashlib.blake2b(
            encoded,
            digest_size=_DIGEST_SIZE,
            salt=counter.to_bytes(8, "big"),
        ).digest()
        counter += 1

    return l2_normalise(
        [
            int.from_bytes(material[i : i + _BYTES_PER_FLOAT], "big")
            / _UINT32_MAX
            * 2.0
            - 1.0
            for i in range(0, needed, _BYTES_PER_FLOAT)
        ]
    )
