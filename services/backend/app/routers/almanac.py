"""WorldReport Almanac endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse
from starlette.responses import Response

from app.admin_auth import require_admin_token
from app.config import settings
from app.models.almanac import (
    AlmanacSignalResponse,
    BriefingSaveRequest,
    CountryAlmanac,
    SpatialAlmanacSignalResponse,
    SpatialCountryAlmanacResponse,
)
from app.models.intel import RetrievalSpatialRelation
from app.models.report import ReportMessageCreate, ReportRecord
from app.models.spatial import (
    CatalogProblemCode,
    ScopeKind,
    SpatialCatalogProblem,
    SpatialScopeTokenV1,
    parse_scope_key,
)
from app.routers.spatial import spatial_problem_response
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
from app.services.spatial_catalog import SpatialCatalogLoader
from app.services.spatial_filters import spatial_scope_token_from_resolution

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/almanac", tags=["almanac"])


@dataclass(frozen=True, slots=True)
class _CountrySpatialContext:
    country: CountryAlmanac
    token: SpatialScopeTokenV1
    legacy_scope_keys: tuple[str, ...]


def _country_spatial_context(
    request: Request,
    country: CountryAlmanac,
) -> _CountrySpatialContext | Response:
    loader = getattr(request.app.state, "spatial_catalog", None)
    if not isinstance(loader, SpatialCatalogLoader):
        return spatial_problem_response(
            SpatialCatalogProblem(
                code=CatalogProblemCode.CATALOG_UNAVAILABLE,
                message="Spatial catalog is unavailable",
                recoverable=True,
            )
        )
    identifiers = tuple(
        value for value in (country.id, country.iso3, country.m49) if value
    )
    resolved = loader.resolve_country_identifiers(identifiers)
    if isinstance(resolved, SpatialCatalogProblem):
        return spatial_problem_response(resolved)
    token = spatial_scope_token_from_resolution(resolved)
    previous_key = (
        f"country:{country.iso3}"
        if country.iso3
        else f"country:m49:{country.m49}"
    )
    legacy_scope_keys = () if previous_key == token.scope_key else (previous_key,)
    return _CountrySpatialContext(
        country=country,
        token=token,
        legacy_scope_keys=legacy_scope_keys,
    )


def _resolve_committed_country_scope(
    request: Request,
    scope_key: str,
    catalog_revision: str,
) -> _CountrySpatialContext | Response:
    """Resolve an exact browser-committed country query without identity fallback."""

    loader = getattr(request.app.state, "spatial_catalog", None)
    if not isinstance(loader, SpatialCatalogLoader):
        return spatial_problem_response(
            SpatialCatalogProblem(
                code=CatalogProblemCode.CATALOG_UNAVAILABLE,
                message="Spatial catalog is unavailable",
                recoverable=True,
            )
        )

    resolved = loader.resolve_scope(scope_key, catalog_revision)
    if isinstance(resolved, SpatialCatalogProblem):
        return spatial_problem_response(resolved)

    parsed = parse_scope_key(resolved.record.scope.key)
    if parsed.kind is not ScopeKind.COUNTRY or parsed.canonical_code is None:
        return spatial_problem_response(
            SpatialCatalogProblem(
                code=CatalogProblemCode.INVALID_SCOPE_KEY,
                message="Country almanac requires a country scope",
                target=resolved.record.scope.key,
                recoverable=False,
                active_catalog_revision=resolved.catalog_revision,
            )
        )

    country = get_country_almanac_store().get_country(parsed.canonical_code)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")

    token = spatial_scope_token_from_resolution(resolved)
    previous_key = (
        f"country:{country.iso3}"
        if country.iso3
        else f"country:m49:{country.m49}"
    )
    legacy_scope_keys = () if previous_key == token.scope_key else (previous_key,)
    return _CountrySpatialContext(
        country=country,
        token=token,
        legacy_scope_keys=legacy_scope_keys,
    )


def _require_report_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    require_admin_token(
        expected_token=settings.reports_admin_token or settings.incidents_admin_token,
        supplied_token=x_admin_token,
        area="reports",
    )


@router.get("/countries/{country_id}", response_model=CountryAlmanac)
async def get_country_almanac(country_id: str) -> CountryAlmanac:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    return country


@router.get("/country", response_model=SpatialCountryAlmanacResponse)
async def get_spatial_country_almanac(
    request: Request,
    scope_key: str = Query(),
    catalog_revision: str = Query(),
) -> SpatialCountryAlmanacResponse | Response:
    """Resolve catalog identity before adapting it to existing almanac data."""

    context = _resolve_committed_country_scope(request, scope_key, catalog_revision)
    if isinstance(context, Response):
        return context
    return SpatialCountryAlmanacResponse.model_validate({
        **context.country.model_dump(),
        "scope_key": context.token.scope_key,
        "catalog_revision": context.token.catalog_revision,
    })


def _country_signal_response(
    country: CountryAlmanac,
    limit: int,
) -> AlmanacSignalResponse:
    store = get_country_almanac_store()
    items = store.match_signals(
        country.id,
        get_signal_stream().snapshot(),
        limit=limit,
    )
    return AlmanacSignalResponse(
        country_id=country.iso3 or country.id,
        items=items,
    )


def _spatial_country_signal_response(
    context: _CountrySpatialContext,
    limit: int,
) -> SpatialAlmanacSignalResponse:
    response = _country_signal_response(context.country, limit)
    return SpatialAlmanacSignalResponse.model_validate({
        **response.model_dump(),
        "scope_key": context.token.scope_key,
        "catalog_revision": context.token.catalog_revision,
    })


def _country_briefing_response(
    context: _CountrySpatialContext,
) -> EventSourceResponse:
    store = get_country_almanac_store()
    signals = store.match_signals(
        context.country.id,
        get_signal_stream().snapshot(),
        limit=5,
    )
    briefing = build_briefing_context(
        context.country,
        signals,
        factbook_revision=store.factbook_revision,
        refreshed_at=store.refreshed_at,
    )

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        async for event in stream_intel_query(
            query=briefing.task,
            spatial_scope=context.token,
            spatial_relation=RetrievalSpatialRelation.EITHER,
            grounding_context=briefing.grounding_context,
            grounding_evidence=briefing.grounding_evidence,
        ):
            yield event

    return EventSourceResponse(event_generator())


@router.get("/country/signals", response_model=SpatialAlmanacSignalResponse)
async def get_spatial_country_signals(
    request: Request,
    scope_key: str = Query(),
    catalog_revision: str = Query(),
    limit: int = Query(default=5, ge=1, le=20),
) -> SpatialAlmanacSignalResponse | Response:
    context = _resolve_committed_country_scope(request, scope_key, catalog_revision)
    if isinstance(context, Response):
        return context
    return _spatial_country_signal_response(context, limit)


@router.post("/country/briefing", response_model=None)
async def generate_spatial_country_briefing(
    request: Request,
    scope_key: str = Query(),
    catalog_revision: str = Query(),
) -> EventSourceResponse | Response:
    context = _resolve_committed_country_scope(request, scope_key, catalog_revision)
    if isinstance(context, Response):
        return context
    return _country_briefing_response(context)


@router.get("/countries/{country_id}/signals", response_model=AlmanacSignalResponse)
async def get_country_signals(
    country_id: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> AlmanacSignalResponse:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    return _country_signal_response(country, limit)


@router.post("/countries/{country_id}/briefing", response_model=None)
async def generate_country_briefing(
    country_id: str,
    request: Request,
) -> EventSourceResponse | Response:
    store = get_country_almanac_store()
    country = store.get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    spatial = _country_spatial_context(request, country)
    if isinstance(spatial, Response):
        return spatial
    return _country_briefing_response(spatial)


async def _save_resolved_country_briefing(
    context: _CountrySpatialContext,
    body: BriefingSaveRequest,
) -> ReportRecord:
    country = context.country
    scope_key = context.token.scope_key
    coords = (
        f"{country.capital.lat:.2f},{country.capital.lon:.2f}" if country.capital else "--"
    )
    # Build (and thereby validate) the hydration patch BEFORE any store access so an invalid
    # client payload (e.g. confidence outside [0,1]) returns 422 with no orphan dossier write.
    # build_hydration_patch is pure (no I/O), so this cannot itself cause a storage side effect.
    # Its trusted_spatial_application default deliberately discards the browser field even when
    # scope identity matches: consumer status and coverage could still be fabricated. Explicit
    # None in the resulting patch also clears any stale report snapshot.
    try:
        patch = build_hydration_patch(body.analysis, country_name=country.name)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid analysis payload: {exc}") from exc
    # Map storage failures (Neo4j outage) to 503 for consistency with the reports router. Our own
    # 404/503 HTTPExceptions are re-raised as-is; the schema-ready + country 404 checks stay above.
    try:
        report = await get_or_create_report_by_scope(
            scope_key,
            title=f"{country.name} — Lagebild",
            location=country.name,
            coords=coords,
            legacy_aliases=context.legacy_scope_keys,
        )
        updated = await update_report(report.id, patch)
        if updated is None:  # dossier vanished between create and update — never false success
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
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("briefing_save_failed", scope_key=scope_key, error=str(exc))
        raise HTTPException(status_code=503, detail="report store unavailable") from exc


@router.post(
    "/country/briefing/save",
    response_model=ReportRecord,
    dependencies=[Depends(_require_report_admin)],
)
async def save_spatial_country_briefing(
    body: BriefingSaveRequest,
    request: Request,
    scope_key: str = Query(),
    catalog_revision: str = Query(),
) -> ReportRecord | Response:
    if not getattr(request.app.state, "report_schema_ready", False):
        raise HTTPException(
            status_code=503, detail="report schema not bootstrapped; saves disabled"
        )
    context = _resolve_committed_country_scope(request, scope_key, catalog_revision)
    if isinstance(context, Response):
        return context
    return await _save_resolved_country_briefing(context, body)


# Router prefix is "/almanac" → full mounted path /api/almanac/countries/{id}/briefing/save
@router.post(
    "/countries/{country_id}/briefing/save",
    response_model=ReportRecord,
    dependencies=[Depends(_require_report_admin)],
)
async def save_country_briefing(
    country_id: str, body: BriefingSaveRequest, request: Request
) -> ReportRecord | Response:
    if not getattr(request.app.state, "report_schema_ready", False):
        raise HTTPException(
            status_code=503, detail="report schema not bootstrapped; saves disabled"
        )
    country = get_country_almanac_store().get_country(country_id)
    if country is None:
        raise HTTPException(status_code=404, detail="country almanac not found")
    context = _country_spatial_context(request, country)
    if isinstance(context, Response):
        return context
    return await _save_resolved_country_briefing(context, body)
