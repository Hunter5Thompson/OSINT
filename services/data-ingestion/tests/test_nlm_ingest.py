from unittest.mock import AsyncMock

import httpx
import pytest

from nlm_ingest.ingest_neo4j import _build_statements, ingest_extraction
from nlm_ingest.relation_validator import validate_relations
from nlm_ingest.schemas import Claim, Entity, Extraction, Relation


def _make_extraction() -> Extraction:
    return Extraction(
        notebook_id="nb1",
        entities=[
            Entity(
                name="NATO", type="ORGANIZATION",
                aliases=["North Atlantic Treaty Organization"], confidence=0.95,
            ),
            Entity(name="China", type="COUNTRY", aliases=["PRC"], confidence=0.9),
        ],
        relations=[
            Relation(
                source="China", target="NATO", type="COMPETES_WITH",
                evidence="opposes expansion", confidence=0.75,
            ),
        ],
        claims=[
            Claim(
                statement="NATO expanded eastward", type="factual", polarity="neutral",
                entities_involved=["NATO"], confidence=0.95, temporal_scope="ongoing",
            ),
        ],
        extraction_model="qwen3.5",
        prompt_version="v1",
        source_kind="transcript",
        source_id="transcript",
    )

_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:7474/db/neo4j/tx/commit")

class TestEntityCanonicalizationNLM:
    """Curated alias canonicalization is applied consistently across the NLM
    write-path — entity upsert AND the name-based MATCHes (relations, claim
    links) — so canonicalizing a name never orphans its relationships.
    """

    def _entity_upserts(self, statements) -> list[dict]:
        return [
            s["parameters"]
            for s in statements
            if "MERGE (e:Entity" in s["statement"]
        ]

    def _params_for(self, statements, needle) -> list[dict]:
        return [s["parameters"] for s in statements if needle in s["statement"]]

    def _extraction(self, entities, relations=None, claims=None) -> Extraction:
        return Extraction(
            notebook_id="nb1",
            entities=entities,
            relations=relations or [],
            claims=claims or [],
            extraction_model="qwen3.5",
            prompt_version="v1",
            source_kind="transcript",
            source_id="transcript",
        )

    def test_curated_alias_canonicalized_in_entity_upsert(self):
        ex = self._extraction(
            [Entity(name="US Navy", type="ORGANIZATION", aliases=[], confidence=0.9)]
        )
        params = self._entity_upserts(_build_statements(ex, "RAND", []))
        assert params[0]["name"] == "U.S. Navy"
        assert params[0]["type"] == "MILITARY_UNIT"
        assert "US Navy" in params[0]["aliases"]

    def test_generic_name_not_folded(self):
        ex = self._extraction(
            [Entity(name="Navy", type="ORGANIZATION", aliases=[], confidence=0.9)]
        )
        params = self._entity_upserts(_build_statements(ex, "RAND", []))
        assert params[0]["name"] == "Navy"
        assert params[0]["type"] == "ORGANIZATION"

    def test_relation_endpoints_canonicalized_consistently(self):
        # Endpoint canonicalization now lives in the validator (it keys its
        # entity-type map by _canonical_name and emits already-canonicalized
        # endpoints). Verify the curated alias flows through to a canonical
        # relation's endpoints, else the downstream MATCH (name+type) fails.
        ex = self._extraction(
            entities=[
                Entity(name="US Navy", type="ORGANIZATION", aliases=[], confidence=0.9),
                Entity(name="USS Gerald R. Ford", type="VESSEL", aliases=[], confidence=0.9),
            ],
            relations=[
                Relation(
                    source="US Navy", target="USS Gerald R. Ford", type="OPERATES",
                    evidence="flagship", confidence=0.8,
                ),
            ],
        )
        res = validate_relations(ex)
        assert len(res.canonical) == 1, res.candidates
        c = res.canonical[0]
        # endpoint NAME must match the canonicalized entity node, else the MATCH
        # fails. (Endpoint TYPE is the declared extraction type, which the
        # validator keys its role check on — here ORGANIZATION, valid for OPERATES.)
        assert c.source == "U.S. Navy"
        assert c.source_type == "ORGANIZATION"
        assert c.target == "USS Gerald R. Ford"
        assert c.target_type == "VESSEL"

    def test_entity_upsert_preserves_existing_aliases(self):
        # UPSERT_ENTITY must append-dedup aliases, never overwrite — a later NLM
        # ingest with a smaller alias list must not delete aliases preserved by
        # the canonicalization cleanup or an earlier ingest.
        ex = self._extraction(
            [Entity(
                name="NATO", type="ORGANIZATION",
                aliases=["North Atlantic Treaty Organization"], confidence=0.9,
            )]
        )
        stmt = next(
            s for s in _build_statements(ex, "RAND", [])
            if "MERGE (e:Entity" in s["statement"]
        )
        assert "coalesce(e.aliases" in stmt["statement"]
        assert "SET e.aliases = $aliases" not in stmt["statement"]

    def test_claim_entity_link_canonicalized_consistently(self):
        ex = self._extraction(
            entities=[
                Entity(name="US Navy", type="ORGANIZATION", aliases=[], confidence=0.9)
            ],
            claims=[
                Claim(
                    statement="US Navy deployed", type="factual", polarity="neutral",
                    entities_involved=["US Navy"], confidence=0.9,
                    temporal_scope="ongoing",
                )
            ],
        )
        link = self._params_for(_build_statements(ex, "RAND", []), "MERGE (c)-[:INVOLVES]")[0]
        assert link["entity_name"] == "U.S. Navy"


