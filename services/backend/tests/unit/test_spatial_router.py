"""Strict HTTP adapter tests for the local spatial catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.main import app as production_app
from app.routers.spatial import router
from app.services.spatial_catalog import CatalogReadyState, SpatialCatalogLoader
from tests.unit.test_spatial_catalog import _canonical_bytes, _publish_catalog


def _build_app(loader: SpatialCatalogLoader) -> FastAPI:
    app = FastAPI()
    app.state.spatial_catalog = loader
    app.include_router(router, prefix="/api")
    return app


async def _get(
    loader: SpatialCatalogLoader,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    transport = ASGITransport(app=_build_app(loader))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url, headers=headers)


def _expected_problem(
    *,
    code: str,
    message: str,
    target: str | None,
    recoverable: bool,
    active_revision: str | None,
) -> dict[str, object]:
    return {
        "detail": {
            "schema_version": 1,
            "code": code,
            "message": message,
            "target": target,
            "recoverable": recoverable,
            "active_catalog_revision": active_revision,
        }
    }


def test_production_app_registers_spatial_routes_under_central_api_prefix() -> None:
    paths = set(production_app.openapi()["paths"])
    assert {
        "/api/spatial/catalog",
        "/api/spatial/scope",
        "/api/spatial/assets/{asset_id}",
    } <= paths


@pytest.mark.asyncio
async def test_catalog_bootstrap_serves_active_previous_and_bounded_attribution(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    previous, _, _ = _publish_catalog(
        spatial_root,
        asset_content=b'{"revision":"previous"}',
        modified_ns=2_000_000_000,
    )
    active, _, _ = _publish_catalog(
        spatial_root,
        asset_content=b'{"revision":"active"}',
        carry_forward_from=previous,
        modified_ns=1_000_000_000,
    )
    loader = SpatialCatalogLoader(spatial_root)
    assert isinstance(await loader.load(), CatalogReadyState)

    response = await _get(loader, "/api/spatial/catalog")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"
    assert response.json() == {
        "schema_version": 1,
        "active_catalog_revision": active,
        "served_catalog_revisions": [active, previous],
        "boundary_policy": "odin-reference-v1",
        "root_scope_key": "world",
        "capabilities": {
            "max_enabled_kind": "world",
            "timeline_scope": "bbox_approximate",
            "intelligence_scope": "unavailable",
        },
        "attributions": [
            {
                "catalog_revision": active,
                "representation_note": "ODIN reference boundary representation",
                "sources": [
                    {
                        "source_id": "fixture-source",
                        "release": "fixture-v1",
                        "license_id": "public-domain",
                        "text": "Fixture source",
                    }
                ],
            },
            {
                "catalog_revision": previous,
                "representation_note": "ODIN reference boundary representation",
                "sources": [
                    {
                        "source_id": "fixture-source",
                        "release": "fixture-v1",
                        "license_id": "public-domain",
                        "text": "Fixture source",
                    }
                ],
            },
        ],
    }
    assert len(response.json()["attributions"]) == len(
        response.json()["served_catalog_revisions"]
    )
    assert "example.invalid" not in response.text
    assert str(tmp_path) not in response.text


@pytest.mark.asyncio
async def test_scope_resolve_returns_canonical_server_path_and_requested_revision(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, _ = _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    response = await _get(
        loader,
        f"/api/spatial/scope?scope_key=world&catalog_revision={revision}",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["catalog_revision"] == revision
    assert payload["boundary_policy"] == "odin-reference-v1"
    assert payload["canonicalized_from"] is None
    assert payload["scope"]["key"] == "world"
    assert payload["path"] == [payload["scope"]]
    assert payload["presentation"]["preferred_lod"] is None
    descriptor = payload["presentation"]["outline_lods"]["overview"]
    assert descriptor["role"] == "render"
    assert descriptor["lod"] == "overview"
    assert "feature_count" not in descriptor
    assert payload["containment"] is None
    assert payload["provenance_ref"] == "fixture-source"


@pytest.mark.asyncio
async def test_scope_resolve_uses_active_revision_when_omitted(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, _ = _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    response = await _get(loader, "/api/spatial/scope?scope_key=world")

    assert response.status_code == 200
    assert response.json()["catalog_revision"] == revision


@pytest.mark.asyncio
async def test_unknown_scope_and_asset_return_stable_404(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, _ = _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    scope_response = await _get(
        loader,
        f"/api/spatial/scope?scope_key=country:ZZZ&catalog_revision={revision}",
    )
    asset_response = await _get(loader, f"/api/spatial/assets/{'f' * 64}")

    assert scope_response.status_code == 404
    assert scope_response.json() == _expected_problem(
        code="UNKNOWN_SCOPE",
        message="Spatial scope was not found",
        target="country:ZZZ",
        recoverable=False,
        active_revision=revision,
    )
    assert asset_response.status_code == 404
    assert asset_response.json() == _expected_problem(
        code="UNKNOWN_ASSET",
        message="Spatial asset was not found",
        target="f" * 64,
        recoverable=False,
        active_revision=revision,
    )


@pytest.mark.asyncio
async def test_unserved_revision_returns_stable_409(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    active, _, _ = _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()
    unavailable = "spatial-v1-000000000000"

    response = await _get(
        loader,
        f"/api/spatial/scope?scope_key=world&catalog_revision={unavailable}",
    )

    assert response.status_code == 409
    assert response.json() == _expected_problem(
        code="CATALOG_REVISION_UNAVAILABLE",
        message="Requested spatial catalog revision is not served",
        target=unavailable,
        recoverable=True,
        active_revision=active,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "/api/spatial/scope?scope_key=../secret",
        "/api/spatial/scope?scope_key=country%3AUSA%2Fsecret",
        "/api/spatial/scope?scope_key=country%3AUSA%5Csecret",
        "/api/spatial/scope?scope_key=country%3AXKX",
        "/api/spatial/scope?scope_key=",
        "/api/spatial/scope",
        "/api/spatial/scope?scope_key=world&catalog_revision=latest",
        "/api/spatial/assets/not-a-sha256",
        "/api/spatial/assets/%2E%2E%2Fsecret",
        "/api/spatial/assets/abc%5Cdef",
    ],
)
async def test_invalid_scope_revision_or_asset_is_stable_422(
    tmp_path: Path,
    url: str,
) -> None:
    spatial_root = tmp_path / "spatial"
    _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    response = await _get(loader, url)

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {
        "schema_version",
        "code",
        "message",
        "target",
        "recoverable",
        "active_catalog_revision",
    }
    assert body["detail"]["code"] in {
        "INVALID_SCOPE_KEY",
        "INVALID_CATALOG_REVISION",
        "INVALID_ASSET_ID",
    }
    assert body["detail"]["target"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        "catalog-missing",
        "attribution-missing",
        "malformed",
        "html",
        "oversized",
        "too-many-sources",
        "extra",
    ],
)
async def test_catalog_or_attribution_corruption_returns_generic_503_without_leakage(
    tmp_path: Path,
    corruption: str,
) -> None:
    spatial_root = tmp_path / "spatial"
    if corruption != "catalog-missing":
        revision, _, _ = _publish_catalog(spatial_root)
        attribution_path = spatial_root / "catalogs" / revision / "attribution.json"
        if corruption == "attribution-missing":
            attribution_path.unlink()
        elif corruption == "malformed":
            attribution_path.write_bytes(b"not-json")
        else:
            payload = json.loads(attribution_path.read_bytes())
            if corruption == "html":
                payload["sources"][0]["attribution"] = "<strong>unsafe</strong>"
            elif corruption == "oversized":
                payload["sources"][0]["attribution"] = "x" * 301
            elif corruption == "too-many-sources":
                payload["sources"] = payload["sources"] * 33
            else:
                payload["unexpected"] = True
            attribution_path.write_bytes(_canonical_bytes(payload))
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    response = await _get(loader, "/api/spatial/catalog")

    assert response.status_code == 503
    assert response.json() == _expected_problem(
        code="CATALOG_UNAVAILABLE",
        message="Spatial catalog is unavailable",
        target=None,
        recoverable=True,
        active_revision=None,
    )
    assert str(tmp_path) not in response.text
    assert "example.invalid" not in response.text


@pytest.mark.asyncio
async def test_reference_scope_canonicalizes_only_the_iso_segment() -> None:
    reference_root = Path(__file__).parents[2] / "data" / "spatial"
    loader = SpatialCatalogLoader(reference_root)
    await loader.load()

    response = await _get(loader, "/api/spatial/scope?scope_key=country:ukr")

    assert response.status_code == 200
    assert response.json()["scope"]["key"] == "country:UKR"
    assert response.json()["canonicalized_from"] == "country:ukr"


@pytest.mark.asyncio
async def test_catalog_and_scope_etag_support_304(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    for url in ("/api/spatial/catalog", "/api/spatial/scope?scope_key=world"):
        first = await _get(loader, url)
        assert first.status_code == 200
        assert first.headers["etag"].startswith('"')

        cached = await _get(loader, url, headers={"If-None-Match": first.headers["etag"]})

        assert cached.status_code == 304
        assert cached.content == b""
        assert cached.headers["etag"] == first.headers["etag"]
        assert cached.headers["cache-control"] == "public, max-age=60, must-revalidate"


@pytest.mark.asyncio
async def test_asset_success_etag_304_and_range_headers(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    content = b"abcdefghijklmnop"
    _, asset_id, _ = _publish_catalog(spatial_root, asset_content=content)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()
    url = f"/api/spatial/assets/{asset_id}"

    full = await _get(loader, url)
    partial = await _get(loader, url, headers={"Range": "bytes=2-5"})
    cached = await _get(loader, url, headers={"If-None-Match": f'"{asset_id}"'})

    assert full.status_code == 200
    assert full.content == content
    assert full.headers["content-type"] == "application/vnd.odin.boundary+json;v=1"
    assert full.headers["content-length"] == str(len(content))
    assert full.headers["content-encoding"] == "identity"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert full.headers["etag"] == f'"{asset_id}"'
    assert partial.status_code == 206
    assert partial.content == b"cdef"
    assert partial.headers["content-range"] == f"bytes 2-5/{len(content)}"
    assert partial.headers["content-length"] == "4"
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == f'"{asset_id}"'


@pytest.mark.asyncio
async def test_invalid_range_returns_416_without_internal_path(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    _, asset_id, _ = _publish_catalog(spatial_root, asset_content=b"short")
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()

    response = await _get(
        loader,
        f"/api/spatial/assets/{asset_id}",
        headers={"Range": "bytes=50-60"},
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */5"
    assert str(tmp_path) not in response.text
