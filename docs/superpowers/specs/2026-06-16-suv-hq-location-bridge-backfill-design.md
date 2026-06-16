# SUV HQ Location Bridge Backfill — Design

**Date:** 2026-06-16 · **Status:** approved (brainstorm) · **Type:** tactical, reversible bridge — NOT a final country ontology.

## Problem

SUV Track 2 Slice 1 wrote 77 defense-company `Entity{type:"ORGANIZATION"}` nodes with `hq_country`/`hq_city` as **properties only**. The `HEADQUARTERED_IN` relation never materialized: its write-template MATCHes `Entity{type:"COUNTRY"}`, and the graph has **no** Germany/Netherlands COUNTRY node (only 7 conflict-zone COUNTRY nodes). So company→country is queryable only via a property scan, not graph traversal.

The graph's geo representation is duplicated (audited 2026-06-16, read-only):

| "Germany" representation | degree |
|---|---|
| `Entity{type:"LOCATION"}` "Germany" | **276 (dominant)** |
| `:Location` label node "Germany" | 54 |
| `Entity{type:"ORGANIZATION"}` "Germany" | 3 |
| `Entity{type:"LOCATION"}` "Deutschland" (German, separate) | 40 |

`HEADQUARTERED_IN` is used **0×** anywhere in the graph today (brand-new from SUV).

## Decision

Link `HEADQUARTERED_IN` to the **existing dominant `Entity{type:"LOCATION"}`** node (Germany deg 276, Netherlands deg 29). Rationale: smallest step that delivers graph-traversal value **without adding a 5th Germany representation** — creating `Entity{type:"COUNTRY"}` now would fight the in-flight `graph-integrity-geo` workstream.

This is an explicit **reversible compatibility bridge**, documented as such — re-pointable to canonical COUNTRY nodes once geo canonicalization lands. (Considered + rejected for now: (B) create canonical COUNTRY + reconcile duplicates = the graph-integrity-geo work, too big + dangerous as a SUV one-off; (C) defer entirely = leaves useful edges on the table.)

## Design

### 1. `write_templates.py` — `LINK_COMPANY_COUNTRY`
Change the country endpoint from COUNTRY to LOCATION (MATCH-only, never MERGE):
```
MATCH (c:Entity {name: $name, type: "ORGANIZATION"})
MATCH (co:Entity {type: "LOCATION"}) WHERE toLower(co.name) = toLower($country)
MERGE (c)-[r:HEADQUARTERED_IN]->(co)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.last_seen = datetime()
```
Because we MATCH `:Entity` (with `type:"LOCATION"`), the separate `:Location`-label node is **never** matched. This also makes **future `build` runs** create the edge automatically. Tests: assert `type: "LOCATION"`, assert no `type: "COUNTRY"`, assert no `:Location` label in the template.

### 2. `countries.py`
No logic change — `to_graph_country` already maps `Deutschland→Germany`, `Niederlande→Netherlands` (= the LOCATION node names). Update the module/function docstring: target is now `Entity{type:"LOCATION"}` as a tactical bridge (reference this spec).

### 3. New backfill migration — `suv_structured/backfill_hq.py`
A **separate, targeted** migration (NOT a `build --approved-matches` re-run: the hardened `detect_drift` gate would now correctly abort, because the 74 once-`new` companies already exist → fresh re-derivation = `match` ≠ approved `new`).

Pure, unit-tested core + thin live orchestration:
- `build_hq_link_statements(org_rows: list[tuple[str, str]]) -> tuple[list[dict], list[tuple[str, str]]]`
  - input `(org_name, hq_country_german)` rows; for each: `loc = to_graph_country(hq_country)`; if mapped → emit a `LINK_COMPANY_COUNTRY` statement `{"name": org_name, "country": loc}`; else → collect in `skipped` (logged). Returns `(statements, skipped)`. Pure.
- `unmapped_or_ambiguous_targets(counts: dict[str, int]) -> list[str]` — preflight helper: returns country names whose `Entity{type:"LOCATION"}` count `!= 1`. Pure.
- live helpers (httpx, Neo4j HTTP tx): `fetch_suv_orgs(client, ...)` → rows via `MATCH (c:Entity{type:"ORGANIZATION", data_source:"suv.report"}) WHERE c.hq_country IS NOT NULL RETURN c.name, c.hq_country`; `count_location_targets(client, country_names) -> dict[str,int]`.
- writer: reuse `build_companies.write_neo4j`.

### 4. CLI — `odin-suv-structured backfill-hq`
- **`--dry-run` is the DEFAULT**; a real write requires explicit **`--apply`** (no accidental prod write).
- Dry-run output: # SUV orgs found · # mapped vs skipped · **per distinct mapped country, the concrete target node + count** (e.g. `Germany -> Entity{type:"LOCATION"} count=1`) so the operator check before `--apply` is unambiguous · # statements that would be written.
- **Preflight (both modes):** per distinct mapped country, require **exactly one** `Entity{type:"LOCATION"}` target. If any country resolves to 0 or >1 LOCATION nodes → **abort** (a `toLower` MATCH against >1 node would silently create multiple edges). `--apply` runs the preflight, then writes.

## Safety

- **Backup not required:** purely additive (`MERGE HEADQUARTERED_IN` only, MATCH-only on both endpoints, no node/property mutation); `HEADQUARTERED_IN` currently exists 0×. The 2026-06-16 pre-SUV dump (`backups/neo4j-pre-suv-20260616/neo4j.dump`) additionally covers it.
- **Reversal query** (documented; full rollback of this backfill):
  ```cypher
  MATCH ()-[r:HEADQUARTERED_IN {data_source:"suv.report"}]->()
  DELETE r
  ```
- Dry-run default + explicit `--apply` + the exactly-1-target preflight together prevent an accidental or fan-out write.

## Verification (post `--apply`)
```cypher
MATCH (c:Entity{type:"ORGANIZATION", data_source:"suv.report"})-[:HEADQUARTERED_IN]->(l:Entity{type:"LOCATION"})
RETURN l.name, count(*) ORDER BY count(*) DESC
```
Expected: ~77 edges → `Germany` (76), `Netherlands` (1).

## Testing
- `test_suv_write_templates`: LINK targets `type:"LOCATION"`; asserts no `type:"COUNTRY"`, no `:Location` label.
- `test_suv_backfill_hq`: `build_hq_link_statements` emits a LINK for a mapped row (Deutschland→Germany), skips an unmapped row (Atlantis), uses `LINK_COMPANY_COUNTRY` with `{name, country}`; `unmapped_or_ambiguous_targets` flags counts `0` and `2`, passes `1`.

## Out of scope
- Geo canonicalization (merging the LOCATION/`:Location`/`Deutschland` duplicates, a real COUNTRY taxonomy) — owned by the `graph-integrity-geo` workstream. This bridge is intentionally re-pointable when that lands.

## ADR note
Recorded in `write_templates.py` + `countries.py`: `HEADQUARTERED_IN` targets `Entity{type:"LOCATION"}` as a **tactical, reversible bridge** to the current dominant geo representation, pending the canonical-country model from graph-integrity-geo.
