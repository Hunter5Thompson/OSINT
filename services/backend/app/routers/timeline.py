"""GET /api/timeline/window — storage-agnostic windowed-data contract (READ-ONLY)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.models.timeline import BBox

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
