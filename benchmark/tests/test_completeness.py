"""The completeness contract. Stage 3.1.

**The most important behaviour in the harness**, and the easiest to get subtly
wrong, because every failure mode here produces a number that looks fine.

A run with any failure is not a benchmark. Its metrics are not a smaller
measurement of the same thing — they measure whichever questions happened to
succeed, which is a sample selected by the failure. So:

    "complete": false, a non-zero exit code, INCOMPLETE in the filename,
    and no baseline written, whatever --baseline said.

`run_eval.retrieve` is replaced rather than HTTP being stubbed: what is under
test is the decision, not the transport. The transport's own guarantee — that
a misaligned response is detected — is tested separately at the bottom.
"""

import json
import pathlib

import pytest

from benchmark import run_eval
from benchmark.tests.conftest import SHORT


@pytest.fixture
def paths(tmp_path: pathlib.Path, monkeypatch) -> dict[str, pathlib.Path]:
    """Redirect the output directories into the test's own tmp_path."""
    runs = tmp_path / "runs"
    baselines = tmp_path / "baselines"
    monkeypatch.setattr(run_eval, "RUNS", runs)
    monkeypatch.setattr(run_eval, "BASELINES", baselines)
    return {"runs": runs, "baselines": baselines}


def chunk(page: int, score: float = 0.5) -> dict:
    return {
        "document_id": "doc-1",
        "filename": SHORT,
        "page": page,
        "chunk_index": 0,
        "score": score,
        "text": f"page {page}",
    }


def run(corpus: pathlib.Path, questions: pathlib.Path, *extra: str) -> int:
    return run_eval.main(
        [
            "--questions",
            str(questions),
            "--documents",
            str(corpus),
            "--top-k",
            "3",
            *extra,
        ]
    )


def only_report(directory: pathlib.Path) -> dict:
    files = sorted(directory.glob("*.json"))
    assert len(files) == 1, f"expected one report in {directory}, found {files}"
    return json.loads(files[0].read_text(encoding="utf-8"))


@pytest.fixture
def two_questions(write_questions) -> pathlib.Path:
    return write_questions(
        f"q1,{SHORT},What is on page one?,1,Page one,lookup,true",
        f"q2,{SHORT},What is on page two?,2,Page two,lookup,true",
    )


def test_a_complete_run_reports_complete_and_exits_zero(
    corpus, two_questions, paths, monkeypatch
) -> None:
    monkeypatch.setattr(
        run_eval, "retrieve", lambda client, questions, *, top_k: [[chunk(1)], [chunk(2)]]
    )

    assert run(corpus, two_questions) == 0

    report = only_report(paths["runs"])
    assert report["complete"] is True
    assert report["questions_evaluated"] == 2
    assert report["questions_failed"] == 0
    assert "INCOMPLETE" not in sorted(paths["runs"].glob("*.json"))[0].name


def test_a_failed_batch_makes_the_run_incomplete(
    corpus, two_questions, paths, monkeypatch
) -> None:
    """**The contract.** One failure, and nothing is a benchmark.

    Note what is asserted alongside the exit code: the metrics are still
    computed and written, because the per-question detail is the most useful
    thing you have when diagnosing why a run failed. What must not happen is
    that number being *called* a baseline.
    """

    def fail(client, questions, *, top_k):
        raise RuntimeError("the agent refused us")

    monkeypatch.setattr(run_eval, "retrieve", fail)

    assert run(corpus, two_questions) == 1

    report = only_report(paths["runs"])
    assert report["complete"] is False
    assert report["questions_evaluated"] == 0
    assert report["questions_failed"] == 2
    assert [f["id"] for f in report["failures"]] == ["q1", "q2"]
    assert "the agent refused us" in report["failures"][0]["reason"]


def test_an_incomplete_run_is_named_incomplete(
    corpus, two_questions, paths, monkeypatch
) -> None:
    """The filename says so, for the case where nobody opens the JSON."""
    monkeypatch.setattr(
        run_eval, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no"))
    )

    run(corpus, two_questions)

    assert "INCOMPLETE" in sorted(paths["runs"].glob("*.json"))[0].name


def test_an_incomplete_run_writes_no_baseline_even_when_asked(
    corpus, two_questions, paths, monkeypatch
) -> None:
    """`--baseline` is not an override. **This is the one that matters.**

    Someone running with `--baseline` has already decided they want a
    comparable number. A partial run handing them one is how a biased sample
    becomes the thing every later stage is measured against.
    """
    monkeypatch.setattr(
        run_eval, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no"))
    )

    assert run(corpus, two_questions, "--baseline") == 1
    assert not paths["baselines"].exists() or list(paths["baselines"].glob("*")) == []


def test_a_complete_run_with_the_flag_writes_a_baseline(
    corpus, two_questions, paths, monkeypatch
) -> None:
    monkeypatch.setattr(
        run_eval, "retrieve", lambda client, questions, *, top_k: [[chunk(1)], [chunk(2)]]
    )

    assert run(corpus, two_questions, "--baseline") == 0
    assert only_report(paths["baselines"])["complete"] is True


