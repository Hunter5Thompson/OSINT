"""Post-fetch intelligence extraction pipeline.

Called between feed-fetch and Qdrant-embed to:
1. Extract events + entities via vLLM
2. Write to Neo4j knowledge graph
3. Publish to Redis Stream for frontend live-updates
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml

from canonicalize import canonicalize_entity
from config import Settings, settings
from graph_integrity.country_centroids import centroid_for, resolve_iso2
from graph_integrity.loc_key import centroid_key
from nlm_ingest.schemas import normalize_entity_type

log = structlog.get_logger(__name__)


def build_event_geo_fragment(country: str | None) -> dict | None:
    """Cypher FRAGMENT appended to an event-create statement where `ev` is
    already bound (after `MERGE (d)-[:DESCRIBES]->(ev)`). It does NOT re-MATCH
    the event — no node-id round-trip. Returns None when country is unknown."""
    iso2 = resolve_iso2(country)
    if iso2 is None:
        return None
    cc = centroid_for(iso2)
    if cc is None:
        return None
    lat, lon = cc
    return {
        "cypher": (
            " MERGE (l:Location {loc_key: $loc_key}) "
            "   ON CREATE SET l.lat = $lat, l.lon = $lon, "
            "                 l.geo_basis = $geo_basis, l.geo_precision = $geo_precision "
            " MERGE (ev)-[:OCCURRED_AT]->(l)"
        ),
        "parameters": {
            "loc_key": centroid_key(iso2), "lat": lat, "lon": lon,
            "geo_basis": "country_centroid", "geo_precision": "country",
        },
    }


def _normalize_iso(value: str | None) -> str | None:
    """Validate + normalize an ISO-8601 string to tz-aware UTC; None if invalid.

    A non-string (or empty) value drops to None — exactly like a malformed string —
    so a stray hint falls back to ingested_at instead of crashing the whole write.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _resolve_timeline(
    *, occurred_at: str | None, observed_at: str | None,
    published_at: str | None, ingested_at: str,
) -> tuple[str, str]:
    """Canonical timeline_at + time_basis by precedence. Never fabricates a time."""
    for value, basis in (
        (occurred_at, "occurred"),
        (observed_at, "observed"),
        (published_at, "published"),
    ):
        norm = _normalize_iso(value)
        if norm is not None:
            return norm, basis
    return ingested_at, "ingested"


class ExtractionTransientError(Exception):
    """vLLM extraction failed transiently (timeout, connect-error, 5xx, JSON-parse).

    Caller MUST skip Qdrant upsert so the item is retried via source re-fetch.
    """


class ExtractionConfigError(Exception):
    """vLLM extraction failed due to misconfiguration (404 model, 401/403 auth).

    Caller MUST skip Qdrant upsert. Recovery requires fixing config — no auto-retry.
    """


class Neo4jWriteError(Exception):
    """The Neo4j write failed — an httpx transport error, a non-JSON HTTP-200 body, a
    non-dict response body, or the tx/commit endpoint returning HTTP 200 with a non-empty
    errors[] (the Cypher/tx itself failed). Under raise_on_write_error=True, process_item
    also normalizes ANY other unexpected write failure into this type, so the T1 collectors
    handle every graph-write failure uniformly.

    process_item re-raises this to the caller only when raise_on_write_error=True, so a
    partial-success tick (graph failed, vector would still commit) can skip the Qdrant
    upsert and retry cleanly instead of orphaning a vector.
    """


class CodebookConfigError(RuntimeError):
    """Canonical event codebook is missing or invalid."""


# Load event types from the canonical codebook YAML (single source of truth)
_FALLBACK_CODEBOOK_TYPE = "other.unclassified"


