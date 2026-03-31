"""Submarine cable and landing point data models."""

from pydantic import BaseModel, Field


class SubmarineCable(BaseModel):
    id: str
    name: str
    color: str = "#00bcd4"
    is_planned: bool = False
    owners: str | None = None
    capacity_tbps: float | None = None
    length_km: float | None = None
    rfs: str | None = None
    url: str | None = None
    landing_point_ids: list[str] = Field(default_factory=list)
    coordinates: list[list[list[float]]]  # MultiLineString


class LandingPoint(BaseModel):
    id: str
    name: str
    country: str | None = None
    latitude: float
    longitude: float


class CableDataset(BaseModel):
    cables: list[SubmarineCable]
    landing_points: list[LandingPoint]
    source: str  # "live" | "fallback"
