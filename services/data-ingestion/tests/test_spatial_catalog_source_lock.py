from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from spatial_catalog.identity import load_country_crosswalk
from spatial_catalog.source_lock import (
    CATALOG_PLAN_PATH,
    DEFAULT_SOURCE_LOCK_PATH,
    CatalogPlan,
    SourceHashMismatchError,
    SourceLock,
    load_catalog_plan,
    load_source_lock,
    parse_verified_source,
    read_verified_repo_source,
    validate_catalog_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _lock_payload() -> dict[str, object]:
    return json.loads(DEFAULT_SOURCE_LOCK_PATH.read_text(encoding="utf-8"))


def _plan_payload() -> dict[str, object]:
    return json.loads(CATALOG_PLAN_PATH.read_text(encoding="utf-8"))


def test_source_lock_contains_real_pinned_release_metadata() -> None:
    source_lock = load_source_lock()
    by_id = {source.source_id: source for source in source_lock.sources}

    assert set(by_id) == {
        "geoboundaries-gbopen-ukr-admin1",
        "mapshaper",
        "natural-earth-admin0",
        "odin-country-crosswalk",
    }
    assert by_id["natural-earth-admin0"].release == "5.1.2+f1890d9f152c"
    assert by_id["geoboundaries-gbopen-ukr-admin1"].release == (
        "2023-12-12+9469f09592ce"
    )
    assert by_id["mapshaper"].release == "0.7.49"
    for source in source_lock.sources:
        serialized = source.model_dump_json().lower()
        assert "placeholder" not in serialized
        assert "<pinned" not in serialized
        assert "/current/" not in source.url
        assert "/latest/" not in source.url
        assert len(source.sha256) == 64


@pytest.mark.parametrize("bad_release", ["", "<pinned release>", "placeholder", "latest"])
def test_source_lock_rejects_missing_or_placeholder_releases(bad_release: str) -> None:
    payload = _lock_payload()
    payload["sources"][0]["release"] = bad_release  # type: ignore[index]
    with pytest.raises(ValidationError, match="release"):
        SourceLock.model_validate(payload)


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com/source.zip",
        "https://www.geoboundaries.org/api/current/gbOpen/UKR/ADM1/",
        "https://raw.githubusercontent.com/org/repo/main/source.geojson",
        "https://registry.npmjs.org/mapshaper/-/mapshaper-latest.tgz",
        "repo:../outside.json",
        "not-a-url",
    ],
)
def test_source_lock_rejects_mutable_or_malformed_urls(bad_url: str) -> None:
    payload = _lock_payload()
    payload["sources"][0]["url"] = bad_url  # type: ignore[index]
    with pytest.raises(ValidationError, match="immutable source URL"):
        SourceLock.model_validate(payload)


def test_source_lock_rejects_unknown_license_duplicate_id_and_missing_attribution() -> None:
    payload = _lock_payload()
    payload["sources"][0]["license_id"] = "UNKNOWN"  # type: ignore[index]
    with pytest.raises(ValidationError, match="license_id"):
        SourceLock.model_validate(payload)

    payload = _lock_payload()
    payload["sources"][1]["source_id"] = payload["sources"][0]["source_id"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="duplicate source ID"):
        SourceLock.model_validate(payload)

    payload = _lock_payload()
    payload["sources"][0]["attribution"] = ""  # type: ignore[index]
    with pytest.raises(ValidationError, match="attribution"):
        SourceLock.model_validate(payload)


@pytest.mark.parametrize("bad_hash", ["f" * 63, "F" * 64, "g" * 64])
def test_source_lock_rejects_malformed_sha256(bad_hash: str) -> None:
    payload = _lock_payload()
    payload["sources"][0]["sha256"] = bad_hash  # type: ignore[index]
    with pytest.raises(ValidationError, match="sha256"):
        SourceLock.model_validate(payload)


def test_source_hash_mismatch_fails_before_payload_parser() -> None:
    source = load_source_lock().source("odin-country-crosswalk")
    parser_called = False

    def parser(_: bytes) -> object:
        nonlocal parser_called
        parser_called = True
        return object()

    with pytest.raises(SourceHashMismatchError, match="SOURCE_HASH_MISMATCH"):
        parse_verified_source(source, b"not the crosswalk", parser)
    assert parser_called is False


def test_committed_repo_source_matches_lock_hash() -> None:
    source_lock = load_source_lock()
    payload = read_verified_repo_source(
        source_lock.source("odin-country-crosswalk"),
        repo_root=REPO_ROOT,
    )
    assert b'"spatial-crosswalk-v1"' in payload


def test_source_lock_repo_root_is_discovered_from_layout(tmp_path: Path) -> None:
    from spatial_catalog import source_lock as source_lock_module

    lock_path = tmp_path / "services" / "backend" / "data" / "spatial" / "source-lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("{}", encoding="utf-8")
    module_path = (
        tmp_path
        / "services"
        / "data-ingestion"
        / "spatial_catalog"
        / "source_lock.py"
    )

    assert source_lock_module._find_repo_root(module_path) == tmp_path


def test_catalog_plan_has_explicit_reviewed_coverage_and_controls_children() -> None:
    crosswalk = load_country_crosswalk()
    source_lock = load_source_lock()
    plan = load_catalog_plan(crosswalk=crosswalk, source_lock=source_lock)
    by_scope = {entry.scope_key: entry for entry in plan.scopes}

    assert set(by_scope) == {
        record.scope_key for record in crosswalk.records if record.scope_key is not None
    }
    assert by_scope["country:UKR"].children_available is True
    assert by_scope["country:POL"].children_available is False
    assert {feature.record_id for feature in plan.non_scope_features} == {
        "natural-earth-admin0:N. Cyprus"
    }


def test_catalog_plan_rejects_unknown_scope_and_implicit_coverage() -> None:
    crosswalk = load_country_crosswalk()
    source_lock = load_source_lock()

    payload = _plan_payload()
    payload["scopes"][0]["scope_key"] = "country:ZZZ"  # type: ignore[index]
    plan = CatalogPlan.model_validate(payload)
    with pytest.raises(ValueError, match="unknown plan scope"):
        validate_catalog_plan(plan, crosswalk=crosswalk, source_lock=source_lock)

    payload = _plan_payload()
    payload["scopes"].pop()  # type: ignore[union-attr]
    plan = CatalogPlan.model_validate(payload)
    with pytest.raises(ValueError, match="explicit scope coverage"):
        validate_catalog_plan(plan, crosswalk=crosswalk, source_lock=source_lock)


def test_catalog_plan_rejects_unreviewed_special_geometry() -> None:
    crosswalk = load_country_crosswalk()
    source_lock = load_source_lock()
    payload = copy.deepcopy(_plan_payload())
    payload["non_scope_features"] = []
    plan = CatalogPlan.model_validate(payload)

    with pytest.raises(ValueError, match="explicit non-scope coverage"):
        validate_catalog_plan(plan, crosswalk=crosswalk, source_lock=source_lock)
