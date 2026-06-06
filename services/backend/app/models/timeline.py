"""Windowed-data contract models for /api/timeline/window."""

from typing import Literal

from pydantic import BaseModel, Field


class EventSample(BaseModel):
    kind: Literal["event"] = "event"
    id: str
    time: str  # ISO-8601 UTC (the timeline anchor)
    time_basis: str
    title: str | None = None
    codebook_type: str | None = None
    severity: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    country: str | None = None


class TrackPoint(BaseModel):
    ts_ms: int  # epoch milliseconds
    lat: float
    lon: float
    altitude_m: float | None = None
    speed_ms: float | None = None
    heading: float | None = None


class TrackSample(BaseModel):
    kind: Literal["track"] = "track"
    id: str
    icao24: str | None = None
    callsign: str | None = None
    type_code: str | None = None
    military_branch: str | None = None
    registration: str | None = None
    points: list[TrackPoint] = Field(default_factory=list)


class BBox(BaseModel):
    west: float
    south: float
    east: float
    north: float


class WindowResponse(BaseModel):
    domain: Literal["events", "movements"]
    tier: Literal["coarse", "fine"]
    t_start: str
    t_end: str
    bbox: BBox | None = None
    samples: list[EventSample | TrackSample] = Field(default_factory=list)
    total_count: int = 0
    truncated: bool = False
