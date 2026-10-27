"""The shape of "is ingestion healthy?". Stage 2.4.

── Why this is JSON and not a Prometheus exposition ───────────────────────────

Because nothing scrapes yet. Prometheus and Grafana arrive at stage 10.1, and
its own roadmap entry says the problem it solves is *"metrics exist but are not
aggregated"* — so an exposition format now would be a wire format with no
consumer, and a format nobody reads drifts from the thing it describes.

What 10.1 will need is the **query**, not the encoding, and that is written
once in `DocumentRepository.ingestion_stats`. Its collector calls the same SQL.

── Why the numbers are nested rather than flat ────────────────────────────────

`queue.claimable` and `dead_letter.permanent` group the way a person reads
them — the first question is *which part of the pipeline*, and only then *how
many*. A flat `claimable` and `permanent` would also collide as soon as
anything else in the system has a queue or a failure count.

The nesting maps cleanly onto metric names with labels later, so it is not a
decision that has to be undone at 10.1.
"""

from pydantic import BaseModel


class QueueStats(BaseModel):
    """What is waiting, and whether it is moving."""

    claimable: int
    """Queued and claimable now — the real backlog."""

    waiting_for_retry: int
    """Queued but held back by stage 2.1's backoff.

    Separate from `claimable` on purpose. Together they would report "eight
    jobs waiting" when nothing is wrong and nothing is stuck — those eight are
    deliberately asleep, and reading that as a backlog sends someone looking
    for a worker that is not missing.
    """

    oldest_age_seconds: float | None
    """How long the longest-waiting queued job has waited. `None` if empty.

    **The number that says whether the queue is draining.** Depth alone cannot:
    300 jobs moving steadily is healthy, 3 jobs that have not moved in an hour
    is an outage, and depth reports the first as worse.
    """


class DeadLetterStats(BaseModel):
    """What has given up, split by whether anything can be done about it."""

    total: int

    permanent: int
    """Will never succeed. A pile of these is a corpus problem — someone is
    uploading scans — and replaying them changes nothing."""

    transient: int
    """Failed for a reason that has probably passed. Every one is worth
    replaying, and `POST /documents/{id}/retry` is how."""


class DurationStats(BaseModel):
    """How long a successful ingestion takes.

    `None` until something has succeeded. Percentiles of an empty set are not
    zero — zero would read as "instant", which is the opposite of "unknown".
    """

    p50_seconds: float | None
    p95_seconds: float | None


class IngestionStatsResponse(BaseModel):
    """One snapshot, from one query, at one instant.

    The single-statement part matters: separate queries would see different
    instants, so a job could be counted `queued` by one and `processing` by
    another and the totals would disagree — which looks like a counting bug
    rather than a job doing its work.
    """

    queue: QueueStats
    in_flight: int
    """Claimed by a worker and being processed right now."""

    done: int
    dead_letter: DeadLetterStats
    duration: DurationStats