def test_a_complete_run_without_the_flag_writes_no_baseline(
    corpus, two_questions, paths, monkeypatch
) -> None:
    """Writing a baseline is always explicit, so one cannot be overwritten by
    an ordinary run."""
    monkeypatch.setattr(
        run_eval, "retrieve", lambda client, questions, *, top_k: [[chunk(1)], [chunk(2)]]
    )

    assert run(corpus, two_questions) == 0
    assert not paths["baselines"].exists() or list(paths["baselines"].glob("*")) == []


def test_a_bad_question_file_means_no_run_at_all(
    corpus, write_questions, paths
) -> None:
    """Refused before the agent is contacted, with every problem listed.

    No report is written either: there is nothing to report on, and an empty
    one in `runs/` would look like a run that found nothing.
    """
    questions = write_questions(
        f"q1,{SHORT},Bad type?,1,An answer,lookpu,true",
        f"q2,{SHORT},Bad flag?,1,An answer,lookup,yes",
    )

    assert run(corpus, questions) == 1
    assert not paths["runs"].exists() or list(paths["runs"].glob("*")) == []


def test_an_empty_question_file_is_refused(corpus, write_questions, paths) -> None:
    """Zero questions must not be able to produce a report at all.

    Without this, every metric would be `None`, `complete` would be `true`,
    and the run would exit zero — a passing benchmark that measured nothing.
    """
    assert run(corpus, write_questions()) == 1
    assert not paths["runs"].exists() or list(paths["runs"].glob("*")) == []


def test_the_report_records_what_it_measured(
    corpus, two_questions, paths, monkeypatch
) -> None:
    """A number with no record of what produced it is not reproducible.

    Stage 3.1 asks for a baseline that is "committed, versioned, reproducible".
    Two baselines that disagree are then either a real change or a different
    instrument, and the provenance block is what tells them apart.
    """
    monkeypatch.setattr(
        run_eval, "retrieve", lambda client, questions, *, top_k: [[chunk(1)], [chunk(2)]]
    )

    run(corpus, two_questions)
    provenance = only_report(paths["runs"])["provenance"]

    assert len(provenance["questions_sha256"]) == 64
    assert set(provenance["corpus"]) == {"short.pdf", "long.pdf"}
    assert all(len(digest) == 64 for digest in provenance["corpus"].values())


def test_unanswerable_questions_are_their_own_slice(
    corpus, write_questions, paths, monkeypatch
) -> None:
    """Not averaged in as zeros.

    One answerable question found at rank 1, one unanswerable. Overall recall
    must be 1.0 — counting the unanswerable one as a zero would report 0.5 and
    make the system look worse for every good unanswerable question written.
    """
    questions = write_questions(
        f"q1,{SHORT},What is on page one?,1,Page one,lookup,true",
        f"q2,{SHORT},What rate limit?,,,near_miss,false",
    )
    monkeypatch.setattr(
        run_eval,
        "retrieve",
        lambda client, questions, *, top_k: [[chunk(1)], [chunk(3, score=0.2)]],
    )

    assert run(corpus, questions) == 0

    report = only_report(paths["runs"])
    assert report["overall"]["questions"] == 1
    assert report["overall"]["recall@3"] == 1.0
    assert report["unanswerable"]["questions"] == 1
    assert report["unanswerable"]["top1_score"]["median"] == 0.2


# ── the transport's own guarantee ────────────────────────────────────────────


class _StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _StubClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.posted: list[dict] = []

    def post(self, url: str, *, json: dict, timeout: float) -> _StubResponse:
        self.posted.append(json)
        return _StubResponse(self._payload)


def test_a_misaligned_response_is_detected() -> None:
    """**Why the agent echoes the question back.**

    `retrieve_many` guarantees ordering by construction, but serialisation and
    an HTTP hop are a new place for it to break. Without this check a swapped
    pair would attribute each question's chunks to the other, silently, and
    produce a perfectly plausible recall figure.
    """
    swapped = {
        "results": [
            {"question": "beta", "chunks": []},
            {"question": "alpha", "chunks": []},
        ]
    }

    with pytest.raises(RuntimeError, match="misaligned"):
        run_eval.retrieve(_StubClient(swapped), ["alpha", "beta"], top_k=3)


def test_a_short_response_is_detected() -> None:
    """Two questions, one result. Caught before anything is scored."""
    short = {"results": [{"question": "alpha", "chunks": []}]}

    with pytest.raises(RuntimeError, match="got 1 results"):
        run_eval.retrieve(_StubClient(short), ["alpha", "beta"], top_k=3)


def test_top_k_is_omitted_from_the_payload_when_it_is_none() -> None:
    """So the engine's own default applies rather than the harness inventing one."""
    client = _StubClient({"results": [{"question": "alpha", "chunks": []}]})

    run_eval.retrieve(client, ["alpha"], top_k=None)

    assert client.posted == [{"questions": ["alpha"]}]
