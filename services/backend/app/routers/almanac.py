"""WorldReport Almanac endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.models.almanac import AlmanacSignalResponse, CountryAlmanac
from app.services.briefing import build_briefing_context
from app.services.country_almanac import get_country_almanac_store
from app.services.intel_stream import stream_intel_query
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
    items = store.match_signals(country.id, stream.snapshot(), limit=limit)
    # seed ids are UN M49 numerics; prefer iso3 for the response (frontend keys by iso3)
    return AlmanacSignalResponse(country_id=country.iso3 or country.id, items=items)


@router.post("/countries/{country_id}/briefing")
async def generate_country_briefing(country_id: str) -> EventSourceResponse:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    stream = get_signal_stream()
    signals = store.match_signals(country.id, stream.snapshot(), limit=5)
    ctx = build_briefing_context(
        country,
        signals,
        factbook_revision=store.factbook_revision,
        refreshed_at=store.refreshed_at,
    )

    async def event_generator():  # type: ignore[no-untyped-def]
        async for ev in stream_intel_query(
            query=ctx.task,
            region=country.name,
            grounding_context=ctx.grounding_context,
            grounding_evidence=ctx.grounding_evidence,
        ):
            yield ev

    return EventSourceResponse(event_generator())
