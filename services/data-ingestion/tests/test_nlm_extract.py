import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nlm_ingest.extract import (
    extract_context,
    extract_with_qwen,
    load_prompt,
    review_with_claude,
)
from nlm_ingest.schemas import (
    Extraction,
    ExtractionSource,
)


def _make_source(text: str = "NATO expanded eastward. China opposes this.") -> ExtractionSource:
    return ExtractionSource(
        notebook_id="nb1",
        source_id="transcript",
        source_kind="transcript",
        text=text,
    )


_QWEN_RESPONSE = {
    "entities": [
        {"name": "NATO", "type": "ORGANIZATION", "aliases": [], "confidence": 0.95},
        {"name": "China", "type": "COUNTRY", "aliases": ["PRC"], "confidence": 0.9},
    ],
    "relations": [
        {
            "source": "China", "target": "NATO", "type": "COMPETES_WITH",
            "evidence": "China opposes this", "confidence": 0.75,
        },
    ],
    "claims": [
        {
            "statement": "NATO expanded eastward",
            "type": "factual", "polarity": "neutral",
            "entities_involved": ["NATO"],
            "confidence": 0.95, "temporal_scope": "ongoing",
        },
        {
            "statement": "China opposes NATO expansion",
            "type": "assessment", "polarity": "negative",
            "entities_involved": ["China", "NATO"],
            "confidence": 0.6, "temporal_scope": "ongoing",
        },
    ],
}


class TestLoadPrompt:
    def test_loads_v1(self):
        prompt = load_prompt("v1")
        assert "{source_name}" in prompt
        assert "{transcript_text}" in prompt

    def test_missing_version_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("v999")


