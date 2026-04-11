"""Military Aircraft tracks — serves Neo4j-backed SPOTTED_AT tracks for globe rendering."""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.neo4j_client import read_query

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/aircraft", tags=["aircraft"])

_CACHE_TTL_S = 30

_TRACK_QUERY = """
MATCH (a:MilitaryAircraft)-[r:SPOTTED_AT]->()
WHERE r.timestamp >= $since_epoch
  AND r.latitude IS NOT NULL
  AND r.longitude IS NOT NULL
WITH a, r ORDER BY r.timestamp ASC
WITH a,
     collect({
       lat: r.latitude,
       lon: r.longitude,
       altitude_m: r.altitude_m,
       speed_ms: r.speed_ms,
       heading: r.heading,
       timestamp: r.timestamp
     }) AS points
WHERE size(points) >= 1
RETURN a.icao24          AS icao24,
       a.callsign        AS callsign,
       a.type_code       AS type_code,
       a.military_branch AS military_branch,
       a.registration    AS registration,
       points
ORDER BY points[-1].timestamp DESC
LIMIT 500
"""


class AircraftPoint(BaseModel):
    lat: float
    lon: float
    altitude_m: float | None
    speed_ms: float | None
    heading: float | None
    timestamp: int


class AircraftTrack(BaseModel):
    icao24: str
    callsign: str | None
    type_code: str | None
    military_branch: str | None
    registration: str | None
    points: list[AircraftPoint]


@router.get("/tracks", response_model=list[AircraftTrack])
async def get_aircraft_tracks(
    request: Request,
    since_hours: int = Query(default=24, ge=1, le=72),
) -> list[AircraftTrack]:
    cache_key = f"aircraft:tracks:{since_hours}h"
    cache = request.app.state.cache
    cached = await cache.get(cache_key)
    if cached is not None:
        return [AircraftTrack(**t) for t in cached]

    since_epoch = int(time.time()) - since_hours * 3600

    try:
        rows = await read_query(_TRACK_QUERY, {"since_epoch": since_epoch})
    except Exception as exc:
        log.error("aircraft_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc

    tracks = [AircraftTrack(**row) for row in rows]
    await cache.set(cache_key, [t.model_dump() for t in tracks], ttl_seconds=_CACHE_TTL_S)
    return tracks
