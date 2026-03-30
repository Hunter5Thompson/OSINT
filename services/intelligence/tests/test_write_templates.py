"""Tests for deterministic Cypher write templates."""

from graph.write_templates import (
    UPSERT_ENTITY,
    CREATE_EVENT,
    LINK_ENTITY_EVENT,
    LINK_EVENT_SOURCE,
    LINK_EVENT_LOCATION,
)


class TestTemplateStrings:
    def test_upsert_entity_merges_on_name_and_type(self):
        assert "MERGE (e:Entity {name: $name, type: $type})" in UPSERT_ENTITY

    def test_upsert_entity_sets_id_on_create(self):
        assert "ON CREATE SET" in UPSERT_ENTITY
        assert "e.id = $id" in UPSERT_ENTITY

    def test_upsert_entity_returns_id(self):
        assert "RETURN e.id" in UPSERT_ENTITY

    def test_create_event_uses_create_not_merge(self):
        assert "CREATE (ev:Event" in CREATE_EVENT
        assert "MERGE" not in CREATE_EVENT

    def test_create_event_returns_id(self):
        assert "RETURN ev.id" in CREATE_EVENT

    def test_link_entity_event_uses_involves(self):
        assert "[:INVOLVES]" in LINK_ENTITY_EVENT

    def test_link_event_source_uses_reported_by(self):
        assert "[:REPORTED_BY]" in LINK_EVENT_SOURCE

    def test_link_event_location_uses_occurred_at(self):
        assert "[:OCCURRED_AT]" in LINK_EVENT_LOCATION

    def test_all_templates_are_parameterized(self):
        for tmpl in [UPSERT_ENTITY, CREATE_EVENT, LINK_ENTITY_EVENT,
                     LINK_EVENT_SOURCE, LINK_EVENT_LOCATION]:
            assert "$" in tmpl, f"Template has no parameters: {tmpl[:60]}"

    def test_no_template_contains_f_string_markers(self):
        for tmpl in [UPSERT_ENTITY, CREATE_EVENT, LINK_ENTITY_EVENT,
                     LINK_EVENT_SOURCE, LINK_EVENT_LOCATION]:
            assert "{entity" not in tmpl
            assert "{event" not in tmpl