class TestIngestExtraction:
    @pytest.mark.asyncio
    async def test_sends_cypher_statements(self):
        mock_response = httpx.Response(
            200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )
        assert client.post.called
        post_call = client.post.call_args
        assert "/db/neo4j/tx/commit" in post_call.args[0]

    @pytest.mark.asyncio
    async def test_batch_contains_source_entity_claim(self):
        mock_response = httpx.Response(
            200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )
        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        statements = payload["statements"]
        cypher_texts = [s["statement"] for s in statements]
        joined = " ".join(cypher_texts)
        assert "Source" in joined
        assert "Document" in joined
        assert "Entity" in joined
        assert "Claim" in joined

    @pytest.mark.asyncio
    async def test_source_tier_applied(self):
        mock_response = httpx.Response(
            200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        await ingest_extraction(
            extraction=_make_extraction(),
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
        )
        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        statements = payload["statements"]
        source_stmt = next(
            s for s in statements
            if "Source" in s["statement"] and "quality_tier" in s["statement"]
        )
        assert source_stmt["parameters"]["quality_tier"] == "tier_1"

    @pytest.mark.asyncio
    async def test_batch_contains_relation_statement(self):
        """Pre-validated canonical relations are persisted via canonical templates."""
        mock_response = httpx.Response(
            200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        extraction = _make_extraction()
        canonical = validate_relations(extraction).canonical
        assert len(canonical) == 1  # China<->NATO COMPETES_WITH validates

        await ingest_extraction(
            extraction=extraction,
            source_name="RAND",
            client=client,
            neo4j_url="http://localhost:7474",
            neo4j_user="neo4j",
            neo4j_password="odin_yggdrasil",
            canonical_relations=canonical,
        )
        payload = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        statements = payload["statements"]
        cypher_texts = [s["statement"] for s in statements]
        joined = " ".join(cypher_texts)
        assert "[r:COMPETES_WITH]" in joined

        rel_stmt = next(s for s in statements if "[r:COMPETES_WITH]" in s["statement"])
        assert rel_stmt["parameters"]["source"] == "China"
        assert rel_stmt["parameters"]["source_type"] == "COUNTRY"
        assert rel_stmt["parameters"]["target"] == "NATO"
        assert rel_stmt["parameters"]["target_type"] == "ORGANIZATION"
        assert rel_stmt["parameters"]["evidence"] == "opposes expansion"
        assert rel_stmt["parameters"]["confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_neo4j_error_raises_runtime_error(self):
        mock_response = httpx.Response(
            200,
            json={"results": [], "errors": [{"message": "constraint violation"}]},
            request=_DUMMY_REQUEST,
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        with pytest.raises(RuntimeError, match="constraint violation"):
            await ingest_extraction(
                extraction=_make_extraction(),
                source_name="RAND",
                client=client,
                neo4j_url="http://localhost:7474",
                neo4j_user="neo4j",
                neo4j_password="odin_yggdrasil",
            )


def _extraction(**kw):
    base = dict(
        notebook_id="nb1",
        entities=[],
        relations=[],
        claims=[
            Claim(
                statement="X happened",
                type="factual",
                polarity="positive",
                entities_involved=[],
                confidence=0.9,
                temporal_scope="2026",
            )
        ],
        extraction_model="qwen",
        prompt_version="v1",
        source_kind="report",
        source_id="rep-a",
    )
    base.update(kw)
    return Extraction(**base)


def test_link_claim_document_carries_provenance():
    stmts = _build_statements(_extraction(), "RAND", [])
    link = [s for s in stmts if "EXTRACTED_FROM" in s["statement"]][0]
    assert "$source_kind" in link["statement"] and "$source_id" in link["statement"]
    assert "{source_kind: $source_kind, source_id: $source_id}" in link["statement"]
    assert link["parameters"]["source_kind"] == "report"
    assert link["parameters"]["source_id"] == "rep-a"
