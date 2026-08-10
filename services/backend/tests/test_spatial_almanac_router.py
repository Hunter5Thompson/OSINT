"""Canonical Spatial-scope adapter tests for the country almanac."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.routers import almanac
from app.services.country_almanac import get_country_almanac_store
from app.services.spatial_catalog import (
    CatalogReadyState,
    ResolvedSpatialScope,
    SpatialCatalogLoader,
)

REFERENCE_SPATIAL_ROOT = Path(__file__).parents[1] / "data" / "spatial"


async def _loader() -> tuple[SpatialCatalogLoader, str]:
    loader = SpatialCatalogLoader(REFERENCE_SPATIAL_ROOT)
    state = await loader.load()
    assert isinstance(state, CatalogReadyState)
    return loader, state.active_catalog_revision


async def _request(
    loader: SpatialCatalogLoader | None,
    method: str,
    url: str,
    **kwargs: object,
) -> Response:
    app = FastAPI()
    if loader is not None:
        app.state.spatial_catalog = loader
    app.include_router(almanac.router, prefix="/api")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.request(method, url, **kwargs)


async def _get(loader: SpatialCatalogLoader, url: str) -> Response:
    return await _request(loader, "GET", url)


@pytest.mark.asyncio
async def test_scope_and_exact_revision_resolve_before_almanac_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()
    events: list[str] = []
    original_resolve = loader.resolve_scope
    real_store = get_country_almanac_store()

    def resolve(scope_key: str | None, catalog_revision: str | None):
        events.append("resolve")
        return original_resolve(scope_key, catalog_revision)

    class RecordingStore:
        def get_country(self, country_id: str):
            events.append(f"almanac:{country_id}")
            return real_store.get_country(country_id)

    monkeypatch.setattr(loader, "resolve_scope", resolve)
    monkeypatch.setattr(almanac, "get_country_almanac_store", RecordingStore)

    response = await _get(
        loader,
        f"/api/almanac/country?scope_key=country%3AUKR&catalog_revision={revision}",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Ukraine"
    assert events == ["resolve", "almanac:UKR"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope_key", "expected_name"),
    [
        ("country:ukr", "Ukraine"),
        ("country:odin:kosovo", "Kosovo"),
        ("country:m49:010", "Antarctica"),
    ],
)
async def test_reviewed_catalog_identity_maps_to_existing_almanac_aliases(
    scope_key: str,
    expected_name: str,
) -> None:
    loader, revision = await _loader()

    response = await _get(
        loader,
        "/api/almanac/country"
        f"?scope_key={scope_key}&catalog_revision={revision}",
    )

    assert response.status_code == 200
    assert response.json()["name"] == expected_name


@pytest.mark.asyncio
async def test_invalid_unserved_non_country_and_unknown_scope_never_touch_almanac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()

    class GuardStore:
        def get_country(self, country_id: str):
            raise AssertionError(f"unexpected almanac lookup: {country_id}")

    monkeypatch.setattr(almanac, "get_country_almanac_store", GuardStore)
    cases = [
        ("scope_key=..%2Fsecret&catalog_revision=" + revision, 422),
        ("scope_key=country%3AUKR&catalog_revision=spatial-v1-000000000000", 409),
        ("scope_key=admin1%3Aiso3166-2%3AUA-14&catalog_revision=" + revision, 422),
        ("scope_key=country%3AZZZ&catalog_revision=" + revision, 404),
        ("scope_key=country%3AUKR", 422),
    ]

    for query, status in cases:
        response = await _get(loader, f"/api/almanac/country?{query}")
        assert response.status_code == status


@pytest.mark.asyncio
async def test_missing_dossier_returns_404_without_changing_resolved_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()

    class MissingStore:
        def get_country(self, country_id: str):
            assert country_id == "UKR"
            return None

    monkeypatch.setattr(almanac, "get_country_almanac_store", MissingStore)

    response = await _get(
        loader,
        f"/api/almanac/country?scope_key=country%3AUKR&catalog_revision={revision}",
    )
    resolved = loader.resolve_scope("country:UKR", revision)

    assert response.status_code == 404
    assert response.json()["detail"] == "country almanac not found"
    assert isinstance(resolved, ResolvedSpatialScope)
    assert resolved.record.scope.key == "country:UKR"
    assert resolved.catalog_revision == revision


@pytest.mark.asyncio
async def test_spatial_signals_resolve_the_exact_committed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()
    calls: list[tuple[str | None, str | None]] = []
    original_resolve = loader.resolve_scope

    def resolve(scope_key: str | None, catalog_revision: str | None):
        calls.append((scope_key, catalog_revision))
        return original_resolve(scope_key, catalog_revision)

    monkeypatch.setattr(loader, "resolve_scope", resolve)

    response = await _request(
        loader,
        "GET",
        "/api/almanac/country/signals"
        f"?scope_key=country%3AUKR&catalog_revision={revision}&limit=5",
    )

    assert response.status_code == 200
    assert response.json()["country_id"] == "UKR"
    assert calls == [("country:UKR", revision)]


@pytest.mark.asyncio
async def test_spatial_briefing_stream_uses_the_exact_resolved_scope_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()
    captured: dict[str, object] = {}

    async def fake_stream(**kwargs: object):
        captured.update(kwargs)
        yield {"event": "result", "data": '{"analysis":"ok"}'}
        yield {"event": "done", "data": ""}

    monkeypatch.setattr(almanac, "stream_intel_query", fake_stream)

    response = await _request(
        loader,
        "POST",
        "/api/almanac/country/briefing"
        f"?scope_key=country%3AUKR&catalog_revision={revision}",
    )

    assert response.status_code == 200
    token = captured["spatial_scope"]
    assert getattr(token, "scope_key") == "country:UKR"
    assert getattr(token, "catalog_revision") == revision


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "signals"),
        ("POST", "briefing"),
    ],
)
async def test_spatial_inspector_routes_fail_closed_without_identity_fallback(
    method: str,
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, revision = await _loader()

    class GuardStore:
        def get_country(self, country_id: str):
            raise AssertionError(f"unexpected almanac fallback: {country_id}")

    monkeypatch.setattr(almanac, "get_country_almanac_store", GuardStore)
    resolve_calls: list[tuple[str | None, str | None]] = []
    original_resolve = loader.resolve_scope

    def resolve(scope_key: str | None, catalog_revision: str | None):
        resolve_calls.append((scope_key, catalog_revision))
        return original_resolve(scope_key, catalog_revision)

    monkeypatch.setattr(loader, "resolve_scope", resolve)
    cases = [
        (loader, "scope_key=country%3AUKR&catalog_revision=spatial-v1-000000000000", 409),
        (loader, "scope_key=country%3AUKR&catalog_revision=not-a-revision", 422),
        (
            loader,
            f"scope_key=admin1%3Aiso3166-2%3AUA-14&catalog_revision={revision}",
            422,
        ),
        (loader, f"scope_key=country%3AZZZ&catalog_revision={revision}", 404),
        (loader, "scope_key=country%3AUKR", 422),
        (None, f"scope_key=country%3AUKR&catalog_revision={revision}", 503),
    ]

    for candidate, query, expected_status in cases:
        response = await _request(
            candidate,
            method,
            f"/api/almanac/country/{suffix}?{query}",
        )
        assert response.status_code == expected_status

    assert resolve_calls.count(("country:UKR", "spatial-v1-000000000000")) == 1
