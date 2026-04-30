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
_FALLBACK_CODEBOOK_TYPE = "other.unclassified"


def _load_codebook_types() -> frozenset[str]:
    """Load valid codebook types from YAML. Returns at minimum the fallback type."""
    try:
        with open(_CODEBOOK_PATH) as f:
            codebook = yaml.safe_load(f)
        types = {
            entry["type"]
            for cat_data in codebook.get("categories", {}).values()
            for entry in cat_data.get("types", [])
        }
        if not types:
            log.warning("codebook_load_empty_using_fallback_only")
            return frozenset({_FALLBACK_CODEBOOK_TYPE})
        return frozenset(types)
    except (FileNotFoundError, yaml.YAMLError, KeyError) as e:
        log.warning("codebook_load_failed_using_fallback_only", error=str(e))
        return frozenset({_FALLBACK_CODEBOOK_TYPE})


_VALID_CODEBOOK_TYPES: frozenset[str] = _load_codebook_types()


def _validate_codebook_type(value: str | None, *, source: str | None = None, url: str | None = None) -> str:
    """Return value if it's a known codebook_type, else log + fall back to other.unclassified.

    LLMs occasionally hallucinate types that don't exist in event_codebook.yaml
    (e.g. 'attack.drone' instead of 'military.drone_attack'). Without this guard
    those bogus types reach Neo4j and Qdrant, where they corrupt facets and
    silently break frontend filtering.
    """
    if value and value in _VALID_CODEBOOK_TYPES:
        return value
    log.warning(
        "codebook_type_unknown_remapped",
        value=value,
        source=source,
        url=url,
        fallback=_FALLBACK_CODEBOOK_TYPE,
    )
    return _FALLBACK_CODEBOOK_TYPE


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
    # ExtractionTransientError / ExtractionConfigError propagate to caller (collector).
    extraction = await _call_vllm(title, text, url, settings)

    if extraction is None:
        return None

    events = extraction.get("events", [])
    entities = extraction.get("entities", [])
    locations = extraction.get("locations", [])

    # Runtime drift guard: an LLM that emits a codebook_type not in the canonical
    # YAML would otherwise corrupt Neo4j (rogue Event labels), Qdrant payloads
    # (broken facets), and the Redis stream the frontend listens on. Remap once,
    # in place — every downstream step then sees the validated value.
    for event in events:
        event["codebook_type"] = _validate_codebook_type(
            event.get("codebook_type"),
            source=source,
            url=url,
        )

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


async def _call_vllm(title: str, text: str, url: str, settings: Settings) -> dict:
    """Call vLLM for intelligence extraction.

    Returns parsed dict on success.
    Raises ExtractionTransientError for timeout/connect/5xx/JSON-parse failure.
    Raises ExtractionConfigError for 404/401/403 (model/auth misconfiguration).
    """
    payload = {
        "model": settings.ingestion_vllm_model,
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

    try:
        async with httpx.AsyncClient(timeout=settings.ingestion_vllm_timeout) as client:
            resp = await client.post(
                f"{settings.ingestion_vllm_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ExtractionTransientError(f"timeout: {exc}") from exc
    except httpx.ConnectError as exc:
        raise ExtractionTransientError(f"connect: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # Rev-6 (post-merge review): 400/405/422 are deterministic request/schema errors —
        # retrying won't fix an incompatible vLLM version or a malformed payload shape, so
        # they belong in ConfigError so operators stop the spin instead of looping forever.
        if status in (400, 401, 403, 404, 405, 422):
            raise ExtractionConfigError(f"http {status}: {exc}") from exc
        if 500 <= status < 600:
            raise ExtractionTransientError(f"http {status}: {exc}") from exc
        raise ExtractionTransientError(f"http {status}: {exc}") from exc

    try:
        data = resp.json()
        choice = data["choices"][0]
        # Rev-5 (Codex-Review): truncation must surface as an explicit transient error,
        # otherwise the JSON-decode failure below hides the root cause ("llm_truncated"
        # vs. cryptic "parse: Expecting ',' delimiter").
        if choice.get("finish_reason") == "length":
            raise ExtractionTransientError(
                f"llm_truncated: completion hit max_tokens={payload['max_tokens']}"
            )
        content = choice["message"]["content"]
        return json.loads(content)
    except ExtractionTransientError:
        raise  # Already the right class — don't re-wrap.
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        # Rev-6 (post-merge review): IndexError (empty choices array) and TypeError
        # (content is None, or non-subscriptable) are equally "transient: LLM returned
        # garbage shape"; wrapping them keeps _call_vllm's contract that only the two
        # typed errors escape, so collector try/except blocks behave uniformly.
        raise ExtractionTransientError(f"parse: {exc}") from exc


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
            f"{settings.neo4j_http_url}/db/neo4j/tx/commit",
            json={"statements": statements},
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        resp.raise_for_status()
        errors = resp.json().get("errors", [])
        if errors:
            log.warning("neo4j_write_errors", errors=errors)
