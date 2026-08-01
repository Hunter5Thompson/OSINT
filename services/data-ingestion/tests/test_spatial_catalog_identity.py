from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from spatial_catalog.identity import (
    COUNTRY_CROSSWALK_PATH,
    CountryCrosswalk,
    CountryIdentityResolutionError,
    InvalidScopeKeyError,
    load_country_crosswalk,
    normalize_scope_key_candidate,
    parse_scope_key,
    resolve_country,
    validate_natural_earth_coverage,
)
from spatial_catalog.models import ScopeKind


@pytest.mark.parametrize(
    ("candidate", "canonical", "kind", "namespace", "code"),
    [
        ("world", "world", ScopeKind.WORLD, None, None),
        ("country:ukr", "country:UKR", ScopeKind.COUNTRY, "iso3166-1", "UKR"),
        ("country:m49:010", "country:m49:010", ScopeKind.COUNTRY, "m49", "010"),
        (
            "country:odin:somaliland",
            "country:odin:somaliland",
            ScopeKind.COUNTRY,
            "odin",
            "somaliland",
        ),
        (
            "admin1:iso3166-2:ua-14",
            "admin1:iso3166-2:UA-14",
            ScopeKind.ADMIN1,
            "iso3166-2",
            "UA-14",
        ),
        (
            "admin1:gbopen:Case.Sensitive_1",
            "admin1:gbopen:Case.Sensitive_1",
            ScopeKind.ADMIN1,
            "gbopen",
            "Case.Sensitive_1",
        ),
        (
            "admin2:gbopen:UA.14.1_1",
            "admin2:gbopen:UA.14.1_1",
            ScopeKind.ADMIN2,
            "gbopen",
            "UA.14.1_1",
        ),
    ],
)
def test_scope_key_accepts_canonical_examples(
    candidate: str,
    canonical: str,
    kind: ScopeKind,
    namespace: str | None,
    code: str | None,
) -> None:
    assert normalize_scope_key_candidate(candidate) == canonical
    parsed = parse_scope_key(candidate)
    assert parsed.canonical == canonical
    assert parsed.kind is kind
    assert parsed.namespace == namespace
    assert parsed.canonical_code == code


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "country/UKR",
        r"country\UKR",
        "country%2FUKR",
        "country%252FUKR",
        "country:UK R",
        "country:\x00UKR",
        "country:Ukraine",
        "Ukraine",
        "country:UP",
        "country:XKX:extra",
        "locality:Kyiv",
        "aoi:front-line",
        "x" * 129,
    ],
)
def test_scope_key_rejects_path_oversize_and_display_name_input(candidate: str) -> None:
    with pytest.raises(InvalidScopeKeyError, match="INVALID_SCOPE_KEY"):
        parse_scope_key(candidate)


def test_scope_key_normalization_never_rewrites_source_specific_ids() -> None:
    candidate = "admin1:gbopen:Ua.Mixed_Case"
    assert normalize_scope_key_candidate(candidate) == candidate


def test_scope_key_parser_does_not_promote_fips_or_legacy_xkx() -> None:
    with pytest.raises(InvalidScopeKeyError, match="INVALID_SCOPE_KEY"):
        parse_scope_key("country:UP")
    # XKX is accepted only by the reviewed crosswalk as an explicit legacy alias.
    with pytest.raises(InvalidScopeKeyError, match="INVALID_SCOPE_KEY"):
        parse_scope_key("country:XKX")


def test_scope_key_errors_are_deterministic_and_do_not_repair_input() -> None:
    candidate = " country:ukr "
    with pytest.raises(InvalidScopeKeyError) as first:
        parse_scope_key(candidate)
    with pytest.raises(InvalidScopeKeyError) as second:
        parse_scope_key(candidate)
    assert str(first.value) == str(second.value) == f"INVALID_SCOPE_KEY: {candidate!r}"


def test_reviewed_country_policy_fixtures_and_aliases() -> None:
    registry = load_country_crosswalk()

    ukraine = resolve_country(registry, source_system="gdelt-fips", source_code="UP")
    kosovo = resolve_country(
        registry,
        source_system="legacy-scope-key",
        source_code="country:XKX",
    )
    northern_cyprus = resolve_country(
        registry,
        source_system="natural-earth-admin0",
        source_code="N. Cyprus",
    )
    somaliland = resolve_country(
        registry,
        source_system="natural-earth-admin0",
        source_code="Somaliland",
    )
    antarctica = resolve_country(
        registry,
        source_system="natural-earth-admin0",
        source_code="010",
    )

    assert ukraine.scope_key == "country:UKR"
    assert kosovo.scope_key == "country:odin:kosovo"
    assert kosovo.canonical_iso3 is None
    assert northern_cyprus.disposition == "non_scope_feature"
    assert northern_cyprus.non_scope_reason == "disputed-territory-context"
    assert somaliland.scope_key == "country:odin:somaliland"
    assert somaliland.dispute_status == "disputed"
    assert antarctica.scope_key == "country:m49:010"
    assert antarctica.canonical_m49 == "010"


def test_xkx_is_legacy_alias_not_official_iso3_scope() -> None:
    registry = load_country_crosswalk()
    record = resolve_country(
        registry,
        source_system="legacy-scope-key",
        source_code="country:XKX",
    )
    assert record.scope_key == "country:odin:kosovo"
    assert all(item.code != "XKX" for item in record.aliases if item.code_system == "iso3")
    with pytest.raises(InvalidScopeKeyError):
        parse_scope_key("country:XKX")


def test_scope_key_cannot_be_generated_from_display_name() -> None:
    registry = load_country_crosswalk()
    with pytest.raises(CountryIdentityResolutionError, match="UNRESOLVED_COUNTRY_IDENTITY"):
        resolve_country(registry, source_system="display-name", source_code="Ukraine")


def test_crosswalk_rejects_duplicate_canonical_scope_keys() -> None:
    payload = json.loads(COUNTRY_CROSSWALK_PATH.read_text(encoding="utf-8"))
    duplicate = dict(payload["records"][0])
    duplicate["record_id"] = "natural-earth-admin0:duplicate"
    duplicate["source_code"] = "duplicate"
    payload["records"].append(duplicate)

    with pytest.raises(ValidationError, match="duplicate canonical scope key"):
        CountryCrosswalk.model_validate(payload)


def test_non_scope_admin0_feature_requires_reviewed_reason() -> None:
    payload = json.loads(COUNTRY_CROSSWALK_PATH.read_text(encoding="utf-8"))
    record = next(item for item in payload["records"] if item["source_code"] == "N. Cyprus")
    record["non_scope_reason"] = None

    with pytest.raises(ValidationError, match="non-scope feature requires a reviewed reason"):
        CountryCrosswalk.model_validate(payload)


def test_unresolved_admin0_crosswalk_fails_build() -> None:
    registry = load_country_crosswalk()
    with pytest.raises(CountryIdentityResolutionError, match="Unknown Island"):
        validate_natural_earth_coverage(
            registry,
            (("804", "Ukraine"), ("missing-feature", "Unknown Island")),
        )


def test_country_endonyms_topo_index_is_not_a_spatial_identity_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "country-endonyms.json":
            raise AssertionError("legacy _topoIndex must not be read")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    assert load_country_crosswalk().records


def test_country_almanac_and_spatial_catalog_share_one_crosswalk() -> None:
    from infra_atlas import build_country_almanac

    assert build_country_almanac.COUNTRY_CROSSWALK_PATH == COUNTRY_CROSSWALK_PATH
    assert not (
        Path(__file__).parents[1] / "infra_atlas" / "data" / "crosswalk.json"
    ).exists()
