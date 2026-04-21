"""Tests for pipeline error classes."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config import Settings
from pipeline import (
    ExtractionConfigError,
    ExtractionTransientError,
    process_item,
)


def test_extraction_transient_error_exists():
    from pipeline import ExtractionTransientError
    assert issubclass(ExtractionTransientError, Exception)


def test_extraction_config_error_exists():
    from pipeline import ExtractionConfigError
    assert issubclass(ExtractionConfigError, Exception)


def test_error_classes_are_distinct():
    from pipeline import ExtractionConfigError, ExtractionTransientError
    assert not issubclass(ExtractionTransientError, ExtractionConfigError)
    assert not issubclass(ExtractionConfigError, ExtractionTransientError)


def _settings(**overrides) -> Settings:
    base = {
        "redis_url": "redis://localhost:6379/0",
        "qdrant_url": "http://localhost:6333",
        "tei_embed_url": "http://localhost:8001",
        "vllm_url": "http://localhost:8000",
        "vllm_model": "legacy",
        "ingestion_vllm_url": "http://192.168.178.39:8000",
        "ingestion_vllm_model": "Qwen/Qwen3.6-35B-A3B",
        "ingestion_vllm_timeout": 120.0,
        "neo4j_url": "http://localhost:7474",
        "neo4j_user": "neo4j",
        "neo4j_password": "test",
        "redis_stream_events": "events:new",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _ok_resp():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({
            "events": [], "entities": [], "locations": []
        })}}]
    }
    return resp


@pytest.mark.asyncio
async def test_call_vllm_uses_spark_url_and_model():
    """_call_vllm posts to ingestion_vllm_url + /v1/chat/completions, never /v1/v1."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["url"] = url
        captured["model"] = json["model"]
        return _ok_resp()

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await process_item(
            title="t", text="x", url="http://e/1", source="rss",
            settings=_settings(),
        )

    assert captured["url"] == "http://192.168.178.39:8000/v1/chat/completions"
    assert not re.search(r"/v1/v1", captured["url"])
    assert captured["model"] == "Qwen/Qwen3.6-35B-A3B"


@pytest.mark.asyncio
async def test_call_vllm_enforces_json_schema_and_disables_thinking():
    """Rev-6: Qwen3.6 drifts field names + emits thinking-traces without these two guardrails.
    See spec §10. These must be in every _call_vllm payload."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["payload"] = json
        return _ok_resp()

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await process_item(
            title="t", text="x", url="http://e/1", source="rss",
            settings=_settings(),
        )

    rf = captured["payload"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    # Schema must at minimum require the three top-level arrays Pydantic downstream expects
    schema = rf["json_schema"]["schema"]
    assert set(schema["required"]) >= {"events", "entities", "locations"}
    # Qwen3.6 thinking-mode must be off
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_connect_error_raises_transient():
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_timeout_raises_transient():
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("slow")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_http_5xx_raises_transient():
    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=MagicMock(status_code=503)
    )
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 422])
async def test_http_4xx_raises_config(status):
    bad = MagicMock()
    bad.status_code = status
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=MagicMock(status_code=status)
    )
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionConfigError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_json_parse_error_raises_transient():
    """JSON parse failure after 200 OK → transient (not silent unclassified)."""
    bad = MagicMock()
    bad.status_code = 200
    bad.raise_for_status = MagicMock()
    bad.json.return_value = {"choices": [{"message": {"content": "not-json {{"}}]}

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_payload",
    [
        pytest.param({"choices": []}, id="empty_choices_array_IndexError"),
        pytest.param({"choices": [{"message": {"content": None}}]}, id="content_none_TypeError"),
        pytest.param({"choices": [{"message": None}]}, id="message_none_TypeError"),
    ],
)
async def test_unexpected_response_shape_raises_transient(malformed_payload):
    """Rev-6 (post-merge review): IndexError / TypeError on malformed 200 responses
    must surface as ExtractionTransientError, not leak out as uncaught engine errors
    that only ExtractionTransientError/ExtractionConfigError-catching collectors miss."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = malformed_payload

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError, match="parse:"):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_truncated_completion_raises_transient():
    """Rev-5 (Codex-Review edge case): finish_reason=='length' means the constrained-decoded JSON
    is almost certainly mid-object. Treat as ExtractionTransientError('llm_truncated') so the
    auditor sees it in logs, rather than a cryptic JSONDecodeError."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{
            "finish_reason": "length",
            "message": {"content": '{"events": [{"title": "trun'},  # cut mid-string
        }]
    }

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError, match="llm_truncated"):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )
