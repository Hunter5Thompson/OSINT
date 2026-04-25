"""Pydantic models for /api/incidents.

The severity vocabulary is fixed (low/elevated/high/critical) and maps to the
spec's `Conf` field via SEVERITY_TO_CONF. Trigger detection is out of scope
for S4 — incidents are created via the admin POST stub.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

SEVERITY_TO_CONF: dict[str, float] = {
    "low": 0.55,
    "elevated": 0.70,
    "high": 0.85,
    "critical": 0.95,
}

Severity = Literal["low", "elevated", "high", "critical"]


class IncidentStatus(StrEnum):
    OPEN = "open"
    SILENCED = "silenced"
    PROMOTED = "promoted"
    CLOSED = "closed"


class IncidentTimelineEvent(BaseModel):
    """One bullet on §II Timeline."""

    t_offset_s: float = Field(..., description="Seconds since trigger_ts")
    kind: str = Field(..., description="trigger | signal | agent | source | note")
    text: str = ""
    severity: Severity | None = None


class IncidentCreateRequest(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    kind: str = Field(..., description="firms.cluster | ucdp.delta | ais.anomaly | manual")
    severity: Severity
    coords: tuple[float, float]
    location: str = ""
    sources: list[str] = Field(default_factory=list)
    layer_hints: list[str] = Field(default_factory=list)
    initial_text: str | None = None

    @model_validator(mode="after")
    def _validate_coords(self) -> IncidentCreateRequest:
        lat, lon = self.coords
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError(f"coords out of range: ({lat}, {lon})")
        return self


class Incident(BaseModel):
    id: str
    kind: str
    title: str
    severity: Severity
    coords: tuple[float, float]
    location: str = ""
    status: IncidentStatus = IncidentStatus.OPEN
    trigger_ts: datetime
    closed_ts: datetime | None = None
    sources: list[str] = Field(default_factory=list)
    layer_hints: list[str] = Field(default_factory=list)
    timeline: list[IncidentTimelineEvent] = Field(default_factory=list)

    @property
    def confidence(self) -> float:
        return SEVERITY_TO_CONF[self.severity]


class IncidentEnvelope(BaseModel):
    """SSE envelope — same shape as SignalEnvelope (spec §6.1)."""

    event_id: str
    ts: str
    # incident.open | incident.update | incident.close | incident.silence | incident.promote
    type: str
    payload: Incident
