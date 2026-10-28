"""Retrieval metrics, against hand-computed values. Stage 3.1.

Every expected number here was worked out by hand rather than recorded from a
run. A metric test that asserts what the code currently produces is a
regression test for a formula nobody checked — and this module is the
instrument the whole of Module 4 will be argued from.

**One defect got past the first version of this file**, and it is worth reading
`test_the_same_page_in_another_document_is_not_a_hit` before anything else.
Relevance was keyed on page number alone, and every test here used bare page
lists with no second document in play — so the bug was invisible to all of them
and took a live run to surface. The helper below now always names a document.
"""

import math

import pytest

from benchmark import metrics

DOC = "paper.pdf"
OTHER = "other.pdf"


def at(page: int, document: str = DOC) -> metrics.Location:
    """One location: `(filename, page)`. One page per chunk, because
    `rag.chunking.chunk_pages` loops per page."""
    return (document, page)


# ── the defect a live run found ──────────────────────────────────────────────


def test_the_same_page_in_another_document_is_not_a_hit() -> None:
    """**Page 1 exists in every document in the corpus.**

    The first version of these metrics compared page numbers only, so a gold
    answer on page 1 of `acl-dpr-2020.pdf` was satisfied by page 1 of any
    document at all. An index holding leftover test documents duly scored
    `recall@3 = 1.0` on a question whose gold page had never been retrieved.

    Across a five-document corpus that inflates recall by roughly the number
    of documents, and it does so most for the easiest questions — the ones
    whose answers are near the front of a document.
    """
    gold = {at(1)}
    wrong_document = [at(1, OTHER), at(2, OTHER)]

    assert metrics.recall_at_k(gold, wrong_document, k=5) == 0.0
    assert metrics.precision_at_k(gold, wrong_document, k=5) == 0.0
    assert metrics.reciprocal_rank(gold, wrong_document) == 0.0
    assert metrics.first_gold_rank(gold, wrong_document) is None


# ── recall: strict, per gold location ────────────────────────────────────────


def test_recall_is_one_when_the_only_gold_page_is_found() -> None:
    assert metrics.recall_at_k({at(7)}, [at(3), at(7), at(9)], k=5) == 1.0


def test_recall_is_zero_when_no_gold_page_is_found() -> None:
    assert metrics.recall_at_k({at(7)}, [at(3), at(9), at(11)], k=5) == 0.0


def test_recall_is_partial_when_only_one_gold_page_is_found() -> None:
    """**The multi-page decision, and the one most worth disputing.**

    Strict IR recall divides by the number of gold locations, so finding one of
    two is 0.5. The lenient alternative — "any gold location is a hit" — would
    score 1.0 here and make every `multi_page` question indistinguishable from
    a `lookup`, which is most of the reason for having the type.
    """
    assert metrics.recall_at_k({at(73), at(74)}, [at(73), at(9)], k=5) == 0.5


def test_recall_respects_k_rather_than_the_whole_list() -> None:
    """A gold page at rank 6 is not found by recall@5.

    The route may return more chunks than the k being measured, and a metric
    that quietly scored the whole list would report a recall the running system
    never achieves.
    """
    retrieved = [at(1), at(2), at(3), at(4), at(5), at(7)]

    assert metrics.recall_at_k({at(7)}, retrieved, k=5) == 0.0
    assert metrics.recall_at_k({at(7)}, retrieved, k=6) == 1.0


def test_a_duplicate_gold_page_in_the_results_does_not_inflate_recall() -> None:
    """Two chunks from the same gold page is still one location found."""
    gold = {at(73), at(74)}
    assert metrics.recall_at_k(gold, [at(73), at(73), at(73)], k=5) == 0.5


# ── precision: per chunk ─────────────────────────────────────────────────────


def test_precision_counts_chunks_and_recall_counts_locations() -> None:
    """**The asymmetry, asserted so it reads as deliberate.**

    Three chunks, two of them from the one gold page. Precision asks how much
    of what the caller was handed was useful — two of five. Recall asks how
    much of what was needed was found — the single gold location, so 1.0.

    Someone will eventually assume these two use the same notion of relevance.
    This is the test that tells them otherwise.
    """
    gold = {at(7)}
    retrieved = [at(7), at(7), at(3)]

    assert metrics.precision_at_k(gold, retrieved, k=5) == 2 / 5
    assert metrics.recall_at_k(gold, retrieved, k=5) == 1.0


def test_precision_divides_by_k_not_by_what_came_back() -> None:
    """The textbook definition, and the edge it has.

    Two chunks returned, both useful, k=5 gives 0.4 rather than 1.0. This only
    bites when the index holds fewer than k chunks in total — impossible for a
    corpus of this size — and it is the standard convention, so it is kept and
    documented rather than quietly changed.
    """
    assert metrics.precision_at_k({at(7)}, [at(7), at(7)], k=5) == 2 / 5


