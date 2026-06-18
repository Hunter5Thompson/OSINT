# SUV Track 2a — Equipment / Hauptwaffensysteme (Design Spec)

**Date:** 2026-06-18 · **Base:** `main` (post-#55/#57/#58 — has SUV Slice 1 Companies + HQ bridge)
**Author handoff:** [[suv-track2-slice2-procurements-equipment]], `docs/superpowers/HANDOFF-suv-track2-slice2-2026-06-18.md`
**Status:** approved-in-brainstorm, pending spec review → implementation plan

## 1. Goal

Ingest the SUV.report **Hauptwaffensysteme** (equipment) dataset into the ODIN graph as
**`(:MILITARY_UNIT|:ORGANIZATION)-[:OPERATES {count, service_end, note, …}]->(:WEAPON_SYSTEM)`**
edges — *linking to existing `WEAPON_SYSTEM` nodes*, not duplicating them. Deterministic
extraction (no LLM, no GPU, Two-Loop write path). This is the first of two Slice-2 sub-datasets;
procurements (`/modernisierungsvorhaben/`) are **Track 2b** (separate spec, out of scope here).

The analyst value of 2a is the **graph relationship**: *which Teilstreitkraft operates which
weapon system, in what quantity, until when.* It validates the central Track-2 architectural
decision (link existing, don't duplicate) on the equipment side before 2b layers procurement
programs + financials on top.

## 2. Source topology

`/category/datenbank/ausruestung/` is a **category page linking 5 sub-pages**, one per
Organisationsbereich of the Bundeswehr:

| Page slug | Operator (Teilstreitkraft) |
|---|---|
| `hauptwaffensysteme-des-heeres` | Heer |
| `hauptwaffensysteme-der-luftwaffe` | Luftwaffe |
| `hauptwaffensysteme-der-marine` | Marine |
| `hauptwaffensysteme-des-cyber-und-informationsraums` | Cyber- und Informationsraum (CIR) |
| `hauptwaffensysteme-des-unterstuetzungsbereichs` | Unterstützungsbereich |

Each sub-page renders (via crawl4ai `/md` `f=fit`, the existing `fetch.py` pattern) a **Markdown
table**:

```
| Muster | Typ | Anzahl | Nutzungsdauerende | Notiz |
| Leopard 2 | Kampfpanzer | 310 | 2050 | 123 weitere Leopard 2 A8 bestellt. |
| Fuchs | Transportpanzer | 939 in über 30 verschiedenen Varianten | N/A | Ersatz durch Patria 6×6 (CAVS). |
```

Walking-skeleton spike (2026-06-18) confirmed all 5 pages render deterministically and the table
structure is stable. **GO.**

## 3. Data model

### Entities
- **Weapon system** = existing `Entity{type:"WEAPON_SYSTEM"}` (1229 in prod). The `Muster` column.
  Linked, not created (see §5).
- **Operator** = `Entity{type:"MILITARY_UNIT"}` (preferred) or `ORGANIZATION`. Determined by which
  page the row appears on, resolved via a curated seed (§4). Per user direction: model the
  Teilstreitkraft as the **primary operator level**; a `Bundeswehr` aggregate is deferred (2b or later).

### Relation: `OPERATES`
`(operator)-[:OPERATES]->(weapon_system)` with properties:

| Property | Source column | Normalization |
|---|---|---|
| `count` | Anzahl | first integer, German thousands-dot stripped: `"310"`→310, `"1+"`→1, `"939 in über 30 …"`→939, `"337 (189 …)"`→337; `None` if no integer |
| `count_raw` | Anzahl | the original string verbatim (provenance for ambiguous quantities) |
| `service_end` | Nutzungsdauerende | first 4-digit year: `"2050"`→2050, `"2046 (20 Jahre)"`→2046; `"N/A"`/empty → `None` |
| `note` | Notiz | free text, trimmed; `None` if empty |
| `data_source` | — | `"suv.report"` (provenance; makes the edge reversible) |
| `suv_url` | — | the sub-page URL (per-page, so a valid join key here — unlike Slice 1's shared directory URL) |
| `first_seen` / `last_seen` | — | `datetime()` |

Counts/service-end live **on the edge**, never on the node: a system operated by multiple branches
has branch-specific inventory, and a re-run must update idempotently. A system appearing on multiple
pages yields multiple `OPERATES` edges (one per operator) — natural and correct.

### Sharp semantic boundary (codebook, per user constraint)
- `OPERATES` — actor *operates/uses a system or piece of equipment*. Target is always `WEAPON_SYSTEM`.
- `OPERATES_IN` (pre-existing) — actor is *active in a geographic region*. Geographic, unrelated.

These are distinct Neo4j relationship-type strings (no collision), but the read-path schema doc must
state the distinction so the LLM never conflates them (§7).

## 4. Operator resolution — executable seed contract

The 5 operators are a small fixed set, but the graph already contains **duplicates** of each
(probed 2026-06-18): e.g. Heer → `Heer`(MU) + `Deutsches Heer`(MU) + `Deutsches Heer`(ORG);
Luftwaffe → 4 candidate nodes; `Unterstützungsbereich` exists only as `ORGANIZATION`; CIR has no node.

Therefore operator resolution is a **curated decision**, encoded as an explicit, executable contract
in `suv_structured/seeds/suv_operators.yaml` — **one decision per row, no "bzw." alternatives:**

```yaml
- page_slug: hauptwaffensysteme-des-heeres
  page_label: Heer
  decision: match                 # match | create
  target_name: "Deutsches Heer"
  target_type: MILITARY_UNIT
- page_slug: hauptwaffensysteme-des-cyber-und-informationsraums
  page_label: Cyber- und Informationsraum
  decision: create
  target_name: "Cyber- und Informationsraum"
  target_type: MILITARY_UNIT
  create_properties: { aliases: ["CIR"] }
```

Rules:
- `decision: match` → at build time the target must resolve to **exactly one**
  `Entity{name:target_name, type:target_type}` node (the `(name,type)` qualifier disambiguates the
  duplicates). An **exactly-1 preflight** (mirrors `backfill-hq`) aborts the whole build otherwise —
  forcing the operator to pick a more specific target or resolve the duplicate upstream.
- `decision: create` → `MERGE` a new `Entity{name,type}` with `create_properties` (used for CIR,
  which has no node, and for any operator the user deliberately wants as a fresh `MILITARY_UNIT`).
- The committed seed is **human-reviewed in the PR** and re-confirmed in the operational dry-run.

**Proposed default seed** (the curation decision point — confirmed during the operational dry-run):

| page_label | decision | target | note |
|---|---|---|---|
| Heer | match | `Deutsches Heer` (MU) | exactly-1 with the MU type qualifier |
| Luftwaffe | match | `Deutsche Luftwaffe` (MU) | avoids the `Luftwaffe`/`LUFTWAFFE` duplicates |
| Marine | match | `Deutsche Marine` (MU) | |
| Cyber- und Informationsraum | create | `Cyber- und Informationsraum` (MU) | no existing node |
| Unterstützungsbereich | match | `Unterstützungsbereich` (ORGANIZATION) | Link-existing, no duplicate (decided at spec review). Live graph has exactly one `Unterstützungsbereich` ORG; the OPERATES source-guard admits `ORGANIZATION`, so the edge links it directly. No deliberate ORG/MU duplicate is created. |

Linking to one canonical node leaves the other duplicates orphaned; that is **out of scope** —
owned by the graph-integrity-geo / entity-resolution workstream. The OPERATES edge carries
`data_source:"suv.report"` so it is re-pointable when canonicalization lands.

## 5. Weapon-system gate — link-first, creation is the gated exception

**This is the core Track-2 discipline and the highest-risk area (review Finding 1).** Equipment
rows are thin table cells; exact-name matching alone (the current `match_report` behavior) would let
`GTK Boxer`, `Panzerhaubitze 2000`, `Fennek` etc. fall through as **new nodes** when they are almost
certainly alias/surface variants of existing systems. That violates "link to existing."

`match_report.py` is **generalized** (target entity type parametrized; `ORGANIZATION` stays the
default so the Slice-1 companies path is behavior-identical) and gains a **weapon-system creation
policy**:

- Decisions remain `match` / `new` / `ambiguous` (canonicalize-aware, exactly as Slice 1).
- For `target_type == "WEAPON_SYSTEM"`, the build gate (`load_approved` / `resolve_build_inputs`)
  **refuses any approved `new`** unless that entry additionally carries:
  - `approved_new: true`, **and**
  - a non-empty `evidence` string (why this is genuinely a new system, not an alias).
- The intended primary resolution for a non-match is **alias curation**, in priority order:
  1. add a curated alias to `canonicalize.py` `_ALIAS_GROUPS` (e.g. `"GTK Boxer"` → `"Boxer"`), so it
     resolves to `match` on re-run; **or**
  2. set `decision: match` + `existing_name` explicitly in the report.

  Creating a node (`approved_new`) is the deliberate, evidenced exception.
- `ambiguous` (e.g. `PATRIOT` exists as both `Patriot` and `PATRIOT`) must be resolved before
  approval — unchanged from Slice 1 (`load_approved` rejects approved+ambiguous).

All other Slice-1 gate guarantees carry over verbatim: `--approved-matches` required for a real
build, drift detection re-derives matches against the live graph at build time, and the
duplicate-write-name guard prevents two approved rows collapsing onto one node.

## 6. OPERATES write template — Two-Loop, type-guarded

Lives in `suv_structured/write_templates.py` (NOT nlm's key-locked `RELATION_TEMPLATES`). Deterministic,
`$param`-bound, hardcoded label, endpoints **MATCH-only** (never MERGE — no phantom entities):

```cypher
-- OPERATES (operator matched on the seed's exact (name, type); WHERE enforces
-- the allowed-source-type invariant so a malformed seed can't link from a non-actor)
MATCH (op:Entity {name: $op_name, type: $op_type}) WHERE op.type IN ["MILITARY_UNIT", "ORGANIZATION"]
MATCH (ws:Entity {name: $ws_name, type: "WEAPON_SYSTEM"})
WITH op, ws LIMIT 1
MERGE (op)-[r:OPERATES]->(ws)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.count = $count, r.count_raw = $count_raw, r.service_end = $service_end,
    r.note = $note, r.suv_url = $suv_url, r.last_seen = datetime()
```

**`$op_type` is bound from the seed's resolved `target_type`** — binding only `$op_name` would let
`WITH … LIMIT 1` pick arbitrarily when both a `MILITARY_UNIT` and an `ORGANIZATION` of the same name
exist (confirmed live: `Deutsches Heer` exists as both). The build statements MUST pass `op_type`.

Endpoint creation happens **before** the link, in the same transaction batch:
- **Operators** are upserted from the seed (`match` → exists, no write; `create` → `MERGE` once).
- **Weapon systems**: a single `UPSERT_WEAPON_SYSTEM` (MERGE on `(name, type:"WEAPON_SYSTEM")`)
  handles both cases **non-destructively, exactly like Slice-1's `UPSERT_COMPANY`**: `coalesce`
  preserves every existing curated property; it only **appends** the SUV surface-form alias
  (append-dedup), sets `last_seen`, and sets `data_source`/`suv_url`/`weapon_type` (from `Typ`)
  where absent. For a **matched** system the MERGE finds the existing canonical node (enrich-only,
  never clobber). For an **approved-new** system (gated by `approved_new` + `evidence`, §5) the MERGE
  creates the node. The build emits an `UPSERT_WEAPON_SYSTEM` statement only for matched and
  approved-new systems — un-evidenced `new` rows are refused upstream and never reach the writer.

The `WITH op, ws LIMIT 1` is a fan-out guard (belt-and-braces; the exactly-1 operator preflight and
the type-qualified WS match already make endpoints unique).

## 7. Read-path integration (review Finding 2)

The free-Cypher fallback (`graph_query._free_cypher_fallback`) prompts the LLM with a **fixed
relationship whitelist** (`graph/schema_whitelist.py:9` — currently only `INVOLVES, REPORTED_BY,
OCCURRED_AT, MENTIONS`). A natural question like *"Welche Systeme betreibt das Heer?"* matches no
intent template and falls into this path, where `OPERATES` is currently forbidden. Required changes:

1. Add `"OPERATES"` to `schema_whitelist.RELATIONSHIPS`.
2. Add intent keywords (`betreibt`, `operates`, `in Dienst`, `fielded`, `im Bestand`) to
   `graph_query.py`'s intent matcher so such questions route to a **generic `-[r]-` template**
   (`one_hop`/`two_hop` already surface any relationship via `type(r)`), avoiding the restrictive
   free-Cypher path entirely.
3. Mention `OPERATES` in the `graph_query` tool description / schema prompt, with the
   OPERATES-vs-OPERATES_IN distinction (§3).

Noted adjacent gap (NOT fixed in 2a, to keep scope tight): `RELATIONSHIPS` is broadly stale — it also
omits `HEADQUARTERED_IN` (Slice 1) and all nlm relation types. Adding `HEADQUARTERED_IN` alongside
`OPERATES` is a one-line bonus correctness fix and MAY be included; a full whitelist audit is its own
task.

## 8. Qdrant: skipped in 2a (🔸 confirmed)

Equipment rows are too thin to embed usefully (`name/type/count/note`), most systems already exist as
nodes, and embedding terse near-duplicate text pollutes the corpus. 2a is **graph-only**. Qdrant
profiles are revisited for 2b (procurements carry a rich `Beschreibung`).

**Regression test (required):** the equipment build path produces **0 Qdrant points and never
instantiates a `QdrantClient`** — asserted in tests so a future change can't silently start writing.

## 9. Taxonomy / codebook coherence (review Finding 3)

`OPERATES` is owned by SUV; NLM does not extract it. It is therefore documented/registered in:
- `suv_structured/write_templates.py` (the template + docstring) — write path;
- `graph/schema_whitelist.py` + `graph_query` tool docs — read path, incl. the OPERATES↔OPERATES_IN
  semantic boundary (coordinate with `intel-codebook-curator` for the wording).

It is **NOT** added to `event_codebook.yaml` (that is the *event-type* codebook, not the relation
taxonomy) and **NOT** to the `RelationType` Literal / `RELATION_TEMPLATES` (those are NLM's
extraction contract). The `RelationType` Literal is extended only if/when NLM should *extract*
OPERATES from free text — a future, separate decision.

## 10. Module structure (mirrors Slice 1)

New / changed under `services/data-ingestion/`:
- `suv_structured/equipment_schemas.py` — `WeaponSystemRow` Pydantic (muster, type_raw, count,
  count_raw, service_end, note, page_slug, suv_url).
- `suv_structured/equipment_parse.py` — Markdown-table parser (NEW; deterministic, raw-fallback).
- `suv_structured/operators.py` — operator seed loader + resolver (match/create + exactly-1 preflight).
- `suv_structured/match_report.py` — **generalized** (target_type param + WEAPON_SYSTEM new-policy).
- `suv_structured/write_templates.py` — add `OPERATES` + `UPSERT_WEAPON_SYSTEM` (non-destructive,
  handles matched-enrich + approved-new).
- `suv_structured/build_equipment.py` — statements builder + Neo4j writer (reuses `write_neo4j`);
  **no Qdrant**.
- `suv_structured/cli.py` — add an `equipment` subgroup: `fetch | parse | build`.
- `suv_structured/seeds/suv_equipment.yaml`, `suv_structured/seeds/suv_operators.yaml`.
- `graph/schema_whitelist.py` + `agents/tools/graph_query.py` (intelligence service) — read-path.
- `tests/test_suv_equipment_*.py` mirroring the Slice-1 test set.

## 11. CLI surface

```
odin-suv-structured equipment fetch                      # render the 5 sub-pages (inspection)
odin-suv-structured equipment parse                      # render+parse → seeds/suv_equipment.yaml (human review)
odin-suv-structured equipment build --dry-run            # write match_report.yaml (no writes)
odin-suv-structured equipment build --approved-matches <report.yaml>   # gated real build
```

`build` is gated identically to Slice 1: refuses without `--approved-matches`, validates approved
entries, re-derives + drift-checks against the live graph, runs the operator exactly-1 preflight, then
writes Neo4j only.

## 12. Testing strategy (TDD)

Tests first, per module. Fixtures = committed rendered markdown of all 5 sub-pages
(`tests/fixtures/suv_equipment_*.md`), so parser tests are network-free and reproducible.

- **parse**: table-row extraction across the 5 pages; count normalization edge cases (`"1+"`,
  `"939 in über 30 Varianten"`, `"337 (189 …)"`); service_end edge cases (`"2046 (20 Jahre)"`,
  `"N/A"`); note trimming; malformed-row skip + warn.
- **operators**: seed load/validate; `match` exactly-1 preflight passes/aborts; `create` builds the
  MERGE; rejects rows missing a decision.
- **match_report (generalized)**: target_type param; companies path unchanged (regression);
  WEAPON_SYSTEM `match`/`new`/`ambiguous`; PATRIOT-duplicate → ambiguous; the new-policy gate refuses
  approved `new` without `approved_new: true` + `evidence`.
- **write_templates / build_equipment**: OPERATES statement shape; type-guarded endpoints;
  edge properties; approved-new MERGEs the WS node; matched WS not mutated (only linked +
  alias-append).
- **Qdrant regression**: build produces 0 points, no `QdrantClient` instantiated.
- **read-path** (intelligence): `OPERATES` in whitelist; a "betreibt"-style question routes to a
  generic template (not free-Cypher).

## 13. Operational run (gated, dry-run default)

1. `equipment parse` → review `suv_equipment.yaml` in the PR.
2. `equipment build --dry-run` → `match_report.yaml`. Curate: resolve ambiguous, add canonicalize
   aliases for surface variants, mark deliberate creations `approved_new: true` + `evidence`. Confirm
   the operator seed decisions.
3. **Neo4j backup** (dump) before any write — equipment touches the curated WEAPON_SYSTEM corpus.
4. `equipment build --approved-matches <curated.yaml>` → writes operators (create rows) + OPERATES
   edges. Verify with Cypher (`MATCH (:Entity{type:"MILITARY_UNIT"})-[r:OPERATES]->(w) RETURN …`).
5. Deploy read-path change: rebuild/recreate the intelligence image from the worktree
   (`docker compose -p osint … --no-build` per the handoff deploy-friction note); no GPU swap.

## 14. Workflow & reviews

TDD mandatory (red→green→refactor). **Per task: two-stage review (spec-review + quality-review),
never skipped** (`[[feedback-never-skip-reviews]]`). **Plus an explicit adversarial gate-bypass review**
of the generalized gate + the OPERATES type-guard + the new-policy — the hard-won Slice-1 lesson (a
real gate bypass slipped past two ordinary reviews). Final holistic opus review, then a PR; CI green.

## 15. Out of scope
- Track 2b (procurements / Modernisierungsvorhaben) — separate spec.
- Qdrant profiles for equipment (deferred; may revisit in 2b).
- Resolving the operator/weapon-system duplicate nodes themselves (graph-integrity-geo owns it).
- A full `schema_whitelist` audit (only OPERATES, optionally HEADQUARTERED_IN, are added here).
- A `Bundeswehr` aggregate operator level (deferred per user direction).

## 16. Acceptance criteria
1. `equipment parse` renders all 5 sub-pages and writes `suv_equipment.yaml` with a sane row count
   (sanity floor, e.g. ≥30 systems total); refuses to overwrite on a near-empty/error render.
2. `equipment build --dry-run` classifies every system `match`/`new`/`ambiguous`; a known duplicate
   (PATRIOT) is `ambiguous`.
3. The build gate **refuses** an approved `new` WEAPON_SYSTEM lacking `approved_new: true` + `evidence`.
4. The operator exactly-1 preflight aborts the build when a `match` target is not unique.
5. The OPERATES template is type-guarded (`MILITARY_UNIT|ORGANIZATION` → `WEAPON_SYSTEM`) with
   MATCH-only endpoints; verified by template tests.
6. The equipment build creates **0 Qdrant points** and instantiates **no QdrantClient** (regression test).
7. `OPERATES` is in `schema_whitelist.RELATIONSHIPS`; a read-path test shows a "betreibt"-style
   question can surface OPERATES edges.
8. After a real build (`build --approved-matches <curated.yaml>`), `OPERATES` edges exist from the
   operator nodes to weapon systems with `count`/`service_end`, verifiable via Cypher; the companies
   path + full data-ingestion suite stay green.

## 17. Residual risks
- Operator duplicate selection is curated, not algorithmic — the exactly-1 preflight is the safety net.
- WEAPON_SYSTEM corpus is noisy (junk entities like "3D printers"); the new-policy + human curation
  mitigate bad auto-matches, but curation effort is real (~half of probed systems didn't exact-match).
- Re-points needed when graph-integrity-geo introduces canonical operator/system nodes (the
  `data_source` provenance makes this reversible).
