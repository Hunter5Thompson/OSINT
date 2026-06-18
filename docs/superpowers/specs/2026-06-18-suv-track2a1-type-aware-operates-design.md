# SUV Track 2a.1 — Type-aware OPERATES (Design Spec)

**Date:** 2026-06-18 · **Base:** `main` post-#59 (`6101f00`, Track 2a merged) · **Branch:** `feat/suv-track2a1-types`
**Predecessor:** [[suv-track2-slice2-procurements-equipment]], spec `2026-06-18-suv-track2a-equipment-design.md`
**Status:** design from user direction, pending spec review → plan → implementation. **No prod write until this ships + a fresh dry-run + curation + backup.**

## 1. Why (what the 2a dry-run revealed)

The merged Track 2a hardcodes the OPERATES target to `WEAPON_SYSTEM`. The first real dry-run of the
76 parsed Hauptwaffensysteme showed that assumption is too narrow:

- Only **11/76 exist in the graph at all**: 6 as `WEAPON_SYSTEM`, **4 as `AIRCRAFT`** (Eurofighter,
  Tornado, A400M, P-8A Poseidon), **1 as `VESSEL`** (F123). **65 are absent.**
- By SUV `Typ`: **47 ground/other, 19 air, 10 sea** (~38% are aircraft/vessels).

Under WEAPON_SYSTEM-only, the 5 existing AIRCRAFT/VESSEL would be **duplicated** as new
WEAPON_SYSTEM nodes, and ~29 aircraft/vessels would be **mis-typed** WEAPON_SYSTEM — exactly the
"duplicate / wrong-type" debt Track 2's link-existing principle exists to avoid. This slice makes
OPERATES type-aware so equipment links to (and is created with) the correct entity type.

## 2. Type classifier (deterministic, calibrated to the real `Typ` vocabulary)

New `classify_system_type(type_raw: str | None) -> str` (no LLM; pure; first-match keyword rules on
the lowercased `Typ`). Order matters — **air before sea** so `Tankflugzeug` (air) isn't caught by the
`tanker` sea keyword, and `Seefernaufklärer` (air) isn't caught by `see`/sea.

| Result | Keyword substrings (lowercased `Typ`) | Real examples it must catch |
|---|---|---|
| `AIRCRAFT` | `flugzeug`, `hubschrauber`, `drohne`, `flieger`, `seefernaufklärer` | Kampf-/Transport-/Tankflugzeug, alle *hubschrauber, Aufklärungsdrohne ×6, Regierungsflieger, Seefernaufklärer (P-3C/P-8A) |
| `VESSEL` | `fregatte`, `korvette`, `u-boot`, `boot`, `tender`, `tanker`, `underwater` | 3× Fregatte, Korvette, U-Boot, Minenjagdboot, Flottendienstboot, Einsatzboot, Flottentanker, Tender, Large Unmanned Underwater Vehicle (BlueWhale) |
| `WEAPON_SYSTEM` (default/else) | everything else | Kampfpanzer, Schützenpanzer, Panzerhaubitze, Raketenartillerie, Flakpanzer, Brücken/Pionier, transport vehicles, Flugabwehr*, satellites (see §7) |

Classification is by `Typ` only (the page/operator does not determine the system kind — e.g. the
Marine page lists Bordhubschrauber, which are AIRCRAFT). `Typ`-absent rows → `WEAPON_SYSTEM`.

## 3. Widened OPERATES target guard (`write_templates.py`)

`LINK_OPERATES` currently matches `(ws:Entity {name: $ws_name, type: "WEAPON_SYSTEM"})`. Change to bind
the system type per-row (mirroring the `$op_type` pattern) with a widened allowed-target invariant:

```cypher
MATCH (op:Entity {name: $op_name, type: $op_type})
WHERE op.type IN ["MILITARY_UNIT", "ORGANIZATION"]
MATCH (ws:Entity {name: $ws_name, type: $ws_type})
WHERE ws.type IN ["WEAPON_SYSTEM", "AIRCRAFT", "VESSEL"]
WITH op, ws LIMIT 1
MERGE (op)-[r:OPERATES]->(ws)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.count = $count, r.count_raw = $count_raw, r.service_end = $service_end,
    r.note = $note, r.suv_url = $suv_url, r.last_seen = datetime()
```

The `WHERE ws.type IN [...]` keeps the no-Location-as-target invariant the user mandated; binding
`$ws_type` keeps the endpoint deterministic. `UPSERT_WEAPON_SYSTEM` is generalized to
`UPSERT_SYSTEM` taking a `$type` param (`MERGE (w:Entity {name: $name, type: $type})`, same
non-destructive coalesce + `suv_extracted_at`), so new nodes are created with the classified type
and matched nodes (e.g. the existing AIRCRAFT Eurofighter) are enriched in place, never duplicated.

## 4. Type-aware match report (`match_report.py`)

`build_match_report` currently takes one `target_type` str for all items. Generalize so the target
type can vary per item, **without changing the companies path**:
- Add an optional `target_type_of: Callable[[item], str] | None = None`. When provided, the per-item
  expected type comes from it; when `None`, the existing `target_type` str applies to all (companies
  + any single-type caller unchanged → byte-identical).
- Match logic per item: `match` iff exactly one existing node whose `type == expected_type`;
  existing node(s) of other types → `ambiguous` (surfaced for human review); none → `new`.
