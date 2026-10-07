"""GET /health — is this process alive?

Does not check the agent. Same reasoning as the agent's own health endpoint: a
liveness check that fails because a dependency is down invites a restart that
cannot possibly help.

Whether the agent is reachable is a different question, and it belongs to a
readiness endpoint — which arrives at stage 12.1, when something is actually
making routing decisions from the answer.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
