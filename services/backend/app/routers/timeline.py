"""GET /api/timeline/window — storage-agnostic windowed-data contract (READ-ONLY)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Query

from app.models.timeline import (
    BBox,
    EventSample,
    GeoEvent,
    HistogramBucket,
    HistogramResponse,
    Notable,
    TrackPoint,
    TrackSample,
    WindowResponse,
)
from app.services.neo4j_client import read_query
from app.services.severity import (
    category_of,
    dominant_category,
    normalize_severity,
    severity_rank,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/timeline", tags=["timeline"])

_MAX_LIMIT = 500
_MAX_BUCKETS = 240
_SUPPORTED_MOVEMENT_KINDS = {"mil_aircraft", "civil_aircraft", "ship", "satellite"}
_IMPLEMENTED_MOVEMENT_KINDS = {"mil_aircraft"}


def _parse_iso_utc(value: str) -> datetime:
    """Parse ISO-8601 to a tz-AWARE UTC datetime (naive bounds assumed UTC)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def validate_window(t_start: str, t_end: str) -> tuple[datetime, datetime]:
    # Normalize BOTH bounds to tz-aware UTC before comparing — otherwise a mixed
    # aware/naive pair (e.g. one Z-suffixed, one date-only) makes `end < start`
    # raise TypeError (not ValueError) and leak a 500 on a client input error.
    try:
        start = _parse_iso_utc(t_start)
        end = _parse_iso_utc(t_end)
    except (ValueError, TypeError) as exc:
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
WITH ev, collect(l)[0] AS l
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
    start, end = validate_window(t_start, t_end)
    box = parse_bbox(bbox)

    if domain == "events":
        if movement_kind is not None:
            raise HTTPException(
                status_code=422, detail="movement_kind only valid for domain=movements"
            )
        if tier != "coarse":
            raise HTTPException(status_code=422, detail="events only support tier=coarse")
        return await _events_window(t_start, t_end, box, limit)

    return await _movements_window(
        t_start, t_end, tier, movement_kind, box, limit, start=start, end=end
    )


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

# Same window + bbox track-selection as _MIL_TRACKS_QUERY but no LIMIT — counts the
# DISTINCT in-window/in-bbox aircraft so total_count is the true pre-limit match
# count (tracks, not points), per spec §5.
_MIL_TRACKS_COUNT_QUERY = """
MATCH (a:MilitaryAircraft)-[r:SPOTTED_AT]->()
WHERE r.timestamp >= $start_s AND r.timestamp <= $end_s
  AND r.latitude IS NOT NULL AND r.longitude IS NOT NULL
WITH a, collect(r) AS rs
WITH a,
  [x IN rs WHERE $bbox_off
     OR (x.latitude >= $south AND x.latitude <= $north
         AND ( ($west <= $east AND x.longitude >= $west AND x.longitude <= $east)
            OR ($west >  $east AND (x.longitude >= $west OR x.longitude <= $east)) ))] AS inbox
WHERE size(inbox) >= 1
RETURN count(DISTINCT a) AS total
"""


async def _movements_window(
    t_start: str, t_end: str, tier: str, movement_kind: str | None,
    box: BBox | None, limit: int, *, start: datetime, end: datetime,
) -> WindowResponse:
    if movement_kind is None:
        raise HTTPException(status_code=422, detail="movement_kind required for domain=movements")
    if movement_kind not in _SUPPORTED_MOVEMENT_KINDS:
        raise HTTPException(status_code=422, detail="unknown movement_kind")
    if tier != "fine":
        raise HTTPException(status_code=422, detail="movements only support tier=fine")
    if movement_kind not in _IMPLEMENTED_MOVEMENT_KINDS:
        raise HTTPException(status_code=501, detail=f"{movement_kind} not implemented")

    params = {
        "start_s": int(start.timestamp()), "end_s": int(end.timestamp()),
        "limit": limit, **_bbox_params(box),
    }
    try:
        rows = await read_query(_MIL_TRACKS_QUERY, params)
        count_rows = await read_query(_MIL_TRACKS_COUNT_QUERY, params)
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
    total = int(count_rows[0]["total"]) if count_rows else len(samples)
    return WindowResponse(
        domain="movements", tier="fine", t_start=t_start, t_end=t_end, bbox=box,
        samples=samples, total_count=total, truncated=total > len(samples),
    )


