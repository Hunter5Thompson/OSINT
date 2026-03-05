"""Satellite data models."""

from pydantic import BaseModel


class Satellite(BaseModel):
    norad_id: int
    name: str
    tle_line1: str
    tle_line2: str
    category: str = "active"
    inclination_deg: float = 0.0
    period_min: float = 0.0
