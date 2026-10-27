"""GET /health — is this process alive?

Checks nothing else on purpose. A health endpoint that queries Qdrant or pings
the embedding provider reports *its dependencies'* health, so a provider outage
makes a perfectly healthy process look dead and gets it restarted for no reason.

The distinction between liveness (am I running?) and readiness (can I serve
traffic?) becomes load-bearing at stage 12.1, when a load balancer starts making
decisions from these answers.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """**`async def`, and the word is load-bearing — stage 2.5.**

    A plain `def` route runs in FastAPI's bounded worker threadpool, the same
    pool `POST /documents` occupies for the whole of an ingest. Measured under
    40 concurrent uploads with a calibrated 3.2-second embed delay:

        def health      p50 0.008s -> 3.508s     438x worse
        async def       p50 0.008s -> unchanged

    Every thread was blocked inside `rag.ingest`, so a liveness check that
    touches nothing and does no I/O sat in a queue behind forty documents.

    The consequence is the one this file's own docstring wants to avoid: a
    health check that fails because the service is *busy* invites a restart
    that throws away the work in progress and makes the problem worse.

    `async def` puts it on the event loop, where it never competes with
    ingestion for anything. The rule it illustrates: **a route that does no
    I/O should be `async def`; a route that blocks should be `def`.** Both
    halves matter, and `POST /documents` is deliberately the other half.
    """
    return {"status": "ok"}
