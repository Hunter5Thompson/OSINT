"""Tests for event codebook loader and IntelligenceExtractor."""

import pytest
from codebook.loader import load_codebook, get_all_event_types, validate_codebook


class TestCodebookLoader:
    def test_codebook_loads_successfully(self):
        codebook = load_codebook()
        assert "version" in codebook
        assert "categories" in codebook

    def test_all_ten_categories_present(self):
        codebook = load_codebook()
        expected = {"military", "political", "economic", "space", "cyber",
                    "environmental", "social", "humanitarian", "infrastructure", "other"}
        assert set(codebook["categories"].keys()) == expected

    def test_minimum_fifty_event_types(self):
        codebook = load_codebook()
        all_types = get_all_event_types(codebook)
        assert len(all_types) >= 50, f"Only {len(all_types)} types, need >= 50"

    def test_all_types_use_dotted_notation(self):
        codebook = load_codebook()
        for t in get_all_event_types(codebook):
            assert "." in t, f"Type '{t}' missing dotted notation"

    def test_other_unclassified_exists(self):
        codebook = load_codebook()
        all_types = get_all_event_types(codebook)
        assert "other.unclassified" in all_types

    def test_validate_codebook_passes(self):
        codebook = load_codebook()
        validate_codebook(codebook)  # should not raise

    def test_validate_codebook_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_codebook({})


from unittest.mock import AsyncMock, patch, MagicMock
import json
from codebook.extractor import IntelligenceExtractor, IntelligenceExtractionResult


def _mock_vllm_response(content: dict) -> MagicMock:
    """Build a mock httpx Response matching vLLM chat completion format."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(content)}}]
    }
    return mock_resp


class TestIntelligenceExtractor:
    async def test_extract_military_event(self):
        mock_content = {
            "events": [{
                "title": "Drone strike on Odessa",
                "summary": "Russian forces launched drone attack",
                "codebook_type": "military.drone_attack",
                "severity": "high",
                "confidence": 0.9,
                "timestamp": "2026-03-30T10:00:00Z",
            }],
            "entities": [{
                "name": "Russian Armed Forces",
                "type": "organization",
                "confidence": 0.85,
            }],
            "locations": [{"name": "Odessa", "country": "Ukraine"}],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("Russian forces launched drone attack on Odessa port")

        assert len(result.events) == 1
        assert result.events[0].codebook_type.startswith("military.")
        assert len(result.entities) >= 1

    async def test_extract_space_event(self):
        mock_content = {
            "events": [{
                "title": "Yaogan-44 satellite launch",
                "summary": "China launched Yaogan-44 from Jiuquan",
                "codebook_type": "space.satellite_launch",
                "severity": "medium",
                "confidence": 0.95,
                "timestamp": "2026-03-28T02:00:00Z",
            }],
            "entities": [
                {"name": "Yaogan-44", "type": "satellite", "confidence": 0.9},
                {"name": "PLA Strategic Support Force", "type": "military_unit", "confidence": 0.8},
            ],
            "locations": [{"name": "Jiuquan", "country": "China"}],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("China launched Yaogan-44 from Jiuquan")

        assert result.events[0].codebook_type.startswith("space.")
        assert any(e.name == "Yaogan-44" for e in result.entities)

    async def test_extract_returns_valid_pydantic_model(self):
        mock_content = {
            "events": [{"title": "Test", "summary": "", "codebook_type": "military.airstrike",
                        "severity": "low", "confidence": 0.5, "timestamp": "2026-01-01T00:00:00Z"}],
            "entities": [{"name": "NATO", "type": "organization", "confidence": 0.7}],
            "locations": [],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("NATO conducted an airstrike")

        assert isinstance(result, IntelligenceExtractionResult)
        assert all(0 <= e.confidence <= 1 for e in result.entities)
        assert all(0 <= ev.confidence <= 1 for ev in result.events)

    async def test_unknown_event_defaults_to_other(self):
        mock_content = {
            "events": [{"title": "Unknown", "summary": "", "codebook_type": "nonsense.invalid",
                        "severity": "low", "confidence": 0.6, "timestamp": "2026-01-01T00:00:00Z"}],
            "entities": [],
            "locations": [],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor()
            result = await extractor.extract("Something unknown happened")

        assert result.events[0].codebook_type == "other.unclassified"

    async def test_confidence_below_threshold_filtered(self):
        mock_content = {
            "events": [
                {"title": "Weak", "summary": "", "codebook_type": "military.airstrike",
                 "severity": "low", "confidence": 0.1, "timestamp": "2026-01-01T00:00:00Z"},
                {"title": "Strong", "summary": "", "codebook_type": "military.airstrike",
                 "severity": "high", "confidence": 0.9, "timestamp": "2026-01-01T00:00:00Z"},
            ],
            "entities": [],
            "locations": [],
        }

        with patch("codebook.extractor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_vllm_response(mock_content)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            extractor = IntelligenceExtractor(confidence_threshold=0.3)
            result = await extractor.extract("Military activity reported")

        assert len(result.events) == 1
        assert result.events[0].title == "Strong"
