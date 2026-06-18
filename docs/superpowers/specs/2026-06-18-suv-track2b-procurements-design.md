# SUV Track 2b — Procurements / Modernisierungsvorhaben (Design Spec)

**Date:** 2026-06-18 · **Base:** `main` `6a5ffbb` (post-#59 2a + #60 2a.1; equipment data live: 75 OPERATES edges) · **Branch:** `feat/suv-track2b-procurements`
**Predecessors:** [[suv-track2-slice2-procurements-equipment]], specs `2026-06-18-suv-track2a-equipment-design.md` + `2026-06-18-suv-track2a1-type-aware-operates-design.md`
**Status:** design from user direction, pending spec review → plan → implementation. **No prod write until it ships + dry-run + curation + backup** (same operator-gated discipline as 2a).

## 1. Goal & source

Ingest the SUV.report **Modernisierungsvorhaben** (procurement programs) as first-class
`PROCUREMENT_PROGRAM` nodes with their attributes (status, cost, quantity, financing, delivery,
description) and their relationships to the operator (Teilstreitkraft), the contractor (company),
and the subject system (equipment). Single page `/modernisierungsvorhaben/`, **30 programs**, grouped
under the same 5 Teilstreitkraft branches as 2a (Heer, Luftwaffe, Marine, Cyber- und
Informationsraum, Unterstützungsbereich). Deterministic parse (no LLM), Two-Loop write path.

## 2. Graph model (user-approved)

```
(:Entity {type:"PROCUREMENT_PROGRAM"})            # the program — its own identity
   -[:CONTRACTED_TO]-> (:Entity {type:"ORGANIZATION"})                        # contractor (optional, match-gated)
   -[:CONCERNS_SYSTEM]-> (:Entity {type: WEAPON_SYSTEM|AIRCRAFT|VESSEL|SATELLITE})  # subject (optional, match-gated)
(:Entity {type:"MILITARY_UNIT"|"ORGANIZATION"}) -[:PROCURES]-> (:Entity {type:"PROCUREMENT_PROGRAM"})  # operator (seed)
```

Rules (user-set):
- **Every** program is written as a `PROCUREMENT_PROGRAM` node, even without a clear subject/contractor.
- `contractor_raw` (the verbatim Auftragnehmer string) is always kept on the program node; matchable
  contractor parties are **additionally** linked via `CONTRACTED_TO`.
- Consortia (`A & B`, `A, B`, `Konsortium … (A & B)`) are split into parties; each party is
  match-gated/linked. Empty contractors (`/`, `N/A`) create no `CONTRACTED_TO` edge.
- Equipment `CONCERNS_SYSTEM` links are **optional + match-gated**, never forced.
- New relation types + `PROCUREMENT_PROGRAM` are documented in the taxonomy/read-path, but the
  write-templates stay SUV-owned + deterministic (as with `OPERATES`).

## 3. Parser (`procurement_parse.py`)

Same `### <title>` + `**Label:**` block structure as the Slice-1 companies parser, with a
**branch-tracking** pass (the page groups programs under Teilstreitkraft headings):

- Walk the rendered markdown; track the current branch (the Heer/Luftwaffe/Marine/CIR/
  Unterstützungsbereich section heading) as state; assign it to each `###` program block that follows.
- Per program extract: `title` (the `###` line), `branch` (tracked), `typ` (Typ), `status`
  (Projektstatus), `contractor_raw` (Auftragnehmer), `quantity`/`quantity_raw` (Stückzahl),
  `cost_eur`/`cost_raw` (Kosten), `financing` (Finanzierung), `delivery_raw` + `delivery_start`/
  `delivery_end` (Auslieferung), `description` (Beschreibung).
- Skip the photo-caption line that sits between the title and the first `**Label:**` (any line before
  the first field that is not a `**Label:**`).
- Normalizers (best-effort + raw fallback, like Slice-1):
  - `quantity`: first integer (German thousands-dot), `None` if absent (1 program lacks Stückzahl).
  - `cost_eur`: `"1,85 Mrd. Euro"`→1.85e9, `"… Mio. …"`→×1e6, German comma-decimal — **reuse the
    Slice-1 `parse_revenue_eur` logic** (Milliarde/Million scale); `None` if not parseable.
  - `delivery_start`/`delivery_end`: `"2024 – 2029"`→(2024,2029); single year→(y,y); `"N/A"`/ongoing→None.

## 4. PROCUREMENT_PROGRAM nodes — deterministic, all written (no entity-resolution gate)

The 30 programs are a NEW node type — nothing pre-exists, so there is **no match/curation gate for the
program nodes themselves** (unlike the equipment/company entity-resolution). They are written
idempotently: `MERGE (p:Entity {name: $title, type:"PROCUREMENT_PROGRAM"})` (title is the unique key)
+ `coalesce`-set props (status, cost_eur, cost_raw, quantity, quantity_raw, financing, delivery_start,
delivery_end, delivery_raw, description, typ, contractor_raw, data_source="suv.report", suv_url,
suv_extracted_at, first_seen/last_seen). Re-runs update in place.

## 5. Operator — PROCURES (reuse the 2a operator seed)

The branch heading → the canonical operator, **reusing 2a's `suv_operators.yaml` targets** (Heer→
`Deutsches Heer` MU, Luftwaffe→`Deutsche Luftwaffe` MU, Marine→`Deutsche Marine` MU, CIR→`Cyber- und
Informationsraum` MU, Unterstützungsbereich→`Unterstützungsbereich` ORG). The operator resolution
module (`operators.py`) is reused; the only addition is a **branch-label→operator** lookup (the seed
is already keyed by the equivalent page_slug — add a `branch_label` field, or a small alias map, so the
in-page branch headings resolve to the same 5 canonical operators). The exactly-1 preflight (matched
operators resolve to exactly one node) carries over. `LINK_PROCURES` is type-guarded:
`(op {type IN ["MILITARY_UNIT","ORGANIZATION"]}) -[:PROCURES]-> (p {type:"PROCUREMENT_PROGRAM"})`,
both endpoints MATCH-only (program upserted first).

