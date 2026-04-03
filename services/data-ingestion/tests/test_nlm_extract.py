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
from nlm_ingest.schemas import Extraction, Transcript, TranscriptSegment


def _make_transcript(text: str = "NATO expanded eastward. China opposes this.") -> Transcript:
    return Transcript(
        notebook_id="nb1",
        duration_seconds=60.0,
        language="en",
        segments=[TranscriptSegment(start=0.0, end=60.0, text=text)],
        full_text=text,
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
            transcript=_make_transcript(),
            metadata={"source_name": "RAND", "title": "Test Report"},
            client=client,
            vllm_url="http://localhost:8000/v1",
            vllm_model="qwen3.5",
        )
        assert extraction.notebook_id == "nb1"
        assert len(extraction.entities) == 2
        assert len(extraction.claims) == 2
        assert extraction.extraction_model == "qwen3.5"
        assert extraction.prompt_version == "v1"

    @pytest.mark.asyncio
    async def test_vllm_error_raises(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.side_effect = httpx.HTTPStatusError(
            "500", request=httpx.Request("POST", "http://x"), response=httpx.Response(500, request=httpx.Request("POST", "http://x"))
        )
        with pytest.raises(httpx.HTTPStatusError):
            await extract_with_qwen(
                transcript=_make_transcript(),
                metadata={"source_name": "X", "title": "Y"},
                client=client,
                vllm_url="http://localhost:8000/v1",
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
        )
        transcript = _make_transcript()

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.85}')]
        mock_client.messages.create.return_value = mock_message

        reviewed = await review_with_claude(
            extraction=extraction,
            transcript=transcript,
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
        )
        transcript = _make_transcript("word " * 40_000)

        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"verdict": "confirmed", "confidence": 0.8}')]
        mock_client.messages.create.return_value = mock_message

        await review_with_claude(
            extraction=extraction,
            transcript=transcript,
            claude_client=mock_client,
            claude_model="claude-sonnet-4-20250514",
        )
        call_count = mock_client.messages.create.call_count
        assert call_count < 200
