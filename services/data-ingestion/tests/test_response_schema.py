"""Verify _RESPONSE_SCHEMA is tight enough for constrained-decoding anti-drift."""

from pipeline import _RESPONSE_SCHEMA


def test_top_level_rejects_additional_properties():
    assert _RESPONSE_SCHEMA.get("additionalProperties") is False
    assert set(_RESPONSE_SCHEMA["required"]) == {"events", "entities", "locations"}


def test_event_object_rejects_extra_fields_and_requires_summary():
    event_obj = _RESPONSE_SCHEMA["properties"]["events"]["items"]
    assert event_obj.get("additionalProperties") is False
    # Qwen3.6 drifts "description" instead of "summary" — forcing it into required
    # + additionalProperties:false means the decoder rejects "description".
    assert "summary" in event_obj["required"]
    assert "title" in event_obj["required"]
    assert "codebook_type" in event_obj["required"]


def test_entity_object_rejects_extra_fields():
    entity_obj = _RESPONSE_SCHEMA["properties"]["entities"]["items"]
    assert entity_obj.get("additionalProperties") is False
    assert "name" in entity_obj["required"]
    assert "type" in entity_obj["required"]


def test_location_object_rejects_extra_fields():
    location_obj = _RESPONSE_SCHEMA["properties"]["locations"]["items"]
    assert location_obj.get("additionalProperties") is False
    assert "name" in location_obj["required"]
    assert "country" in location_obj["required"]
