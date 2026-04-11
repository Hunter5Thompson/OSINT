"""FIRMS thermal anomalies — serves Qdrant-stored hotspots for globe rendering."""

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

router = APIRouter(prefix="/firms", tags=["firms"])

_PAGE_SIZE = 512
_MAX_TOTAL = 5000
_CACHE_TTL_S = 60


class FIRMSHotspot(BaseModel):
    id: str
    latitude: float
    longitude: float
    frp: float
    brightness: float
    confidence: str
    acq_date: str
    acq_time: str
    satellite: str
    bbox_name: str
    possible_explosion: bool
    firms_map_url: str


def _build_map_url(acq_date: str, lat: float, lon: float) -> str:
    return (
        "https://firms.modaps.eosdis.nasa.gov/map/#d:"
        f"{acq_date};@{lon:.4f},{lat:.4f},10z"
    )


def _point_to_hotspot(point: Any) -> FIRMSHotspot | None:
    p = point.payload or {}
    try:
        lat = float(p["latitude"])
        lon = float(p["longitude"])
        acq_date = str(p.get("acq_date", ""))
        return FIRMSHotspot(
            id=str(point.id),
            latitude=lat,
            longitude=lon,
            frp=float(p.get("frp") or 0),
            brightness=float(p.get("brightness") or 0),
            confidence=str(p.get("confidence", "")),
            acq_date=acq_date,
            acq_time=str(p.get("acq_time", "")),
            satellite=str(p.get("satellite", "")),
            bbox_name=str(p.get("bbox_name", "")),
            possible_explosion=bool(p.get("possible_explosion", False)),
            firms_map_url=_build_map_url(acq_date, lat, lon),
        )
    except (KeyError, ValueError, TypeError):
        return None


@router.get("/hotspots", response_model=list[FIRMSHotspot])
async def get_firms_hotspots(
    request: Request,
    since_hours: int = Query(default=24, ge=1, le=168),
) -> list[FIRMSHotspot]:
    cache_key = f"firms:hotspots:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [FIRMSHotspot(**h) for h in cached]

    cutoff = int(time.time()) - since_hours * 3600
    flt = Filter(
        must=[
            FieldCondition(key="source", match=MatchValue(value="firms")),
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
        log.error("firms_qdrant_scroll_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="qdrant unreachable") from exc

    hotspots = [h for h in (_point_to_hotspot(p) for p in results) if h is not None]
    await cache.set(cache_key, [h.model_dump() for h in hotspots], ttl_seconds=_CACHE_TTL_S)
    return hotspots
