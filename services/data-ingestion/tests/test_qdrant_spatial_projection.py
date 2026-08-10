from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_integrity.spatial_normalizer import (
    CountryCodeSystem,
    RawLocationIdentity,
    SpatialNormalizationIndex,
    build_normalization_index,
    load_normalization_index,
    normalize_location,
)
from spatial_catalog.identity import load_country_crosswalk

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPOSITORY_ROOT / "contracts/qdrant-spatial-payload-v1.json"
LANE_CONTRACT_PATH = REPOSITORY_ROOT / "contracts/qdrant-spatial-writer-lanes-v1.json"
CATALOG_DIRECTORY = (
    REPOSITORY_ROOT
    / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799"
)
CROSSWALK_PATH = (
    REPOSITORY_ROOT
    / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
)


@pytest.fixture(scope="module")
def spatial_index() -> SpatialNormalizationIndex:
    return load_normalization_index(
        CATALOG_DIRECTORY,
        crosswalk_path=CROSSWALK_PATH,
    )


def _evidence(
    raw: RawLocationIdentity,
    spatial_index: SpatialNormalizationIndex,
    *,
    relation: str = "occurrence",
    kind: str = "structured_event_location",
    confidence: float = 1.0,
    crosswalk_status: str = "not_required",
    evidence_id: str = "evidence:1",
):
    from qdrant_spatial import SpatialEvidenceV1

    return SpatialEvidenceV1(
        relation=relation,
        evidence_kind=kind,
        evidence_id=evidence_id,
        normalization=normalize_location(raw, spatial_index),
        confidence=confidence,
        crosswalk_status=crosswalk_status,
    )


def test_occurrence_projection_matches_shared_parent_child_vector(
    spatial_index: SpatialNormalizationIndex,
) -> None:
    from qdrant_spatial import project_spatial_payload

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected = contract["vectors"][0]["payload"]
    payload = project_spatial_payload(
        [
            _evidence(
                RawLocationIdentity(latitude=48.0, longitude=37.8),
                spatial_index,
                evidence_id="gdelt:event:1",
            )
        ],
        spatial_index,
    )

    for field, value in expected.items():
        assert payload[field] == value
    assert "spatial_derivation_revision" not in payload
    assert all("world" not in token for token in payload[
        "spatial_occurrence_scope_revision_tokens"
    ])

    derivation = payload["spatial_derivations"][0]
    assert derivation["raw_location"] == {"latitude": 48.0, "longitude": 37.8}
    assert derivation["scope_assignments"] == [
        {
            "scope_key": "country:UKR",
            "derivation_revision": "spatial-derive-v1-d30efa07e141",
        },
        {
            "scope_key": "admin1:iso3166-2:UA-14",
            "derivation_revision": "spatial-derive-v1-4d1de888e0c7",
        },
    ]


def test_shared_contract_binds_token_limit_and_conflict_admission() -> None:
    from qdrant_spatial import MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract["scope_revision_token"]["maximum_ascii_bytes"] == (
        MAX_SCOPE_REVISION_TOKEN_ASCII_BYTES
    )
    assert contract["conflict_admission"] == {
        "retrieval_authority": "positive-pair-tokens",
        "suppression_granularity": "same-relation-and-exact-scope",
        "record_conflict_fields": "unindexed-audit-only",
        "mixed_status": "filterable-when-any-token-is-admitted",
    }


