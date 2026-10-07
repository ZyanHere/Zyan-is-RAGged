"""Everything the agent itself can raise.

Same convention as `rag/errors.py`, applied consistently: each layer declares
its own failures in one file, and translates them at its own HTTP boundary. The
alternative — an exception class declared in whichever module happened to need
it first — is how the mapping in `main.py` becomes impossible to review.

`ProviderError` lives here rather than in `providers/base.py` for that reason.
The seam defines what a provider must *do*; it should not also be the home of
the vocabulary for how the agent fails.

Failures raised by `rag` are not repeated here. They are a different layer's
vocabulary, and `main.py` maps both sets side by side.

    UploadTooLargeError  413  the upload exceeds MAX_UPLOAD_BYTES
    ProviderError        502  an upstream model provider failed us
    AgentError           500  anything of ours we did not name
"""


class AgentError(Exception):
    """Base class for every failure raised by the agent's own code."""


class UploadTooLargeError(AgentError):
    """The uploaded file exceeds the configured limit.

    Checked before the bytes are read into memory, not after. A limit enforced
    after buffering the whole file protects nothing.
    """


class ProviderError(AgentError):
    """A model provider could not produce a reply.

    Vendor exceptions are translated into this inside `providers/`, so callers
    never import an SDK's error classes. `rag.EmbeddingError` is the exact
    counterpart on the embedding side.
    """