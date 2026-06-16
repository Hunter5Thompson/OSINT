"""Deterministic Cypher for SUV structured ingestion.

Kept SEPARATE from nlm_ingest/write_templates.py:RELATION_TEMPLATES — that dict is
key-locked to nlm_ingest.schemas.RelationType by tests/test_nlm_relations.py. SUV
adds HEADQUARTERED_IN without touching the NLM RelationType contract.

Rules (Two-Loop write path): no LLM-generated Cypher, all values parameter-bound,
relationship labels hardcoded, existing properties preserved on null (coalesce) and
aliases append-deduplicated.

HQ-country endpoint MATCH-ed against the existing Entity{type:"LOCATION"} node
(never MERGE-d, never the :Location-label node) — a reversible tactical bridge,
see docs/superpowers/specs/2026-06-16-suv-hq-location-bridge-backfill-design.md.
"""

UPSERT_COMPANY = """
MERGE (c:Entity {name: $name, type: "ORGANIZATION"})
ON CREATE SET c.first_seen = datetime()
SET c.aliases = coalesce(c.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(c.aliases, [])],
    c.hq_country = coalesce($hq_country, c.hq_country),
    c.hq_city = coalesce($hq_city, c.hq_city),
    c.employees = coalesce($employees, c.employees),
    c.revenue_eur = coalesce($revenue_eur, c.revenue_eur),
    c.founded = coalesce($founded, c.founded),
    c.website = coalesce($website, c.website),
    c.products = CASE WHEN size($products) > 0 THEN $products ELSE c.products END,
    c.sector = "defense",
    c.suv_url = $suv_url,
    c.data_source = "suv.report",
    c.suv_extracted_at = $extracted_at,
    c.last_seen = datetime()
"""

LINK_COMPANY_COUNTRY = """
MATCH (c:Entity {name: $name, type: "ORGANIZATION"})
MATCH (co:Entity {type: "LOCATION"}) WHERE toLower(co.name) = toLower($country)
MERGE (c)-[r:HEADQUARTERED_IN]->(co)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
"""
