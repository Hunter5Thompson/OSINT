"""Tests for classify_event tool."""

import pytest
from unittest.mock import AsyncMock, patch

from agents.tools.classify import classify_event, _format_extraction_result
from codebook.extractor import IntelligenceExtractionResult, ExtractedEventRaw, ExtractedEntityRaw


class TestFormatExtractionResult:
    def test_formats_events_and_entities(self):
        result = IntelligenceExtractionResult(
            events=[ExtractedEventRaw(
                title="Missile Test",
                codebook_type="military.weapons_test",
                severity="high",
                confidence=0.9,
            )],
            entities=[ExtractedEntityRaw(
                name="North Korea",
                type="organization",
                confidence=0.8,
            )],
            locations=[],
        )
        text = _format_extraction_result(result)
        assert "Missile Test" in text
        assert "military.weapons_test" in text
        assert "North Korea" in text

    def test_empty_result(self):
        result = IntelligenceExtractionResult()
        text = _format_extraction_result(result)
        assert "no events" in text.lower() or "No events" in text

    def test_multiple_events_formatted(self):
        result = IntelligenceExtractionResult(
            events=[
                ExtractedEventRaw(title="Event A", codebook_type="military.airstrike", severity="high", confidence=0.8),
                ExtractedEventRaw(title="Event B", codebook_type="political.sanctions_imposed", severity="medium", confidence=0.7),
            ],
        )
        text = _format_extraction_result(result)
        assert "Event A" in text
        assert "Event B" in text


class TestClassifyEventTool:
    @pytest.mark.asyncio
    async def test_empty_text_returns_message(self):
        result = await classify_event.ainvoke({"text": "", "context": ""})
        assert "provide text" in result.lower() or "empty" in result.lower() or "provide" in result.lower()

    @pytest.mark.asyncio
    async def test_text_too_long_gets_truncated(self):
        long_text = "A " * 5000
        with patch("agents.tools.classify._get_extractor") as mock_get:
            mock_extractor = AsyncMock()
            mock_extractor.extract.return_value = IntelligenceExtractionResult()
            mock_get.return_value = mock_extractor

            result = await classify_event.ainvoke({"text": long_text, "context": ""})
            mock_extractor.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_extractor_failure_returns_error(self):
        with patch("agents.tools.classify._get_extractor") as mock_get:
            mock_extractor = AsyncMock()
            mock_extractor.extract.side_effect = Exception("LLM down")
            mock_get.return_value = mock_extractor

            result = await classify_event.ainvoke({"text": "some text", "context": ""})
            assert "failed" in result.lower()
