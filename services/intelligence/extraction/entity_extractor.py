"""
Entity Extractor — LLM-based NER via Qwen3.5-27B (vLLM).

Extracts Person, Organization, Country, Location, Facility,
Commodity, Event entities from OSINT text and writes them to Neo4j
via GraphClient.
"""

from __future__ import annotations

import json
from typing import Literal
import httpx
import structlog
from pydantic import BaseModel, Field

from graph.client import GraphClient
from graph.write_templates import UPSERT_DOCUMENT, UPSERT_ENTITY_WITH_MENTION

log = structlog.get_logger(__name__)

# ── Pydantic schema for structured LLM output ────────────────────────────────

VALID_ENTITY_TYPES = frozenset({
    "Person", "Organization", "Country", "Location",
    "Facility", "Commodity", "Event",
})

class ExtractedEntity(BaseModel):
    name: str = Field(description="Canonical name of the entity")
    type: Literal[
        "Person", "Organization", "Country", "Location",
        "Facility", "Commodity", "Event",
    ] = Field(description="Entity type (whitelisted)")
    mention: str = Field(description="Exact quote from the text that mentions this entity")
    context: str = Field(description="One sentence explaining the entity's role in this document")

class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)

# ── JSON Schema for vLLM response_format ─────────────────────────────────────

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":    {"type": "string"},
                    "type":    {"type": "string", "enum": ["Person", "Organization", "Country", "Location", "Facility", "Commodity", "Event"]},
                    "mention": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["name", "type", "mention", "context"],
            },
        }
    },
    "required": ["entities"],
}

_SYSTEM_PROMPT = """\
You are an OSINT entity extraction specialist. Extract named entities from the provided text.

Rules:
- Extract only entities explicitly mentioned in the text
- Use canonical names (e.g. "Vladimir Putin" not "Putin", "Russian Federation" not "Russia")
- Types: Person, Organization, Country, Location, Facility, Commodity, Event
- Commodity: oil, gas, wheat, rare earths, weapons systems, etc.
- Event: battles, treaties, elections, attacks, sanctions, etc.
- Skip generic terms, pronouns, and vague references
- Maximum 20 entities per document
- Return valid JSON only"""


class EntityExtractor:
    """Extract entities from text using Qwen3.5-27B via vLLM."""

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        vllm_model: str = "models/qwen3.5-27b-awq",
        graph_client: GraphClient | None = None,
    ) -> None:
        self.vllm_url = vllm_url
        self.vllm_model = vllm_model
        self._graph = graph_client

    # ── LLM extraction ────────────────────────────────────────────────────────

    async def extract(self, text: str, source_url: str = "", max_chars: int = 3000) -> ExtractionResult:
        """Extract entities from text using Qwen3.5-27B structured output."""
        truncated = text[:max_chars]

        payload = {
            "model": self.vllm_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract entities from this OSINT document:\n\n{truncated}"},
            ],
            "temperature": 0,
            "max_tokens": 1500,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction_result",
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
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                result = ExtractionResult(**data)
                log.info("extraction_complete", url=source_url, entity_count=len(result.entities))
                return result
        except Exception as e:
            log.warning("extraction_failed", url=source_url, error=str(e))
            return ExtractionResult(entities=[])

    # ── Neo4j write via GraphClient ───────────────────────────────────────────

    async def write_to_neo4j(
        self,
        result: ExtractionResult,
        doc_title: str,
        doc_url: str,
        doc_source: str = "rss",
    ) -> int:
        """Write extracted entities to Neo4j via GraphClient. Returns entity count."""
        if not result.entities or self._graph is None:
            return 0

        # Upsert Document node (deterministic template)
        await self._graph.run_query(
            UPSERT_DOCUMENT,
            {"url": doc_url, "title": doc_title, "source": doc_source},
        )

        # Upsert each Entity + MENTIONS relationship (deterministic template)
        for entity in result.entities:
            await self._graph.run_query(
                UPSERT_ENTITY_WITH_MENTION,
                {
                    "name": entity.name,
                    "type": entity.type,
                    "url": doc_url,
                    "mention": entity.mention,
                    "context": entity.context,
                },
            )

        log.info("neo4j_write_complete", url=doc_url, entities=len(result.entities))
        return len(result.entities)

    # ── Combined pipeline ─────────────────────────────────────────────────────

    async def extract_and_store(
        self,
        text: str,
        doc_title: str,
        doc_url: str,
        doc_source: str = "rss",
    ) -> ExtractionResult:
        """Extract entities from text and write to Neo4j in one call."""
        result = await self.extract(text, source_url=doc_url)
        await self.write_to_neo4j(result, doc_title, doc_url, doc_source)
        return result
