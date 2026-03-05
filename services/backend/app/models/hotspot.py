"""Geopolitical hotspot models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Hotspot(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    region: str
    threat_level: Literal["CRITICAL", "HIGH", "ELEVATED", "MODERATE"]
    description: str
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    sources: list[str] = Field(default_factory=list)
