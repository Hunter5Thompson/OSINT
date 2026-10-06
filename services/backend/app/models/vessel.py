"""Vessel / Ship data models."""

import math

from pydantic import BaseModel, field_validator

# AIS sentinels: SOG 102.3 kn and COG 360° mean "not available". 102.2 kn is the
# saturation value ("102.2 or higher") and stays a real measurement.
AIS_SOG_NOT_AVAILABLE = 102.3
AIS_COG_NOT_AVAILABLE = 360.0


def _measurement(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def normalize_sog(value: object) -> float | None:
    """Speed over ground in knots; sentinel, negative and non-finite values → None."""
    number = _measurement(value)
    if number is None or number < 0 or number >= AIS_SOG_NOT_AVAILABLE:
        return None
    return number


def normalize_cog(value: object) -> float | None:
    """Course over ground in degrees; only [0, 360) is a measurement."""
    number = _measurement(value)
    if number is None or number < 0 or number >= AIS_COG_NOT_AVAILABLE:
        return None
    return number


class Vessel(BaseModel):
    mmsi: int
    name: str | None = None
    latitude: float
    longitude: float
    speed_knots: float | None = None
    course: float | None = None
    ship_type: int = 0
    destination: str | None = None

    @field_validator("speed_knots", mode="before")
    @classmethod
    def _sog(cls, value: object) -> float | None:
        return normalize_sog(value)

    @field_validator("course", mode="before")
    @classmethod
    def _cog(cls, value: object) -> float | None:
        return normalize_cog(value)
