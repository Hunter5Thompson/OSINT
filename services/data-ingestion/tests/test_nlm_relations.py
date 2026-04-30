"""Tests for NLM relation persistence in Neo4j.

Patch A of the codebook-graph-drift plan: ensure validated relations from
LLM extractions are written via deterministic Cypher templates.
"""
from __future__ import annotations

from typing import get_args
from unittest.mock import AsyncMock

import httpx
import pytest

from nlm_ingest.ingest_neo4j import _build_statements, ingest_extraction
from nlm_ingest.schemas import Claim, Entity, Extraction, Relation, RelationType
from nlm_ingest.write_templates import RELATION_TEMPLATES


def _make_extraction_with_relation() -> Extraction:
    return Extraction(
        notebook_id="nb-rel-1",
        entities=[
            Entity(name="China", type="COUNTRY", aliases=["PRC"], confidence=0.9),
            Entity(name="NATO", type="ORGANIZATION", aliases=[], confidence=0.95),
        ],
        relations=[
            Relation(
                source="China",
                target="NATO",
                type="COMPETES_WITH",
                evidence="opposes expansion",
                confidence=0.75,
            ),
        ],
        claims=[
            Claim(
                statement="NATO expanded eastward",
                type="factual",
                polarity="neutral",
                entities_involved=["NATO"],
                confidence=0.95,
                temporal_scope="ongoing",
            ),
        ],
        extraction_model="qwen3.5",
        prompt_version="v1",
    )


_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:7474/db/neo4j/tx/commit")


class TestRelationTemplates:
    def test_every_relation_type_has_template(self):
        """RELATION_TEMPLATES must cover every Literal in RelationType."""
        rel_types = set(get_args(RelationType))
        template_keys = set(RELATION_TEMPLATES.keys())
        assert rel_types == template_keys, (
            f"missing keys: {rel_types - template_keys}, "
            f"unexpected keys: {template_keys - rel_types}"
        )

    def test_relation_template_label_matches_key(self):
        """Each template hardcodes its relationship label matching its dict key."""
        for rel_type, template in RELATION_TEMPLATES.items():
            assert f"[r:{rel_type}]" in template, (
                f"template for {rel_type} must contain [r:{rel_type}]"
            )

    def test_templates_match_endpoints_no_merge_entity(self):
        """Endpoints must be MATCH-ed, never MERGE-d (avoid creating phantom entities)."""
        for rel_type, template in RELATION_TEMPLATES.items():
            assert "MATCH (source:Entity" in template, (
                f"{rel_type}: must MATCH source entity"
            )
            assert "MATCH (target:Entity" in template, (
                f"{rel_type}: must MATCH target entity"
            )
            assert "MERGE (source:Entity" not in template, (
                f"{rel_type}: must NOT MERGE source entity"
            )
            assert "MERGE (target:Entity" not in template, (
                f"{rel_type}: must NOT MERGE target entity"
            )

    def test_templates_use_parameter_binding(self):
        """All templates must reference $source, $target, $evidence, $confidence."""
        for rel_type, template in RELATION_TEMPLATES.items():
            for param in ("$source", "$target", "$evidence", "$confidence"):
                assert param in template, f"{rel_type}: missing {param} parameter"

    def test_templates_have_on_create_and_on_match(self):
        """Templates must use ON CREATE / ON MATCH SET semantics."""
        for rel_type, template in RELATION_TEMPLATES.items():
            assert "ON CREATE SET" in template, f"{rel_type}: missing ON CREATE SET"
            assert "ON MATCH SET" in template, f"{rel_type}: missing ON MATCH SET"

    def test_no_dynamic_label_construction(self):
        """No string interpolation / dynamic labels — labels must be hardcoded."""
        for rel_type, template in RELATION_TEMPLATES.items():
            assert "${" not in template, f"{rel_type}: no dynamic label allowed"
            assert "$type" not in template, (
                f"{rel_type}: relationship label must be hardcoded, not parameterised"
            )


