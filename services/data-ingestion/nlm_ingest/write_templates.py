# notebooklm/write_templates.py
"""
Pinned Neo4j Cypher write templates for NotebookLM ingestion.

Stable templates from intelligence/graph/write_templates.py are copied here
because data-ingestion and intelligence have separate Docker build contexts.
NLM-specific templates (Claim, Source tier) are new.
"""

from nlm_ingest.relation_rules import RELATION_ROLE_RULES

# --- Pinned from intelligence (stable) ---

# Aliases are append-deduplicated (never overwritten) so a later ingest with a
# smaller alias list cannot delete aliases preserved by the canonicalization
# cleanup or an earlier ingest — matches the pipeline.py MENTIONS write path.
UPSERT_ENTITY = """
MERGE (e:Entity {name: $name, type: $type})
ON CREATE SET e.first_seen = datetime()
SET e.aliases = coalesce(e.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(e.aliases, [])],
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
MERGE (c)-[r:EXTRACTED_FROM {source_kind: $source_kind, source_id: $source_id}]->(d)
"""

LINK_CLAIM_ENTITY = """
MATCH (c:Claim {statement_hash: $statement_hash})
MATCH (e:Entity {name: $entity_name})
MERGE (c)-[:INVOLVES]->(e)
"""

# Scoped, idempotent backfill of legacy NLM EXTRACTED_FROM edges that predate
# source provenance. Scoped to Documents carrying a notebook_id (NLM-owned) and
# to edges still missing both properties, so it can never touch foreign edges
# and is safe to re-run. Parameter-bound; no literals on the write path.
BACKFILL_EXTRACTED_FROM = """
MATCH (:Claim)-[r:EXTRACTED_FROM]->(d:Document)
WHERE d.notebook_id IS NOT NULL
  AND r.source_kind IS NULL
  AND r.source_id IS NULL
SET r.source_kind = $source_kind, r.source_id = $source_id
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
    "OPERATES": """
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:OPERATES]->(target)
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

# --- Canonical relation templates (Relation v2 support-set) ---

def _canonical_relation_template(rel_type: str) -> str:
    # rel_type is a known RelationType literal (keys come from RELATION_ROLE_RULES),
    # never model output — safe to interpolate the label.
    return f"""
MATCH (s:Entity {{name:$source, type:$source_type}})
MATCH (t:Entity {{name:$target, type:$target_type}})
MERGE (s)-[r:{rel_type}]->(t)
ON CREATE SET r.first_seen=datetime(), r.last_seen=datetime(),
              r.confidence=$confidence, r.support_count=1,
              r.provenance_keys=[$prov_key], r.notebook_ids=[$notebook_id],
              r.evidence_samples=[$evidence]
ON MATCH SET  r.last_seen=datetime(),
              r.confidence = CASE WHEN $confidence > coalesce(r.confidence,0)
                                  THEN $confidence ELSE r.confidence END,
              r.provenance_keys = CASE WHEN NOT $prov_key IN coalesce(r.provenance_keys,[])
                                  THEN coalesce(r.provenance_keys,[]) + [$prov_key]
                                  ELSE r.provenance_keys END,
              r.notebook_ids = CASE WHEN NOT $notebook_id IN coalesce(r.notebook_ids,[])
                                  THEN coalesce(r.notebook_ids,[]) + [$notebook_id]
                                  ELSE r.notebook_ids END,
              r.evidence_samples = CASE WHEN size(coalesce(r.evidence_samples,[]))<5
                                   AND NOT $evidence IN coalesce(r.evidence_samples,[])
                                   THEN coalesce(r.evidence_samples,[]) + [$evidence]
                                   ELSE r.evidence_samples END
WITH r
SET r.support_count = size(coalesce(r.provenance_keys,[]))
""".strip()


CANONICAL_RELATION_TEMPLATES: dict[str, str] = {
    rt: _canonical_relation_template(rt)
    for rt, rule in RELATION_ROLE_RULES.items()
    if rule.mode == "canonical"
}
