"""WorldReport Almanac endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.models.almanac import AlmanacSignalResponse, BriefingSaveRequest, CountryAlmanac
from app.models.report import ReportMessageCreate, ReportRecord
from app.services.briefing import build_briefing_context, truncate_message
from app.services.country_almanac import get_country_almanac_store
from app.services.intel_stream import stream_intel_query
from app.services.report_store import (
    append_report_message,
    build_hydration_patch,
    get_or_create_report_by_scope,
    update_report,
)
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

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        async for ev in stream_intel_query(
            query=ctx.task,
            region=country.name,
            grounding_context=ctx.grounding_context,
            grounding_evidence=ctx.grounding_evidence,
        ):
            yield ev

    return EventSourceResponse(event_generator())


# Router prefix is "/almanac" → full mounted path /api/almanac/countries/{id}/briefing/save
@router.post("/countries/{country_id}/briefing/save", response_model=ReportRecord)
async def save_country_briefing(
    country_id: str, body: BriefingSaveRequest, request: Request
) -> ReportRecord:
    if not getattr(request.app.state, "report_schema_ready", False):
        raise HTTPException(
            status_code=503, detail="report schema not bootstrapped; saves disabled"
        )
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    scope_key = f"country:{country.iso3}" if country.iso3 else f"country:m49:{country.m49}"
    coords = (
        f"{country.capital.lat:.2f},{country.capital.lon:.2f}" if country.capital else "--"
    )
    report = await get_or_create_report_by_scope(
        scope_key, title=f"{country.name} — Lagebild", location=country.name, coords=coords
    )
    patch = build_hydration_patch(body.analysis, country_name=country.name)
    updated = await update_report(report.id, patch)
    if updated is None:  # dossier vanished between create and update — never report false success
        raise HTTPException(status_code=503, detail="dossier hydration failed")
    chat = truncate_message(body.analysis.analysis.strip()) or "—"  # ≤8000 incl marker
    msg = await append_report_message(
        report.id,
        ReportMessageCreate(role="munin", text=chat, ts=body.analysis.timestamp,
                            refs=body.analysis.sources_used[:6]),
    )
    if msg is None:
        # dossier already hydrated above; a client retry re-hydrates (idempotent) but appends a
        # second munin message (append is not idempotent) — acceptable for append-only chat.
        raise HTTPException(status_code=503, detail="briefing chat persistence failed")
    return updated