- The `gate_new_creation` WEAPON_SYSTEM-evidence gate (2a) still applies, now keyed to whichever
  expected type is a "create"; an approved `new` of ANY equipment type requires `approved_new` +
  `evidence` (link-existing remains the default for all three types).

Result on the live graph: Eurofighter/Tornado/A400M/P-8A → `match` (AIRCRAFT), F123 → `match`
(VESSEL), PATRIOT → still `ambiguous` (two WEAPON_SYSTEM candidates), the 65 absent → `new` with
their classified type.

## 5. Type-aware builder (`build_equipment.py`)

- Compute each row's expected type via `classify_system_type(row.type_raw)`.
- `ws_write_name` unchanged (match → existing canonical name; new → canonicalized muster).
- Emit `UPSERT_SYSTEM` with the row's `$type` (matched rows enrich the existing typed node; new rows
  create with the classified type), then `LINK_OPERATES` with `$ws_type` = that type.
- `resolve_equipment_build_inputs` duplicate-write-name guard: keep, but the collision key becomes
  `(write_name, type)` — two different-typed systems with the same name are not a collision (rare,
  but correct).

## 6. Parser robustness (`equipment_parse.py`)

Skip leaked **secondary-header rows**: the Marine table has a sub-section header that parses as
`muster="Klasse", type_raw="Typ"`. Add a guard: skip any row whose cleaned `type_raw == "Typ"`
(a real data row's Typ is never the literal header token). Re-`parse` must drop the `Klasse` row
(76 → 75). The hyphen-linebreak artifact `Luftlanderettungszen-trum, leicht` is left for curation
(cosmetic; a real entry).

## 7. FLAGGED DECISION — satellites (the one open question)

Two rows are satellites: `COMSATBw` (`Kommunikations-satelliten`) and `SATCOMBw Bodensegment`
(`satellitengestützte Kommunikationssystem`, actually the ground segment). The graph's `EntityType`
enum includes `SATELLITE`. The user's stated scope was the 3 types {WEAPON_SYSTEM, AIRCRAFT, VESSEL}.
- **Default in this spec (honoring the 3-type scope):** no `satellit` rule → both fall to
  `WEAPON_SYSTEM`. Slightly mis-typed (COMSATBw is really a satellite) but within the stated scope.
- **Alternative (recommend if acceptable):** add `SATELLITE` as a 4th classifier result + target
  type (keyword `satellit`), so COMSATBw is typed correctly. `SATCOMBw Bodensegment` is ground infra
  and would also catch `satellit` — acceptable-ish. **Resolve at spec review.**

## 8. Read-path — no change

`OPERATES` is already in `schema_whitelist.RELATIONSHIPS` and the `betreibt/operates` intent routes to
the generic `one_hop` (`-[r]-`, any relationship/any node type). AIRCRAFT/VESSEL OPERATES edges
surface with no further change.

## 9. Module structure & tests

- `suv_structured/operators.py` (or a new `system_types.py`) — `classify_system_type` + tests
  covering every distinct `Typ` bucket (air/sea/ground) + the absent-Typ default.
- `suv_structured/write_templates.py` — widen `LINK_OPERATES` (`$ws_type` + WHERE invariant);
  `UPSERT_WEAPON_SYSTEM` → `UPSERT_SYSTEM($type)`. Update the template tests.
- `suv_structured/match_report.py` — `target_type_of` callable; companies regression stays green.
- `suv_structured/build_equipment.py` — classify per row, thread `$ws_type`/`$type`, collision key
  `(write_name, type)`. Update build tests (incl. an AIRCRAFT match + a VESSEL match case).
- `suv_structured/equipment_parse.py` — skip `type_raw == "Typ"` secondary headers; fixture + test.
- TDD throughout; companies path byte-identical; ruff clean; per-task two-stage review + the
  generalized-gate adversarial pass (the gate now spans 3 types).

## 10. Acceptance criteria
1. `classify_system_type` maps every distinct seed `Typ` correctly (air→AIRCRAFT, sea→VESSEL,
   else→WEAPON_SYSTEM); table-driven test over the real vocabulary.
2. Re-`parse` drops the `Klasse`/`Typ` secondary-header row (76 → 75 systems).
3. `LINK_OPERATES` binds `$ws_type` and guards `ws.type IN ["WEAPON_SYSTEM","AIRCRAFT","VESSEL"]`,
   endpoints MATCH-only; template test verifies.
4. A fresh `equipment build --dry-run` classifies Eurofighter/Tornado/A400M/P-8A as `match`→AIRCRAFT,
   F123 as `match`→VESSEL (no longer ambiguous/duplicated); PATRIOT still `ambiguous`.
5. The new-creation gate still refuses an approved `new` (of any type) lacking `approved_new`+`evidence`.
6. Companies path + full data-ingestion suite stay green; ruff clean.
7. Still graph-only (no Qdrant).

## 11. Out of scope (unchanged from 2a)
- The actual prod load — still the operator-gated sequence AFTER this ships: fresh `parse` → review
  seed → `build --dry-run` → curate (resolve PATRIOT, alias vs approved_new for the 65 absent) →
  **Neo4j backup** → `build --approved-matches`.
- Procurements (Track 2b).
- The `Luftlanderettungszen-trum` hyphen artifact (curation, not code).
