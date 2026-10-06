"""Aircraft / Flight data models."""

import math
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Aircraft(BaseModel):
    icao24: str = Field(..., description="ICAO 24-bit address")
    callsign: str | None = None
    latitude: float
    longitude: float
    # Measurements are nullable: None means unknown, a real 0 stays 0.
    altitude_m: float | None = None
    velocity_ms: float | None = None
    heading: float | None = None
    vertical_rate: float | None = None
    on_ground: bool = False
    last_contact: datetime | None = None
    is_military: bool = False
    aircraft_type: str | None = None

    @field_validator("altitude_m", "velocity_ms", "vertical_rate", mode="before")
    @classmethod
    def _finite_or_none(cls, value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None

    @field_validator("heading", mode="before")
    @classmethod
    def _heading_or_none(cls, value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return number if math.isfinite(number) and 0 <= number < 360 else None