class TestRelationsInBatch:
    def test_batch_contains_relation_statement(self):
        """When extraction has a relation, _build_statements emits the matching template."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(extraction, source_name="RAND")

        rel_statements = [
            s for s in statements if "[r:COMPETES_WITH]" in s["statement"]
        ]
        assert len(rel_statements) == 1
        params = rel_statements[0]["parameters"]
        assert params["source"] == "China"
        assert params["target"] == "NATO"
        assert params["evidence"] == "opposes expansion"
        assert params["confidence"] == 0.75

    def test_relation_statement_uses_template(self):
        """Emitted relation statement is exactly the template — no string mutation."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(extraction, source_name="RAND")

        rel_stmt = next(
            s for s in statements if "[r:COMPETES_WITH]" in s["statement"]
        )
        assert rel_stmt["statement"] == RELATION_TEMPLATES["COMPETES_WITH"]

    def test_entities_ordered_before_relations(self):
        """Entity upserts must precede relation statements so MATCH endpoints exist."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(extraction, source_name="RAND")

        entity_indices = [
            i for i, s in enumerate(statements)
            if "MERGE (e:Entity" in s["statement"]
        ]
        relation_indices = [
            i for i, s in enumerate(statements)
            if "[r:COMPETES_WITH]" in s["statement"]
        ]
        assert entity_indices, "expected at least one entity statement"
        assert relation_indices, "expected at least one relation statement"

        last_entity = max(entity_indices)
        first_relation = min(relation_indices)
        assert last_entity < first_relation, (
            f"entity upserts (last at {last_entity}) must come before "
            f"relation statements (first at {first_relation})"
        )

    def test_relations_ordered_before_claims(self):
        """Relations are inserted between step 4 (entities) and step 5 (claims)."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(extraction, source_name="RAND")

        relation_indices = [
            i for i, s in enumerate(statements)
            if "[r:COMPETES_WITH]" in s["statement"]
        ]
        claim_indices = [
            i for i, s in enumerate(statements)
            if "MERGE (c:Claim" in s["statement"]
        ]
        assert relation_indices and claim_indices
        assert max(relation_indices) < min(claim_indices)

    def test_no_relation_no_relation_statement(self):
        """When extraction.relations is empty, no relation statement is emitted."""
        extraction = _make_extraction_with_relation()
        extraction = extraction.model_copy(update={"relations": []})
        statements = _build_statements(extraction, source_name="RAND")

        for s in statements:
            assert "[r:COMPETES_WITH]" not in s["statement"]
            for rel_type in RELATION_TEMPLATES:
                assert f"[r:{rel_type}]" not in s["statement"]

    def test_unknown_relation_type_logged_and_skipped(self, monkeypatch):
        """Defensive: an unknown RelationType is skipped with a warning."""
        extraction = _make_extraction_with_relation()
        # Bypass pydantic validation by mutating after construction.
        bad_relation = extraction.relations[0].model_copy()
        object.__setattr__(bad_relation, "type", "UNKNOWN_REL")
        extraction = extraction.model_copy(update={"relations": [bad_relation]})

        warnings: list[tuple] = []

        class _Recorder:
            def warning(self, *args, **kwargs):
                warnings.append((args, kwargs))

            def info(self, *args, **kwargs):
                pass

        import nlm_ingest.ingest_neo4j as mod
        monkeypatch.setattr(mod, "log", _Recorder())

        statements = _build_statements(extraction, source_name="RAND")

        # No relation statement was emitted.
        for s in statements:
            for rel_type in RELATION_TEMPLATES:
                assert f"[r:{rel_type}]" not in s["statement"]
        assert warnings, "expected a warning for unknown relation type"


class TestIngestExtractionWithRelations:
    @pytest.mark.asyncio
    async def test_emitted_payload_contains_relation_statement(self):
        mock_response = httpx.Response(
            200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction_with_relation(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )

        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1]["json"]
        statements = payload["statements"]
        cypher_texts = [s["statement"] for s in statements]
        joined = " ".join(cypher_texts)
        assert "[r:COMPETES_WITH]" in joined
