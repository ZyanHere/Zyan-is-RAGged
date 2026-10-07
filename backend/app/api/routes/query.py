"""POST /query — forward a question to the agent and return its answer."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.query import QueryRequest
from app.services.agent_client import query

router = APIRouter()


@router.post("/query")
async def ask(request: QueryRequest) -> JSONResponse:
    status_code, body = await query(
        question=request.question, top_k=request.top_k
    )
    return JSONResponse(status_code=status_code, content=body)