"""Geo-located event response models for Globe markers."""

from pydantic import BaseModel, Field


class GeoEvent(BaseModel):
    id: str
    title: str
    codebook_type: str
    severity: str
    timestamp: str | None = None
    location_name: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None


class GeoEventsResponse(BaseModel):
    events: list[GeoEvent] = Field(default_factory=list)
    total_count: int = 0