## 6. Contractor — CONTRACTED_TO (split + match-gated, link-matchable-only)

- Split `contractor_raw` into parties on `&`, `,`, ` und `, and the `Konsortium … (A & B)` paren form;
  drop `etc.`/empties. `/` and `N/A` → no parties.
- Each party runs through the **generalized match-report gate** (2a's `build_match_report`, target
  `ORGANIZATION`, canonicalize-aware): `match` → `CONTRACTED_TO` link to the existing company;
  `ambiguous` → must resolve (curation); **`new` → NO edge, NO node creation** — the party stays only
  in `contractor_raw`. Rationale: new defense companies belong to the companies source (Slice-1 /
  Track-1), not auto-created from messy procurement contractor strings (consortia, partial names).
  (~6/30 exact-match today; canonicalize + curation will lift that, e.g. `KNDS Deutschland`→`KNDS`.)
- `LINK_CONTRACTED_TO` type-guarded: `(p {type:"PROCUREMENT_PROGRAM"}) -[:CONTRACTED_TO]-> (c {type:"ORGANIZATION"})`,
  both MATCH-only (the company must already exist — match-gated).

## 7. Subject — CONCERNS_SYSTEM (candidate-detect + match-gated, optional)

- Detect the subject-equipment **candidate** from the program `title` (+ `typ`) by scanning for an
  existing equipment node name (the 2a-created WEAPON_SYSTEM/AIRCRAFT/VESSEL/SATELLITE nodes), longest
  match wins — e.g. `"Konsolidierte Nachrüstung Puma 1. Los"`→`Puma`, `"Leopard 2 A6A3 / …"`→`Leopard 2`,
  `"KH Tiger"`, `"NH-90"`, `"Eurofighter"`, `"Tornado"`, `"A400M"` (~12/30 have a clean subject).
- The candidate runs through the match-report gate (target = the 4 equipment types): `match` →
  `CONCERNS_SYSTEM` link; `ambiguous`/`new`/no-candidate → **NO edge** (the program node still exists).
  Equipment links are optional — a descriptive program ("Beobachtungs- und Aufklärungsausstattung III")
  simply has no `CONCERNS_SYSTEM`.
- `LINK_CONCERNS_SYSTEM` type-guarded: `(p {type:"PROCUREMENT_PROGRAM"}) -[:CONCERNS_SYSTEM]-> (s {type:$sys_type})`
  with `s.type IN ["WEAPON_SYSTEM","AIRCRAFT","VESSEL","SATELLITE"]`, both MATCH-only.

## 8. Qdrant — per-program profiles (FLAGGED decision; recommend YES)

Unlike 2a equipment (thin rows → graph-only), procurement programs carry a **rich `Beschreibung`** →
a per-program Qdrant profile enables semantic queries ("which programs modernize the Puma / are in
Auslieferung"). **Recommended: write one Qdrant profile per program** (mirroring Slice-1 companies:
`source="suv_structured"`, `provenance_fields(source_type="dataset", provider="suv.report")`,
`content = profile_text(program)` [title + typ + status + quantity + cost + delivery + contractor_raw +
description], point-id = uuid5 on the normalized title). The read-path corpus_policy already admits
`suv_structured/dataset`. **Decision to confirm at spec review** (vs graph-only like 2a).

## 9. Write templates (SUV-owned, deterministic) + read-path/taxonomy

`suv_structured/write_templates.py` gains: `UPSERT_PROCUREMENT_PROGRAM` (MERGE title+type, coalesce
props), `LINK_PROCURES`, `LINK_CONTRACTED_TO`, `LINK_CONCERNS_SYSTEM` — all `$param`-bound, hardcoded
labels, relation-endpoint nodes MATCH-only (the program node is upserted first in the same tx;
operator/company/system endpoints must pre-exist). New types documented in:
- read-path `graph/schema_whitelist.py` — add `PROCURES`, `CONTRACTED_TO`, `CONCERNS_SYSTEM` to
  `RELATIONSHIPS` and `PROCUREMENT_PROGRAM` to the entity-type guidance; add intent keywords
  (`beschafft`, `procures`, `modernisierung`, `vorhaben`, `contractor`, `auftragnehmer`).
