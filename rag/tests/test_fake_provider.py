"""The fake embedding provider. Stage 2.5.

Every property here exists to make the provider a *drop-in substitute* — a
measurement taken against it has to be a measurement of the same system, or the
numbers it produces describe something nobody runs.

── The test that cannot be written in-process ─────────────────────────────────

`test_the_same_text_embeds_identically_in_a_fresh_process` runs a subprocess,
and that is not caution. Python's builtin `hash()` is salted **per process**:
within one interpreter it is perfectly stable, so a loop-based test passes
against an implementation that would produce different vectors after every
restart — making a stored index unusable and a retrieval assertion impossible.

The bug is only visible across a process boundary, so the test has to cross
one.
"""

import math
import subprocess
import sys
import time

import pytest

from rag.providers.fake import _MAX_BATCH, FakeEmbeddingModel, _vector_for

DIMENSIONS = 768


def model(delay_ms: int = 0) -> FakeEmbeddingModel:
    return FakeEmbeddingModel(dimensions=DIMENSIONS, delay_ms=delay_ms)


# ── Determinism ──────────────────────────────────────────────────────────────


def test_the_same_text_embeds_identically_in_a_fresh_process() -> None:
    """**The one test that catches `hash()` instead of `hashlib`.**

    Within a process, builtin `hash()` is stable and every in-process
    assertion about determinism passes. Across processes it is salted, so the
    same document would embed differently after every restart — a stored index
    would stop matching its own corpus and no retrieval test could be written
    at all.

    Two subprocesses, because comparing a subprocess to *this* process would
    also work but would couple the expected value to whichever interpreter
    pytest happens to be running under.
    """
    script = (
        "from rag.providers.fake import FakeEmbeddingModel;"
        f"m = FakeEmbeddingModel(dimensions={DIMENSIONS}, delay_ms=0);"
        "print(sum(m.embed_query('the Zephyr project')))"
    )

    runs = [
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    ]

    assert runs[0] == runs[1], (
        "the same text embedded differently in two processes — the hash is "
        "salted per process, so a stored index would not survive a restart"
    )


def test_different_texts_embed_differently() -> None:
    """The control. A provider returning one constant vector would satisfy
    every determinism test in this file and index a corpus into a single
    point."""
    m = model()

    assert m.embed_query("alpha") != m.embed_query("beta")


def test_a_one_character_difference_changes_the_whole_vector() -> None:
    """Hashing, not encoding.

    If the vector were derived positionally from the bytes, near-identical
    texts would produce near-identical vectors — which would look like
    semantic similarity and be nothing of the kind. Hashed vectors have no
    semantics at all, and that must be *obvious* rather than subtly false.
    """
    m = model()
    a = m.embed_query("the Zephyr project")
    b = m.embed_query("the Zephyr projecz")

    # Cosine similarity of two unrelated unit vectors clusters near zero.
    cosine = sum(x * y for x, y in zip(a, b, strict=True))

    assert abs(cosine) < 0.2, f"cosine {cosine:.3f} — these should be unrelated"


# ── Drop-in substitutability ─────────────────────────────────────────────────


def test_vectors_are_unit_length() -> None:
    """Otherwise it is not a substitute for Gemini and the measurement moves.

    Qdrant normalises once at insertion and assumes what it stored was
    sensible. A provider whose vectors are differently scaled would distort
    scores invisibly — and a load test run against it would not be measuring
    the same system.
    """
    m = model()

    for text in ("alpha", "beta", "a much longer piece of text " * 20, ""):
        magnitude = math.sqrt(sum(x * x for x in m.embed_query(text)))
        assert magnitude == pytest.approx(1.0, abs=1e-9), text[:20]


def test_the_vector_has_the_configured_dimensions() -> None:
    """A mismatch here fails at the Qdrant boundary with a message about the
    collection, which is a long way from the cause."""
    for dimensions in (8, 768, 1536):
        m = FakeEmbeddingModel(dimensions=dimensions, delay_ms=0)
        assert len(m.embed_query("x")) == dimensions


