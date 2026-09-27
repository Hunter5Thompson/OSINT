"""Tests for Cypher query templates and intent routing."""

import pytest

from agents.tools.graph_templates import (
    SCOPED_TEMPLATES,
    TEMPLATES,
    build_cypher_from_template,
    inject_limit,
    select_scoped_template,
    select_template,
)
from spatial import ScopeKind


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

    @pytest.mark.parametrize("selector", [select_template, select_scoped_template])
    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(-1, 1), (0, 1), (1, 1), (100, 100), (101, 100), (10**9, 100)],
    )
    def test_limit_is_bounded_after_defaults_and_params_are_merged(
        self, selector, requested, expected
    ):
        if selector is select_template:
            result = selector("event_timeline", {"location": "Kyiv", "limit": requested})
        else:
            result = selector(
                "event_timeline",
                ScopeKind.COUNTRY,
                {"location": "Kyiv", "limit": requested},
            )

        assert result is not None
        _, params = result
        assert params["limit"] == expected

    @pytest.mark.parametrize("selector", [select_template, select_scoped_template])
    @pytest.mark.parametrize("requested", [True, "10", None])
    def test_non_integer_limit_is_rejected_after_merge(self, selector, requested):
        with pytest.raises((TypeError, ValueError)):
            if selector is select_template:
                selector("event_timeline", {"location": "Kyiv", "limit": requested})
            else:
                selector(
                    "event_timeline",
                    ScopeKind.COUNTRY,
                    {"location": "Kyiv", "limit": requested},
                )

    def test_every_global_and_scoped_template_uses_a_bounded_default(self):
        for template_id, template in TEMPLATES.items():
            if "$limit" in template["cypher"]:
                selected = select_template(template_id, {})
                assert selected is not None
                assert 1 <= selected[1]["limit"] <= 100

        for (template_id, scope_kind), template in SCOPED_TEMPLATES.items():
            if "$limit" in template["cypher"]:
                selected = select_scoped_template(template_id, scope_kind, {})
                assert selected is not None
                assert 1 <= selected[1]["limit"] <= 100


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


class TestTimestampCoalesce:
    def test_time_ordered_templates_coalesce_and_sort_on_alias(self):
        for tid in ("events_by_entity", "event_timeline", "source_backed"):
            cypher = TEMPLATES[tid]["cypher"]
            assert (
                "coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp"
                in cypher
            ), f"{tid} must return the coalesced timestamp"
            assert "ORDER BY timestamp DESC" in cypher, f"{tid} must sort on the alias"
            assert "ORDER BY ev.timestamp" not in cypher, f"{tid} must not sort on ev.timestamp"
