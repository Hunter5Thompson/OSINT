"""Runtime spatial-catalog loading and integrity tests."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.models.spatial import CatalogAttribution, CatalogProblemCode
from app.services import spatial_catalog as spatial_catalog_module
from app.services.spatial_catalog import (
    CatalogReadyState,
    CatalogUnavailableState,
    SpatialAsset,
    SpatialCatalogLoader,
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _derivation_revision(scope_path: list[str]) -> str:
    inputs = {
        "schema_version": 1,
        "crosswalk_sha256": "c" * 64,
        "scope_path": scope_path,
        "assignment_asset_ids": [],
    }
    return f"spatial-derive-v1-{hashlib.sha256(_canonical_bytes(inputs)).hexdigest()[:12]}"


def _source_lock(
    *,
    source_release: str = "fixture-v1",
    source_license_id: str = "public-domain",
    source_attribution: str = "Fixture source",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "sources": [
            {
                "source_id": "fixture-source",
                "release": source_release,
                "url": "https://example.invalid/must-never-be-opened.json",
                "sha256": "c" * 64,
                "license_id": source_license_id,
                "attribution": source_attribution,
            }
        ],
    }


def test_shared_attribution_contract_fixture_is_accepted() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[4]
        / "tests"
        / "fixtures"
        / "spatial"
        / "attribution-contract-v1.json"
    )

    attribution = CatalogAttribution.model_validate_json(fixture_path.read_bytes())

    assert tuple(source.release for source in attribution.sources) == (
        "fixture-v1",
        "tool-v1",
    )


def _publish_catalog(
    root: Path,
    *,
    asset_content: bytes = b"{}",
    declared_byte_length: int | None = None,
    carry_forward_from: str | None = None,
    scope_path: list[str] | None = None,
    compatible: list[str] | None = None,
    modified_ns: int | None = None,
    source_release: str = "fixture-v1",
    source_license_id: str = "public-domain",
    source_attribution: str = "Fixture source",
    attribution_only_release: str | None = None,
) -> tuple[str, str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source_lock = _source_lock(
        source_release=source_release,
        source_license_id=source_license_id,
        source_attribution=source_attribution,
    )
    attribution_sources: list[dict[str, object]] = [
        {
            "source_id": "fixture-source",
            "release": source_release,
            "license_id": source_license_id,
            "attribution": source_attribution,
        }
    ]
    if attribution_only_release is not None:
        source_lock["sources"].append(  # type: ignore[union-attr]
            {
                "source_id": "fixture-tool",
                "release": attribution_only_release,
                "url": "repo:fixture-tool",
                "sha256": "d" * 64,
                "license_id": "MPL-2.0",
                "attribution": "Fixture tool",
            }
        )
        attribution_sources.append(
            {
                "source_id": "fixture-tool",
                "release": attribution_only_release,
                "license_id": "MPL-2.0",
                "attribution": "Fixture tool",
            }
        )
    (root / "source-lock.json").write_bytes(_canonical_bytes(source_lock))

    asset_id = hashlib.sha256(asset_content).hexdigest()
    path = scope_path or ["world"]
    derivation_revision = _derivation_revision(path)
    descriptor = {
        "asset_id": asset_id,
        "media_type": "application/vnd.odin.boundary+json;v=1",
        "byte_length": declared_byte_length or len(asset_content),
        "vertex_count": 1,
        "feature_count": None,
        "role": "render",
        "lod": "overview",
    }
    record = {
        "scope": {
            "key": "world",
            "kind": "world",
            "label": "World",
            "short_label": "World",
            "parent_key": None,
            "children_available": False,
            "presentation": "boundary",
        },
        "path": path,
        "provenance": {
            "boundary_policy": "odin-reference-v1",
            "representation_id": "fixture-representation",
            "dispute_status": "none",
            "source_id": "fixture-source",
            "source_release": source_release,
            "license_id": source_license_id,
            "attribution": source_attribution,
        },
        "presentation": {
            "preferred_lod": None,
            "outline_lods": {"overview": descriptor},
            "children_lods": {},
            "containment": None,
        },
        "provenance_ref": "fixture-source",
        "derivation_inputs": {
            "crosswalk_sha256": "c" * 64,
            "scope_path": path,
            "assignment_asset_ids": [],
        },
        "derivation_revision": derivation_revision,
        "compatible_derivation_revisions": compatible or [derivation_revision],
        "carry_forward_from": carry_forward_from,
    }
    revision_payload = {
        "schema_version": 1,
        "boundary_policy": "odin-reference-v1",
        "root_scope_key": "world",
        "attribution_sources_sha256": hashlib.sha256(
            _canonical_bytes(attribution_sources)
        ).hexdigest(),
        "scopes": [record],
        "assets": [asset_id],
    }
    revision = (
        "spatial-v1-" + hashlib.sha256(_canonical_bytes(revision_payload)).hexdigest()[:12]
    )
    manifest = {"catalog_revision": revision, **revision_payload}
    catalog_dir = root / "catalogs" / revision
    assets_dir = catalog_dir / "assets"
    assets_dir.mkdir(parents=True)
    (catalog_dir / "manifest.json").write_bytes(_canonical_bytes(manifest))
    (catalog_dir / "attribution.json").write_bytes(
        _canonical_bytes(
            {
                "schema_version": 1,
                "catalog_revision": revision,
                "sources": attribution_sources,
            }
        )
    )
    asset_path = assets_dir / f"{asset_id}.json"
    asset_path.write_bytes(asset_content)
    if modified_ns is not None:
        os.utime(catalog_dir, ns=(modified_ns, modified_ns))
    return revision, asset_id, asset_path


@pytest.mark.asyncio
async def test_loader_serves_active_and_previous_catalogs(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    previous, previous_asset, _ = _publish_catalog(
        spatial_root,
        asset_content=b'{"revision":"previous"}',
        modified_ns=2_000_000_000,
    )
    active, active_asset, _ = _publish_catalog(
        spatial_root,
        asset_content=b'{"revision":"active"}',
        carry_forward_from=previous,
        modified_ns=1_000_000_000,
    )

    loader = SpatialCatalogLoader(spatial_root)
    state = await loader.load()

    assert isinstance(state, CatalogReadyState)
    assert state.active_catalog_revision == active
    assert state.served_catalog_revisions == (active, previous)
    assert loader.get_scope(active, "world").scope.key == "world"
    assert loader.get_scope(previous, "world").scope.key == "world"
    assert loader.get_asset(active, active_asset).asset_id == active_asset
    assert loader.get_asset(previous, previous_asset).asset_id == previous_asset


@pytest.mark.asyncio
async def test_each_revision_projects_its_own_reviewed_source_release(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    previous, _, _ = _publish_catalog(
        spatial_root,
        source_release="fixture-v1",
        source_license_id="public-domain",
        source_attribution="Fixture source v1",
        modified_ns=2_000_000_000,
    )
    active, _, _ = _publish_catalog(
        spatial_root,
        carry_forward_from=previous,
        source_release="fixture-v2",
        source_license_id="CC-BY-4.0",
        source_attribution="Fixture source v2",
        modified_ns=1_000_000_000,
    )
    loader = SpatialCatalogLoader(spatial_root)

    state = await loader.load()
    bootstrap = loader.bootstrap()

    assert isinstance(state, CatalogReadyState)
    assert bootstrap.active_catalog_revision == active
    assert tuple(
        (
            attribution.catalog_revision,
            attribution.sources[0].release,
            attribution.sources[0].license_id,
            attribution.sources[0].text,
        )
        for attribution in bootstrap.attributions
    ) == (
        (active, "fixture-v2", "CC-BY-4.0", "Fixture source v2"),
        (previous, "fixture-v1", "public-domain", "Fixture source v1"),
    )


@pytest.mark.asyncio
async def test_attribution_only_release_is_pinned_per_catalog_revision(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    previous, _, _ = _publish_catalog(
        spatial_root,
        attribution_only_release="tool-v1",
        modified_ns=2_000_000_000,
    )
    active, _, _ = _publish_catalog(
        spatial_root,
        carry_forward_from=previous,
        attribution_only_release="tool-v2",
        modified_ns=1_000_000_000,
    )
    loader = SpatialCatalogLoader(spatial_root)

    state = await loader.load()
    bootstrap = loader.bootstrap()

    assert isinstance(state, CatalogReadyState)
    projected = {
        attribution.catalog_revision: {
            source.source_id: source.release for source in attribution.sources
        }
        for attribution in bootstrap.attributions
    }
    assert projected == {
        active: {"fixture-source": "fixture-v1", "fixture-tool": "tool-v2"},
        previous: {"fixture-source": "fixture-v1", "fixture-tool": "tool-v1"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda source: source.pop("release"),
        lambda source: source.update(release=""),
        lambda source: source.update(release="x" * 129),
        lambda source: source.update(release_metadata="unexpected"),
    ],
    ids=("missing", "empty", "oversized", "extra"),
)
async def test_attribution_release_contract_fails_closed(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, _ = _publish_catalog(spatial_root)
    attribution_path = spatial_root / "catalogs" / revision / "attribution.json"
    attribution = json.loads(attribution_path.read_bytes())
    mutate(attribution["sources"][0])
    attribution_path.write_bytes(_canonical_bytes(attribution))

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "diagnostic"),
    [
        (
            lambda sources: sources.append(dict(sources[0])),
            "duplicate attribution source",
        ),
        (lambda sources: sources.reverse(), "canonically ordered"),
    ],
    ids=("duplicate", "noncanonical-order"),
)
async def test_attribution_source_collection_contract_fails_closed(
    tmp_path: Path,
    mutate: Callable[[list[dict[str, Any]]], object],
    diagnostic: str,
) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, _ = _publish_catalog(
        spatial_root,
        attribution_only_release="tool-v1",
    )
    attribution_path = spatial_root / "catalogs" / revision / "attribution.json"
    attribution = json.loads(attribution_path.read_bytes())
    mutate(attribution["sources"])
    attribution_path.write_bytes(_canonical_bytes(attribution))
    loader = SpatialCatalogLoader(spatial_root)

    state = await loader.load()

    assert isinstance(state, CatalogUnavailableState)
    assert loader.diagnostic is not None
    assert diagnostic in loader.diagnostic


@pytest.mark.asyncio
async def test_active_attribution_source_set_must_match_source_lock(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    _publish_catalog(spatial_root)
    source_lock_path = spatial_root / "source-lock.json"
    source_lock = json.loads(source_lock_path.read_bytes())
    source_lock["sources"].append(
        {
            "source_id": "fixture-tool",
            "release": "tool-v1",
            "url": "repo:fixture-tool",
            "sha256": "d" * 64,
            "license_id": "MPL-2.0",
            "attribution": "Fixture tool",
        }
    )
    source_lock_path.write_bytes(_canonical_bytes(source_lock))

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)


@pytest.mark.asyncio
async def test_active_attribution_only_source_must_match_source_lock(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    _publish_catalog(spatial_root, attribution_only_release="tool-v1")
    source_lock_path = spatial_root / "source-lock.json"
    source_lock = json.loads(source_lock_path.read_bytes())
    tool_source = next(
        source
        for source in source_lock["sources"]
        if source["source_id"] == "fixture-tool"
    )
    tool_source["release"] = "tool-v2"
    source_lock_path.write_bytes(_canonical_bytes(source_lock))

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)


@pytest.mark.asyncio
async def test_loader_accepts_the_reviewed_reference_catalog() -> None:
    reference_root = Path(__file__).parents[2] / "data" / "spatial"
    loader = SpatialCatalogLoader(reference_root)

    state = await loader.load()

    assert isinstance(state, CatalogReadyState)
    assert state.active_catalog_revision == "spatial-v1-e76a16bff799"
    assert loader.get_scope(state.active_catalog_revision, "country:UKR").scope.label == "Ukraine"
    admin1 = loader.get_scope(
        state.active_catalog_revision,
        "admin1:iso3166-2:UA-14",
    )
    assert admin1.scope.label == "Donetsk Oblast"
    assert admin1.scope.presentation == "boundary"
    assert admin1.presentation.preferred_lod is None
    assert admin1.presentation.outline_lods["regional"].asset_id == (
        "a7c85e0208cf628a320a2f4642e3589168e2da34a573f7d2daaebed220017123"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(schema_version=2),
        lambda value: value["scopes"][0]["scope"].update(label="Tampered"),
        lambda value: value["scopes"][0].update(path=["world", "world"]),
        lambda value: value["scopes"][0].update(
            compatible_derivation_revisions=["spatial-derive-v1-000000000000"]
        ),
        lambda value: value["scopes"][0].update(
            compatible_derivation_revisions=[value["scopes"][0]["derivation_revision"]] * 2
        ),
    ],
    ids=("schema", "manifest-hash", "lineage", "compatibility-current", "compatibility-unique"),
)
async def test_loader_marks_invalid_catalog_unavailable(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, _ = _publish_catalog(spatial_root)
    manifest_path = spatial_root / "catalogs" / revision / "manifest.json"
    value: dict[str, Any] = json.loads(manifest_path.read_bytes())
    mutate(value)
    manifest_path.write_bytes(_canonical_bytes(value))

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)
    assert state.problem.code is CatalogProblemCode.CATALOG_UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "malformed"])
async def test_missing_or_corrupt_catalog_is_an_unavailable_state(
    tmp_path: Path,
    case: str,
) -> None:
    spatial_root = tmp_path / "spatial"
    if case == "malformed":
        revision, _, _ = _publish_catalog(spatial_root)
        (spatial_root / "catalogs" / revision / "manifest.json").write_bytes(b"not-json")

    loader = SpatialCatalogLoader(spatial_root)
    state = await loader.load()

    assert isinstance(state, CatalogUnavailableState)
    assert loader.is_available is False
    assert state.problem.message == "Spatial catalog is unavailable"


@pytest.mark.asyncio
async def test_loader_rejects_undeclared_asset(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    revision, _, asset_path = _publish_catalog(spatial_root)
    (asset_path.parent / f"{'f' * 64}.json").write_bytes(b"undeclared")

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)


@pytest.mark.asyncio
async def test_loader_rejects_asset_symlink_even_when_target_size_matches(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    _, _, asset_path = _publish_catalog(spatial_root)
    content = asset_path.read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(content)
    asset_path.unlink()
    asset_path.symlink_to(outside)

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)


@pytest.mark.asyncio
async def test_loader_rejects_declared_byte_length_mismatch(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    _publish_catalog(spatial_root, asset_content=b"{}", declared_byte_length=3)

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogUnavailableState)


@pytest.mark.asyncio
async def test_loader_startup_has_no_network_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spatial_root = tmp_path / "spatial"
    _publish_catalog(spatial_root)

    def deny_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("spatial catalog startup attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", deny_connect)

    state = await SpatialCatalogLoader(spatial_root).load()

    assert isinstance(state, CatalogReadyState)


@pytest.mark.asyncio
async def test_successful_immutable_asset_hash_is_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spatial_root = tmp_path / "spatial"
    revision, asset_id, _ = _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    assert isinstance(await loader.load(), CatalogReadyState)
    asset = loader.get_asset(revision, asset_id)
    assert isinstance(asset, SpatialAsset)

    hash_calls = 0
    real_sha256 = spatial_catalog_module._sha256_bytes

    def count_hash(payload: bytes) -> str:
        nonlocal hash_calls
        hash_calls += 1
        return real_sha256(payload)

    monkeypatch.setattr(spatial_catalog_module, "_sha256_bytes", count_hash)

    assert await loader.read_asset(asset) == b"{}"
    assert await loader.read_asset(asset) == b"{}"
    assert hash_calls == 1
    assert loader.verified_asset_count == 1


@pytest.mark.asyncio
async def test_transient_asset_io_error_does_not_disable_loaded_catalog(
    tmp_path: Path,
) -> None:
    spatial_root = tmp_path / "spatial"
    revision, asset_id, _ = _publish_catalog(spatial_root, asset_content=b"available")
    calls = 0

    def flaky_reader(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient fixture read failure")
        return path.read_bytes()

    loader = SpatialCatalogLoader(spatial_root, file_reader=flaky_reader)
    assert isinstance(await loader.load(), CatalogReadyState)
    asset = loader.get_asset(revision, asset_id)
    assert isinstance(asset, SpatialAsset)

    first = await loader.read_asset(asset)

    assert first.code is CatalogProblemCode.CATALOG_UNAVAILABLE
    assert loader.is_available is True
    assert await loader.read_asset(asset) == b"available"
    assert calls == 2


@pytest.mark.asyncio
async def test_close_discards_loaded_catalog_and_hash_cache(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    revision, asset_id, _ = _publish_catalog(spatial_root)
    loader = SpatialCatalogLoader(spatial_root)
    await loader.load()
    asset = loader.get_asset(revision, asset_id)
    assert isinstance(asset, SpatialAsset)
    await loader.read_asset(asset)

    await loader.close()

    assert loader.is_available is False
    assert loader.verified_asset_count == 0


@pytest.mark.asyncio
async def test_readiness_resolve_and_hash_events_are_bounded_metadata(tmp_path: Path) -> None:
    spatial_root = tmp_path / "spatial"
    revision, asset_id, _ = _publish_catalog(spatial_root)
    events: list[tuple[str, dict[str, object]]] = []
    loader = SpatialCatalogLoader(
        spatial_root,
        monotonic=lambda: 10.0,
        event_sink=lambda name, fields: events.append((name, fields)),
    )

    await loader.load()
    loader.resolve_scope("world", revision)
    asset = loader.get_asset(revision, asset_id)
    assert isinstance(asset, SpatialAsset)
    await loader.read_asset(asset)

    names = {name for name, _ in events}
    assert {
        "spatial_catalog_readiness",
        "spatial_catalog_resolve",
        "spatial_asset_hash_verified",
        "spatial_asset_load",
    } <= names
    serialized = json.dumps(events)
    assert str(tmp_path) not in serialized
    assert "example.invalid" not in serialized
