"""Tests for Cypher query templates and intent routing."""

import pytest

from agents.tools.graph_templates import (
    TEMPLATES,
    select_template,
    inject_limit,
    build_cypher_from_template,
)


class TestTemplateRegistry:
    def test_eight_templates_registered(self):
        assert len(TEMPLATES) == 8

    def test_all_templates_have_required_keys(self):
        for tid, t in TEMPLATES.items():
            assert "cypher" in t, f"{tid} missing cypher"
            assert "description" in t, f"{tid} missing description"
            assert "params" in t, f"{tid} missing params"

    def test_all_templates_are_readonly(self):
        from graph.read_queries import validate_cypher_readonly
        for tid, t in TEMPLATES.items():
            assert validate_cypher_readonly(t["cypher"]), f"{tid} failed readonly check"


class TestSelectTemplate:
    def test_entity_lookup_by_exact_match(self):
        result = select_template("entity_lookup", {"name": "PLA SSF"})
        assert result is not None
        cypher, params = result
        assert "$name" in cypher
        assert params["name"] == "PLA SSF"

    def test_unknown_template_returns_none(self):
        result = select_template("nonexistent_template", {})
        assert result is None

    def test_events_by_entity(self):
        result = select_template("events_by_entity", {"name": "Yaogan-44"})
        assert result is not None
        cypher, params = result
        assert "INVOLVES" in cypher
        assert params["name"] == "Yaogan-44"

    def test_top_connected_default_limit(self):
        result = select_template("top_connected", {})
        assert result is not None
        _, params = result
        assert params["limit"] == 20


class TestInjectLimit:
    def test_adds_limit_when_missing(self):
        cypher = "MATCH (n) RETURN n"
        assert "LIMIT 100" in inject_limit(cypher)

    def test_preserves_existing_limit(self):
        cypher = "MATCH (n) RETURN n LIMIT 50"
        result = inject_limit(cypher)
        assert "LIMIT 50" in result
        assert result.count("LIMIT") == 1

    def test_case_insensitive_detection(self):
        cypher = "MATCH (n) RETURN n limit 25"
        result = inject_limit(cypher)
        assert result.count("LIMIT") + result.count("limit") == 1


class TestBuildCypherFromTemplate:
    def test_entity_lookup_fills_params(self):
        cypher, params = build_cypher_from_template("entity_lookup", {"name": "NATO"})
        assert params["name"] == "NATO"
        assert "$name" in cypher

    def test_two_hop_network_has_limit(self):
        cypher, _ = build_cypher_from_template("two_hop_network", {"name": "Iran"})
        assert "LIMIT" in cypher

    def test_invalid_template_raises(self):
        with pytest.raises(KeyError):
            build_cypher_from_template("does_not_exist", {})