def test_about_gate_is_reviewed_exact_and_keeps_below_gate_audit(
    spatial_index: SpatialNormalizationIndex,
) -> None:
    from qdrant_spatial import ABOUT_CONFIDENCE_THRESHOLD, project_spatial_payload

    raw = RawLocationIdentity(
        country_code="UKR",
        country_code_system=CountryCodeSystem.ISO3,
        source_country_name="Ukraine",
    )
    accepted = _evidence(
        raw,
        spatial_index,
        relation="about",
        kind="extracted_geo_entity",
        confidence=ABOUT_CONFIDENCE_THRESHOLD,
        crosswalk_status="unique_reviewed",
        evidence_id="nlm:entity:Ukraine",
    )
    below_gate = _evidence(
        raw,
        spatial_index,
        relation="about",
        kind="extracted_geo_entity",
        confidence=ABOUT_CONFIDENCE_THRESHOLD - 0.01,
        crosswalk_status="unique_reviewed",
        evidence_id="nlm:entity:Ukraine-low",
    )
    occurrence = _evidence(
        RawLocationIdentity(latitude=48.0, longitude=37.8),
        spatial_index,
        evidence_id="gdelt:event:1",
    )

    payload = project_spatial_payload(
        [below_gate, occurrence, accepted],
        spatial_index,
    )

    assert payload["spatial_about_scope_revision_tokens"] == [
        "sr1|country:UKR|spatial-derive-v1-d30efa07e141"
    ]
    assert payload["spatial_occurrence_scope_revision_tokens"] == [
        "sr1|country:UKR|spatial-derive-v1-d30efa07e141",
        "sr1|admin1:iso3166-2:UA-14|spatial-derive-v1-4d1de888e0c7",
    ]
    assert payload["spatial_basis"] == ["coordinate", "source"]
    assert payload["source_country_code"] == ["UKR"]
    assert payload["source_country_code_system"] == ["iso3"]
    assert payload["country_iso3"] == ["UKR"]
    assert payload["admin1_code"] == ["UA-14"]
    assert payload["spatial_derivation_status"] == "filterable"
    assert [item["filter_reason"] for item in payload["spatial_derivations"]] == [
        "accepted",
        "accepted",
        "about_confidence_below_gate",
    ]


def test_conflict_is_audited_but_never_published_as_filterable(
    spatial_index: SpatialNormalizationIndex,
) -> None:
    from qdrant_spatial import project_spatial_payload

    conflicting = _evidence(
        RawLocationIdentity(
            country_code="UP",
            country_code_system=CountryCodeSystem.GDELT_GEC,
            latitude=37.0,
            longitude=-95.0,
        ),
        spatial_index,
    )

    payload = project_spatial_payload([conflicting], spatial_index)

    assert payload["spatial_about_scope_revision_tokens"] == []
    assert payload["spatial_occurrence_scope_revision_tokens"] == []
    assert payload["spatial_conflict"] is True
    assert payload["spatial_conflict_scope_keys"] == ["country:UKR", "country:USA"]
    assert payload["spatial_derivation_status"] == "conflict"
    assert payload["spatial_derivations"][0]["filter_reason"] == "spatial_conflict"
    assert "geo" not in payload


def test_conflict_preserves_independent_valid_relation_assignments(
    spatial_index: SpatialNormalizationIndex,
) -> None:
    from qdrant_spatial import project_spatial_payload

    valid_about = _evidence(
        RawLocationIdentity(
            country_code="UKR",
            country_code_system=CountryCodeSystem.ISO3,
        ),
        spatial_index,
        relation="about",
        kind="extracted_geo_entity",
        confidence=0.95,
        crosswalk_status="unique_reviewed",
        evidence_id="about:Ukraine",
    )
    conflicting_occurrence = _evidence(
        RawLocationIdentity(
            country_code="UP",
            country_code_system=CountryCodeSystem.GDELT_GEC,
            latitude=37.0,
            longitude=-95.0,
        ),
        spatial_index,
        evidence_id="occurrence:conflict",
    )

    payload = project_spatial_payload(
        [valid_about, conflicting_occurrence],
        spatial_index,
    )

    assert payload["spatial_about_scope_revision_tokens"] == [
        "sr1|country:UKR|spatial-derive-v1-d30efa07e141"
    ]
    assert payload["spatial_occurrence_scope_revision_tokens"] == []
    assert payload["spatial_conflict"] is True
    assert payload["spatial_derivation_status"] == "filterable"
    derivations = {
        item["evidence_id"]: item for item in payload["spatial_derivations"]
    }
    assert derivations["about:Ukraine"]["filter_reason"] == "accepted"
    assert derivations["about:Ukraine"]["filterable"] is True
    assert (
        derivations["occurrence:conflict"]["filter_reason"]
        == "spatial_conflict"
    )


