"""Tests for entity canonicalization — curated alias map + type-conflict resolution.

Mirrors the curated Neo4j entity-resolution policy ("Name != Identity"):
only national-qualified aliases collapse to a canonical (name, type); generic
names pass through unchanged. No fuzzy/semantic matching — behaviour is driven
solely by the explicit alias map.
"""

from __future__ import annotations

import pytest

from canonicalize import canonicalize_entity

# --- mapped US service families collapse to canonical name + MILITARY_UNIT ---


@pytest.mark.parametrize(
    "raw", ["U.S. Navy", "US Navy", "US navy", "United States Navy", "  us   navy "]
)
def test_us_navy_variants_canonicalize(raw):
    r = canonicalize_entity(raw, "organization")
    assert r.name == "U.S. Navy"
    assert r.type == "MILITARY_UNIT"


@pytest.mark.parametrize(
    "raw", ["U.S. Air Force", "US Air Force", "USAF", "United States Air Force"]
)
def test_us_air_force_variants_canonicalize(raw):
    r = canonicalize_entity(raw, "ORGANIZATION")
    assert r.name == "U.S. Air Force"
    assert r.type == "MILITARY_UNIT"


@pytest.mark.parametrize(
    "raw",
    ["DC National Guard", "D.C. National Guard", "District of Columbia National Guard"],
)
def test_dc_national_guard_short_forms_canonicalize(raw):
    # The cleanup consolidated DC National Guard; the extractor commonly emits
    # the short forms, which must resolve to the same canonical node.
    r = canonicalize_entity(raw, "organization")
    assert r.name == "District of Columbia National Guard"
    assert r.type == "MILITARY_UNIT"


def test_type_conflict_resolves_to_military_unit_for_known_alias():
    # The same alias arriving typed as ORGANIZATION or MILITARY_UNIT must yield
    # one canonical (name, type) — this is the ORG<->MILITARY_UNIT resolution.
    org = canonicalize_entity("US Army", "organization")
    mil = canonicalize_entity("U.S. Army", "military_unit")
    assert (org.name, org.type) == ("U.S. Army", "MILITARY_UNIT")
    assert (mil.name, mil.type) == ("U.S. Army", "MILITARY_UNIT")


# --- generic names are NOT folded (Name != Identity) ---


def test_generic_navy_is_not_folded_into_us_navy():
    r = canonicalize_entity("Navy", "organization")
    assert r.name == "Navy"
    assert r.type == "organization"  # unchanged: not a curated alias


def test_unknown_name_passes_through_unchanged():
    r = canonicalize_entity("Hezbollah Brigades", "organization")
    assert r.name == "Hezbollah Brigades"
    assert r.type == "organization"
    assert r.aliases == ()


# --- behaviour driven by the explicit map only (no fuzzy matching) ---


def test_irgc_acronym_canonicalizes_only_via_explicit_map():
    r = canonicalize_entity("IRGC", "organization")
    assert r.name == "IRGC"
    assert r.type == "MILITARY_UNIT"


def test_irgc_full_name_kept_separate_from_acronym():
    # Curated DB policy kept these distinct (Tier-2 alias, decided separately):
    # the full name must NOT auto-collapse into the IRGC acronym node.
    r = canonicalize_entity("Islamic Revolutionary Guard Corps", "organization")
    assert r.name == "Islamic Revolutionary Guard Corps"
    assert r.type == "MILITARY_UNIT"


# --- provenance: original name preserved as alias ---


def test_raw_name_preserved_as_alias():
    r = canonicalize_entity("USAF", "ORGANIZATION")
    assert r.raw_name == "USAF"
    assert r.raw_type == "ORGANIZATION"
    assert "USAF" in r.aliases
    assert "U.S. Air Force" in r.aliases


def test_novel_spelling_of_known_alias_is_kept_in_aliases():
    # A US/U.S. spelling normalises onto the canonical; the exact raw spelling
    # is still retained for provenance.
    r = canonicalize_entity("US navy", "organization")
    assert r.name == "U.S. Navy"
    assert "US navy" in r.aliases


def test_whitespace_is_trimmed_for_unmapped_names():
    r = canonicalize_entity("  Wagner Group  ", "organization")
    assert r.name == "Wagner Group"


# --- invariant: every canonical name canonicalizes to itself (idempotent) ---


@pytest.mark.parametrize(
    "canon",
    [
        "U.S. Navy",
        "U.S. Air Force",
        "U.S. Army",
        "U.S. Marine Corps",
        "IRGC",
        "French Navy",
        "Royal Navy",
        "People's Liberation Army",
        "Iran’s Navy",
        "Chinese Coast Guard",
    ],
)
def test_canonical_names_are_idempotent(canon):
    r = canonicalize_entity(canon, "MILITARY_UNIT")
    assert r.name == canon
