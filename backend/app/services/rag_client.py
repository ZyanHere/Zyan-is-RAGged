"""Boundary for future communication with the RAG engine.

RAG functionality is intentionally not implemented in this backend scaffold.
Future work can define a concrete client here once the agent service contract exists.
"""


class RagClientNotImplementedError(NotImplementedError):
    """Raised if future code tries to use the RAG client before it exists."""


class RagClient:
    """Placeholder interface for the future RAG engine client."""

    def __init__(self) -> None:
        raise RagClientNotImplementedError("RAG engine integration is not implemented yet.")