def _load_codebook(path: Path) -> dict[str, Any]:
    """Load and validate the canonical event codebook."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise CodebookConfigError(f"cannot read event codebook {path}: {exc}") from exc
    if not text.strip():
        raise CodebookConfigError(f"event codebook is empty: {path}")

    try:
        codebook = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CodebookConfigError(f"invalid event codebook YAML {path}: {exc}") from exc

    if not isinstance(codebook, dict):
        raise CodebookConfigError(f"event codebook root must be a mapping: {path}")
    categories = codebook.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise CodebookConfigError(f"event codebook has no categories: {path}")

    type_count = 0
    for category_name, category in categories.items():
        if not isinstance(category, dict):
            raise CodebookConfigError(f"event codebook category {category_name!r} is not a mapping")
        entries = category.get("types")
        if not isinstance(entries, list):
            raise CodebookConfigError(
                f"event codebook category {category_name!r} has no types list"
            )
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("type"), str)
                or not entry["type"].strip()
                or not isinstance(entry.get("description"), str)
            ):
                raise CodebookConfigError(
                    f"event codebook category {category_name!r} contains an invalid type entry"
                )
            type_count += 1
    if type_count == 0:
        raise CodebookConfigError(f"event codebook has no types: {path}")
    return codebook


def _get_codebook_types(codebook: dict[str, Any]) -> frozenset[str]:
    """Return the validated type identifiers from a loaded codebook."""
    return frozenset(
        entry["type"]
        for category in codebook["categories"].values()
        for entry in category["types"]
    )


def _load_codebook_types(path: Path | None = None) -> frozenset[str]:
    """Load valid codebook types from the configured YAML file."""
    return _get_codebook_types(_load_codebook(path or settings.event_codebook_path))


def _validate_codebook_type(
    value: str | None, *, source: str | None = None, url: str | None = None
) -> str:
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


def _build_system_prompt(codebook: dict[str, Any]) -> str:
    """Build the extraction system prompt from a loaded codebook."""
    type_lines = [
        f"   {entry['type']}: {entry['description']}"
        for category in codebook["categories"].values()
        for entry in category["types"]
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


_CODEBOOK = _load_codebook(settings.event_codebook_path)
_VALID_CODEBOOK_TYPES: frozenset[str] = _get_codebook_types(_CODEBOOK)
_SYSTEM_PROMPT = _build_system_prompt(_CODEBOOK)

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


_EVENT_TITLE_MAXLEN = 200


def content_hash(title: str, url: str) -> str:
    """Canonical content hash shared by the Qdrant dedup point-id and the Event key,
    so the graph Event identity and the vector dedup identity share one root.
    MUST stay byte-identical to the value the collectors derive for their Qdrant point.
    """
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _normalize_event_title(title: str) -> str:
    """trim -> whitespace-collapse -> lowercase -> cap length, so minor LLM title
    variations do not fork a new Event under the MERGE key."""
    collapsed = re.sub(r"\s+", " ", title.strip()).lower()
    return collapsed[:_EVENT_TITLE_MAXLEN]


def _event_key(doc_content_hash: str, codebook_type: str, event_title: str) -> str:
    """Deterministic per-event identity for idempotent MERGE. One article can yield
    several events, so the doc hash alone is not unique — fold in codebook_type and
    the normalized event title."""
    raw = f"{doc_content_hash}|{codebook_type}|{_normalize_event_title(event_title)}"
    # 96 bits — ample for per-document event identity
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def process_item(
    title: str,
    text: str,
    url: str,
    source: str,
    *,
    settings: Settings,
    redis_client: Any | None = None,
    occurred_at: str | None = None,
    observed_at: str | None = None,
    published_at: str | None = None,
    content_hash: str | None = None,
    raise_on_write_error: bool = False,
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
        # ingested_at is the always-present honest fallback for the canonical
        # timeline anchor; structured collector time (occurred/observed/published)
        # takes precedence and we never fabricate an occurred_at from now().
        ingested_at = datetime.now(UTC).isoformat()
        try:
            await _write_to_neo4j(
                events, entities, url, title, source, settings,
                occurred_at=occurred_at, observed_at=observed_at,
                published_at=published_at, ingested_at=ingested_at,
                locations=locations, doc_content_hash=content_hash,
            )
        except Neo4jWriteError as e:
            log.error("pipeline_neo4j_failed", url=url, error=str(e))
            # T1 collectors pass raise_on_write_error=True so they can skip the Qdrant
            # upsert (no orphan vector, no phantom Redis event). Other callers keep the
            # historical swallow-and-continue behavior.
            if raise_on_write_error:
                raise
        except Exception as e:  # noqa: BLE001 — preserve resilience for non-T1 callers
            log.error("pipeline_neo4j_failed", url=url, error=str(e))
            if raise_on_write_error:
                # T1 contract: ANY graph-write failure must exit before Redis/Qdrant.
                # Normalize to Neo4jWriteError so the collectors' handler skips the point.
                raise Neo4jWriteError(f"unexpected neo4j write failure: {e}") from e

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
    *,
    occurred_at: str | None = None,
    observed_at: str | None = None,
    published_at: str | None = None,
    ingested_at: str | None = None,
    locations: list[dict] | None = None,
    doc_content_hash: str | None = None,
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
        # Canonicalize known aliases (e.g. "US Navy" -> "U.S. Navy" /
        # MILITARY_UNIT) BEFORE the write so the pipeline cannot regenerate the
        # duplicates the curated Neo4j merge removed. Unknown names pass through
        # unchanged. See canonicalize.py for the curated alias map and policy.
        canon = canonicalize_entity(entity["name"], entity["type"])
        entity_name = canon.name
        entity_type = canon.type
        # WP-04: canonicalise legacy lowercase entity-type emissions onto the
        # uppercase EntityType set so RSS and NLM writes converge on one
        # (name, type) node. Default ON (settings.entity_type_normalize, config.py);
        # set False to reproduce the pre-WP-04 lowercase-passthrough behaviour.
        if settings.entity_type_normalize:
            try:
                entity_type = normalize_entity_type(entity_type)
            except ValueError:
                log.warning(
                    "entity_type_unknown_passthrough",
                    value=entity["type"],
                    url=doc_url,
                    source=doc_source,
                    extraction_model=settings.ingestion_vllm_model,
                    entity_name=entity["name"],
                )
                # Fail-soft: pass through unchanged so a single bad LLM emission
                # does not block the whole document.
        statement = (
            "MERGE (e:Entity {name: $name, type: $type}) "
            "SET e.last_seen = datetime() "
        )
        parameters = {
            "name": entity_name,
            "type": entity_type,
            "url": doc_url,
        }
        # Preserve the original spelling as provenance only when we actually
        # rewrote the name — avoids stamping a redundant aliases list on the
        # entities whose name was left unchanged.
        if canon.aliases:
            statement += (
                "SET e.aliases = coalesce(e.aliases, []) + "
                "[a IN $aliases WHERE NOT a IN coalesce(e.aliases, [])] "
            )
            parameters["aliases"] = list(canon.aliases)
        statement += (
            "WITH e "
            "MATCH (d:Document {url: $url}) "
            "MERGE (d)-[r:MENTIONS]->(e)"
        )
        statements.append({"statement": statement, "parameters": parameters})

    # Create Events — stamp the canonical timeline anchor with honest precedence
    # (occurred -> observed -> published -> ingested). Structured collector time
    # beats the optional LLM 'timestamp' hint; a malformed hint is dropped, never
    # turned into a fabricated occurred_at.
    effective_ingested = ingested_at or datetime.now(UTC).isoformat()
    # Derive coarse document country for geo-tagging events (country-centroid).
    doc_country = next((loc["country"] for loc in (locations or []) if loc.get("country")), None)
    doc_hash = doc_content_hash or content_hash(doc_title, doc_url)
    for event in events:
        ev_occurred = occurred_at or event.get("timestamp")
        timeline_at, time_basis = _resolve_timeline(
            occurred_at=ev_occurred, observed_at=observed_at,
            published_at=published_at, ingested_at=effective_ingested,
        )
        ev_codebook_type = event.get("codebook_type", "other.unclassified")
        ev_key = _event_key(doc_hash, ev_codebook_type, event.get("title", ""))
        # event_key identifies the same event (doc hash + codebook_type + normalized title), so a
        # re-MERGE is the SAME event: freeze the create-time fields (ON CREATE SET) and only stamp
        # updated_at on re-match — do not overwrite with a later re-extraction.
        statements.append({
            "statement": (
                "MERGE (ev:Event {event_key: $event_key}) "
                "ON CREATE SET "
                "  ev.title = $title, ev.summary = $summary,"
                "  ev.codebook_type = $codebook_type,"
                "  ev.severity = $severity, ev.confidence = $confidence,"
                "  ev.timeline_at = datetime($timeline_at), ev.time_basis = $time_basis "
                "ON MATCH SET ev.updated_at = datetime() "
                "WITH ev "
                "MATCH (d:Document {url: $url}) "
                "MERGE (d)-[:DESCRIBES]->(ev)"
            ),
            "parameters": {
                "event_key": ev_key,
                "title": event.get("title", ""),
                "summary": event.get("summary", ""),
                "codebook_type": ev_codebook_type,
                "severity": event.get("severity", "low"),
                "confidence": event.get("confidence", 0.5),
                "timeline_at": timeline_at,
                "time_basis": time_basis,
                "url": doc_url,
            },
        })
        # Append country-centroid geo fragment to the event statement.
        # `ev` is still in scope from the preceding `MERGE (d)-[:DESCRIBES]->(ev)`.
        frag = build_event_geo_fragment(doc_country)
        if frag is not None:
            statements[-1]["statement"] += frag["cypher"]
            statements[-1]["parameters"].update(frag["parameters"])

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.neo4j_http_url}/db/neo4j/tx/commit",
                json={"statements": statements},
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        # Connect/timeout/5xx — the graph write did not land.
        raise Neo4jWriteError(f"neo4j http error: {exc}") from exc
    except ValueError as exc:
        # HTTP 200 with a non-JSON body (e.g. a proxy/error page) — treat as a write failure.
        raise Neo4jWriteError(f"neo4j non-json response: {exc}") from exc
    if not isinstance(body, dict):
        # HTTP 200 with valid JSON that isn't an object (null/array/scalar) — the
        # tx/commit contract is a {"results", "errors"} object; anything else means
        # the write outcome is unknown, so treat it as a failure (no silent .get()).
        raise Neo4jWriteError(f"neo4j non-dict response body: {type(body).__name__}")
    errors = body.get("errors", [])
    if errors:
        # The tx/commit endpoint returns HTTP 200 with a populated errors[] when the
        # Cypher/transaction itself failed. Must NOT be swallowed — it is a real failure.
        log.warning("neo4j_write_errors", errors=errors)
        raise Neo4jWriteError(f"neo4j tx errors: {errors}")
