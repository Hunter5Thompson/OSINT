"""Every model trigger must authorize before SSE, stores, or outbound HTTP."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import almanac, intel
from app.services import intel_stream, report_store
from app.services.spatial_catalog import CatalogReadyState, SpatialCatalogLoader

TOKEN = "test-only-operator"
TRIGGERS = [
    ("/api/intel/query", {"query": "global analysis"}),
    (
        "/api/intel/query",
        {"query": "dossier analysis", "report_id": "r-test", "report_message": "question"},
    ),
    ("/api/intel/hotspot/ukr-001", None),
    ("/api/almanac/countries/UKR/briefing", None),
    ("/api/almanac/country/briefing?scope_key=country:UKR&catalog_revision={revision}", None),
]


@pytest.fixture
async def operator_app():
    loader = SpatialCatalogLoader(Path(__file__).parents[2] / "data" / "spatial")
    state = await loader.load()
    assert isinstance(state, CatalogReadyState)
    application = FastAPI()
    application.state.spatial_catalog = loader
    application.include_router(intel.router, prefix="/api")
    application.include_router(almanac.router, prefix="/api")
    return application, state.active_catalog_revision


@pytest.mark.parametrize(("path", "payload"), TRIGGERS)
@pytest.mark.parametrize(
    ("configured", "supplied", "status"),
    [
        (TOKEN, None, 401),
        (TOKEN, "wrong", 401),
        (" \t", TOKEN, 503),
    ],
)
def test_rejected_trigger_has_no_side_effects(
    operator_app,
    monkeypatch,
    path,
    payload,
    configured,
    supplied,
    status,
):
    application, revision = operator_app
    monkeypatch.setattr(settings, "reports_admin_token", configured)
    monkeypatch.setattr(settings, "incidents_admin_token", "")
    guards = []
    for module, name in [
        (report_store, "get_report"),
        (report_store, "append_report_message"),
        (report_store, "update_report"),
        (almanac, "get_country_almanac_store"),
        (intel_stream.httpx, "AsyncClient"),
        (application.state.spatial_catalog, "resolve_scope"),
        (application.state.spatial_catalog, "resolve_country_identifiers"),
    ]:
        guard = Mock(side_effect=AssertionError(f"unauthorized access: {name}"))
        guards.append(guard)
        monkeypatch.setattr(module, name, guard)
    # Also prove authorization precedes spatial resolution and SSE construction.
    guard = Mock(side_effect=AssertionError("unauthorized SSE"))
    guards.append(guard)
    monkeypatch.setattr(intel.EventSourceResponse, "__init__", guard)
    headers = {} if supplied is None else {"X-Admin-Token": supplied}
    response = TestClient(application).post(
        path.format(revision=revision),
        json=payload,
        headers=headers,
    )
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")
    for guard in guards:
        guard.assert_not_called()


@pytest.mark.parametrize(("path", "payload"), TRIGGERS)
@pytest.mark.parametrize("fallback", [False, True])
def test_authorized_trigger_reaches_analysis(operator_app, monkeypatch, path, payload, fallback):
    application, revision = operator_app
    monkeypatch.setattr(settings, "reports_admin_token", " \t" if fallback else f" {TOKEN} ")
    monkeypatch.setattr(settings, "incidents_admin_token", f" {TOKEN} " if fallback else "other")
    requests = []

    async def fake_stream(**kwargs):
        requests.append(kwargs)
        yield {"event": "result", "data": '{"query":"test","analysis":"authorized"}'}
        yield {"event": "done", "data": ""}

    monkeypatch.setattr(intel, "stream_intel_query", fake_stream)
    monkeypatch.setattr(almanac, "stream_intel_query", fake_stream)
    response = TestClient(application).post(
        path.format(revision=revision),
        json=payload,
        headers={"X-Admin-Token": f" {TOKEN} "},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "authorized" in response.text
    assert len(requests) == 1
    if payload and "report_id" in payload:
        assert requests[0]["report_id"] == "r-test"
        assert requests[0]["report_message"] == "question"


def test_public_reads_do_not_require_operator(operator_app, monkeypatch):
    application, _ = operator_app
    monkeypatch.setattr(settings, "reports_admin_token", "")
    monkeypatch.setattr(settings, "incidents_admin_token", "")
    client = TestClient(application)
    assert client.get("/api/almanac/countries/UKR").status_code == 200
    assert client.get("/api/almanac/countries/UKR/signals").status_code == 200
    assert client.get("/api/intel/history").status_code == 200
