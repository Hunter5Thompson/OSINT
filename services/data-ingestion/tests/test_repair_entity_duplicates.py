import pytest

from migrations.repair_entity_duplicates import merged_properties, validate_group


def test_entity_metadata_union_preserves_aliases_and_time_range():
    rows = [{"name": "F-35", "type": "AIRCRAFT", "aliases": ["a"],
             "first_seen": "2026-01-01", "last_seen": "2026-01-02", "confidence": .8},
            {"name": "F-35", "type": "AIRCRAFT", "aliases": ["a", "b"],
             "first_seen": "2026-01-03", "last_seen": "2026-01-04", "confidence": .9}]
    assert merged_properties(rows) == {"aliases": ["a", "b"],
                                      "first_seen": "2026-01-01",
                                      "last_seen": "2026-01-04", "confidence": .9}


def test_entity_merge_rejects_different_names_or_types():
    with pytest.raises(ValueError, match="identity"):
        validate_group([{"name": "x", "type": "PERSON"},
                        {"name": "x", "type": "ORGANIZATION"}])


def test_entity_merge_does_not_invent_missing_metadata():
    assert merged_properties([{"name": "x", "type": "PERSON"}] * 2) == {}
