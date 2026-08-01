from __future__ import annotations

import pytest

from spatial_catalog.identity import (
    InvalidScopeKeyError,
    normalize_scope_key_candidate,
    parse_scope_key,
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
