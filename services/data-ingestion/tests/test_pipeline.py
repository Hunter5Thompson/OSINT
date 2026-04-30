"""Tests for the intelligence extraction pipeline."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import structlog

from config import Settings
from pipeline import process_item


def _make_settings(**overrides) -> Settings:
    defaults = {
        "redis_url": "redis://localhost:6379/0",
        "qdrant_url": "http://localhost:6333",
        "tei_embed_url": "http://localhost:8001",
        "vllm_url": "http://localhost:8000",
        "vllm_model": "models/qwen3.5-27b-awq",
        "ingestion_vllm_url": "http://192.168.178.39:8000",
        "ingestion_vllm_model": "Qwen/Qwen3.6-35B-A3B",
        "ingestion_vllm_timeout": 120.0,
        "neo4j_url": "http://localhost:7474",
        "neo4j_http_url": "http://localhost:7474",
        "neo4j_user": "neo4j",
        "neo4j_password": "test",
        "redis_stream_events": "events:new",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def _mock_vllm_response(events=None, entities=None, locations=None):
    """Build mock httpx response for vLLM extraction call."""
    content = {
        "events": events or [],
        "entities": entities or [],
        "locations": locations or [],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(content)}}]
    }
    return mock_resp


def _mock_neo4j_response():
    """Build mock httpx response for Neo4j transactional API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": [], "errors": []}
    return mock_resp


class TestProcessItem:
    async def test_extracts_and_returns_enrichment(self):
        """process_item calls vLLM and returns enrichment metadata."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Drone strike",
                "summary": "Attack on port",
                "codebook_type": "military.drone_attack",
                "severity": "high",
                "confidence": 0.9,
                "timestamp": "2026-03-30T10:00:00Z",
            }],
            entities=[{"name": "NATO", "type": "organization", "confidence": 0.8}],
            locations=[{"name": "Odessa", "country": "Ukraine"}],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            # First call: vLLM, Second call: Neo4j
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await process_item(
                title="Drone strike on Odessa",
                text="Russian forces launched drone attack on Odessa port",
                url="http://example.com/article",
                source="rss",
                settings=_make_settings(),
            )

        assert result is not None
        assert result["codebook_type"] == "military.drone_attack"
        assert len(result["entities"]) >= 1
        # vLLM was called
        assert mock_client.post.call_count >= 1

    async def test_writes_to_neo4j(self):
        """process_item sends Cypher statements to Neo4j HTTP API."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Test event",
                "summary": "Test event summary",
                "codebook_type": "military.airstrike",
                "severity": "medium",
                "confidence": 0.7,
                "timestamp": "2026-01-01",
            }],
            entities=[{"name": "Test Entity", "type": "organization", "confidence": 0.6}],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_item(
                title="Test",
                text="Test text",
                url="http://test.com",
                source="rss",
                settings=_make_settings(),
            )

        # Second post call should be to Neo4j
        neo4j_call = mock_client.post.call_args_list[1]
        assert "/db/neo4j/tx/commit" in str(neo4j_call)

    async def test_neo4j_write_uses_http_url_when_driver_url_is_bolt(self):
        """The shared pipeline writes through Neo4j HTTP API, not the Bolt driver URI."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Test event",
                "summary": "Test event summary",
                "codebook_type": "military.airstrike",
                "severity": "medium",
                "confidence": 0.7,
                "timestamp": "2026-01-01",
            }],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_item(
                title="Test",
                text="Test text",
                url="http://test.com",
                source="rss",
                settings=_make_settings(
                    neo4j_url="bolt://neo4j:7687",
                    neo4j_http_url="http://neo4j:7474",
                ),
            )

        neo4j_call = mock_client.post.call_args_list[1]
        assert neo4j_call.args[0] == "http://neo4j:7474/db/neo4j/tx/commit"

    async def test_publishes_to_redis_stream(self):
        """process_item publishes events to Redis Stream."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Stream event",
                "summary": "Stream event summary",
                "codebook_type": "space.satellite_launch",
                "severity": "low",
                "confidence": 0.8,
                "timestamp": "2026-01-01",
            }],
        )
        neo4j_resp = _mock_neo4j_response()

        mock_redis = AsyncMock()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_item(
                title="Stream event",
                text="China launched satellite",
                url="http://test.com",
                source="rss",
                settings=_make_settings(),
                redis_client=mock_redis,
            )

        # Redis XADD should have been called
        mock_redis.xadd.assert_called()
        call_args = mock_redis.xadd.call_args
        assert call_args.args[0] == "events:new"

    async def test_raises_transient_on_vllm_failure(self):
        """If vLLM call fails transiently, process_item raises ExtractionTransientError."""
        from pipeline import ExtractionTransientError

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("down")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ExtractionTransientError):
                await process_item(
                    title="t", text="x", url="http://e/1", source="rss",
                    settings=_make_settings(),
                )

    async def test_no_events_still_returns_entities(self):
        """Even if no events classified, entities are still returned."""
        vllm_resp = _mock_vllm_response(
            events=[],
            entities=[{"name": "NATO", "type": "organization", "confidence": 0.8}],
        )

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = vllm_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await process_item(
                title="NATO meeting",
                text="NATO held discussions",
                url="http://test.com",
                source="rss",
                settings=_make_settings(),
            )

        assert result is not None
        assert len(result["entities"]) == 1


