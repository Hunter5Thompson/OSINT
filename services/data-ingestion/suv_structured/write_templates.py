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
The link is fan-out-guarded by WITH c, co LIMIT 1 (at most one edge even if duplicate
LOCATION nodes exist); the backfill additionally preflights for exactly-one target.
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
WITH c, co LIMIT 1
MERGE (c)-[r:HEADQUARTERED_IN]->(co)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
"""

# --- Track 2a: equipment / Hauptwaffensysteme ---
#
# OPERATES links an operator (MILITARY_UNIT|ORGANIZATION) to a WEAPON_SYSTEM it
# operates/uses. Distinct from the geographic OPERATES_IN (actor active in a
# region). The operator is matched on the seed's exact (name, type); the WHERE
# enforces the allowed-source-type invariant so a malformed seed cannot link from
# a non-actor (e.g. a LOCATION). Both endpoints are MATCH-ed, never MERGE-d.

UPSERT_OPERATOR = """
MERGE (o:Entity {name: $name, type: $type})
ON CREATE SET o.first_seen = datetime(), o.data_source = "suv.report"
SET o.aliases = coalesce(o.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(o.aliases, [])],
    o.suv_extracted_at = $extracted_at,
    o.last_seen = datetime()
"""

UPSERT_WEAPON_SYSTEM = """
MERGE (w:Entity {name: $name, type: "WEAPON_SYSTEM"})
ON CREATE SET w.first_seen = datetime()
SET w.aliases = coalesce(w.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(w.aliases, [])],
    w.weapon_type = coalesce(w.weapon_type, $weapon_type),
    w.data_source = coalesce(w.data_source, $data_source),
    w.suv_url = coalesce(w.suv_url, $suv_url),
    w.suv_extracted_at = $extracted_at,
    w.last_seen = datetime()
"""

LINK_OPERATES = """
MATCH (op:Entity {name: $op_name, type: $op_type}) WHERE op.type IN ["MILITARY_UNIT", "ORGANIZATION"]
MATCH (ws:Entity {name: $ws_name, type: "WEAPON_SYSTEM"})
WITH op, ws LIMIT 1
MERGE (op)-[r:OPERATES]->(ws)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.count = $count, r.count_raw = $count_raw, r.service_end = $service_end,
    r.note = $note, r.suv_url = $suv_url, r.last_seen = datetime()
"""
