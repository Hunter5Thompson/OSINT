"""Backend-owned resolution of Munin's immutable spatial run token."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.spatial import SpatialScopeTokenV1
from app.routers import almanac, intel
from app.services.spatial_catalog import CatalogReadyState, SpatialCatalogLoader

REFERENCE_SPATIAL_ROOT = Path(__file__).parents[2] / "data" / "spatial"


async def _loader() -> tuple[SpatialCatalogLoader, str]:
    loader = SpatialCatalogLoader(REFERENCE_SPATIAL_ROOT)
    state = await loader.load()
    assert isinstance(state, CatalogReadyState)
    return loader, state.active_catalog_revision


def _intel_app(loader: SpatialCatalogLoader) -> FastAPI:
    application = FastAPI()
    application.state.spatial_catalog = loader
    application.include_router(intel.router, prefix="/api")
    return application


def _almanac_app(loader: SpatialCatalogLoader) -> FastAPI:
    application = FastAPI()
    application.state.spatial_catalog = loader
    application.include_router(almanac.router, prefix="/api")
    return application


async def _post(application: FastAPI, path: str, payload: dict[str, Any] | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        return await client.post(path, json=payload)


@pytest.mark.asyncio
async def test_intel_router_resolves_server_owned_token_and_defaults_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()
    captured: dict[str, object] = {}

    async def fake_stream(**kwargs: object) -> AsyncIterator[dict[str, str]]:
        captured.update(kwargs)
        yield {"event": "result", "data": '{"query":"q","analysis":"ok"}'}
        yield {"event": "done", "data": ""}

    monkeypatch.setattr(intel, "stream_intel_query", fake_stream)
    response = await _post(
        _intel_app(loader),
        "/api/intel/query",
        {
            "query": "q",
            "spatial_scope": {
                "schema_version": 1,
                "scope_key": "country:UKR",
                "catalog_revision": revision,
                "boundary_policy": "odin-reference-v1",
            },
        },
    )

    assert response.status_code == 200
    token = captured["spatial_scope"]
    assert isinstance(token, SpatialScopeTokenV1)
    assert token.scope_key == "country:UKR"
    assert token.catalog_revision == revision
    assert token.compatible_derivation_revisions == (
        "spatial-derive-v1-d30efa07e141",
    )
    assert captured["spatial_relation"] == "either"
    assert captured["region"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("catalog_revision", "expected_status", "expected_code"),
    [
        ("latest", 422, "INVALID_CATALOG_REVISION"),
        ("spatial-v1-000000000000", 409, "CATALOG_REVISION_UNAVAILABLE"),
    ],
)
async def test_intel_router_rejects_invalid_or_unserved_catalog_revision(
    catalog_revision: str,
    expected_status: int,
    expected_code: str,
) -> None:
    loader, _ = await _loader()
    response = await _post(
        _intel_app(loader),
        "/api/intel/query",
        {
            "query": "q",
            "spatial_scope": {
                "schema_version": 1,
                "scope_key": "country:UKR",
                "catalog_revision": catalog_revision,
                "boundary_policy": "odin-reference-v1",
            },
        },
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code


@pytest.mark.asyncio
async def test_country_briefing_resolves_reviewed_canonical_scope_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()
    captured: dict[str, object] = {}

    async def fake_stream(**kwargs: object) -> AsyncIterator[dict[str, str]]:
        captured.update(kwargs)
        yield {"event": "result", "data": json.dumps({"analysis": "ok"})}
        yield {"event": "done", "data": ""}

    monkeypatch.setattr(almanac, "stream_intel_query", fake_stream)
    response = await _post(
        _almanac_app(loader),
        "/api/almanac/countries/XKX/briefing",
    )

    assert response.status_code == 200
    token = captured["spatial_scope"]
    assert isinstance(token, SpatialScopeTokenV1)
    assert token.scope_key == "country:odin:kosovo"
    assert token.catalog_revision == revision
    assert captured["spatial_relation"] == "either"
    assert "region" not in captured or captured["region"] is None
