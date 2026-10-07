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
def health() -> dict[str, str]:
    return {"status": "ok"}
