"""Earthquake data models."""

from datetime import datetime

from pydantic import BaseModel, Field


class Earthquake(BaseModel):
    id: str
    latitude: float
    longitude: float
    depth_km: float
    magnitude: float
    place: str
    time: datetime
    tsunami: bool = False
    url: str | None = Field(default=None, description="USGS event page URL")
