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


# --- Relation templates ---
#
# One deterministic Cypher template per RelationType.  Endpoints are MATCH-ed
# (never MERGE-d) so phantom entities can never be created on the write path —
# the entity upsert step must run first in the same batch / transaction.
# Relationship labels are hardcoded; never construct labels dynamically from
# untrusted input.

RELATION_TEMPLATES: dict[str, str] = {
    "ALLIED_WITH": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:ALLIED_WITH]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "COMMANDS": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:COMMANDS]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "COMPETES_WITH": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:COMPETES_WITH]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "MEMBER_OF": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:MEMBER_OF]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "NEGOTIATES_WITH": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:NEGOTIATES_WITH]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "OPERATES_IN": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:OPERATES_IN]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "SANCTIONS": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:SANCTIONS]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "SUPPLIES_TO": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:SUPPLIES_TO]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
    "TARGETS": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:TARGETS]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
""",
}
