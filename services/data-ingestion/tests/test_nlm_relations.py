"""Tests for NLM relation persistence in Neo4j.

Patch A of the codebook-graph-drift plan: ensure validated relations from
LLM extractions are written via deterministic Cypher templates.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from nlm_ingest.ingest_neo4j import (
    _build_relation_statements,
    _build_statements,
    ingest_extraction,
)
from nlm_ingest.relation_validator import CanonicalRelation
from nlm_ingest.schemas import Claim, Entity, Extraction, Relation
from nlm_ingest.write_templates import CANONICAL_RELATION_TEMPLATES


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
    # Smoke A: COMPETES_WITH is now candidate_only, so the batch tests use a still-canonical
    # type. OPERATES with COUNTRY source (USA→Patriot) is canonical and direction-unambiguous.
    return Extraction(
        notebook_id="nb-rel-1",
        entities=[
            Entity(name="USA", type="COUNTRY", aliases=[], confidence=0.9),
            Entity(name="Patriot", type="WEAPON_SYSTEM", aliases=[], confidence=0.95),
        ],
        relations=[
            Relation(
                source="USA",
                target="Patriot",
                type="OPERATES",
                evidence="USA operates Patriot batteries",
                confidence=0.9,
            ),
        ],
        claims=[
            Claim(
                statement="USA deploys Patriot missile systems",
                type="factual",
                polarity="neutral",
                entities_involved=["USA"],
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



def _operates_canon() -> CanonicalRelation:
    """The USA->Patriot OPERATES edge matching _make_extraction_with_relation.
    Smoke A: re-pointed from COMPETES_WITH (now candidate_only) to the still-canonical
    OPERATES with a COUNTRY source — same assertion intent (template bijection + ordering)."""
    return _canon(
        rel_type="OPERATES",
        source="USA",
        source_type="COUNTRY",
        target="Patriot",
        target_type="WEAPON_SYSTEM",
        confidence=0.9,
        evidence="USA operates Patriot batteries",
        notebook_id="nb-rel-1",
        provenance_key="pk-operates",
        symmetric=False,
    )


class TestRelationsInBatch:
    def test_batch_contains_relation_statement(self):
        """A canonical relation passed in emits the matching canonical template."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_operates_canon()]
        )

        rel_statements = [
            s for s in statements if "[r:OPERATES]" in s["statement"]
        ]
        assert len(rel_statements) == 1
        params = rel_statements[0]["parameters"]
        assert params["source"] == "USA"
        assert params["source_type"] == "COUNTRY"
        assert params["target"] == "Patriot"
        assert params["target_type"] == "WEAPON_SYSTEM"
        assert params["evidence"] == "USA operates Patriot batteries"
        assert params["confidence"] == 0.9
        assert params["prov_key"] == "pk-operates"
        assert params["notebook_id"] == "nb-rel-1"

    def test_relation_statement_uses_template(self):
        """Emitted relation statement is exactly the canonical template — no mutation."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_operates_canon()]
        )

        rel_stmt = next(
            s for s in statements if "[r:OPERATES]" in s["statement"]
        )
        assert rel_stmt["statement"] == CANONICAL_RELATION_TEMPLATES["OPERATES"]

    def test_entities_ordered_before_relations(self):
        """Entity upserts must precede relation statements so MATCH endpoints exist."""
        extraction = _make_extraction_with_relation()
        statements = _build_statements(
            extraction, source_name="RAND", canonical_relations=[_operates_canon()]
        )

        entity_indices = [
            i for i, s in enumerate(statements)
            if "MERGE (e:Entity" in s["statement"]
        ]
        relation_indices = [
            i for i, s in enumerate(statements)
            if "[r:OPERATES]" in s["statement"]
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
            extraction, source_name="RAND", canonical_relations=[_operates_canon()]
        )

        relation_indices = [
            i for i, s in enumerate(statements)
            if "[r:OPERATES]" in s["statement"]
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
            assert "[r:OPERATES]" not in s["statement"]
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
            canonical_relations=[_operates_canon()],
        )

        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1]["json"]
        statements = payload["statements"]
        cypher_texts = [s["statement"] for s in statements]
        joined = " ".join(cypher_texts)
        assert "[r:OPERATES]" in joined
