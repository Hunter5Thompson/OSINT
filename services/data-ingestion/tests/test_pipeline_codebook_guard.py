"""Runtime drift guard: LLM-emitted codebook_type values are validated against
the canonical event_codebook.yaml before they reach Neo4j, Redis, or the
returned enrichment dict.

If the guard is wired correctly, an unknown codebook_type from the LLM is
remapped to "other.unclassified" everywhere downstream — the only safe
fallback that's guaranteed to exist in the codebook."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": [], "errors": []}
    return mock_resp


class TestCodebookDriftGuard:
    @pytest.mark.asyncio
    async def test_unknown_codebook_type_is_remapped_in_enrichment(self):
        """An LLM hallucination like 'nonsense.invalid' is replaced with
        'other.unclassified' in the returned enrichment dict (which feeds Qdrant)."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Suspicious event",
                "summary": "Vendor model went off-script",
                "codebook_type": "nonsense.invalid",
                "severity": "low",
                "confidence": 0.7,
                "timestamp": "2026-04-30T10:00:00Z",
            }],
            entities=[],
            locations=[],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await process_item(
                title="Suspicious event",
                text="Some unparseable content",
                url="http://example.com/1",
                source="rss",
                settings=_make_settings(),
            )

        assert result is not None
        assert result["codebook_type"] == "other.unclassified"
        assert result["events"][0]["codebook_type"] == "other.unclassified"

    @pytest.mark.asyncio
    async def test_unknown_codebook_type_is_remapped_in_neo4j_payload(self):
        """The Cypher CREATE for the Event node must carry the remapped type,
        not the LLM's bad output. Otherwise Neo4j accumulates ghost types."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Suspicious event",
                "summary": "x",
                "codebook_type": "nonsense.invalid",
                "severity": "low",
                "confidence": 0.7,
                "timestamp": "2026-04-30T10:00:00Z",
            }],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_item(
                title="Suspicious event",
                text="Some unparseable content",
                url="http://example.com/2",
                source="rss",
                settings=_make_settings(),
            )

        # The second post call is to Neo4j; inspect the JSON body
        neo4j_call = mock_client.post.call_args_list[1]
        body = neo4j_call.kwargs["json"]
        # Find the statement that creates the Event node
        event_statements = [s for s in body["statements"] if "CREATE (ev:Event" in s["statement"]]
        assert event_statements, "Expected an Event CREATE statement"
        for stmt in event_statements:
            assert stmt["parameters"]["codebook_type"] == "other.unclassified"
            assert "nonsense.invalid" not in str(stmt["parameters"])

    @pytest.mark.asyncio
    async def test_unknown_codebook_type_is_remapped_in_redis_payload(self):
        """The Redis xadd must publish 'other.unclassified', not the LLM's bad type."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Suspicious event",
                "summary": "x",
                "codebook_type": "nonsense.invalid",
                "severity": "low",
                "confidence": 0.7,
                "timestamp": "2026-04-30T10:00:00Z",
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
                title="Suspicious event",
                text="x",
                url="http://example.com/3",
                source="rss",
                settings=_make_settings(),
                redis_client=mock_redis,
            )

        mock_redis.xadd.assert_called()
        call = mock_redis.xadd.call_args
        # xadd("events:new", {fields...})
        fields = call.args[1] if len(call.args) > 1 else call.kwargs.get("fields", {})
        assert fields.get("codebook_type") == "other.unclassified"

    @pytest.mark.asyncio
    async def test_known_codebook_type_passes_through_unchanged(self):
        """Sanity: a valid type must NOT be rewritten — the guard is a fallback,
        not a clamp."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Drone strike",
                "summary": "x",
                "codebook_type": "military.drone_attack",
                "severity": "high",
                "confidence": 0.9,
                "timestamp": "2026-04-30T10:00:00Z",
            }],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await process_item(
                title="Drone strike",
                text="x",
                url="http://example.com/4",
                source="rss",
                settings=_make_settings(),
            )

        assert result["codebook_type"] == "military.drone_attack"

    @pytest.mark.asyncio
    async def test_new_civil_type_is_recognized(self):
        """Patch B added 'civil.protest' to the codebook — the guard must accept it."""
        vllm_resp = _mock_vllm_response(
            events=[{
                "title": "Mass protest",
                "summary": "x",
                "codebook_type": "civil.protest",
                "severity": "medium",
                "confidence": 0.8,
                "timestamp": "2026-04-30T10:00:00Z",
            }],
        )
        neo4j_resp = _mock_neo4j_response()

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [vllm_resp, neo4j_resp]
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await process_item(
                title="Mass protest",
                text="x",
                url="http://example.com/5",
                source="rss",
                settings=_make_settings(),
            )

        assert result["codebook_type"] == "civil.protest"
