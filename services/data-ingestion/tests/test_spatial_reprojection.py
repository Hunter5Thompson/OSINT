from pathlib import Path

import pytest

from graph_integrity.spatial_normalizer import load_normalization_index
from spatial_reprojection import reproject_payload


@pytest.fixture(scope="module")
def index():
    return load_normalization_index(
        Path("../backend/data/spatial/catalogs/spatial-v1-a8e3a4af02d0"),
        crosswalk_path=Path("spatial_catalog/data/country_crosswalk.json"),
    )


def test_reprojection_recomputes_raw_evidence_and_revokes_conflicting_tokens(index):
    payload = {
        "source": "gdelt_gkg",
        "linked_event_ids": ["gdelt:event:1"],
        "spatial_occurrence_scope_revision_tokens": ["old-token"],
        "spatial_derivations": [
            {
                "relation": "occurrence",
                "evidence_kind": "structured_event_location",
                "evidence_id": "gdelt:event:1",
                "confidence": 1.0,
                "crosswalk_status": "not_required",
                "raw_location": {
                    "country_code": "IRQ",
                    "country_code_system": "iso3",
                    "latitude": 24.7136,
                    "longitude": 46.6753,
                },
            }
        ],
    }
    result = reproject_payload(payload, index)
    assert result["spatial_occurrence_scope_revision_tokens"] == []
    assert result["spatial_conflict"] is True
    assert result["spatial_catalog_revision"] == index.catalog_revision
    assert payload["spatial_occurrence_scope_revision_tokens"] == ["old-token"]


def test_reprojection_never_treats_old_tokens_as_source_evidence(index):
    result = reproject_payload(
        {"source": "gdelt_gkg", "spatial_occurrence_scope_revision_tokens": ["old-token"]}, index
    )
    assert result["spatial_occurrence_scope_revision_tokens"] == []
    assert result["spatial_derivation_status"] != "filterable"


def test_reprojection_supports_structured_legacy_points(index):
    result = reproject_payload(
        {"source": "usgs", "usgs_id": "one", "latitude": 33.3152, "longitude": 44.3661}, index
    )
    assert result["spatial_occurrence_scope_revision_tokens"]


@pytest.mark.parametrize("source", [[], {}, 12])
def test_malformed_source_is_audit_only_instead_of_crashing(index, source):
    result = reproject_payload({"source": source}, index)
    assert result["spatial_occurrence_scope_revision_tokens"] == []


def test_notebooklm_cannot_promote_occurrence_evidence(index):
    payload = {
        "source_type": "notebooklm",
        "spatial_derivations": [
            {
                "relation": "occurrence",
                "evidence_kind": "sensor_coordinate",
                "evidence_id": "one",
                "confidence": 1.0,
                "crosswalk_status": "not_required",
                "raw_location": {"latitude": 33.3152, "longitude": 44.3661},
            }
        ],
    }
    assert reproject_payload(payload, index)["spatial_occurrence_scope_revision_tokens"] == []
