"""Read-only dependency readiness, distinct from process liveness."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.services.cache_service import CacheService
from app.services.neo4j_client import read_query
from app.services.qdrant_client import get_qdrant_client
from app.services.qdrant_schema import validate_collection_schema

router = APIRouter(prefix="/health", tags=["health"])
PROBE_TIMEOUT_S = 2.0


class DependencyReadiness(BaseModel):
    name: str
    required: bool
    status: Literal["ready", "unavailable"]


class ReadinessReport(BaseModel):
    status: Literal["ready", "degraded", "unavailable"]
    dependencies: list[DependencyReadiness]


async def check_neo4j() -> bool:
    return await read_query("RETURN 1 AS ready", {}) == [{"ready": 1}]


async def check_qdrant() -> bool:
    client = await get_qdrant_client()
    info = await client.get_collection(settings.qdrant_collection)
    validate_collection_schema(info, enable_hybrid=getattr(settings, "enable_hybrid", False))
    return True


async def _probe(
    name: str, required: bool, operation: Callable[[], Awaitable[bool]],
) -> DependencyReadiness:
    ready = False
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            ready = await operation()
    except Exception:
        pass
    return DependencyReadiness(
        name=name, required=required, status="ready" if ready else "unavailable"
    )


async def readiness_report(cache: CacheService) -> ReadinessReport:
    dependencies = list(await asyncio.gather(
        _probe("neo4j", True, check_neo4j),
        _probe("qdrant", True, check_qdrant),
        _probe("redis", False, cache.check_ready),
    ))
    status: Literal["ready", "degraded", "unavailable"] = "ready"
    if any(row.status != "ready" for row in dependencies):
        status = "unavailable" if any(
            row.required and row.status != "ready" for row in dependencies
        ) else "degraded"
    return ReadinessReport(status=status, dependencies=dependencies)


@router.get("/ready", response_model=ReadinessReport)
async def get_readiness(request: Request) -> JSONResponse:
    report = await readiness_report(request.app.state.cache)
    return JSONResponse(
        report.model_dump(), status_code=503 if report.status == "unavailable" else 200
    )
