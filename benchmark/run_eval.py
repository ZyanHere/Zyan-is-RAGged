"""Run the retrieval evaluation. Stage 3.1.

    agent/.venv/Scripts/python.exe benchmark/run_eval.py
    agent/.venv/Scripts/python.exe benchmark/run_eval.py --baseline

Measures retrieval and nothing else: no language model is involved anywhere in
this path, which is what makes the number attributable to retrieval rather than
to generation.

── The completeness contract ──────────────────────────────────────────────────

**A run with any failure is not a benchmark.** If one question's batch fails,
or a response comes back misaligned, or the question file has a single bad row,
then:

    "complete": false  in the report
    a non-zero exit code
    the file lands in benchmark/runs/ with INCOMPLETE in its name
    no baseline is written, whatever --baseline says

The reason is that a partial run's metrics are not a smaller measurement of the
same thing — they are a measurement of whichever questions happened to succeed,
which is a biased sample selected by the failure. Averaging 47 of 50 questions
and calling it recall invites exactly the comparison it cannot support.

This is the same all-or-nothing rule `rag.retrieve_many` applies to its inputs
and `RetrieveRequest` applies at the HTTP boundary, applied to the run.

── Why a baseline records its own provenance ──────────────────────────────────

Stage 3.1's "done when" asks for a baseline that is *"committed, versioned,
reproducible"*. A number with no record of what produced it is none of those,
so every report carries the SHA-256 of each corpus document, the SHA-256 of
the question file, and the `top_k` used. Two baselines that disagree are then
either a real change or a different instrument, and the report says which.

── Why it talks to the agent over HTTP ────────────────────────────────────────

It has no choice. Embedded Qdrant holds an exclusive lock on its storage, and
that storage is a named Docker volume inside the agent's container —
`docker-compose.yml` has said since 1.3 that a host-side harness "cannot read
it directly". Worse, it fails silently: `get_client()` creates the folder if
missing, so a host script reports plausible numbers against an empty or stale
index. `POST /retrieve` is the agent exposing retrieval without generation.
"""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import statistics
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from benchmark import metrics  # noqa: E402
from benchmark.loader import load_questions  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCUMENTS = ROOT / "benchmark" / "documents"
QUESTIONS = ROOT / "benchmark" / "questions" / "questions.csv"
RUNS = ROOT / "benchmark" / "runs"
BASELINES = ROOT / "benchmark" / "baselines"

AGENT = "http://localhost:8001"

BATCH = 100
"""Questions per HTTP request. The agent refuses more; see `MAX_QUESTIONS`."""

TIMEOUT = 300.0
"""Generous. One batch is one embedding request plus N local searches, and a
timeout here would record a failure where the true answer is "slow"."""


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentiles(values: list[float]) -> dict[str, float] | None:
    """Nearest-rank, the same convention `tools/capacity_probe.py` uses."""
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
    }


def retrieve(
    client: httpx.Client, questions: list[str], *, top_k: int | None
) -> list[list[dict]]:
    """One batch through POST /retrieve, with alignment verified.

    The agent echoes each question back, and this is where that pays for
    itself. `retrieve_many` guarantees ordering by construction, but
    serialisation and an HTTP hop are a new place for it to break — and a
    misaligned response would attribute every later metric to the wrong
    question, silently, producing a plausible number.
    """
    payload: dict = {"questions": questions}
    if top_k is not None:
        payload["top_k"] = top_k

    response = client.post("/retrieve", json=payload, timeout=TIMEOUT)
    response.raise_for_status()

    results = response.json()["results"]

    if len(results) != len(questions):
        raise RuntimeError(
            f"asked for {len(questions)} questions, got {len(results)} results"
        )

    for sent, got in zip(questions, results, strict=True):
        if got["question"] != sent:
            raise RuntimeError(
                f"response misaligned: asked {sent!r}, got {got['question']!r}"
            )

    return [result["chunks"] for result in results]


