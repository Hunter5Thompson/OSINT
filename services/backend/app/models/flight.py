"""Aircraft / Flight data models."""

from datetime import datetime, timezone
from functools import partial

from pydantic import BaseModel, Field

_utc_now = partial(datetime.now, timezone.utc)


class Aircraft(BaseModel):
    icao24: str = Field(..., description="ICAO 24-bit address")
    callsign: str | None = None
    latitude: float
    longitude: float
    altitude_m: float = 0.0
    velocity_ms: float = 0.0
    heading: float = 0.0
    vertical_rate: float = 0.0
    on_ground: bool = False
    last_contact: datetime = Field(default_factory=_utc_now)
    is_military: bool = False
    aircraft_type: str | None = None