_HISTOGRAM_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
WITH DISTINCT ev
RETURN toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity
"""


@router.get("/histogram", response_model=HistogramResponse)
async def get_histogram(
    t_start: str,
    t_end: str,
    buckets: int = 120,
    domain: str = "events",
    bbox: str | None = None,
) -> HistogramResponse:
    if domain != "events":
        raise HTTPException(status_code=422, detail="histogram supports domain=events only")
    if not (1 <= buckets <= _MAX_BUCKETS):
        raise HTTPException(status_code=422, detail=f"buckets must be in [1,{_MAX_BUCKETS}]")
    start, end = validate_window(t_start, t_end)
    box = parse_bbox(bbox)
    params = {"t_start": t_start, "t_end": t_end, **_bbox_params(box)}

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    span = max(end_ms - start_ms, 1)
    bucket_ms = max(span // buckets, 1)

    try:
        rows = await read_query(_HISTOGRAM_QUERY, params)
    except Exception as exc:
        log.error("timeline_histogram_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc

    # Bin in Python so the deterministic rules live in one tested place.
    cats: dict[int, list[str | None]] = {}
    sevs: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    for r in rows:
        t = r.get("time")
        if not t:
            continue
        ts_ms = int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp() * 1000)
        bi = min(int((ts_ms - start_ms) // bucket_ms), buckets - 1)
        bi = max(bi, 0)
        counts[bi] = counts.get(bi, 0) + 1
        cats.setdefault(bi, []).append(r.get("codebook_type"))
        sevs.setdefault(bi, []).append(normalize_severity(r.get("severity")))

    bucket_list: list[HistogramBucket] = []
    for bi in sorted(counts):
        bcats = cats[bi]
        by_cat: dict[str, int] = {}
        for c in bcats:
            cat = category_of(c)
            by_cat[cat] = by_cat.get(cat, 0) + 1
        by_sev: dict[str, int] = {}
        for s in sevs[bi]:
            by_sev[s] = by_sev.get(s, 0) + 1
        bucket_list.append(HistogramBucket(
            ts=datetime.fromtimestamp((start_ms + bi * bucket_ms) / 1000, tz=UTC).isoformat(),
            count=counts[bi],
            dominant_category=dominant_category(bcats),
            by_category=by_cat,
            by_severity=by_sev,
        ))

    notables = await _histogram_notables(t_start, t_end, box)
    geo_events, geo_count, geo_trunc = await _histogram_geo(t_start, t_end, box)

    return HistogramResponse(
        t_start=t_start, t_end=t_end, bucket_ms=bucket_ms, buckets=bucket_list,
        notables=notables, geo_events=geo_events, total_count=len(rows),
        geo_located_count=geo_count, geo_truncated=geo_trunc,
    )


_NOTABLE_EVENTS_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
  AND ev.severity IS NOT NULL
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       ev.severity AS severity, ev.title AS title, ev.codebook_type AS codebook_type,
       l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at DESC
LIMIT 400
"""

_NOTABLE_INCIDENTS_QUERY = """
MATCH (i:Incident)
WHERE datetime(i.trigger_ts) >= datetime($t_start)
  AND datetime(i.trigger_ts) <= datetime($t_end)
  AND ($bbox_off
       OR (i.lat IS NOT NULL AND i.lon IS NOT NULL
           AND i.lat >= $south AND i.lat <= $north
           AND ( ($west <= $east AND i.lon >= $west AND i.lon <= $east)
              OR ($west >  $east AND (i.lon >= $west OR i.lon <= $east)) )))
RETURN i.incident_id AS id, toString(i.trigger_ts) AS time, 'occurred' AS time_basis,
       i.severity AS severity, i.title AS title, i.lat AS lat, i.lon AS lon
ORDER BY i.trigger_ts DESC
LIMIT 200
"""

_NOTABLE_CAP = 40


def _neg_time_key(t: object) -> str:
    # newer time sorts first within a rank tier (descending by ISO string)
    return "".join(chr(0x10FFFF - ord(ch)) for ch in str(t or ""))


async def _histogram_notables(t_start: str, t_end: str, box: BBox | None) -> list[Notable]:
    params = {"t_start": t_start, "t_end": t_end, **_bbox_params(box)}
    ev_rows = await read_query(_NOTABLE_EVENTS_QUERY, params)
    inc_rows = await read_query(_NOTABLE_INCIDENTS_QUERY, params)

    candidates: list[dict] = []
    for r in ev_rows:
        sev = normalize_severity(r.get("severity"))
        if sev in ("high", "critical"):
            candidates.append({**r, "severity": sev, "is_incident": False})
    for r in inc_rows:
        candidates.append({
            **r, "severity": normalize_severity(r.get("severity")),
            "codebook_type": None, "is_incident": True,
        })

    def _key(c: dict) -> tuple:
        sev = c["severity"]
        tier = 0 if sev == "critical" else (1 if c["is_incident"] else (2 if sev == "high" else 3))
        return (tier, _neg_time_key(c.get("time")))

    candidates.sort(key=_key)
    out: list[Notable] = []
    seen: set[str] = set()
    for c in candidates:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        out.append(Notable(
            id=str(c["id"]), time=str(c.get("time") or ""),
            time_basis=str(c.get("time_basis") or "indexed"), severity=c["severity"],
            title=c.get("title"), codebook_type=c.get("codebook_type"),
            lat=float(c["lat"]) if c.get("lat") is not None else None,
            lon=float(c["lon"]) if c.get("lon") is not None else None,
            is_incident=bool(c["is_incident"]), rank=len(out),
        ))
        if len(out) >= _NOTABLE_CAP:
            break
    return out


_GEO_EVENTS_QUERY = """
MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
  AND l.lat IS NOT NULL AND l.lon IS NOT NULL
  AND ($bbox_off
       OR (l.lat >= $south AND l.lat <= $north
           AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
              OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) )))
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity, l.lat AS lat, l.lon AS lon
"""

_GEO_CAP = 200


async def _histogram_geo(t_start: str, t_end: str, box: BBox | None):
    params = {"t_start": t_start, "t_end": t_end, **_bbox_params(box)}
    rows = await read_query(_GEO_EVENTS_QUERY, params)
    total = len(rows)
    ranked = sorted(
        rows,
        key=lambda r: (-severity_rank(r.get("severity")), _neg_time_key(r.get("time"))),
    )
    out = [
        GeoEvent(
            id=str(r["id"]), time=str(r.get("time") or ""),
            codebook_type=r.get("codebook_type"),
            severity=normalize_severity(r.get("severity")),
            lat=float(r["lat"]), lon=float(r["lon"]),
            is_incident=False,
        )
        for r in ranked[:_GEO_CAP]
    ]
    return out, total, total > _GEO_CAP
