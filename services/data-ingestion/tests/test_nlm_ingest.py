from unittest.mock import AsyncMock, call, patch, MagicMock

import pytest
import httpx

from notebooklm.ingest_neo4j import ingest_extraction
from notebooklm.schemas import Extraction, Entity, Relation, Claim


def _make_extraction() -> Extraction:
    return Extraction(
        notebook_id="nb1",
        entities=[
            Entity(name="NATO", type="ORGANIZATION", aliases=["North Atlantic Treaty Organization"], confidence=0.95),
            Entity(name="China", type="COUNTRY", aliases=["PRC"], confidence=0.9),
        ],
        relations=[
            Relation(source="China", target="NATO", type="COMPETES_WITH", evidence="opposes expansion", confidence=0.75),
        ],
        claims=[
            Claim(
                statement="NATO expanded eastward", type="factual", polarity="neutral",
                entities_involved=["NATO"], confidence=0.95, temporal_scope="ongoing",
            ),
        ],
        extraction_model="qwen3.5",
        prompt_version="v1",
    )

_DUMMY_REQUEST = httpx.Request("POST", "http://localhost:7474/db/neo4j/tx/commit")

class TestIngestExtraction:
    @pytest.mark.asyncio
    async def test_sends_cypher_statements(self):
        mock_response = httpx.Response(200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST)
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
        mock_response = httpx.Response(200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST)
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
        mock_response = httpx.Response(200, json={"results": [], "errors": []}, request=_DUMMY_REQUEST)
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
        source_stmt = next(s for s in statements if "Source" in s["statement"] and "quality_tier" in s["statement"])
        assert source_stmt["parameters"]["quality_tier"] == "tier_1"

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
