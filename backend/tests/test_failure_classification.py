"""Which failures are worth retrying. Stage 2.3.

Two pure things, tested purely: the classifier, and the delay the retry policy
computes. Neither touches a database, because neither has any business doing
so — the whole of `classify` is a decision about a number, and `delay_for` is
arithmetic plus a random draw.

── Why this file exists separately from test_worker.py ─────────────────────────

`test_worker.py` proves the classification *reaches the database*: a 400 lands
on `failed`, a 429 lands back on `queued`. Those are integration tests and they
are slow, so they cover a handful of representative codes.

This file covers the whole table cheaply, including the codes nothing emits
yet. A classifier with a hole in it fails silently — the document is simply
retried, or not, for several minutes — so the cases nobody has seen are the
ones most worth writing down.
"""

import pytest

from app.db.models import FailureKind
from app.services.ingestion import RetryPolicy, classify


# ── The classifier ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status_code", "expected", "raised_by"),
    [
        # 4xx — the request is the problem, and will still be the problem.
        (400, FailureKind.PERMANENT, "InvalidDocumentError — not a PDF"),
        (413, FailureKind.PERMANENT, "UploadTooLargeError"),
        (422, FailureKind.PERMANENT, "NoTextExtractedError — scanned"),
        (404, FailureKind.PERMANENT, "a route that does not exist"),
        # The carve-out. 4xx by number, transient by meaning.
        (429, FailureKind.TRANSIENT, "a rate limit — 'come back later'"),
        # 5xx — the system is the problem.
        (500, FailureKind.TRANSIENT, "VectorStoreError / AgentError"),
        (502, FailureKind.TRANSIENT, "EmbeddingError / ProviderError"),
        (503, FailureKind.TRANSIENT, "a dependency refusing connections"),
        (504, FailureKind.TRANSIENT, "a gateway timeout"),
        # No response at all.
        (None, FailureKind.TRANSIENT, "AgentUnavailableError"),
    ],
)
def test_the_classification_table(
    status_code: int | None, expected: FailureKind, raised_by: str
) -> None:
    """The whole mapping, including codes nothing emits yet.

    `raised_by` is carried through the parametrisation so a failure names the
    *situation* rather than a bare number — "429 — a rate limit" is a
    different kind of bug report from "429".
    """
    assert classify(status_code) is expected, raised_by


def test_the_boundary_is_500_and_not_499() -> None:
    """Off-by-one on the one comparison that decides everything.

    `>= 500` is the whole of the 5xx rule, so a `>` would quietly make every
    500 permanent — and 500 is `VectorStoreError`, our own storage. A disk
    blip would then permanently destroy the document, which is the exact
    failure mode this stage exists to remove, arriving through a typo.
    """
    assert classify(499) is FailureKind.PERMANENT
    assert classify(500) is FailureKind.TRANSIENT


def test_a_success_code_is_never_asked_about() -> None:
    """Documents the contract rather than guarding behaviour.

    `classify` is only called on a failure, so 2xx never reaches it. It still
    returns something — `PERMANENT`, by falling through — and that is worth
    pinning: if a refactor ever routes a success through here, the result is a
    job that fails immediately rather than one that retries forever. The first
    is noticed in minutes; the second is noticed by the bill.
    """
    assert classify(200) is FailureKind.PERMANENT


# ── The delay cap ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("attempt", range(1, 21))
def test_no_single_delay_exceeds_the_cap(attempt: int) -> None:
    """The property the cap exists for, across far more attempts than are used.

    Twenty, not eight, because the cap must hold for whatever `max_attempts`
    is configured to — it is the thing that makes raising the attempt count
    safe. Without `min(...)` the ceiling at attempt 20 is 2 × 2^19 seconds,
    which is twelve days.

    Sampled rather than reasoned about, because `delay_for` draws randomly and
    the bound is on the draw.
    """
    policy = RetryPolicy(max_attempts=20, base_seconds=2.0, max_delay_seconds=60.0)

    delays = [policy.delay_for(attempt) for _ in range(200)]

    assert all(0 <= d <= 60.0 for d in delays), f"max was {max(delays)}"


