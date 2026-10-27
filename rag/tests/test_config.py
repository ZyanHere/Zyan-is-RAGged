"""Configuration validation.

Settings are constructed with explicit keyword arguments throughout, which take
precedence over both the environment and any `.env` file. That keeps these
tests independent of whatever machine they run on — a test that passes or fails
depending on a developer's local `.env` is worse than no test.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rag.config import Settings

# Required field, and irrelevant to everything being asserted here.
KEY = {"google_api_key": "test-key-not-used"}


def test_overlap_not_smaller_than_size_is_refused() -> None:
    """Caught at load, not at the first upload.

    Overlap >= size means each chunk window starts at or before the previous
    one, so chunking never reaches the end of the text. That is an infinite
    loop, and discovering it as a hung request at 3am is the failure mode stage
    15.1 exists to prevent.
    """
    with pytest.raises(ValidationError, match="smaller than"):
        Settings(**KEY, chunk_size=500, chunk_overlap=500)


def test_zero_overlap_is_allowed() -> None:
    """Adjacent windows with no repetition is a legitimate configuration.

    It is the right setting when a corpus is already chunked by structure, and
    it is the baseline that stage 4.1 measures overlap's cost against.
    """
    settings = Settings(**KEY, chunk_size=500, chunk_overlap=0)
    assert settings.chunk_overlap == 0


@pytest.mark.parametrize("field", ["chunk_size", "embedding_dim", "top_k"])
def test_non_positive_values_are_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**KEY, **{field: 0})


def test_qdrant_path_is_resolved_to_an_absolute_path() -> None:
    """A relative path means a different index per working directory.

    Launching the agent from `agent/` and a script from the repo root would
    otherwise create two separate stores with the same name, and questions
    would mysteriously fail to find documents that were definitely uploaded.
    """
    settings = Settings(**KEY, qdrant_path=Path("./some-relative-dir"))
    assert settings.qdrant_path.is_absolute()


def test_embedded_mode_is_the_default_and_a_url_overrides_it() -> None:
    """Embedded Qdrant needs no Docker, which is why stage 1.1 starts there.

    Setting QDRANT_URL is the whole migration to a server — needed at stage
    1.3, when a separate worker process appears and embedded mode's
    single-process lock on the storage folder stops being acceptable.
    """
    assert Settings(**KEY).uses_embedded_qdrant is True
    assert (
        Settings(**KEY, qdrant_url="http://localhost:6333").uses_embedded_qdrant
        is False
    )


def test_a_missing_api_key_names_the_field_and_the_provider() -> None:
    """The error must say which setting is missing, and now *why* it is needed.

    Without the key this surfaces much later as an opaque provider error, and
    "401 from Google" does not tell you that GOOGLE_API_KEY was never set.

    **The mechanism changed at stage 2.5 and the message got better for it.**
    The field was required by pydantic until the fake provider needed to run
    without one; it is `str | None` now, and a validator enforces it only on
    the Gemini branch. Pydantic would have said "field required", which is
    confusing once it is required only sometimes — so the message names the
    provider that wants it and the escape hatch.
    """
    with pytest.raises(ValidationError, match="GOOGLE_API_KEY"):
        Settings(_env_file=None)

    message = str(
        pytest.raises(ValidationError, Settings, _env_file=None).value
    )
    assert "gemini" in message, "say which provider needs it"
    assert "EMBEDDING_PROVIDER=fake" in message, "and how to need no provider"


# ── The fake provider's refusals (stage 2.5) ─────────────────────────────────


def test_the_fake_provider_needs_no_api_key() -> None:
    """The point of making the key conditional.

    A capacity probe that required a paid credential to measure queueing would
    defeat its own purpose — and `rag` is a library, so importing it to run a
    load test must not demand an embedding key any more than running the
    chunking tests does.
    """
    settings = Settings(
        _env_file=None,
        embedding_provider="fake",
        qdrant_collection="loadtest",
    )

    assert settings.google_api_key is None
    assert settings.embedding_provider == "fake"


def test_the_fake_provider_refuses_the_default_collection() -> None:
    """**The refusal that matters most, because the damage it prevents is silent.**

    Fake vectors are hashes and carry no meaning. Mixed into a real index they
    are indistinguishable from the outside, and nothing goes wrong until
    somebody asks a question and gets a confident answer assembled from noise.

    Every other safeguard is *detective* — `model_name` is written into each
    payload, so the damage is findable afterwards. This one is the only
    preventive one.

    It fires at config load rather than at write time deliberately: by the time
    `upsert_chunks` runs, a document has been read, chunked and embedded, and
    the failure would arrive after all the expensive parts.
    """
    with pytest.raises(ValidationError, match="documents"):
        Settings(
            _env_file=None,
            embedding_provider="fake",
            google_api_key="unused",
        )


def test_the_fake_provider_is_allowed_a_separate_collection() -> None:
    """The refusal must not be so broad that the provider is unusable.

    A test that only checks the refusal passes trivially if the fake provider
    is rejected everywhere.
    """
    settings = Settings(
        _env_file=None,
        embedding_provider="fake",
        qdrant_collection="loadtest",
    )

    assert settings.qdrant_collection == "loadtest"


def test_an_unknown_provider_is_refused_rather_than_defaulted() -> None:
    """A typo must not silently give you either provider.

    `EMBEDDING_PROVIDER=feke` falling back to Gemini means a load test quietly
    spends quota; falling back to the fake means a production index quietly
    fills with noise. Both failures are silent and they point in opposite
    directions, which is the worst possible pair to choose between — so the
    `Literal` refuses to choose.
    """
    with pytest.raises(ValidationError, match="embedding_provider"):
        Settings(_env_file=None, embedding_provider="feke", google_api_key="x")


def test_the_delay_defaults_to_zero_and_rejects_negatives() -> None:
    """Zero by default, so the fake is usable as a *fast* deterministic
    embedder in ordinary tests, not only as a slow one in a load test.

    A negative delay would be a `time.sleep` that raises, deep inside a worker
    thread, long after the configuration that caused it.
    """
    settings = Settings(
        _env_file=None,
        embedding_provider="fake",
        qdrant_collection="loadtest",
    )
    assert settings.fake_embed_delay_ms == 0

    with pytest.raises(ValidationError, match="fake_embed_delay_ms"):
        Settings(
            _env_file=None,
            embedding_provider="fake",
            qdrant_collection="loadtest",
            fake_embed_delay_ms=-1,
        )
