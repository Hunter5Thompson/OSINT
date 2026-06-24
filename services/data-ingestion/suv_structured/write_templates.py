"""Deterministic Cypher for SUV structured ingestion.

Kept SEPARATE from nlm_ingest/write_templates.py — SUV adds HEADQUARTERED_IN
without touching the NLM RelationType contract.

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

UPSERT_SYSTEM = """
MERGE (w:Entity {name: $name, type: $type})
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
MATCH (op:Entity {name: $op_name, type: $op_type})
WHERE op.type IN ["MILITARY_UNIT", "ORGANIZATION"]
MATCH (ws:Entity {name: $ws_name, type: $ws_type})
WHERE ws.type IN ["WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "SATELLITE"]
WITH op, ws LIMIT 1
MERGE (op)-[r:OPERATES]->(ws)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.count = $count, r.count_raw = $count_raw, r.service_end = $service_end,
    r.note = $note, r.suv_url = $suv_url, r.last_seen = datetime()
"""

# --- Track 2b: procurements / Modernisierungsvorhaben ---

UPSERT_PROCUREMENT_PROGRAM = """
MERGE (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})
ON CREATE SET p.first_seen = datetime()
SET p.status = coalesce($status, p.status),
    p.program_type = coalesce($typ, p.program_type),
    p.quantity = coalesce($quantity, p.quantity),
    p.quantity_raw = coalesce($quantity_raw, p.quantity_raw),
    p.cost_eur = coalesce($cost_eur, p.cost_eur),
    p.cost_raw = coalesce($cost_raw, p.cost_raw),
    p.financing = coalesce($financing, p.financing),
    p.delivery_start = coalesce($delivery_start, p.delivery_start),
    p.delivery_end = coalesce($delivery_end, p.delivery_end),
    p.delivery_raw = coalesce($delivery_raw, p.delivery_raw),
    p.description = coalesce($description, p.description),
    p.branch = coalesce($branch, p.branch),
    p.contractor_raw = coalesce($contractor_raw, p.contractor_raw),
    p.data_source = "suv.report",
    p.suv_url = $suv_url,
    p.suv_extracted_at = $extracted_at,
    p.last_seen = datetime()
"""

LINK_PROCURES = """
MATCH (op:Entity {name: $op_name, type: $op_type})
WHERE op.type IN ["MILITARY_UNIT", "ORGANIZATION"]
MATCH (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})
WITH op, p LIMIT 1
MERGE (op)-[r:PROCURES]->(p)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
"""

LINK_CONTRACTED_TO = """
MATCH (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})
MATCH (c:Entity {name: $company, type: "ORGANIZATION"})
WITH p, c LIMIT 1
MERGE (p)-[r:CONTRACTED_TO]->(c)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
"""

LINK_CONCERNS_SYSTEM = """
MATCH (p:Entity {name: $title, type: "PROCUREMENT_PROGRAM"})
MATCH (s:Entity {name: $sys_name, type: $sys_type})
WHERE s.type IN ["WEAPON_SYSTEM", "AIRCRAFT", "VESSEL", "SATELLITE"]
WITH p, s LIMIT 1
MERGE (p)-[r:CONCERNS_SYSTEM]->(s)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
"""
