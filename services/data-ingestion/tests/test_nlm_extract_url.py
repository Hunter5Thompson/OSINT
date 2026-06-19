"""Verify extract_with_qwen treats vllm_url as base URL without /v1."""

import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from nlm_ingest.extract import extract_with_qwen
from nlm_ingest.schemas import ExtractionSource


def _source():
    return ExtractionSource(
        notebook_id="nb1",
        source_id="transcript",
        source_kind="transcript",
        text="hello world",
    )


def _ok_resp():
    # extract_with_qwen parses entities/relations/claims (see extract.py:79-81).
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps({
        "entities": [], "relations": [], "claims": [],
    })}}]}
    return resp


@pytest.mark.asyncio
async def test_extract_appends_v1_chat_completions_to_base_url():
    """vllm_url is base URL (no /v1). Function appends /v1/chat/completions."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["url"] = url
        captured["model"] = json["model"]
        return _ok_resp()

    client = AsyncMock()
    client.post.side_effect = fake_post

    await extract_with_qwen(
        source=_source(),
        metadata={},
        client=client,
        vllm_url="http://192.168.178.39:8000",
        vllm_model="Qwen/Qwen3.6-35B-A3B",
    )

    assert captured["url"] == "http://192.168.178.39:8000/v1/chat/completions"
    assert not re.search(r"/v1/v1", captured["url"])
    assert captured["model"] == "Qwen/Qwen3.6-35B-A3B"


@pytest.mark.asyncio
async def test_extract_default_timeout_is_generous():
    """Default per-request timeout is 600s, not the old hardcoded 120s — the shared
    Spark can take ~160s under RSS concurrency, which 120s would ReadTimeout."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["timeout"] = kw.get("timeout")
        return _ok_resp()

    client = AsyncMock()
    client.post.side_effect = fake_post

    await extract_with_qwen(
        source=_source(), metadata={}, client=client,
        vllm_url="http://192.168.178.39:8000", vllm_model="m",
    )
    assert captured["timeout"] == 600.0


@pytest.mark.asyncio
async def test_extract_timeout_is_overridable():
    """Callers (the CLI) pass settings.nlm_ingestion_vllm_timeout; it must reach httpx."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["timeout"] = kw.get("timeout")
        return _ok_resp()

    client = AsyncMock()
    client.post.side_effect = fake_post

    await extract_with_qwen(
        source=_source(), metadata={}, client=client,
        vllm_url="http://192.168.178.39:8000", vllm_model="m", timeout=42.5,
    )
    assert captured["timeout"] == 42.5
