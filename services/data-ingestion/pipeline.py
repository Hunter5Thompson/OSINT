"""Post-fetch intelligence extraction pipeline.

Called between feed-fetch and Qdrant-embed to:
1. Extract events + entities via vLLM
2. Write to Neo4j knowledge graph
3. Publish to Redis Stream for frontend live-updates
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml

from config import Settings

log = structlog.get_logger(__name__)


class ExtractionTransientError(Exception):
    """vLLM extraction failed transiently (timeout, connect-error, 5xx, JSON-parse).

    Caller MUST skip Qdrant upsert so the item is retried via source re-fetch.
    """


class ExtractionConfigError(Exception):
    """vLLM extraction failed due to misconfiguration (404 model, 401/403 auth).

    Caller MUST skip Qdrant upsert. Recovery requires fixing config — no auto-retry.
    """


# Load event types from the canonical codebook YAML (single source of truth)
_CODEBOOK_PATH = Path(__file__).parent.parent / "intelligence" / "codebook" / "event_codebook.yaml"


def _build_system_prompt() -> str:
    """Build system prompt from the codebook YAML. Falls back to minimal prompt if YAML missing."""
    type_lines = []
    try:
        with open(_CODEBOOK_PATH) as f:
            codebook = yaml.safe_load(f)
        for cat_data in codebook.get("categories", {}).values():
            for entry in cat_data.get("types", []):
                type_lines.append(f"   {entry['type']}: {entry['description']}")
    except (FileNotFoundError, yaml.YAMLError, KeyError) as e:
        log.warning("codebook_load_failed_using_fallback", error=str(e))
        type_lines = [
            "   military.airstrike, military.drone_attack, political.election,",
            "   space.satellite_launch, cyber.data_breach, other.unclassified",
        ]

    event_types_str = "\n".join(type_lines)
    return f"""\
You are an OSINT intelligence extraction specialist. Analyze the provided text and extract:

1. EVENTS: Classify events using these codebook types:
{event_types_str}
   If no type matches, use "other.unclassified".

2. ENTITIES: Extract named entities.
   Types: person, organization, location, weapon_system, satellite, vessel, aircraft, military_unit

3. LOCATIONS: Geographic locations with country.

RULES:
- Confidence: 0.0 to 1.0
- Severity: low, medium, high, critical
- Maximum 5 events and 20 entities per document
- Return valid JSON only"""


_SYSTEM_PROMPT = _build_system_prompt()

_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "codebook_type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "confidence": {"type": "number"},
                    "timestamp": {"type": "string"},
                },
                "required": ["title", "summary", "codebook_type", "severity", "confidence"],
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
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
                "additionalProperties": False,
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


async def process_item(
    title: str,
    text: str,
    url: str,
    source: str,
    *,
    settings: Settings,
    redis_client: Any | None = None,
) -> dict | None:
    """Extract intelligence from a feed item, write to Neo4j, publish to Redis.

    Returns enrichment dict with codebook_type/entities/events, or None on failure.
    Caller continues with Qdrant upsert regardless.
    """
    # Step 1: Call vLLM for extraction
    try:
        extraction = await _call_vllm(title, text, url, settings)
    except Exception as e:
        log.error("pipeline_extraction_failed", url=url, error=str(e))
        return None

    if extraction is None:
        return None

    events = extraction.get("events", [])
    entities = extraction.get("entities", [])
    locations = extraction.get("locations", [])

    # Step 2: Write to Neo4j
    if events or entities:
        try:
            await _write_to_neo4j(events, entities, url, title, source, settings)
        except Exception as e:
            log.error("pipeline_neo4j_failed", url=url, error=str(e))

    # Step 3: Publish to Redis Stream
    if redis_client and events:
        for event in events:
            try:
                await redis_client.xadd(
                    settings.redis_stream_events,
                    {
                        "title": event.get("title", ""),
                        "codebook_type": event.get("codebook_type", "other.unclassified"),
                        "severity": event.get("severity", "low"),
                        "source": source,
                        "url": url,
                    },
                )
            except Exception as e:
                log.warning("pipeline_redis_publish_failed", url=url, error=str(e))

    # Return enrichment for Qdrant payload
    primary_type = events[0]["codebook_type"] if events else "other.unclassified"
    return {
        "codebook_type": primary_type,
        "entities": [{"name": e["name"], "type": e["type"]} for e in entities],
        "events": events,
        "locations": locations,
    }


async def _call_vllm(title: str, text: str, url: str, settings: Settings) -> dict | None:
    """Call vLLM for intelligence extraction. Returns parsed dict or None."""
    payload = {
        "model": settings.vllm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Source: {url}\n\nText: {text[:4000]}"},
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

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.vllm_url}/v1/chat/completions",
            json=payload,
        )
        resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


async def _write_to_neo4j(
    events: list[dict],
    entities: list[dict],
    doc_url: str,
    doc_title: str,
    doc_source: str,
    settings: Settings,
) -> None:
    """Write extraction results to Neo4j via HTTP transactional API."""
    statements = []

    # Upsert Document
    statements.append({
        "statement": (
            "MERGE (d:Document {url: $url}) "
            "SET d.title = $title, d.source = $source, d.updated_at = datetime() "
        ),
        "parameters": {"url": doc_url, "title": doc_title, "source": doc_source},
    })

    # Upsert Entities with MENTIONS
    for entity in entities:
        statements.append({
            "statement": (
                "MERGE (e:Entity {name: $name, type: $type}) "
                "SET e.last_seen = datetime() "
                "WITH e "
                "MATCH (d:Document {url: $url}) "
                "MERGE (d)-[r:MENTIONS]->(e)"
            ),
            "parameters": {
                "name": entity["name"],
                "type": entity["type"],
                "url": doc_url,
            },
        })

    # Create Events
    for event in events:
        statements.append({
            "statement": (
                "CREATE (ev:Event {"
                "  title: $title, summary: $summary,"
                "  codebook_type: $codebook_type,"
                "  severity: $severity, confidence: $confidence"
                "}) "
                "WITH ev "
                "MATCH (d:Document {url: $url}) "
                "MERGE (d)-[:DESCRIBES]->(ev)"
            ),
            "parameters": {
                "title": event.get("title", ""),
                "summary": event.get("summary", ""),
                "codebook_type": event.get("codebook_type", "other.unclassified"),
                "severity": event.get("severity", "low"),
                "confidence": event.get("confidence", 0.5),
                "url": doc_url,
            },
        })

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{settings.neo4j_url}/db/neo4j/tx/commit",
            json={"statements": statements},
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        resp.raise_for_status()
        errors = resp.json().get("errors", [])
        if errors:
            log.warning("neo4j_write_errors", errors=errors)
