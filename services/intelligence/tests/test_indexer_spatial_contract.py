from __future__ import annotations


def test_legacy_region_is_preserved_but_marked_spatially_unavailable() -> None:
    from rag.indexer import build_document_payload

    payload = build_document_payload(
        title="Situation report",
        content="Ukraine and Donetsk are mentioned in prose.",
        source="legacy-test",
        region="Ukraine",
        hotspot_ids=[],
        published_at=None,
        chunk_index=0,
        total_chunks=1,
    )

    assert payload["region"] == "Ukraine"
    assert payload["spatial_derivation_status"] == "unavailable"
    assert payload["spatial_derivation_unavailable_reason"] == (
        "legacy region string is not reviewed spatial evidence"
    )
    assert payload["spatial_about_scope_revision_tokens"] == []
    assert payload["spatial_occurrence_scope_revision_tokens"] == []
    assert payload["spatial_derivations"] == []
