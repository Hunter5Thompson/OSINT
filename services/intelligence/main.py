"""Intelligence service FastAPI app — exposes LangGraph pipeline over HTTP."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from pydantic import BaseModel, Field

from graph.workflow import run_intelligence_query, shutdown_graph_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await shutdown_graph_client()


app = FastAPI(title="WorldView Intelligence Service", version="0.2.0", lifespan=lifespan)


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    region: str | None = None
    image_url: str | None = None
    use_legacy: bool = False


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/query")
async def query_intelligence(req: QueryRequest) -> dict:
    """Run intelligence pipeline and return full analysis result."""
    return await run_intelligence_query(
        req.query,
        req.region,
        req.image_url,
        req.use_legacy,
    )
