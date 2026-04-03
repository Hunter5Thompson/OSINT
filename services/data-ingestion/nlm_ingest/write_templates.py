# notebooklm/write_templates.py
"""
Pinned Neo4j Cypher write templates for NotebookLM ingestion.

Stable templates from intelligence/graph/write_templates.py are copied here
because data-ingestion and intelligence have separate Docker build contexts.
NLM-specific templates (Claim, Source tier) are new.
"""

# --- Pinned from intelligence (stable) ---

UPSERT_ENTITY = """
MERGE (e:Entity {name: $name, type: $type})
ON CREATE SET e.first_seen = datetime()
SET e.aliases = $aliases,
    e.confidence = $confidence,
    e.last_seen = datetime()
"""

UPSERT_DOCUMENT = """
MERGE (d:Document {notebook_id: $notebook_id})
SET d.title = $title,
    d.source = $source,
    d.type = $type,
    d.updated_at = datetime()
"""

# --- NLM-specific ---

UPSERT_SOURCE_WITH_TIER = """
MERGE (s:Source {name: $source_name})
SET s.quality_tier = $quality_tier,
    s.updated_at = datetime()
"""

LINK_DOCUMENT_SOURCE = """
MATCH (d:Document {notebook_id: $notebook_id})
MATCH (s:Source {name: $source_name})
MERGE (d)-[:FROM_SOURCE]->(s)
"""

UPSERT_CLAIM = """
MERGE (c:Claim {statement_hash: $statement_hash})
ON CREATE SET
    c.statement = $statement,
    c.type = $type,
    c.polarity = $polarity,
    c.confidence = $confidence,
    c.temporal_scope = $temporal_scope,
    c.extracted_at = datetime(),
    c.extraction_model = $model,
    c.prompt_version = $prompt_version
ON MATCH SET
    c.confidence = CASE WHEN $confidence > c.confidence THEN $confidence ELSE c.confidence END,
    c.last_seen_at = datetime()
"""

LINK_CLAIM_DOCUMENT = """
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (d:Document {notebook_id: $notebook_id})
MERGE (c)-[:EXTRACTED_FROM]->(d)
"""

LINK_CLAIM_ENTITY = """
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (e:Entity {name: $entity_name})
MERGE (c)-[:INVOLVES]->(e)
"""

SOURCE_TIERS: dict[str, str] = {
    "RAND": "tier_1",
    "CSIS": "tier_1",
    "Brookings": "tier_1",
    "CNA": "tier_2",
    "IISS": "tier_2",
}


def get_source_tier(source_name: str) -> str:
    """Return quality tier for a source. Default: tier_3."""
    for key, tier in SOURCE_TIERS.items():
        if key.lower() in source_name.lower():
            return tier
    return "tier_3"