- coordinate wording with **`intel-codebook-curator`** (the relations' semantics + the new node type),
  but NOT `event_codebook.yaml` and NOT the nlm `RelationType` Literal (SUV-owned, NLM doesn't extract them).

## 10. Module structure (reuse-heavy)

- `suv_structured/procurement_schemas.py` — NEW. `ProcurementProgram` Pydantic + `profile_text`.
- `suv_structured/procurement_parse.py` — NEW. Branch-tracking `###`/`**field**` parser + cost/quantity/delivery normalizers (cost reuses Slice-1 revenue logic).
- `suv_structured/contractors.py` — NEW. `split_contractors(raw) -> list[str]` (consortium/empty handling).
- `suv_structured/operators.py` — MODIFY (small): branch-label → canonical operator lookup (reuse the 5 targets).
- `suv_structured/match_report.py` — REUSE as-is (target_type / target_type_of already generalized in 2a/2a.1) for contractor (ORGANIZATION) + subject (equipment types) gates.
- `suv_structured/write_templates.py` — MODIFY. Add the 4 templates above.
- `suv_structured/build_procurements.py` — NEW. Statement builder (program upsert → PROCURES → CONTRACTED_TO → CONCERNS_SYSTEM, ordered) + optional Qdrant points + gate (`resolve_*`).
- `suv_structured/cli.py` — MODIFY. Add `procurements fetch|parse|build [--dry-run|--approved-matches]`.
- `suv_structured/seeds/suv_procurements.yaml` — generated by `parse` (committed snapshot, 30 programs).
- Tests mirroring the 2a set; intelligence read-path tests for the new relationships.

## 11. Gates & new-creation policy
- **Program nodes:** deterministic, all written (MERGE title+type); no entity-resolution gate.
- **Operator (PROCURES):** branch→operator seed + exactly-1 preflight (reuse 2a).
- **Contractor (CONTRACTED_TO):** match-gated; `match`→link, `ambiguous`→resolve, `new`→no edge (contractor_raw only, no node creation).
- **Subject (CONCERNS_SYSTEM):** candidate-detect + match-gated; `match`→link, else no edge.
- The `--approved-matches` dry-run report covers the **two entity-resolution surfaces** (contractor parties + subject candidates); the program nodes + operator are deterministic. Drift-check + the hard gate carry over from 2a.

## 12. Testing (TDD) & reviews
Tests first, per module; committed markdown fixtures (the rendered page). Parser tests (branch
tracking; cost `"1,85 Mrd. Euro"`→1.85e9; delivery `"2024 – 2029"`→(2024,2029); caption skip; the 1
missing-Stückzahl program). Contractor-split tests (consortium/`/`/`N/A`/`etc.`). Gate tests (contractor
ORGANIZATION match/ambiguous/new-no-edge; subject candidate match/none). Template tests (type guards,
MATCH-only endpoints). Build tests (statement ordering: program upsert before its edges; Qdrant points
iff §8 = yes). Read-path tests (new relations discoverable). Per-task two-stage review + an adversarial
pass on the new type-guards; final whole-branch review; companies/equipment paths stay green.

## 13. Operational run (post-merge, operator-gated)
`procurements parse` → review `suv_procurements.yaml` → `procurements build --dry-run` → curate the
contractor + subject match report (resolve ambiguous; the program nodes + operators are automatic) →
**Neo4j backup** → `procurements build --approved-matches`. Verify: 30 PROCUREMENT_PROGRAM nodes, 30
PROCURES edges, N CONTRACTED_TO (matchable parties), M CONCERNS_SYSTEM (~12 clean subjects),
Qdrant +30 (if §8 yes).

## 14. Acceptance criteria
1. Parser yields 30 programs with branch + normalized cost/quantity/delivery; caption skipped; sane floor (≥20).
2. All 30 written as `PROCUREMENT_PROGRAM` (even subject-less/contractor-less); MERGE title+type idempotent.
3. `PROCURES` edges (30) from the branch operators (type-guarded MU|ORG → PROCUREMENT_PROGRAM); exactly-1 operator preflight.
4. `CONTRACTED_TO` only for matched contractor parties (consortia split); `new` party → no edge, contractor_raw retained; `/`/`N/A` → no edge.
5. `CONCERNS_SYSTEM` only for matched subjects (optional); descriptive programs have none.
6. New relations + `PROCUREMENT_PROGRAM` in `schema_whitelist` + intent; NOT in event_codebook/RelationType Literal.
7. Qdrant per §8 decision (regression-tested either way).
8. Companies (Slice-1) + equipment (2a) paths + full suite stay green; ruff clean.

## 15. Out of scope
- Creating new ORGANIZATION nodes from procurement contractors (contractor_raw preserves them; companies source owns new firms).
- Free-text subject extraction beyond scanning for existing equipment names (descriptive programs stay subject-less).
- The prod load itself (operator-gated, post-merge).