def test_conflict_suppresses_only_the_same_relation_scope(
    spatial_index: SpatialNormalizationIndex,
) -> None:
    from qdrant_spatial import project_spatial_payload

    valid_occurrence = _evidence(
        RawLocationIdentity(
            country_code="UKR",
            country_code_system=CountryCodeSystem.ISO3,
        ),
        spatial_index,
        evidence_id="occurrence:Ukraine",
    )
    conflicting_occurrence = _evidence(
        RawLocationIdentity(
            country_code="UP",
            country_code_system=CountryCodeSystem.GDELT_GEC,
            latitude=37.0,
            longitude=-95.0,
        ),
        spatial_index,
        evidence_id="occurrence:conflict",
    )

    payload = project_spatial_payload(
        [valid_occurrence, conflicting_occurrence],
        spatial_index,
    )

    assert payload["spatial_occurrence_scope_revision_tokens"] == []
    assert payload["spatial_derivation_status"] == "conflict"
    derivations = {
        item["evidence_id"]: item for item in payload["spatial_derivations"]
    }
    admitted = derivations["occurrence:Ukraine"]
    assert admitted["filterable"] is False
    assert admitted["filter_reason"] == "relation_scope_conflict"
    assert admitted["published_scope_assignments"] == []
    assert admitted["withheld_conflict_scope_keys"] == ["country:UKR"]


def test_projection_revision_uses_derivations_not_catalog_revision() -> None:
    from qdrant_spatial import derive_spatial_projection_revision

    crosswalk = load_country_crosswalk(CROSSWALK_PATH)

    def index(catalog: str, derivation: str) -> SpatialNormalizationIndex:
        return build_normalization_index(
            catalog_revision=catalog,
            country_crosswalk=crosswalk,
            scope_parents={"country:UKR": None},
            scope_derivation_revisions={"country:UKR": derivation},
            containment={},
        )

    first = index("spatial-v1-111111111111", "spatial-derive-v1-111111111111")
    carry_forward = index(
        "spatial-v1-222222222222",
        "spatial-derive-v1-111111111111",
    )
    changed = index("spatial-v1-333333333333", "spatial-derive-v1-333333333333")

    assert derive_spatial_projection_revision(first) == (
        derive_spatial_projection_revision(carry_forward)
    )
    assert derive_spatial_projection_revision(first) != (
        derive_spatial_projection_revision(changed)
    )


def test_projection_rejects_pair_tokens_above_contract_byte_limit() -> None:
    from qdrant_spatial import SpatialProjectionError, project_spatial_payload

    oversized_revision = f"spatial-derive-v{'9' * 200}-{'a' * 12}"
    crosswalk = load_country_crosswalk(CROSSWALK_PATH)
    index = build_normalization_index(
        catalog_revision="spatial-v1-111111111111",
        country_crosswalk=crosswalk,
        scope_parents={"country:UKR": None},
        scope_derivation_revisions={"country:UKR": oversized_revision},
        containment={},
    )
    evidence = _evidence(
        RawLocationIdentity(
            country_code="UKR",
            country_code_system=CountryCodeSystem.ISO3,
        ),
        index,
    )

    with pytest.raises(SpatialProjectionError, match="229 ASCII bytes"):
        project_spatial_payload([evidence], index)


def test_unsupported_payload_is_explicit_and_has_no_filterable_keys() -> None:
    from qdrant_spatial import unavailable_spatial_payload

    payload = unavailable_spatial_payload("legacy region string is not evidence")

    assert payload["spatial_derivation_status"] == "unavailable"
    assert payload["spatial_derivation_unavailable_reason"] == (
        "legacy region string is not evidence"
    )
    assert payload["spatial_about_scope_revision_tokens"] == []
    assert payload["spatial_occurrence_scope_revision_tokens"] == []
    assert payload["spatial_derivations"] == []


def test_lane_inventory_keeps_scope_bounded_to_two_supported_writers() -> None:
    contract = json.loads(LANE_CONTRACT_PATH.read_text(encoding="utf-8"))

    assert [item["lane"] for item in contract["supported_writers"]] == [
        "gdelt_raw_gkg",
        "notebooklm_claim",
    ]
    assert {item["lane"] for item in contract["unavailable_writers"]} == {
        "intelligence_legacy_indexer",
        "legacy_feed_collectors",
        "suv_structured",
    }