class TestEntityTypeNormalization:
    """Patch C Phase 5: default-OFF entity-type normalizer.

    Operator guardrail: when ``entity_type_normalize=False`` (the default)
    pipeline behaviour must be bit-for-bit identical to pre-Phase-5 main —
    the entity ``type`` field flows through unchanged.
    """

    def _extract_entity_param(self, mock_client) -> dict:
        """Pull the entity MERGE statement parameters out of the Neo4j call."""
        neo4j_call = mock_client.post.call_args_list[1]
        statements = neo4j_call.kwargs["json"]["statements"]
        # Statements: [Document MERGE, Entity MERGE..., Event CREATE...]
        # The entity statement is the one that contains "MERGE (e:Entity".
        for stmt in statements:
            if "MERGE (e:Entity" in stmt["statement"]:
                return stmt["parameters"]
        raise AssertionError("no Entity MERGE statement found")

    async def test_pipeline_passes_through_when_flag_off(self):
        """Flag OFF (default): vLLM 'organization' lands in Cypher unchanged.

        This is the bit-for-bit-identical guarantee — the legacy lowercase
        value must still reach Neo4j when the operator has not opted in.
        """
        vllm_resp = _mock_vllm_response(
            entities=[{"name": "NATO", "type": "organization", "confidence": 0.8}],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_item(
                title="t",
                text="x",
                url="http://example.com/a",
                source="rss",
                # Default flag value is False — pass nothing.
                settings=_make_settings(),
            )

        params = self._extract_entity_param(mock_client)
        assert params["type"] == "organization", (
            "flag-OFF must preserve the legacy lowercase value bit-for-bit"
        )
        assert params["name"] == "NATO"
        assert params["url"] == "http://example.com/a"

    async def test_pipeline_normalizes_when_flag_on(self):
        """Flag ON: legacy 'organization' is canonicalised to 'ORGANIZATION'."""
        vllm_resp = _mock_vllm_response(
            entities=[{"name": "NATO", "type": "organization", "confidence": 0.8}],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_item(
                title="t",
                text="x",
                url="http://example.com/b",
                source="rss",
                settings=_make_settings(entity_type_normalize=True),
            )

        params = self._extract_entity_param(mock_client)
        assert params["type"] == "ORGANIZATION"

    async def test_pipeline_unknown_entity_type_passes_through_with_flag_on(self):
        """Flag ON, unknown legacy value: pass-through + structlog warning.

        Fail-soft so a single bad LLM emission doesn't block the whole document.
        """
        vllm_resp = _mock_vllm_response(
            entities=[{"name": "Wraith", "type": "alien_species", "confidence": 0.4}],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with structlog.testing.capture_logs() as cap_logs:
                await process_item(
                    title="t",
                    text="x",
                    url="http://example.com/c",
                    source="rss",
                    settings=_make_settings(entity_type_normalize=True),
                )

        params = self._extract_entity_param(mock_client)
        assert params["type"] == "alien_species", "unknown values must pass through unchanged"

        warnings = [
            entry for entry in cap_logs
            if entry.get("log_level") == "warning"
            and entry.get("event") == "entity_type_unknown_passthrough"
        ]
        assert warnings, f"expected entity_type_unknown_passthrough warning, got: {cap_logs}"
        assert warnings[0].get("value") == "alien_species"


class TestPipelineCodebookBinding:
    """Verify system prompt is built from codebook YAML, not hardcoded."""

    def test_system_prompt_contains_codebook_types(self):
        from pipeline import _SYSTEM_PROMPT
        # These types are in event_codebook.yaml but would NOT be in a minimal hardcoded list
        assert (
            "military.ground_offensive" in _SYSTEM_PROMPT
            or "military.airstrike" in _SYSTEM_PROMPT
        )
        assert "space.satellite_launch" in _SYSTEM_PROMPT
        assert "other.unclassified" in _SYSTEM_PROMPT

    def test_system_prompt_has_many_types(self):
        from pipeline import _SYSTEM_PROMPT
        # The codebook has 65 types — the prompt should contain most of them
        # A hardcoded list would have ~18
        type_count = _SYSTEM_PROMPT.count(":")  # each "type: description" line has a colon
        assert type_count > 30, f"Prompt seems hardcoded, only {type_count} colons found"


class TestCollectorRedisIntegration:
    """Verify collectors pass redis_client through to process_item."""

    def test_rss_collector_accepts_redis_client(self):
        from unittest.mock import MagicMock
        mock_redis = MagicMock()
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="odin_intel")]
        )
        with patch("feeds.rss_collector.QdrantClient", return_value=mock_qdrant):
            from feeds.rss_collector import RSSCollector
            collector = RSSCollector(redis_client=mock_redis)
            assert collector._redis is mock_redis

    def test_gdelt_collector_accepts_redis_client(self):
        from unittest.mock import MagicMock
        mock_redis = MagicMock()
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="odin_intel")]
        )
        with patch("feeds.gdelt_collector.QdrantClient", return_value=mock_qdrant):
            from feeds.gdelt_collector import GDELTCollector
            collector = GDELTCollector(redis_client=mock_redis)
            assert collector._redis is mock_redis
