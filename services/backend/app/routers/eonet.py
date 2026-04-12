"""EONET natural events — serves Qdrant-stored events for globe rendering."""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.config import settings
from app.services.qdrant_client import get_qdrant_client

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/eonet", tags=["eonet"])

_PAGE_SIZE = 512
_MAX_TOTAL = 2000
_CACHE_TTL_S = 120


class EONETEvent(BaseModel):
    id: str
    title: str
    category: str
    status: str
    latitude: float
    longitude: float
    event_date: str


def _point_to_event(point: Any) -> EONETEvent | None:
    p = point.payload or {}
    try:
        return EONETEvent(
            id=str(point.id),
            title=str(p.get("title", "")),
            category=str(p.get("category", "")),
            status=str(p.get("status", "")),
            latitude=float(p["latitude"]),
            longitude=float(p["longitude"]),
            event_date=str(p.get("event_date", "")),
        )
    except (KeyError, ValueError, TypeError):
        return None


@router.get("/events", response_model=list[EONETEvent])
async def get_eonet_events(
    request: Request,
    since_hours: int = Query(default=168, ge=1, le=720),
) -> list[EONETEvent]:
    cache_key = f"eonet:events:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [EONETEvent(**e) for e in cached]

    cutoff = int(time.time()) - since_hours * 3600
    flt = Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="eonet")),
            FieldCondition(key="ingested_epoch", range=Range(gte=cutoff)),
        ]
    )

    try:
        qdrant = await get_qdrant_client()
        results: list[Any] = []
        next_offset: Any = None
        while True:
            points, next_offset = await qdrant.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=flt,
                limit=_PAGE_SIZE,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            results.extend(points)
            if next_offset is None or len(results) >= _MAX_TOTAL:
                break
    except Exception as exc:
        log.error("eonet_qdrant_scroll_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="qdrant unreachable") from exc

    events = [e for e in (_point_to_event(p) for p in results) if e is not None]
    await cache.set(cache_key, [e.model_dump() for e in events], ttl_seconds=_CACHE_TTL_S)
    return events
