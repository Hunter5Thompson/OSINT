"""Tests for the stateless POST /almanac/countries/{id}/briefing/save endpoint."""

import datetime as _dt

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.models.almanac import BriefingSaveRequest
from app.models.intel import IntelAnalysis
from app.models.report import ReportMessage, ReportRecord
from app.routers import almanac as almanac_router


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
async def test_save_requires_schema_and_truncates_with_marker(monkeypatch):
    captured: dict = {}

    async def fake_goc(scope_key, title, location, coords):
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
            await ac.post("/api/almanac/countries/276/briefing/save", json=body)
        ).status_code == 503
        app.state.report_schema_ready = True
        r = await ac.post("/api/almanac/countries/276/briefing/save", json=body)
        assert r.status_code == 200
    assert len(captured["text"]) == 8000 and captured["text"].endswith("…[gekürzt]")


@pytest.mark.asyncio
async def test_save_404_for_unknown_country(monkeypatch):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post("/api/almanac/countries/zzz/briefing/save",
                          json={"analysis": {"query": "q", "analysis": "Lage stabil"}})
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
            json={"analysis": {"query": "q", "analysis": "Lage stabil"}},
        )
        assert r.status_code == 503


@pytest.mark.asyncio
async def test_save_503_when_hydration_returns_none(monkeypatch):
    async def fake_goc(scope_key, title, location, coords):
        return _rec(scope_key)

    async def fake_update(rid, patch):
        return None                                   # dossier vanished mid-save

    monkeypatch.setattr(almanac_router, "get_or_create_report_by_scope", fake_goc)
    monkeypatch.setattr(almanac_router, "update_report", fake_update)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        app.state.report_schema_ready = True
        r = await ac.post("/api/almanac/countries/276/briefing/save",
                          json={"analysis": {"query": "q", "analysis": "Lage stabil"}})
        assert r.status_code == 503
        assert "hydration failed" in r.text
