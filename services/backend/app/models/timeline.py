"""Windowed-data contract models for /api/timeline/window."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.models.spatial import CatalogRevision, DerivationRevision, PolicyIdentifier, ScopeKey


class SpatialFilterMode(StrEnum):
    GLOBAL = "global"
    SEMANTIC_KEY = "semantic_key"
    POINT_IN_BOUNDARY = "point_in_boundary"
    BBOX_APPROXIMATE = "bbox_approximate"


class SpatialCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class SpatialApplicationV1(BaseModel):
    """Truthful accounting for the spatial filter applied to a timeline response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    requested_scope_key: ScopeKey | None
    catalog_revision: CatalogRevision | None
    derivation_revision: DerivationRevision | None
    boundary_policy: PolicyIdentifier | None
    relation: Literal["occurs-in", "intersects"]
    mode: SpatialFilterMode
    completeness: SpatialCompleteness
    included_count: StrictInt = Field(ge=0)
    excluded_unlocated_count: StrictInt = Field(ge=0)
    excluded_conflict_count: StrictInt = Field(ge=0)
    excluded_stale_revision_count: StrictInt = Field(ge=0)


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
    spatial_application: SpatialApplicationV1


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
    spatial_application: SpatialApplicationV1


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
