"""Tests for the stateless POST /almanac/countries/{id}/briefing/save endpoint."""

import datetime as _dt
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import settings
from app.main import app
from app.models.almanac import BriefingSaveRequest
from app.models.intel import IntelAnalysis, SpatialRunApplicationV1
from app.models.report import ReportMessage, ReportRecord, ReportUpdateRequest
from app.routers import almanac as almanac_router
from app.services.spatial_catalog import (
    CatalogReadyState,
    ResolvedSpatialScope,
    SpatialCatalogLoader,
)
from app.services.spatial_filters import spatial_scope_token_from_resolution

ADMIN_HEADERS = {"X-Admin-Token": "reports-secret"}


@pytest.fixture(autouse=True)
async def _report_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "reports_admin_token", "reports-secret")
    loader = SpatialCatalogLoader(Path(__file__).parents[1] / "data" / "spatial")
    assert isinstance(await loader.load(), CatalogReadyState)
    app.state.spatial_catalog = loader


def test_empty_analysis_rejected():
    with pytest.raises(ValidationError):
        BriefingSaveRequest(analysis=IntelAnalysis(query="q", analysis="   "))


def test_nonempty_analysis_accepted():
    BriefingSaveRequest(analysis=IntelAnalysis(query="q", analysis="Lage stabil"))


def test_hydration_mapping_overrides_defaults():
    from app.services.report_store import build_hydration_patch

    analysis = IntelAnalysis(
        query="q",
        analysis="## Executive Summary\nKurz.\n\n## Key Findings\n- A\n- B",
        confidence=0.8,
        threat_assessment="HIGH",
        sources_used=["odin-country-almanac"],
    )
    patch = build_hydration_patch(analysis, country_name="Germany")
    assert patch.body_title == "Germany — Munin Lagebriefing"
    assert patch.findings == ["A", "B"]
    assert patch.confidence == 0.8
    assert len(patch.metrics) == 3 and patch.metrics[0].label == "Threat"


def _application(
    *,
    scope_key: str,
    catalog_revision: str,
    derivation_revision: str,
    boundary_policy: str,
    coverage_revision: str | None = None,
) -> SpatialRunApplicationV1:
    return SpatialRunApplicationV1.model_validate({
        "schema_version": 1,
        "scope": {
            "schema_version": 1,
            "scope_key": scope_key,
            "catalog_revision": catalog_revision,
            "derivation_revision": derivation_revision,
            "boundary_policy": boundary_policy,
        },
        "relation": "either",
        "qdrant": {
            "status": "applied",
            "mode": "semantic-key",
            "completeness": "complete",
        },
        "neo4j": {
            "status": "applied",
            "mode": "semantic-key",
            "completeness": "complete",
        },
        "blocked_tools": [],
        "coverage_revision": coverage_revision,
    })


def test_hydration_preserves_trusted_internal_application_without_relabel() -> None:
    from app.services.report_store import build_hydration_patch

    application = _application(
        scope_key="country:UKR",
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision="spatial-derive-v1-d30efa07e141",
        boundary_policy="odin-reference-v1",
    )
    analysis = IntelAnalysis(
        query="q",
        analysis="Pinned Ukraine result",
        spatial_application=application,
    )

    patch = build_hydration_patch(
        analysis,
        country_name="Poland",
        trusted_spatial_application=application,
    )

    assert patch.spatial_application == application
    assert patch.spatial_application.scope.scope_key == "country:UKR"


