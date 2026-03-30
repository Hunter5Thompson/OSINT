"""Combined event classifier + entity extractor. One LLM call, Pydantic-validated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import httpx
import structlog
from pydantic import BaseModel, Field

from codebook.loader import load_codebook, get_all_event_types, validate_codebook

log = structlog.get_logger(__name__)


# ── Pydantic models for structured LLM output ───────────────────────────────

class ExtractedEventRaw(BaseModel):
    title: str
    summary: str = ""
    codebook_type: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    timestamp: str = ""


class ExtractedEntityRaw(BaseModel):
    name: str
    type: Literal[
        "person", "organization", "location", "weapon_system",
        "satellite", "vessel", "aircraft", "military_unit",
    ]
    confidence: float = Field(ge=0, le=1, default=0.5)


class ExtractedLocationRaw(BaseModel):
    name: str
    country: str


class IntelligenceExtractionResult(BaseModel):
    events: list[ExtractedEventRaw] = Field(default_factory=list)
    entities: list[ExtractedEntityRaw] = Field(default_factory=list)
    locations: list[ExtractedLocationRaw] = Field(default_factory=list)


# ── Response schema for vLLM structured output ──────────────────────────────

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "codebook_type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "confidence": {"type": "number"},
                    "timestamp": {"type": "string"},
                },
                "required": ["title", "codebook_type", "severity", "confidence"],
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": [
                        "person", "organization", "location", "weapon_system",
                        "satellite", "vessel", "aircraft", "military_unit",
                    ]},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "type"],
            },
        },
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "country": {"type": "string"},
                },
                "required": ["name", "country"],
            },
        },
    },
    "required": ["events", "entities", "locations"],
}


class IntelligenceExtractor:
    """Combined event classifier + entity extractor.

    One LLM call → JSON with events, entities, locations → Pydantic-validated.
    Post-validation: unknown codebook_type → other.unclassified, low confidence filtered.
    """

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        vllm_model: str = "models/qwen3.5-27b-awq",
        codebook_path: Path | None = None,
        confidence_threshold: float = 0.3,
    ) -> None:
        self.vllm_url = vllm_url
        self.vllm_model = vllm_model
        self.confidence_threshold = confidence_threshold

        codebook = load_codebook(codebook_path)
        validate_codebook(codebook)
        self._valid_types = set(get_all_event_types(codebook))
        self._system_prompt = self._build_system_prompt(codebook)

    def _build_system_prompt(self, codebook: dict) -> str:
        """Build system prompt with all event types and entity types."""
        type_lines = []
        for cat_key, cat_data in codebook["categories"].items():
            for entry in cat_data["types"]:
                type_lines.append(f"  - {entry['type']}: {entry['description']}")

        event_types_str = "\n".join(type_lines)

        return f"""\
You are an OSINT intelligence extraction specialist. Analyze the provided text and extract:

1. EVENTS: Classify each event using the codebook types below.
2. ENTITIES: Extract all named entities (persons, organizations, locations, weapons, satellites, vessels, aircraft, military units).
3. LOCATIONS: Extract geographic locations with country.

EVENT CODEBOOK TYPES:
{event_types_str}

ENTITY TYPES: person, organization, location, weapon_system, satellite, vessel, aircraft, military_unit

RULES:
- Use exact codebook_type values from the list above
- If no event type matches, use "other.unclassified"
- Confidence: 0.0 to 1.0 (how certain you are)
- Severity: low, medium, high, critical
- Maximum 5 events and 20 entities per document
- Return valid JSON only"""

    async def extract(
        self,
        text: str,
        source_url: str = "",
        max_chars: int = 4000,
    ) -> IntelligenceExtractionResult:
        """Extract events, entities, and locations from text."""
        truncated = text[:max_chars]

        payload = {
            "model": self.vllm_model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": f"Source: {source_url}\n\nText: {truncated}"},
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "intelligence_extraction",
                    "schema": _RESPONSE_SCHEMA,
                    "strict": True,
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
        except httpx.HTTPError as e:
            log.error("intelligence_extraction_http_error", url=source_url, error=str(e))
            return IntelligenceExtractionResult()

        try:
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            result = IntelligenceExtractionResult.model_validate(data)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.error("intelligence_extraction_parse_error", url=source_url, error=str(e))
            return IntelligenceExtractionResult()
        except ValueError as e:
            log.error("intelligence_extraction_validation_error", url=source_url, error=str(e))
            return IntelligenceExtractionResult()

        # Post-validation: remap unknown codebook types
        for event in result.events:
            if event.codebook_type not in self._valid_types:
                event.codebook_type = "other.unclassified"

        # Filter low-confidence events
        result.events = [
            ev for ev in result.events
            if ev.confidence >= self.confidence_threshold
        ]

        log.info(
            "intelligence_extraction_complete",
            url=source_url,
            events=len(result.events),
            entities=len(result.entities),
            locations=len(result.locations),
        )
        return result
