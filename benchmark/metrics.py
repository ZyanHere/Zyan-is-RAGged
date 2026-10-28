"""Retrieval metrics at page granularity. Stage 3.1.

Pure functions over `(gold, retrieved, k)`. No I/O, no CSV, no HTTP, no
knowledge of how retrieval happened — the same discipline `rag`'s
`chunking.py` follows, and for the same reason: a metric that needs a
configured world cannot be checked against a hand-computed value.

── A location is a document *and* a page ──────────────────────────────────────

**This was wrong in the first version of this file, and only a live run found
it.** Relevance was keyed on the page number alone, so a gold answer on page 1
of `acl-dpr-2020.pdf` was satisfied by page 1 of *any* document. The first
end-to-end run against an index holding leftover test documents scored
`recall@3 = 1.0` on a question whose gold page had never been retrieved — the
right page number from the wrong document.

Every unit test missed it, because every one of them used bare page lists with
no second document in play. The corpus has five, and page 1 exists in all of
them.

So relevance is `(filename, page)`. The filename comes from `Chunk.filename`,
carried onto every chunk since stage 1.1, and the gold document is the
question's `document` column. If a corpus document was ingested under a
different name than the manifest records, nothing will ever match — which is
why the runner reports the filenames it actually saw alongside the ones the
gold expects.

── Why pages, rather than character spans ─────────────────────────────────────

`rag.chunking.chunk_pages` loops *per page*, so every `Chunk` carries exactly
one page number. Page-level relevance is therefore not a simplification — it is
the finest granularity the data actually has, and it needs no span alignment
between a gold answer's text and a chunk's text.

── Three relevance models, one per question being asked ───────────────────────

This is the part to read carefully, because it looks like inconsistency and is
not. Each metric answers a different question, and the right notion of
"relevant" differs with the question:

    recall@k      per gold location   "how much of what I needed did I find?"
    precision@k   per chunk           "how much of what I was handed was useful?"
    MRR           per chunk           "how far down was the first useful thing?"
    nDCG@k        per gold location,  "was the useful thing near the top?"
                  first hit only

Recall divides by `|gold|`, so finding one of two gold pages is **0.5**. That
is the textbook definition and it is what makes `multi_page` questions worth
writing; the lenient alternative — "any gold location is a hit" — would score
1.0 and flatter the system.

Precision counts *chunks*, because the thing it measures is how much junk ends
up in a context window. Two chunks from the same gold page are two useful
chunks by that measure, and both would genuinely help a generator.

nDCG de-duplicates by location, and that is **load-bearing rather than tidy**.
Without it the metric breaks: with one gold location and two retrieved chunks
from it, a per-chunk DCG is `1/log2(2) + 1/log2(3) = 1.63` against an ideal DCG
of `1.0`, giving nDCG > 1. De-duplicating caps the number of relevant items at
`|gold|`, which makes the ideal exact and the ratio bounded.

── What nDCG is worth here, stated rather than implied ────────────────────────

Almost nothing, for most of this eval set, and the arithmetic says why. With a
single gold location and binary relevance there is exactly one relevant item:

    nDCG@k = 1 / log2(rank + 1)        and        RR = 1 / rank

Both are strictly decreasing functions of the same rank. They order two systems
identically, so nDCG adds a number and no information. It differs from MRR
**only** when `|gold| > 1` — the `multi_page` questions — where it rewards
finding the second gold page high rather than ignoring it.

It is implemented because the curriculum names it under Learn, and because the
degeneracy above is more useful to have measured and written down than to have
omitted. It must not be quoted as if it carried independent evidence.
"""

import math
from dataclasses import dataclass

Location = tuple[str, int]
"""Where a chunk is: `(filename, page)`. Pages are 1-indexed, as `Chunk.page`
records them and as a human counts."""