class TestExtractWithQwen:
    @pytest.mark.asyncio
    async def test_returns_extraction(self):
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(_QWEN_RESPONSE)}}
                ]
            },
            request=httpx.Request("POST", "http://localhost:8000/v1/chat/completions"),
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = mock_response

        extraction = await extract_with_qwen(
            source=_make_source(),
            metadata={"source_name": "RAND", "title": "Test Report"},
            client=client,
            vllm_url="http://localhost:8000",
            vllm_model="qwen3.5",
        )
        assert extraction.notebook_id == "nb1"
        assert len(extraction.entities) == 2
        assert len(extraction.claims) == 2
        assert extraction.extraction_model == "qwen3.5"
        assert extraction.prompt_version == "v3"  # v3 is the default since the prompt PR

    @pytest.mark.asyncio
    async def test_vllm_error_raises(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        err_req = httpx.Request("POST", "http://x")
        client.post.side_effect = httpx.HTTPStatusError(
            "500", request=err_req, response=httpx.Response(500, request=err_req)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await extract_with_qwen(
                source=_make_source(),
                metadata={"source_name": "X", "title": "Y"},
                client=client,
                vllm_url="http://localhost:8000",
                vllm_model="qwen3.5",
            )


class TestExtractContext:
    def test_extracts_window(self):
        text = "A " * 500 + "TARGET " + "B " * 500
        window = extract_context(text, "TARGET", radius=50)
        assert "TARGET" in window
        assert len(window) < len(text)

    def test_short_text_returns_all(self):
        text = "short text"
        window = extract_context(text, "short", radius=500)
        assert window == text


class TestReviewWithClaude:
    @pytest.mark.asyncio
    async def test_upgrades_low_confidence(self):
        extraction = Extraction(
            notebook_id="nb1",
            entities=[],
            relations=[],
            claims=[
                {
                    "statement": "China opposes NATO expansion",
                    "type": "assessment", "polarity": "negative",
                    "entities_involved": ["China", "NATO"],
                    "confidence": 0.6, "temporal_scope": "ongoing",
                },
            ],
            extraction_model="qwen3.5",
            prompt_version="v1",
            source_kind="transcript",
            source_id="transcript",
        )
        source = _make_source()

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.85}')]
        mock_client.messages.create.return_value = mock_message

        reviewed = await review_with_claude(
            extraction=extraction,
            source=source,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        assert reviewed.claims[0].confidence == 0.85

    @pytest.mark.asyncio
    async def test_respects_budget(self):
        claims = [
            {
                "statement": f"Claim number {i} about geopolitics",
                "type": "assessment", "polarity": "neutral",
                "entities_involved": [], "confidence": 0.5,
                "temporal_scope": "ongoing",
            }
            for i in range(200)
        ]
        extraction = Extraction(
            notebook_id="nb1", entities=[], relations=[],
            claims=claims, extraction_model="qwen3.5", prompt_version="v1",
            source_kind="transcript", source_id="transcript",
        )
        source = _make_source("word " * 40_000)

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.8}')]
        mock_client.messages.create.return_value = mock_message

        await review_with_claude(
            extraction=extraction,
            source=source,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        call_count = mock_client.messages.create.call_count
        assert call_count < 200


_REQ = httpx.Request("POST", "http://x/v1/chat/completions")


@pytest.mark.asyncio
async def test_extract_with_qwen_sets_provenance():
    content = '{"entities": [], "relations": [], "claims": []}'
    body = {"choices": [{"message": {"content": content}}]}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(200, json=body, request=_REQ)

    source = ExtractionSource(
        notebook_id="nb1", source_id="rep-a", source_kind="report", text="report text"
    )
    result = await extract_with_qwen(
        source=source,
        metadata={"source_name": "RAND", "title": "T"},
        client=client,
        vllm_url="http://x",
        vllm_model="qwen",
    )
    assert result.source_kind == "report"
    assert result.source_id == "rep-a"
    assert result.notebook_id == "nb1"


def _sent_prompt(client) -> str:
    """The user-message content of the chat-completions payload the client received."""
    return client.post.call_args.kwargs["json"]["messages"][0]["content"]


def _ok_client():
    empty = '{"entities": [], "relations": [], "claims": []}'
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = httpx.Response(
        200, json={"choices": [{"message": {"content": empty}}]}, request=_REQ)
    return client


class TestPromptV3:
    def test_v3_loads_and_is_source_agnostic(self):
        prompt = load_prompt("v3")
        assert "{source_name}" in prompt
        assert "{source_text}" in prompt          # honest, source-agnostic placeholder
        assert "{source_hint}" in prompt           # dynamic source-kind hint slot
        assert "{transcript_text}" not in prompt   # old placeholder retired in v3
        # v3 is derived from v1, NOT v2 — must not carry v2's opt-in LOCATION entity type
        assert "LOCATION" not in prompt

    @pytest.mark.asyncio
    async def test_v3_is_default_version(self):
        client = _ok_client()
        result = await extract_with_qwen(
            source=_make_source(), metadata={"source_name": "RAND", "title": "T"},
            client=client, vllm_url="http://x", vllm_model="qwen")
        assert result.prompt_version == "v3"

    @pytest.mark.asyncio
    async def test_v3_injects_report_hint_and_text(self):
        client = _ok_client()
        source = ExtractionSource(notebook_id="nb1", source_id="rep-a",
                                  source_kind="report", text="REPORT BODY CONTENT")
        await extract_with_qwen(source=source, metadata={"source_name": "RAND", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen")
        prompt = _sent_prompt(client)
        assert "The following source is a written research report." in prompt
        assert "REPORT BODY CONTENT" in prompt
        for ph in ("{source_text}", "{source_hint}", "{source_name}", "{title}"):
            assert ph not in prompt                # every placeholder resolved

    @pytest.mark.asyncio
    async def test_v3_injects_transcript_hint(self):
        client = _ok_client()
        await extract_with_qwen(source=_make_source(text="PODCAST WORDS"),
                                metadata={"source_name": "RAND", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen")
        prompt = _sent_prompt(client)
        assert "The following source is a podcast transcript." in prompt
        assert "PODCAST WORDS" in prompt

    @pytest.mark.asyncio
    async def test_legacy_v1_still_injects_source_text(self):
        # Backward compat: v1 uses {transcript_text}; source.text must still land in the prompt
        # because extract.py replaces both {source_text} and {transcript_text}.
        client = _ok_client()
        await extract_with_qwen(source=_make_source(text="LEGACY V1 TEXT"),
                                metadata={"source_name": "RAND", "title": "T"},
                                client=client, vllm_url="http://x", vllm_model="qwen",
                                prompt_version="v1")
        prompt = _sent_prompt(client)
        assert "LEGACY V1 TEXT" in prompt
        assert "{transcript_text}" not in prompt
