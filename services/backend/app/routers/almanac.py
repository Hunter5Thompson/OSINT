"""WorldReport Almanac endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.almanac import AlmanacSignalResponse, CountryAlmanac
from app.services.country_almanac import get_country_almanac_store
from app.services.signal_stream import get_signal_stream

router = APIRouter(prefix="/almanac", tags=["almanac"])


@router.get("/countries/{country_id}", response_model=CountryAlmanac)
async def get_country_almanac(country_id: str) -> CountryAlmanac:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    return country


@router.get("/countries/{country_id}/signals", response_model=AlmanacSignalResponse)
async def get_country_signals(
    country_id: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> AlmanacSignalResponse:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    stream = get_signal_stream()
    items = store.match_signals(country.id, stream.get_latest(50), limit=limit)
    return AlmanacSignalResponse(country_id=country.id, items=items)
