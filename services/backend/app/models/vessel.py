"""Vessel / Ship data models."""

from pydantic import BaseModel


class Vessel(BaseModel):
    mmsi: int
    name: str | None = None
    latitude: float
    longitude: float
    speed_knots: float = 0.0
    course: float = 0.0
    ship_type: int = 0
    destination: str | None = None
