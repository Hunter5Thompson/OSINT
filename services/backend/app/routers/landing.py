"""Landing page aggregate numerals — `/api/landing/summary`.

Powers the four hero numerals (Hotspots / Conflictus / Nuntii / Libri)
on the Landing page. All metrics are per-source-isolated: any single
upstream failure yields `null` for that metric with a `:unavailable`
source marker; the response is still HTTP 200.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Query

from app.models.landing import LandingSummary
from app.services.landing_summary import LandingSummaryService

router = APIRouter(prefix="/landing", tags=["landing"])

_WINDOW_MAP: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
}


@router.get("/summary", response_model=LandingSummary)
async def get_landing_summary(
    window: Literal["24h"] = Query(default="24h"),
) -> LandingSummary:
    service = LandingSummaryService()
    return await service.get_summary(_WINDOW_MAP[window])
