"""HTTP shapes for POST /query.

Validated here as well as at the agent. The duplication is deliberate: this is
the boundary the browser reaches, and the agent must not assume it is only ever
called by our own backend. Defence in depth at a trust boundary is cheap, and
stage 5.2 is where "who is calling" stops being an assumption at all.
"""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, gt=0, le=50)