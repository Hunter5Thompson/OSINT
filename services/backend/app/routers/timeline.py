"""GET /api/timeline/window — storage-agnostic windowed-data contract (READ-ONLY)."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Query

from app.models.timeline import BBox, EventSample, TrackPoint, TrackSample, WindowResponse
from app.services.neo4j_client import read_query

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/timeline", tags=["timeline"])

_MAX_LIMIT = 500
_SUPPORTED_MOVEMENT_KINDS = {"mil_aircraft", "civil_aircraft", "ship", "satellite"}
_IMPLEMENTED_MOVEMENT_KINDS = {"mil_aircraft"}


def validate_window(t_start: str, t_end: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.fromisoformat(t_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(t_end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="t_start/t_end must be ISO-8601") from exc
    if end < start:
        raise HTTPException(status_code=422, detail="t_end must be >= t_start")
    return start, end


def parse_bbox(raw: str | None) -> BBox | None:
    if raw is None:
        return None
    parts = raw.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must be west,south,east,north")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox values must be numeric") from exc
    if not (
        -180 <= west <= 180
        and -180 <= east <= 180
        and -90 <= south <= 90
        and -90 <= north <= 90
    ):
        raise HTTPException(status_code=422, detail="bbox out of range")
    if south > north:
        raise HTTPException(status_code=422, detail="bbox south must be <= north")
    return BBox(west=west, south=south, east=east, north=north)


_EVENTS_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at ASC
LIMIT $limit
"""

_EVENTS_COUNT_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
RETURN count(DISTINCT ev) AS total
"""


def _bbox_params(bbox: BBox | None) -> dict:
    if bbox is None:
        return {"bbox_off": True, "west": -180.0, "east": 180.0, "south": -90.0, "north": 90.0}
    return {
        "bbox_off": False,
        "west": bbox.west, "east": bbox.east, "south": bbox.south, "north": bbox.north,
    }


@router.get("/window", response_model=WindowResponse)
async def get_window(
    t_start: str,
    t_end: str,
    domain: str = "events",
    tier: str = "coarse",
    movement_kind: str | None = None,
    bbox: str | None = None,
    limit: int = Query(default=200),
) -> WindowResponse:
    if domain not in ("events", "movements"):
        raise HTTPException(status_code=422, detail="domain must be events|movements")
    if tier not in ("coarse", "fine"):
        raise HTTPException(status_code=422, detail="tier must be coarse|fine")
    if not (1 <= limit <= _MAX_LIMIT):
        raise HTTPException(status_code=422, detail=f"limit must be in [1,{_MAX_LIMIT}]")
    validate_window(t_start, t_end)
    box = parse_bbox(bbox)

    if domain == "events":
        if movement_kind is not None:
            raise HTTPException(
                status_code=422, detail="movement_kind only valid for domain=movements"
            )
        if tier != "coarse":
            raise HTTPException(status_code=422, detail="events only support tier=coarse")
        return await _events_window(t_start, t_end, box, limit)

    return await _movements_window(t_start, t_end, tier, movement_kind, box, limit)


async def _events_window(
    t_start: str, t_end: str, box: BBox | None, limit: int
) -> WindowResponse:
    params = {"t_start": t_start, "t_end": t_end, "limit": limit, **_bbox_params(box)}
    try:
        rows = await read_query(_EVENTS_QUERY, params)
        count_rows = await read_query(_EVENTS_COUNT_QUERY, params)
    except Exception as exc:
        log.error("timeline_events_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc
    total = int(count_rows[0]["total"]) if count_rows else len(rows)
    samples = [
        EventSample(
            id=str(r.get("id") or ""),
            time=str(r.get("time") or ""),
            time_basis=str(r.get("time_basis") or "indexed"),
            title=r.get("title"),
            codebook_type=r.get("codebook_type"),
            severity=r.get("severity"),
            lat=float(r["lat"]) if r.get("lat") is not None else None,
            lon=float(r["lon"]) if r.get("lon") is not None else None,
            location_name=r.get("location_name"),
            country=r.get("country"),
        )
        for r in rows
    ]
    return WindowResponse(
        domain="events", tier="coarse", t_start=t_start, t_end=t_end, bbox=box,
        samples=samples, total_count=total, truncated=total > len(samples),
    )


_MIL_TRACKS_QUERY = """
MATCH (a:MilitaryAircraft)-[r:SPOTTED_AT]->()
WHERE r.timestamp >= $start_s AND r.timestamp <= $end_s
  AND r.latitude IS NOT NULL AND r.longitude IS NOT NULL
WITH a, r ORDER BY r.timestamp ASC
WITH a, collect(r) AS rs
WITH a, rs,
  [x IN rs WHERE $bbox_off
     OR (x.latitude >= $south AND x.latitude <= $north
         AND ( ($west <= $east AND x.longitude >= $west AND x.longitude <= $east)
            OR ($west >  $east AND (x.longitude >= $west OR x.longitude <= $east)) ))] AS inbox
WHERE size(inbox) >= 1
WITH a, [x IN rs | {
    ts_ms: x.timestamp * 1000, lat: x.latitude, lon: x.longitude,
    altitude_m: x.altitude_m, speed_ms: x.speed_ms, heading: x.heading
  }] AS points
RETURN a.icao24 AS icao24, a.callsign AS callsign, a.type_code AS type_code,
       a.military_branch AS military_branch, a.registration AS registration, points
ORDER BY points[-1].ts_ms DESC
LIMIT $limit
"""


async def _movements_window(
    t_start: str, t_end: str, tier: str, movement_kind: str | None,
    box: BBox | None, limit: int,
) -> WindowResponse:
    if movement_kind is None:
        raise HTTPException(status_code=422, detail="movement_kind required for domain=movements")
    if movement_kind not in _SUPPORTED_MOVEMENT_KINDS:
        raise HTTPException(status_code=422, detail="unknown movement_kind")
    if tier != "fine":
        raise HTTPException(status_code=422, detail="movements only support tier=fine")
    if movement_kind not in _IMPLEMENTED_MOVEMENT_KINDS:
        raise HTTPException(status_code=501, detail=f"{movement_kind} not implemented")

    start, end = validate_window(t_start, t_end)
    params = {
        "start_s": int(start.timestamp()), "end_s": int(end.timestamp()),
        "limit": limit, **_bbox_params(box),
    }
    try:
        rows = await read_query(_MIL_TRACKS_QUERY, params)
    except Exception as exc:
        log.error("timeline_movements_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc
    samples = [
        TrackSample(
            id=str(r.get("icao24") or ""),
            icao24=r.get("icao24"),
            callsign=r.get("callsign"),
            type_code=r.get("type_code"),
            military_branch=r.get("military_branch"),
            registration=r.get("registration"),
            points=[TrackPoint(**p) for p in (r.get("points") or [])],
        )
        for r in rows
    ]
    return WindowResponse(
        domain="movements", tier="fine", t_start=t_start, t_end=t_end, bbox=box,
        samples=samples, total_count=len(samples), truncated=len(samples) >= limit,
    )