def test_values_span_the_negative_range() -> None:
    """Derived as `byte / UINT32_MAX * 2 - 1`, so the range is [-1, 1].

    All-positive vectors would be a quietly different distribution from a real
    embedder's, and cosine similarity between them could never be negative —
    so retrieval scores measured against this provider would occupy half the
    range they normally do.
    """
    values = model().embed_query("the Zephyr project")

    assert min(values) < 0 < max(values)


def test_documents_and_queries_embed_the_same() -> None:
    """Symmetric, unlike Gemini, and deliberately.

    Gemini is asymmetric and that matters for ranking — but this provider
    measures latency, not relevance. Symmetry buys one extra thing: a query
    embeds to exactly its own chunk's vector, so a retrieval smoke test can
    assert *which* chunk came back with no model in the loop.
    """
    m = model()
    text = "the Zephyr project was approved on 14 March 2021"

    assert m.embed_documents([text]) == [m.embed_query(text)]


def test_order_is_preserved() -> None:
    """`vectors[i]` must belong to `texts[i]`.

    The same contract `gemini.py` refuses to violate. A reordering here would
    attach every chunk's vector to the wrong text and produce an index that
    looks healthy and retrieves nonsense.
    """
    m = model()
    texts = [f"document number {n}" for n in range(5)]

    assert m.embed_documents(texts) == [m.embed_query(t) for t in texts]


def test_an_empty_list_embeds_to_an_empty_list() -> None:
    """And costs no delay — the early return is before the loop."""
    assert model(delay_ms=10_000).embed_documents([]) == []


# ── The delay is per batch, which is the whole point ─────────────────────────


def test_the_delay_is_per_batch_not_per_text() -> None:
    """**The property that makes the probe's numbers mean anything.**

    The real provider costs one network round trip per batch of 100. A
    per-text delay would make duration scale with chunk count, which is the
    wrong model of a batching API — a 300-page document would appear
    catastrophically slower than it is, and the capacity probe would be
    measuring a fiction.

    ── Why this subtracts a baseline instead of timing absolutely ────────────

    The first version compared `elapsed(1)` with `elapsed(100)` directly and
    failed: 62 ms against 141 ms. The delay was per batch exactly as intended,
    but **hashing 100 vectors of 768 dimensions is ~80 ms of real CPU**, and
    the assertion was charging that to the sleep.

    So each measurement is taken twice — once at zero delay, once at the real
    one — and the difference is what the delay actually contributed. That
    isolates the claim from the provider's own cost, which is not negligible
    and is worth knowing before reading any probe output.
    """
    delay_ms = 100
    delay_s = delay_ms / 1000.0
    repeats = 3

    def contribution(count: int) -> float:
        """Seconds attributable to the delay for `count` texts.

        **The minimum of several runs, not the mean.** Scheduling noise only
        ever makes a timing measurement larger — the thread can be descheduled
        but it cannot run faster than it runs — so the minimum is the closest
        estimate of the true cost, and it is the estimator that does not drift
        when the machine is busy.

        The first version used a single run of each and flaked on a loaded
        machine: two subtracted measurements carry two measurements' worth of
        noise, which is the worst possible shape for a tight tolerance.
        """
        texts = [f"text {n}" for n in range(count)]

        def run(ms: int) -> float:
            m = model(delay_ms=ms)
            start = time.perf_counter()
            m.embed_documents(texts)
            return time.perf_counter() - start

        with_delay = min(run(delay_ms) for _ in range(repeats))
        without = min(run(0) for _ in range(repeats))
        return with_delay - without

    one_text = contribution(1)
    full_batch = contribution(_MAX_BATCH)
    two_batches = contribution(_MAX_BATCH + 1)

    assert one_text == pytest.approx(delay_s, abs=0.04), (
        f"1 text cost {one_text:.3f}s of delay, expected ~{delay_s:.3f}s"
    )
    assert full_batch == pytest.approx(delay_s, abs=0.04), (
        f"{_MAX_BATCH} texts cost {full_batch:.3f}s of delay but 1 text cost "
        f"{one_text:.3f}s — the delay is scaling with texts, not batches"
    )
    assert two_batches == pytest.approx(2 * delay_s, abs=0.06), (
        f"{_MAX_BATCH + 1} texts cost {two_batches:.3f}s of delay, expected "
        f"~{2 * delay_s:.3f}s — the second batch did not sleep"
    )