def test_early_delays_are_not_flattened_by_the_cap() -> None:
    """The cap must bound the tail without destroying the backoff.

    A cap applied too eagerly — or a `min` written as a `max` — would make
    every attempt wait the same distribution, and the "exponential" in
    exponential backoff would be decoration. Attempt 1 draws from [0, 2]; the
    cap is 60 and must not come into it.

    Asserted on the maximum of many draws rather than on one, because a single
    small draw proves nothing about the ceiling.
    """
    policy = RetryPolicy(max_attempts=8, base_seconds=2.0, max_delay_seconds=60.0)

    first = max(policy.delay_for(1) for _ in range(500))
    later = max(policy.delay_for(6) for _ in range(500))

    assert first <= 2.0, "attempt 1's ceiling is base_seconds"
    assert later > 2.0, "the ceiling must still grow before it is capped"


def test_full_jitter_spreads_the_retries() -> None:
    """The jitter, which is the half people leave out.

    Without it every worker that failed against one outage computes the same
    delay and returns in the same instant, re-creating the outage. The
    property is that two draws at the same attempt differ — a fixed backoff
    would make them identical.

    Five hundred draws of a continuous uniform collapsing to one value is not
    a flake; it is a missing `random`.
    """
    policy = RetryPolicy(max_attempts=8, base_seconds=2.0, max_delay_seconds=60.0)

    draws = {policy.delay_for(3) for _ in range(500)}

    assert len(draws) > 1, "every retry would return at the same instant"


def test_the_configured_budget_covers_about_five_minutes() -> None:
    """**The test that should have caught a three-fold error, and did not.**

    Its previous version hardcoded `RetryPolicy(max_attempts=8, ...)` and
    checked the ceilings summed to 182 seconds. Every assertion passed while
    the policy the system actually ran covered a **median of 91 seconds**
    against a decision of about five minutes.

    Two failures at once, both worth naming:

    1. **It tested a literal, not the configuration.** `max_attempts` could
       change to anything and this file would keep agreeing with itself.
    2. **It asserted the sum of the ceilings**, which is the worst case, when
       what a document experiences is the sum of the *draws* — and full jitter
       halves every one. Reasoning about the bound instead of the distribution
       is exactly how "about three minutes" was written down for a policy that
       usually gave up in ninety seconds.

    So this version reads `Settings()` and simulates. The range is wide on
    purpose: it is not pinning a tuning choice, it is catching the case where
    the configuration and the stated intent have drifted apart by an order of
    magnitude — which is the mistake that actually happened.
    """
    import random
    import statistics

    from app.core.config import Settings

    settings = Settings()
    policy = RetryPolicy(
        max_attempts=settings.max_attempts,
        base_seconds=settings.retry_base_seconds,
        max_delay_seconds=settings.max_delay_seconds,
    )

    # Seeded, so a tuning change fails this deterministically rather than
    # one run in twenty.
    random.seed(20260226)

    coverage = sorted(
        sum(policy.delay_for(attempt) for attempt in range(1, policy.max_attempts))
        for _ in range(2000)
    )
    median = statistics.median(coverage)
    p10 = coverage[len(coverage) // 10]

    assert 240 <= median <= 420, (
        f"the retry budget covers a median of {median:.0f}s of outage; the "
        f"decision on record is about five minutes. Either re-tune "
        f"max_attempts/max_delay_seconds or change the decision — do not "
        f"widen this assertion."
    )

    # The tail matters more than the median. A tenth of documents giving up
    # early is what made eight attempts unacceptable: at p10 = 55s an ordinary
    # container restart still destroyed one upload in ten.
    assert p10 >= 120, (
        f"one document in ten gives up after only {p10:.0f}s of outage, which "
        f"a routine restart fits inside"
    )


def test_the_ceilings_grow_then_flatten_at_the_cap() -> None:
    """The shape of the backoff, separately from how much it covers.

    Kept from the previous version of the budget test, because the shape is
    worth pinning on its own: exponential growth until the cap, flat
    afterwards. What is *not* kept is the claim about what that shape adds up
    to — that belongs with a simulation, above.
    """
    ceilings = [min(2.0 * 2 ** (attempt - 1), 60.0) for attempt in range(1, 10)]

    assert ceilings == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0, 60.0]

    policy = RetryPolicy(max_attempts=10, base_seconds=2.0, max_delay_seconds=60.0)
    for attempt, ceiling in enumerate(ceilings, start=1):
        worst = max(policy.delay_for(attempt) for _ in range(200))
        assert worst <= ceiling
