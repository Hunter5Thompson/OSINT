from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from main import QueryRequest, query_intelligence
from spatial import ScopeKind, SpatialScopeTokenV1
from spatial_catalog import (
    IntelligenceSpatialCatalog,
    SpatialCatalogResolutionError,
    SpatialScopeRefV1,
)


def _reference_root() -> Path:
    return Path(__file__).resolve().parents[2] / "backend" / "data" / "spatial"


def test_resolver_uses_served_pointer_and_derives_token_from_manifest() -> None:
    catalog = IntelligenceSpatialCatalog(_reference_root())
    catalog.load()

    token = catalog.resolve(SpatialScopeRefV1(
        scope_key="country:UKR",
        catalog_revision="spatial-v1-e76a16bff799",
    ))

    assert token.kind is ScopeKind.COUNTRY
    assert token.boundary_policy == "odin-reference-v1"
    assert token.derivation_revision in token.compatible_derivation_revisions


def test_resolver_rejects_revision_outside_server_owned_pointer() -> None:
    catalog = IntelligenceSpatialCatalog(_reference_root())
    catalog.load()

    with pytest.raises(SpatialCatalogResolutionError):
        catalog.resolve(SpatialScopeRefV1(
            scope_key="country:UKR",
            catalog_revision="spatial-v1-aaaaaaaaaaaa",
        ))


@pytest.mark.asyncio
async def test_query_route_resolves_ref_before_workflow() -> None:
    revision = "spatial-derive-v1-d30efa07e141"
    token = SpatialScopeTokenV1(
        scope_key="country:UKR",
        kind=ScopeKind.COUNTRY,
        catalog_revision="spatial-v1-e76a16bff799",
        derivation_revision=revision,
        boundary_policy="odin-reference-v1",
        compatible_derivation_revisions=(revision,),
    )
    request = QueryRequest(
        query="q",
        spatial_scope={
            "scope_key": "country:UKR",
            "catalog_revision": "spatial-v1-e76a16bff799",
        },
        spatial_relation="either",
    )
    with (
        patch("main._spatial_catalog.resolve", return_value=token) as resolve,
        patch("main.run_intelligence_query", new_callable=AsyncMock) as run,
    ):
        run.return_value = {"analysis": "ok"}
        result = await query_intelligence(request)

    assert result == {"analysis": "ok"}
    resolve.assert_called_once_with(request.spatial_scope)
    assert run.await_args.kwargs["spatial_scope"] is token


@pytest.mark.asyncio
async def test_query_route_returns_409_without_running_for_unserved_ref() -> None:
    request = QueryRequest(
        query="q",
        spatial_scope={
            "scope_key": "country:UKR",
            "catalog_revision": "spatial-v1-aaaaaaaaaaaa",
        },
        spatial_relation="either",
    )
    with (
        patch(
            "main._spatial_catalog.resolve",
            side_effect=SpatialCatalogResolutionError("unserved"),
        ),
        patch("main.run_intelligence_query", new_callable=AsyncMock) as run,
    ):
        result = await query_intelligence(request)

    assert result.status_code == 409
    run.assert_not_awaited()
