"""Geopolitical hotspot models."""

from datetime import datetime, timezone
from functools import partial
from typing import Literal

from pydantic import BaseModel, Field

_utc_now = partial(datetime.now, timezone.utc)


class Hotspot(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    region: str
    threat_level: Literal["CRITICAL", "HIGH", "ELEVATED", "MODERATE"]
    description: str
    last_updated: datetime = Field(default_factory=_utc_now)
    sources: list[str] = Field(default_factory=list)
