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


def test_a_missing_api_key_names_the_field() -> None:
    """The error must say which setting is missing.

    Without the key this surfaces much later as an opaque provider error, and
    "401 from Google" does not tell you that GOOGLE_API_KEY was never set.
    """
    with pytest.raises(ValidationError, match="google_api_key"):
        Settings(_env_file=None)