# Every metric returns `None` rather than 0.0 when a question has no gold
# location. An unanswerable question has no recall — not zero recall — and
# averaging it in as a zero would understate the system by however many such
# questions the eval set happens to contain. They are reported as their own
# slice instead; calibrating abstention against them is stage 17.3.
Undefined = None


@dataclass(frozen=True)
class QuestionScores:
    """Every metric for one question, or `None` where undefined."""

    recall: float | None
    precision: float | None
    reciprocal_rank: float | None
    ndcg: float | None

    # Not a metric, and the most useful single number when a question fails:
    # the 1-indexed rank of the first chunk at a gold location, or None if none
    # appeared at all. "It was at rank 7 with top_k=5" and "it was nowhere" are
    # different diagnoses with different fixes.
    first_gold_rank: int | None


def recall_at_k(
    gold: set[Location], retrieved: list[Location], k: int
) -> float | None:
    """Fraction of gold locations that appear in the top k chunks.

    Strict: `|gold ∩ retrieved@k| / |gold|`. One of two gold pages is 0.5.
    """
    if not gold:
        return Undefined

    return len(gold & set(retrieved[:k])) / len(gold)


def precision_at_k(
    gold: set[Location], retrieved: list[Location], k: int
) -> float | None:
    """Fraction of the top k chunks that came from a gold location.

    Divided by `k`, not by how many chunks actually came back — the textbook
    definition. The two differ only when the index holds fewer than `k` chunks
    in total, which cannot happen for a corpus of this size but would make the
    number pessimistic rather than wrong if it did.
    """
    if not gold:
        return Undefined

    return sum(1 for location in retrieved[:k] if location in gold) / k


def first_gold_rank(gold: set[Location], retrieved: list[Location]) -> int | None:
    """1-indexed rank of the first chunk at a gold location, or None.

    Ranks count from 1, because a reciprocal rank divides by this number.
    """
    for rank, location in enumerate(retrieved, start=1):
        if location in gold:
            return rank
    return None


def reciprocal_rank(gold: set[Location], retrieved: list[Location]) -> float | None:
    """1 / rank of the first useful chunk. Zero when none was found.

    Zero rather than `None` for a question that found nothing: the question
    *had* an answer and retrieval missed it, which is a score of zero and not
    an undefined measurement. `None` is reserved for questions with no gold
    location at all.
    """
    if not gold:
        return Undefined

    rank = first_gold_rank(gold, retrieved)
    return 1.0 / rank if rank is not None else 0.0


def ndcg_at_k(gold: set[Location], retrieved: list[Location], k: int) -> float | None:
    """Normalised DCG, binary relevance, de-duplicated by location.

    Only the *first* chunk from each gold location counts as relevant — see the
    module docstring for why that is required rather than preferred.
    """
    if not gold:
        return Undefined

    gain = 0.0
    credited: set[Location] = set()

    for rank, location in enumerate(retrieved[:k], start=1):
        if location in gold and location not in credited:
            credited.add(location)
            gain += 1.0 / math.log2(rank + 1)

    # The ideal ranking puts as many gold locations as could fit at the very
    # top. Exact, now that relevance is capped at one hit per location.
    ideal = sum(
        1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(gold)) + 1)
    )

    return gain / ideal if ideal else Undefined


def score_question(
    gold: set[Location], retrieved: list[Location], k: int
) -> QuestionScores:
    """Every metric for one question."""
    return QuestionScores(
        recall=recall_at_k(gold, retrieved, k),
        precision=precision_at_k(gold, retrieved, k),
        reciprocal_rank=reciprocal_rank(gold, retrieved),
        ndcg=ndcg_at_k(gold, retrieved, k),
        first_gold_rank=first_gold_rank(gold, retrieved),
    )


def mean(values: list[float | None]) -> float | None:
    """Average, ignoring undefined measurements rather than counting them zero.

    `None` in, `None` out when nothing is defined — a slice containing only
    unanswerable questions has no mean recall, and reporting 0.0 would read as
    "retrieval failed completely" rather than "this was not measured".
    """
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined) if defined else Undefined
