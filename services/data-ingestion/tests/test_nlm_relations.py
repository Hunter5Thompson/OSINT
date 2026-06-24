"""Tests for NLM relation persistence in Neo4j.

Patch A of the codebook-graph-drift plan: ensure validated relations from
LLM extractions are written via deterministic Cypher templates.
"""
from __future__ import annotations

from typing import get_args
from unittest.mock import AsyncMock

import httpx
import pytest

from nlm_ingest.ingest_neo4j import (
    _build_relation_statements,
    _build_statements,
    ingest_extraction,
)
from nlm_ingest.relation_validator import CanonicalRelation
from nlm_ingest.schemas import Claim, Entity, Extraction, Relation, RelationType
from nlm_ingest.write_templates import CANONICAL_RELATION_TEMPLATES, RELATION_TEMPLATES


def _canon(**kw) -> CanonicalRelation:
    base = dict(
        rel_type="OPERATES",
        source="USA",
        source_type="COUNTRY",
        target="Patriot",
        target_type="WEAPON_SYSTEM",
        confidence=0.9,
        evidence="ev",
        notebook_id="nb1",
        source_kind="transcript",
        source_id="transcript",
        prompt_version="v4",
        extraction_model="qwen",
        relation_hash="h",
        provenance_key="pk",
        symmetric=False,
    )
    base.update(kw)
    return CanonicalRelation(**base)


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
        source_kind="transcript",
        source_id="transcript",
    )


_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:7474/db/neo4j/tx/commit")


def test_build_relation_statements_binds_name_type_and_params():
    stmts = _build_relation_statements([_canon()])
    assert len(stmts) == 1
    s = stmts[0]
    assert "[r:OPERATES]" in s["statement"]
    assert s["parameters"]["source"] == "USA" and s["parameters"]["source_type"] == "COUNTRY"
    assert s["parameters"]["prov_key"] == "pk" and s["parameters"]["notebook_id"] == "nb1"


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


def _competes_canon() -> CanonicalRelation:
    """The China<->NATO COMPETES_WITH edge matching _make_extraction_with_relation,
    as the validator would emit it (symmetric sort keeps China first: C < N)."""
    return _canon(
        rel_type="COMPETES_WITH",
        source="China",
        source_type="COUNTRY",
        target="NATO",
        target_type="ORGANIZATION",
        confidence=0.75,
        evidence="opposes expansion",
        notebook_id="nb-rel-1",
        provenance_key="pk-competes",
        symmetric=True,
    )


class TestRelationsInBatch:
    def test_batch_contains_relation_statement(self):
        """A canonical relation passed in emits the matching canonical template."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_competes_canon()]
        )

        rel_statements = [
            s for s in statements if "[r:COMPETES_WITH]" in s["statement"]
        ]
        assert len(rel_statements) == 1
        params = rel_statements[0]["parameters"]
        assert params["source"] == "China"
        assert params["source_type"] == "COUNTRY"
        assert params["target"] == "NATO"
        assert params["target_type"] == "ORGANIZATION"
        assert params["evidence"] == "opposes expansion"
        assert params["confidence"] == 0.75
        assert params["prov_key"] == "pk-competes"
        assert params["notebook_id"] == "nb-rel-1"

    def test_relation_statement_uses_template(self):
        """Emitted relation statement is exactly the canonical template — no mutation."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_competes_canon()]
        )

        rel_stmt = next(
            s for s in statements if "[r:COMPETES_WITH]" in s["statement"]
        )
        assert rel_stmt["statement"] == CANONICAL_RELATION_TEMPLATES["COMPETES_WITH"]

    def test_entities_ordered_before_relations(self):
        """Entity upserts must precede relation statements so MATCH endpoints exist."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_competes_canon()]
        )

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
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_competes_canon()]
        )

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
        """When no canonical relations are passed, no relation statement is emitted."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[]
        )

        for s in statements:
            assert "[r:COMPETES_WITH]" not in s["statement"]
            for rel_type in CANONICAL_RELATION_TEMPLATES:
                assert f"[r:{rel_type}]" not in s["statement"]


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
            canonical_relations=[_competes_canon()],
        )

        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1]["json"]
        statements = payload["statements"]
        cypher_texts = [s["statement"] for s in statements]
        joined = " ".join(cypher_texts)
        assert "[r:COMPETES_WITH]" in joined
