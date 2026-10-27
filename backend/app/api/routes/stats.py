"""GET /stats — is ingestion healthy right now?

── The question this exists to answer in one request ──────────────────────────

Before stage 2.4 it took hand-written SQL against a container. Both of stage
2.3's defects were found by going and looking — a corrupt PDF fed in by hand, a
valid one uploaded with the agent stopped — and nothing in the system would
have reported either.

── Why this is not `/health` ──────────────────────────────────────────────────

`/health` answers *is this process alive?* and is deliberately shallow: a
liveness check that fails because a dependency is down invites a restart that
cannot help. This answers *is the work getting done?*, which is a different
question with a different consumer — a person or a dashboard, not a
supervisor.

Keeping them apart is what stops someone wiring a restart to a deep check and
cycling a healthy process because a queue is briefly long.
"""

from fastapi import APIRouter

from app.api.deps import DocumentRepositoryDep
from app.schemas.stats import (
    DeadLetterStats,
    DurationStats,
    IngestionStatsResponse,
    QueueStats,
)

router = APIRouter()


@router.get("/stats", response_model=IngestionStatsResponse)
async def ingestion_stats(
    repository: DocumentRepositoryDep,
) -> IngestionStatsResponse:
    """A snapshot of the ingestion pipeline.

    One query, deliberately — see `DocumentRepository.ingestion_stats`. The
    route's only job is to group the columns into something a person can read
    without knowing the schema.

    ── Not authenticated, like everything else here ──────────────────────────

    It exposes counts, not content: how many documents are queued, not what is
    in them. That is still more than nothing — a count is a signal about usage
    — so it is `[deferrable]` rather than free, and the trigger is stage 5.2,
    where the whole API gets authentication at once rather than endpoint by
    endpoint.

    ── Why there is no `?window=` parameter ─────────────────────────────────

    The counts are all "right now" by nature. Only the percentiles are over
    history, and the right window for them is a thing to learn from looking at
    them rather than to guess at before anyone has. Adding a parameter now
    would mean choosing a default that becomes the answer everyone gets.
    """
    stats = await repository.ingestion_stats()

    return IngestionStatsResponse(
        queue=QueueStats(
            claimable=stats.claimable,
            waiting_for_retry=stats.waiting_for_retry,
            oldest_age_seconds=stats.oldest_queued_age_seconds,
        ),
        in_flight=stats.in_flight,
        done=stats.done,
        dead_letter=DeadLetterStats(
            total=stats.failed,
            permanent=stats.failed_permanent,
            transient=stats.failed_transient,
        ),
        duration=DurationStats(
            p50_seconds=stats.duration_p50_seconds,
            p95_seconds=stats.duration_p95_seconds,
        ),
    )