# ── rank and MRR ─────────────────────────────────────────────────────────────


def test_the_first_gold_rank_counts_from_one() -> None:
    """Ranks are 1-indexed because a reciprocal rank divides by them.

    From zero, the first result would divide by zero; worse, it would silently
    make every reciprocal rank one position too generous.
    """
    assert metrics.first_gold_rank({at(7)}, [at(7), at(3), at(9)]) == 1
    assert metrics.first_gold_rank({at(7)}, [at(3), at(7), at(9)]) == 2
    assert metrics.first_gold_rank({at(7)}, [at(3), at(9)]) is None


@pytest.mark.parametrize(
    ("pages", "expected"),
    [([7, 3, 9], 1.0), ([3, 7, 9], 0.5), ([3, 9, 7], 1 / 3), ([3, 9, 11], 0.0)],
)
def test_mrr_is_the_reciprocal_of_the_first_gold_rank(
    pages: list[int], expected: float
) -> None:
    retrieved = [at(page) for page in pages]
    assert metrics.reciprocal_rank({at(7)}, retrieved) == pytest.approx(expected)


def test_a_miss_on_an_answerable_question_scores_zero_not_undefined() -> None:
    """Zero and "not measured" are different facts.

    The question had an answer and retrieval missed it. That is a score of
    zero. `None` is reserved for a question with no gold location at all, and
    conflating them would either hide real failures or invent them.
    """
    assert metrics.reciprocal_rank({at(7)}, [at(1), at(2)]) == 0.0
    assert metrics.reciprocal_rank(set(), [at(1), at(2)]) is None


# ── nDCG ─────────────────────────────────────────────────────────────────────


def test_ndcg_matches_a_hand_computed_value() -> None:
    """One gold location, found at rank 2.

        DCG  = 1 / log2(2 + 1) = 1 / 1.585 = 0.6309
        IDCG = 1 / log2(1 + 1) = 1.0
        nDCG = 0.6309
    """
    expected = (1 / math.log2(3)) / (1 / math.log2(2))
    assert metrics.ndcg_at_k({at(7)}, [at(3), at(7), at(9)], k=5) == pytest.approx(
        expected
    )


def test_ndcg_credits_a_gold_page_only_once() -> None:
    """**Required, not tidy.** Without it nDCG can exceed 1.

    One gold location, two retrieved chunks from it. Counting both gives
    `1/log2(2) + 1/log2(3) = 1.631` against an ideal of `1.0` — a normalised
    metric above 1, which is meaningless. De-duplicating by location caps the
    relevant count at `|gold|` and makes the ideal exact.
    """
    assert metrics.ndcg_at_k({at(7)}, [at(7), at(7), at(7)], k=5) == pytest.approx(1.0)


def test_ndcg_rewards_finding_the_second_gold_page_higher() -> None:
    """The only case where nDCG says anything MRR does not.

    With a single gold location, nDCG@k is `1/log2(rank+1)` and MRR is
    `1/rank` — both strictly decreasing in the same rank, so they order systems
    identically and nDCG carries no independent information. Two gold locations
    is where it earns its place: both runs below have the same first-gold rank,
    and therefore the same MRR.
    """
    gold = {at(73), at(74)}
    early = [at(73), at(74), at(1)]
    late = [at(73), at(1), at(74)]

    assert metrics.reciprocal_rank(gold, early) == metrics.reciprocal_rank(gold, late)
    assert metrics.ndcg_at_k(gold, early, k=5) > metrics.ndcg_at_k(gold, late, k=5)


def test_ndcg_is_one_for_a_perfect_ranking() -> None:
    gold = {at(73), at(74)}
    assert metrics.ndcg_at_k(gold, [at(74), at(73), at(1)], k=5) == pytest.approx(1.0)


# ── unanswerable questions ───────────────────────────────────────────────────


def test_a_question_with_no_gold_location_has_no_metrics() -> None:
    """Not zeros. **This is the decision that protects the headline number.**

    Averaging a fifth of the eval set in as zeros would understate recall by
    roughly a fifth, and the error would scale with how many unanswerable
    questions were written — so adding good questions would make the system
    look worse. They are reported as their own slice instead.
    """
    scores = metrics.score_question(set(), [at(1), at(2), at(3)], k=5)

    assert scores.recall is None
    assert scores.precision is None
    assert scores.reciprocal_rank is None
    assert scores.ndcg is None


def test_mean_ignores_undefined_rather_than_counting_it_zero() -> None:
    assert metrics.mean([1.0, 0.0, None]) == pytest.approx(0.5)
    assert metrics.mean([None, None]) is None
    assert metrics.mean([]) is None
