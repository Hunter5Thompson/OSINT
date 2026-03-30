"""Neo4j schema whitelist for free Cypher generation.

Used in graph_query fallback mode — the LLM prompt includes these
so it only references labels/relationships/properties that exist.
"""

LABELS = ("Entity", "Event", "Source", "Location", "Document")

RELATIONSHIPS = ("INVOLVES", "REPORTED_BY", "OCCURRED_AT", "MENTIONS")

ENTITY_PROPERTIES = (
    "name", "type", "aliases", "confidence",
    "first_seen", "last_seen", "id",
)

EVENT_PROPERTIES = (
    "id", "title", "summary", "timestamp",
    "codebook_type", "severity", "confidence",
)

SOURCE_PROPERTIES = ("url", "name", "last_fetched")

LOCATION_PROPERTIES = ("name", "country", "lat", "lon")

DOCUMENT_PROPERTIES = ("url", "title", "source", "updated_at")


def schema_prompt_block() -> str:
    """Return a text block describing the Neo4j schema for LLM prompts."""
    return f"""\
Neo4j Schema:
  Node labels: {', '.join(LABELS)}
  Relationships: {', '.join(RELATIONSHIPS)}
  Entity properties: {', '.join(ENTITY_PROPERTIES)}
  Event properties: {', '.join(EVENT_PROPERTIES)}
  Source properties: {', '.join(SOURCE_PROPERTIES)}
  Location properties: {', '.join(LOCATION_PROPERTIES)}
  Document properties: {', '.join(DOCUMENT_PROPERTIES)}

Rules:
  - ONLY use labels, relationships, and properties listed above
  - Always include LIMIT (max 100)
  - No semicolons, no write operations
  - Use parameterized values ($param) for user-provided strings"""