def test_a_zero_delay_costs_nothing() -> None:
    """The default, and what makes this provider usable in ordinary tests.

    It is a *fast* fake as well as a slow one: determinism without latency is
    what a retrieval test wants, and paying 100 ms for it would make the suite
    worse for no gain.
    """
    m = model(delay_ms=0)
    start = time.perf_counter()
    m.embed_documents([f"text {n}" for n in range(_MAX_BATCH * 3)])

    assert time.perf_counter() - start < 1.0


# ── A test that is deliberately absent ───────────────────────────────────────
#
# There was one here asserting that `_vector_for("x")` and `_vector_for("x1")`
# are uncorrelated *because* the counter salts the digest rather than extending
# the text. It survived the mutation that replaces the salt with concatenation,
# and investigating why showed the claim behind it was wrong: the two texts do
# share digest blocks under that mutation, but at different offsets, so no
# components align and the cosine is zero either way.
#
# The salt is still the right choice — see `_vector_for` — but for a reason no
# test can observe today, so there is no test. Writing one that passes for a
# different reason than it states is how the stage 2.4 logging test went wrong.

# ── The seam (stage 2.5) ─────────────────────────────────────────────────────
#
# These exist because a mutation said they had to. Replacing the branch in
# `get_embedding_model` with `if False:` — so the setting is read and ignored
# and Gemini is always returned — passed every test in this file and every
# test of the provider itself.
#
# Everything above tests `FakeEmbeddingModel`. Nothing tested that the system
# would ever *build* one, which is the whole claim of the stage.


def build(monkeypatch: pytest.MonkeyPatch, **overrides):
    """Build a provider through the real seam, under crafted settings.

    Both `get_settings` and `get_embedding_model` are `lru_cache`d — one per
    process each, which is right in production and means a test has to clear
    them or it reads whatever an earlier test cached.
    """
    from rag import config
    from rag.providers import base

    settings = config.Settings(_env_file=None, **overrides)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    base.get_embedding_model.cache_clear()

    try:
        return base.get_embedding_model()
    finally:
        base.get_embedding_model.cache_clear()


def test_the_seam_builds_the_fake_when_configured_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The claim the seam has been making since stage 1.1.**

    `get_embedding_model` returned Gemini unconditionally for four stages, on
    the promise that adding a provider would change this function and nothing
    else. This is the assertion that the promise was kept — and that the
    setting is read rather than merely declared.
    """
    model = build(
        monkeypatch,
        embedding_provider="fake",
        qdrant_collection="loadtest",
        fake_embed_delay_ms=25,
    )

    assert isinstance(model, FakeEmbeddingModel)
    assert model.model_name == "fake-embedding"
    assert model._delay_seconds == pytest.approx(0.025)


def test_the_seam_still_builds_gemini_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control. A branch that returns the fake unconditionally would pass
    the test above and quietly fill a real index with noise."""
    model = build(monkeypatch, google_api_key="not-a-real-key")

    assert not isinstance(model, FakeEmbeddingModel)
    assert model.model_name == "gemini-embedding-001"


def test_choosing_the_fake_announces_itself(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """At WARNING, and the level is a fact about this codebase.

    Stage 2.4 gave the backend and the worker a root log handler. **The agent
    still has none**, so `logging.lastResort` carries this line — and
    lastResort passes WARNING and above only. An `info` would be invisible in
    exactly the process that most needs to announce it is embedding nonsense.

    The message carries the collection, because the single most useful thing
    to know when you see this line is *where* the meaningless vectors are
    going.
    """
    with caplog.at_level("INFO", logger="rag.providers.base"):
        build(
            monkeypatch,
            embedding_provider="fake",
            qdrant_collection="loadtest",
            fake_embed_delay_ms=25,
        )

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "choosing the fake provider said nothing"

    message = warnings[0].getMessage()
    assert "loadtest" in message, "say which collection is being filled"
    assert "no meaning" in message


def test_choosing_gemini_says_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A warning on the ordinary path is a warning people stop reading."""
    with caplog.at_level("INFO", logger="rag.providers.base"):
        build(monkeypatch, google_api_key="not-a-real-key")

    assert [r for r in caplog.records if r.levelname == "WARNING"] == []