def main(argv: list[str] | None = None) -> int:
    """`argv` is taken rather than read from `sys.argv` so a test can drive it.

    The completeness contract is the most important behaviour in this file and
    the easiest to get subtly wrong, so it has to be exercisable without a
    subprocess and without a live agent.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", default=AGENT)
    parser.add_argument("--questions", type=pathlib.Path, default=QUESTIONS)
    parser.add_argument("--documents", type=pathlib.Path, default=DOCUMENTS)
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="chunks per question; omitted means the engine's configured default",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="also write to benchmark/baselines/ — only ever on a complete run",
    )
    args = parser.parse_args(argv)

    # ── The question set, refused whole if any row is bad ──────────────────────
    loaded = load_questions(args.questions, documents_dir=args.documents)

    if loaded.problems:
        print(f"{len(loaded.problems)} problem(s) in {args.questions.name}:\n")
        for problem in loaded.problems:
            print(f"  {problem}")
        print(
            "\nNo run, and no partial run. Every problem is listed above rather "
            "than one at a time."
        )
        return 1

    questions = loaded.questions
    if not questions:
        print(f"{args.questions.name} has no questions. Nothing to measure.")
        return 1

    # ── Retrieval, in batches ─────────────────────────────────────────────────
    failures: list[dict] = []
    chunks_by_id: dict[str, list[dict]] = {}

    with httpx.Client(base_url=args.agent) as client:
        for start in range(0, len(questions), BATCH):
            batch = questions[start : start + BATCH]
            try:
                answers = retrieve(
                    client, [q.question for q in batch], top_k=args.top_k
                )
            except Exception as exc:
                # The whole batch is untrustworthy, not just one question: an
                # alignment failure means we do not know which result belonged
                # to which question, and an HTTP failure means we have none.
                for question in batch:
                    failures.append(
                        {
                            "id": question.id,
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    )
                continue

            for question, chunks in zip(batch, answers, strict=True):
                chunks_by_id[question.id] = chunks

    # ── Scoring ───────────────────────────────────────────────────────────────
    # `top_k` for the metrics is what retrieval actually returned at most, not
    # what was asked for: `--top-k` may be None, meaning the engine chose.
    # Measuring recall@5 against a run that returned 3 would be a different
    # metric wearing the same name.
    observed_k = max((len(c) for c in chunks_by_id.values()), default=0)
    k = args.top_k or observed_k or 1

    detail: list[dict] = []

    for question in questions:
        chunks = chunks_by_id.get(question.id)
        if chunks is None:
            continue  # already recorded as a failure

        # `(filename, page)`, not page alone. A gold answer on page 1 of one
        # document must not be satisfied by page 1 of another — page 1 exists
        # in every document in the corpus. The first live run scored
        # recall@3 = 1.0 on a question whose gold page had never been
        # retrieved, because the index held a leftover test document with its
        # own page 1.
        retrieved = [(chunk["filename"], chunk["page"]) for chunk in chunks]
        gold = {(question.document, page) for page in question.gold_pages}

        scores = metrics.score_question(gold, retrieved, k)

        detail.append(
            {
                "id": question.id,
                "type": question.type,
                "answerable": question.answerable,
                "document": question.document,
                "gold_pages": sorted(question.gold_pages),
                "retrieved": [list(location) for location in retrieved],
                "top1_score": chunks[0]["score"] if chunks else None,
                "first_gold_rank": scores.first_gold_rank,
                "recall": scores.recall,
                "precision": scores.precision,
                "reciprocal_rank": scores.reciprocal_rank,
                "ndcg": scores.ndcg,
            }
        )

    answerable = [d for d in detail if d["answerable"]]
    unanswerable = [d for d in detail if not d["answerable"]]

    def aggregate(rows: list[dict]) -> dict:
        return {
            "questions": len(rows),
            f"recall@{k}": metrics.mean([r["recall"] for r in rows]),
            f"precision@{k}": metrics.mean([r["precision"] for r in rows]),
            "mrr": metrics.mean([r["reciprocal_rank"] for r in rows]),
            f"ndcg@{k}": metrics.mean([r["ndcg"] for r in rows]),
        }

    by_type: dict[str, dict] = {}
    for kind in sorted({d["type"] for d in answerable}):
        by_type[kind] = aggregate([d for d in answerable if d["type"] == kind])

    complete = not failures

    report = {
        "complete": complete,
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "agent": args.agent,
        "top_k_requested": args.top_k,
        "k_used": k,
        "questions_total": len(questions),
        "questions_evaluated": len(detail),
        "questions_failed": len(failures),
        "failures": failures,
        "provenance": {
            "questions_sha256": sha256(args.questions),
            "corpus": {
                path.name: sha256(path)
                for path in sorted(args.documents.glob("*.pdf"))
            },
        },
        # A naming mismatch between the corpus on disk and the filenames the
        # index was built with would make every gold location unreachable, and
        # the symptom is recall 0.0 everywhere — indistinguishable from
        # genuinely terrible retrieval. These two sets side by side name it
        # immediately. They need not be equal: retrieval may legitimately
        # return a document no question asks about.
        "documents": {
            "expected_by_gold": sorted(
                {q.document for q in questions if q.document is not None}
            ),
            "seen_in_results": sorted(
                {location[0] for row in detail for location in row["retrieved"]}
            ),
        },
        "overall": aggregate(answerable),
        "by_type": by_type,
        # No recall for these: an unanswerable question has no gold page, so it
        # has no recall rather than zero recall. Averaging them in as zeros
        # would understate the system by however many were written. What is
        # useful is how confident retrieval was about nothing — which stage
        # 17.3 calibrates abstention against.
        "unanswerable": {
            "questions": len(unanswerable),
            "top1_score": percentiles(
                [d["top1_score"] for d in unanswerable if d["top1_score"] is not None]
            ),
        },
        "questions": detail,
    }

    # ── Writing it out ────────────────────────────────────────────────────────
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if complete else "-INCOMPLETE"

    RUNS.mkdir(parents=True, exist_ok=True)
    run_path = RUNS / f"{stamp}{suffix}.json"
    run_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{'COMPLETE' if complete else 'INCOMPLETE'}  ->  {run_path}")
    print(
        f"  {report['questions_evaluated']}/{report['questions_total']} evaluated, "
        f"{report['questions_failed']} failed"
    )

    if not complete:
        print("\nfailures:")
        for failure in failures:
            print(f"  {failure['id']}: {failure['reason']}")
        print(
            "\nNot a benchmark. A partial run's metrics measure whichever "
            "questions happened to succeed, which is a sample selected by the "
            "failure — so no baseline was written and the exit code is non-zero."
        )
        return 1

    print(f"\n  answerable: {report['overall']}")
    for kind, slice_ in by_type.items():
        print(f"  {kind:14} {slice_}")
    print(f"  unanswerable: {report['unanswerable']}")

    if args.baseline:
        BASELINES.mkdir(parents=True, exist_ok=True)
        baseline_path = BASELINES / f"{stamp}.json"
        baseline_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nbaseline written  ->  {baseline_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