def _rec(scope_key: str) -> ReportRecord:
    now = _dt.datetime.now(_dt.UTC)
    return ReportRecord(
        id="r-001",
        paragraph_num=1,
        stamp="2026·VI·01",
        title="Germany — Lagebild",
        scope_key=scope_key,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_save_discards_browser_application_even_when_scope_identity_matches(
    monkeypatch,
):
    loader = app.state.spatial_catalog
    assert isinstance(loader, SpatialCatalogLoader)
    resolved = loader.resolve_country_identifiers(("276", "DEU"))
    assert isinstance(resolved, ResolvedSpatialScope)
    token = spatial_scope_token_from_resolution(resolved)
    forged_application = _application(
        scope_key=token.scope_key,
        catalog_revision=token.catalog_revision,
        derivation_revision=token.derivation_revision,
        boundary_policy=token.boundary_policy,
        coverage_revision="spatial-projection-v1-aaaaaaaaaaaa",
    )
    captured: dict[str, ReportUpdateRequest] = {}

    async def fake_goc(scope_key, title, location, coords, *, legacy_aliases=()):
        return _rec(scope_key)

    async def fake_update(rid, patch):
        captured["patch"] = patch
        return _rec(token.scope_key)

    async def fake_append(rid, payload):
        return ReportMessage(id="m1", role="munin", text=payload.text)

    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", fake_goc)
    monkeypatch.setattr(almanac_router, "update_report", fake_update)
    monkeypatch.setattr(almanac_router, "append_report_message", fake_append)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        response = await ac.post(
            "/api/almanac/countries/276/briefing/save",
            headers=ADMIN_HEADERS,
            json={
                "analysis": {
                    "query": "q",
                    "analysis": "Browser supplied briefing",
                    "spatial_application": forged_application.model_dump(mode="json"),
                }
            },
        )

    assert response.status_code == 200
    patch = captured["patch"]
    assert "spatial_application" in patch.model_fields_set
    assert patch.spatial_application is None


@pytest.mark.asyncio
async def test_save_requires_schema_and_truncates_with_marker(monkeypatch):
    captured: dict = {}

    async def fake_goc(scope_key, title, location, coords, *, legacy_aliases=()):
        return _rec(scope_key)

    async def fake_update(rid, patch):
        return _rec("country:DEU")

    async def fake_append(rid, payload):
        captured["text"] = payload.text
        return ReportMessage(id="m1", role="munin", text=payload.text)  # not None → succeeds

    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", fake_goc)
    monkeypatch.setattr(almanac_router, "update_report", fake_update)
    monkeypatch.setattr(almanac_router, "append_report_message", fake_append)

    body = {"analysis": {"query": "q", "analysis": "Z" * 9000, "confidence": 0.5}}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = False
        assert (
            await ac.post(
                "/api/almanac/countries/276/briefing/save",
                headers=ADMIN_HEADERS,
                json=body,
            )
        ).status_code == 503
        app.state.report_schema_ready = True
        r = await ac.post(
            "/api/almanac/countries/276/briefing/save",
            headers=ADMIN_HEADERS,
            json=body,
        )
        assert r.status_code == 200
    assert len(captured["text"]) == 8000 and captured["text"].endswith("…[gekürzt]")


@pytest.mark.asyncio
async def test_save_404_for_unknown_country(monkeypatch):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post(
            "/api/almanac/countries/zzz/briefing/save",
            headers=ADMIN_HEADERS,
            json={"analysis": {"query": "q", "analysis": "Lage stabil"}},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_maps_storage_failure_to_503(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", boom)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post(
            "/api/almanac/countries/276/briefing/save",
            headers=ADMIN_HEADERS,
            json={"analysis": {"query": "q", "analysis": "Lage stabil"}},
        )
        assert r.status_code == 503


@pytest.mark.asyncio
async def test_save_503_when_hydration_returns_none(monkeypatch):
    async def fake_goc(scope_key, title, location, coords, *, legacy_aliases=()):
        return _rec(scope_key)

    async def fake_update(rid, patch):
        return None                                   # dossier vanished mid-save

    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", fake_goc)
    monkeypatch.setattr(almanac_router, "update_report", fake_update)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post(
            "/api/almanac/countries/276/briefing/save",
            headers=ADMIN_HEADERS,
            json={"analysis": {"query": "q", "analysis": "Lage stabil"}},
        )
        assert r.status_code == 503
        assert "hydration failed" in r.text


@pytest.mark.asyncio
async def test_save_invalid_confidence_is_422_without_store_write(monkeypatch):
    called = {"goc": False}

    async def fake_goc(scope_key, title, location, coords, *, legacy_aliases=()):
        called["goc"] = True
        return _rec(scope_key)

    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", fake_goc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post(
            "/api/almanac/countries/276/briefing/save",
            headers=ADMIN_HEADERS,
            json={"analysis": {"query": "q", "analysis": "Lage", "confidence": 2.0}},
        )
        assert r.status_code == 422               # client error, not 503
        assert called["goc"] is False             # no orphan dossier created before validation


@pytest.mark.asyncio
async def test_save_fails_closed_without_report_admin_token(monkeypatch):
    called = {"goc": False}

    async def fake_goc(scope_key, title, location, coords, *, legacy_aliases=()):
        called["goc"] = True
        return _rec(scope_key)

    async def fake_update(rid, patch):
        return _rec("country:DEU")

    async def fake_append(rid, payload):
        return ReportMessage(id="m1", role="munin", text=payload.text)

    monkeypatch.setattr(settings, "reports_admin_token", "")
    monkeypatch.setattr(settings, "incidents_admin_token", "")
    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", fake_goc)
    monkeypatch.setattr(almanac_router, "update_report", fake_update)
    monkeypatch.setattr(almanac_router, "append_report_message", fake_append)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post(
            "/api/almanac/countries/276/briefing/save",
            json={"analysis": {"query": "q", "analysis": "Lage stabil"}},
        )

    assert r.status_code == 503
    assert called["goc"] is False
