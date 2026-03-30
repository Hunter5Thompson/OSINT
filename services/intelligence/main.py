"""Intelligence service FastAPI app — exposes LangGraph pipeline over HTTP."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from graph.workflow import run_intelligence_query

app = FastAPI(title="WorldView Intelligence Service", version="0.1.0")


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    region: str | None = None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/query")
async def query_intelligence(req: QueryRequest) -> dict:
    """Run intelligence pipeline and return full analysis result."""
    return await run_intelligence_query(req.query, req.region)
