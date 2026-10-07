"""HTTP shapes for POST /query."""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    # None means "let the engine decide". The agent holds no default of its
    # own — `rag` owns what top_k means.
    top_k: int | None = Field(default=None, gt=0, le=50)


class Citation(BaseModel):
    """One source the answer actually referenced.

    `marker` is the number the model wrote in the answer text (`[1]`), so a
    client can turn it into a link without re-parsing anything.
    """

    marker: int
    document_id: str
    filename: str
    page: int


class SourceChunk(BaseModel):
    """A chunk that was put in front of the model, cited or not.

    Returned so you can see what retrieval actually found — which is most of
    the debugging you will do at this stage. A development affordance, not a
    product feature.
    """

    marker: int
    document_id: str
    filename: str
    page: int
    score: float
    text: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    sources: list[SourceChunk]