"""Feed freshness health — is data actually still arriving per source?"""

from __future__ import annotations

import asyncio
import time
from typing import cast

import redis.asyncio as redis
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.config import settings
from app.services.collector_availability import (
    KEY,
    CollectorAvailabilityReport,
    availability_report,
)
from app.services.feed_freshness import FeedFreshnessReport, compute_feed_freshness
from app.services.qdrant_client import get_qdrant_client

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

_CACHE_KEY = "health:feeds"
_CACHE_TTL_S = 60


@router.get("/collectors", response_model=CollectorAvailabilityReport)
async def get_collector_availability() -> CollectorAvailabilityReport:
    """Per-publisher fetch outcomes, including failed and unobserved feeds."""
    try:
        async with asyncio.timeout(3):
            async with redis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=1, socket_timeout=1,
            ) as client:
                snapshot = cast(dict[str, str], await client.hgetall(KEY))
        return availability_report(snapshot, now=int(time.time()))
    except Exception as exc:
        log.warning("collector_health_unavailable")
        raise HTTPException(503, "collector fetch telemetry unavailable") from exc


@router.get("/feeds", response_model=FeedFreshnessReport)
async def get_feed_freshness(request: Request) -> FeedFreshnessReport:
    cache = request.app.state.cache
    cached = await cache.get(_CACHE_KEY)
    if isinstance(cached, dict):
        try:
            return FeedFreshnessReport.model_validate(cached)
        except ValidationError:
            log.warning("feed_health_cache_invalid")

    try:
        qdrant = await get_qdrant_client()
    except Exception as exc:
        log.error("feed_health_qdrant_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="qdrant unreachable") from exc

    report = await compute_feed_freshness(
        qdrant,
        collection=settings.qdrant_collection,
        max_age_s=settings.feed_max_age_s,
    )
    stale = [s.source for s in report.sources if s.status != "fresh"]
    if stale:
        log.warning("feed_freshness_degraded", sources=stale)
    await cache.set(_CACHE_KEY, report.model_dump(mode="json"), ttl_seconds=_CACHE_TTL_S)
    return report
