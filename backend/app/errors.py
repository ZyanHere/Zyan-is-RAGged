"""Everything the backend itself can raise.

Same convention as `rag/errors.py` and `agent/app/errors.py`: one hierarchy per
layer, declared in one file, translated at that layer's HTTP boundary in
`main.py`.

    UploadTooLargeError   413  the upload exceeds MAX_UPLOAD_BYTES
    AgentUnavailableError 503  the agent could not be reached at all
    BackendError          500  anything of ours we did not name

Note what 503 means here and why it is not 500. Nothing is wrong with *this*
service — its dependency is unreachable. That distinction is what makes an
error rate readable later, when the question "whose fault was the outage?" has
to be answered from metrics rather than memory.
"""


class BackendError(Exception):
    """Base class for every failure raised by the backend's own code."""


class BadUploadError(BackendError):
    """The upload is unusable on its face, before the agent is involved.

    A client error, so a 400 — not a 500. Raising the bare `BackendError` here
    would report our own failure for something the caller did wrong, which
    matters as soon as you start reading error rates and asking whose fault an
    outage was.

    This overlaps with the engine's own checks on purpose: the agent validates
    again, because it must not assume it is only ever called by this backend.
    What this catches early is the most common bad upload, at the outermost
    boundary, without a round trip.
    """


class UploadTooLargeError(BackendError):
    """The uploaded file exceeds the configured limit."""


class AgentUnavailableError(BackendError):
    """The agent could not be reached, or did not answer in time.

    Distinct from the agent *answering* with an error — that is a real response
    and is passed through with its own status code and body. This is the case
    where there was no response at all, which is the backend's to report.
    """