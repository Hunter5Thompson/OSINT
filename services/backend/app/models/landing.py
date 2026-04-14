"""Pydantic models for the /api/landing/summary endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LandingSummary(BaseModel):
    """24h aggregate counts for the Landing page hero numerals.

    One numeral per tile — Hotspots, Conflictus, Nuntii, Libri.
    If an upstream source is unavailable, the corresponding `*_24h`
    field is `None` and `*_source` gets a `:unavailable` suffix.
    The response remains HTTP 200 regardless of upstream health.
    """

    window: str = Field(..., description="Aggregation window; S1 only supports '24h'")
    generated_at: datetime = Field(..., description="Response timestamp (UTC)")

    hotspots_24h: int | None
    hotspots_source: str

    conflict_24h: int | None
    conflict_source: str

    nuntii_24h: int | None
    nuntii_source: str

    libri_24h: int
    libri_source: str
    reports_not_available_yet: bool = True
