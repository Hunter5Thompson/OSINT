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


class HistogramBucket(BaseModel):
    ts: str  # ISO-8601 UTC bucket start
    count: int
    dominant_category: str
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class Notable(BaseModel):
    id: str
    time: str
    time_basis: str
    severity: str
    title: str | None = None
    codebook_type: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_incident: bool = False
    rank: int = 0


class GeoEvent(BaseModel):
    id: str
    time: str
    codebook_type: str | None = None
    severity: str
    lat: float
    lon: float
    is_incident: bool = False


class HistogramResponse(BaseModel):
    t_start: str
    t_end: str
    bucket_ms: int
    buckets: list[HistogramBucket] = Field(default_factory=list)
    notables: list[Notable] = Field(default_factory=list)
    geo_events: list[GeoEvent] = Field(default_factory=list)
    total_count: int = 0
    geo_located_count: int = 0
    geo_truncated: bool = False


class EventDetail(BaseModel):
    id: str
    time: str
    time_basis: str
    title: str | None = None
    codebook_type: str | None = None
    severity: str | None = None
    source: str | None = None
    url: str | None = None
    location_name: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None
