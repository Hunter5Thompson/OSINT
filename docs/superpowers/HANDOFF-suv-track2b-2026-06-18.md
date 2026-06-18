# HANDOFF — SUV Track 2b (Procurements / Modernisierungsvorhaben)

**Date:** 2026-06-18 · **For:** the next instance executing Track 2b · **Base:** `main` `6a5ffbb` (2a + 2a.1 merged + live). Auto-memory `[[suv-track2-slice2-procurements-equipment]]` + `[[suv-report-source]]` carry the same facts and load each session.

## TL;DR — where to start
Track 2b is **fully spec'd + planned, NOT implemented**. The spec + plan are committed on branch
`feat/suv-track2b-procurements` (off `main`, pushed to origin, no PR yet). **Execute the 8-task plan
with `superpowers:subagent-driven-development`**, then a PR, then the operator-gated load. Just say
"execute the 2b plan". Everything below is context; the plan itself is the instruction set.

- **Spec:** `docs/superpowers/specs/2026-06-18-suv-track2b-procurements-design.md`
- **Plan:** `docs/superpowers/plans/2026-06-18-suv-track2b-procurements.md` (8 TDD tasks, complete code)
- **Branch:** `feat/suv-track2b-procurements` (check it out / new worktree off it; it already has the spec+plan + the 2a/2a.1 + Slice-1 machinery merged)

## DONE this session (all live in prod / merged to main)
- **SUV Track 2a — Equipment** (PR #59 + #60 merged): `(:MILITARY_UNIT|:ORGANIZATION)-[:OPERATES {count,count_raw,service_end,note}]->(:WEAPON_SYSTEM|AIRCRAFT|VESSEL|SATELLITE)`. Type-aware (2a.1) so aircraft/vessels link to existing nodes, not duplicated. **Loaded to PROD: 75 OPERATES edges** (WS40/AIRCRAFT22/VESSEL12/SAT1) from Deutsches Heer/Deutsche Marine/Deutsche Luftwaffe/Unterstützungsbereich/Cyber- und Informationsraum(created). 74 written via `build --approved-matches`, +1 (PATRIOT) after a Patriot/PATRIOT dedup. Graph-only (no Qdrant for equipment). Backups under `backups/suv-track2a1-*` and `backups/suv-track2a-patriot-*`.
- **PATRIOT dedup** (operator-done): survivor `Patriot` (+ alias `PATRIOT`), MENTIONS rehung, duplicate deleted, the `Deutsche Luftwaffe→Patriot` OPERATES edge written.
- **Module `services/data-ingestion/suv_structured/`** now has: `schemas, fetch, parse, countries, write_templates, match_report, build_companies, backfill_hq` (Slice-1 companies) + `equipment_schemas, equipment_parse, operators, build_equipment, system_types` (2a/2a.1). CLI `odin-suv-structured`: `fetch|parse|build|backfill-hq` (companies) + `equipment fetch|parse|build`. Seeds: `suv_companies.yaml`, `suv_operators.yaml`, `suv_equipment.yaml` (75).

## Track 2b scope (the plan implements this)
- **Source:** `/modernisierungsvorhaben/` — **30 programs**, single page grouped under the same 5 Teilstreitkraft `##` headings as 2a (Heer/Luftwaffe/Marine/Cyber- und Informationsraum/Unterstützungsbereich). Fields per `###` block: Typ, Projektstatus, Auftragnehmer, Stückzahl, Kosten, Finanzierung, Auslieferung, Beschreibung (+ a photo-caption line to skip).
- **Model (user-approved):**
  - `(:Entity {type:"PROCUREMENT_PROGRAM"})` — all 30 written (MERGE on title; NO entity-resolution gate — new node type, nothing pre-exists). Props: status, program_type, quantity, cost_eur, financing, delivery_start/end, description, branch, contractor_raw, data_source, suv_url, suv_extracted_at.
  - `(operator MU|ORG) -[:PROCURES]-> (program)` — operator from the **branch heading → 2a `suv_operators.yaml` canonical** (reuse `operator_for_branch`). Deterministic (no gate beyond the exactly-1 preflight inherited from 2a operators).
  - `(program) -[:CONTRACTED_TO]-> (:ORGANIZATION)` — Auftragnehmer: `split_contractors` (consortia `A & B`/`A, B`/`Konsortium (…)`; `/`,`N/A`→none). **Match-gated, LINK-ONLY** (no node creation): match→link, ambiguous→resolve, new→no edge (contractor_raw retains it). ~6/30 exact-match today (canonicalize + curation lifts it).
  - `(program) -[:CONCERNS_SYSTEM]-> (equipment)` — subject equipment detected from the title (`subject_candidate`, longest existing-name match), **match-gated + OPTIONAL** (~12/30 have a clean subject; descriptive programs have none).
- **Qdrant: YES** — one profile per program (rich Beschreibung). **Neo4j-first** (graph write must succeed before any Qdrant upsert). point-id `uuid5(SUV_QDRANT_NAMESPACE, "suv_procurement_program|"+normalized_title)` — namespaced apart from company points. Payload incl. structured fields (program_status/type, quantity, cost_eur, financing, delivery) + entities (program + contractors + linked systems).
- **New types are SUV-owned** (write_templates in `suv_structured/`) + documented in the read-path (`schema_whitelist` RELATIONSHIPS + graph_query intent). **NOT** in `event_codebook.yaml` or the nlm `RelationType` Literal. Coordinate the relation/node wording with the `intel-codebook-curator` agent.

## Proven workflow (do this)
1. Fresh worktree off `main` (or check out `feat/suv-track2b-procurements`). Copy `/home/deadpool-ultra/ODIN/OSINT/.env` to the worktree root (gitignored) for any CLI/compose run.
2. `superpowers:subagent-driven-development` over the 8-task plan: per task = a sonnet implementer (TDD red→green) + **spec-review + quality-review (BOTH, never skip)** + fix loops. Use **opus + an adversarial pass** for the gate-relevant tasks (Task 5 templates + Task 6 builder: type-guards, MATCH-only endpoints, program-upsert-before-edges, contractor/subject link-only no-creation, Neo4j-first Qdrant). Final whole-branch opus review. Keep an SDD ledger (`$(git rev-parse --git-path sdd)/progress-2b.md`).
3. PR against `main`; CI green (the diff-based ruff gate + guard-read-templates + the service test jobs).
4. **Operator-gated load** (post-merge, HUMAN GATE): `procurements parse` → review `suv_procurements.yaml` → `procurements build --dry-run` → curate the combined contractor+subject match report (resolve ambiguous; programs+operators are automatic) → **Neo4j backup** → `procurements build --approved-matches`. Verify 30 PROCUREMENT_PROGRAM + 30 PROCURES + N CONTRACTED_TO + ~12 CONCERNS_SYSTEM + 30 Qdrant profiles.

## Reusable assets / patterns (copy from 2a — the plan already does)
- Deterministic crawl4ai parse (no LLM); the `###`+`**label:**` block parser (Slice-1 companies) + branch-tracking (`##`); cost parsing reuses Slice-1 `parse_revenue_eur` logic (Mrd/Mio + comma-decimal).
- The generalized `match_report` (`build_match_report(items, lookup, *, target_type, gate_new_creation, target_type_of)` + `load_approved`) — reused as-is for the contractor (ORGANIZATION) + subject (equipment types) surfaces. 2b is LINK-ONLY so `gate_new_creation` is not needed (new→no edge).
- `operators.py` (the 5 canonical Teilstreitkräfte + exactly-1 preflight); add `operator_for_branch`.
- Neo4j HTTP tx writer `build_companies.write_neo4j`; Qdrant `SUV_QDRANT_NAMESPACE` + `embed_text` + `provenance_fields(source_type="dataset", provider="suv.report")`; corpus_policy already admits `suv_structured/dataset` on the read-path.
- Read-path: `schema_whitelist.RELATIONSHIPS` (now has INVOLVES/REPORTED_BY/OCCURRED_AT/MENTIONS/OPERATES/HEADQUARTERED_IN — add PROCURES/CONTRACTED_TO/CONCERNS_SYSTEM); `graph_query._match_intent` (add procurement keywords → `one_hop`); `one_hop` is generic `-[r]-` so edges surface.

## Gotchas / lessons (hard-won this session)
- **Gate logic needs an explicit adversarial "try-to-bypass" review** (the Slice-1 lesson; held through 2a/2a.1 — opus probed every type-guard/ordering). Do it for 2b's templates + builder.
- **`detect_drift` blocks a hand-resolved ambiguous→match** — you cannot "explain" an ambiguous to a match via the approved report; the graph must be made unambiguous first (that's why PATRIOT needed the dedup before its edge). 2b contractors/subjects: resolve ambiguous by curation, not by overriding.
- **Plan code snippets must be ≤100 cols** — 3 ruff E501s in 2a/2a.1 traced to over-length test lines in the plan; the implementers transcribe verbatim. (The 2b plan was written ≤100; verify with `ruff check` per task anyway — implementers must run ruff, not just pytest.)
- **CLI reads `.env` relative to CWD** — for any `odin-suv-structured` run, `set -a; . ./.env; set +a` from the worktree root first, then cd to `services/data-ingestion`. (config.py `env_file=".env"`.)
- **The graph is large** (907k nodes / 20M rels). A full `neo4j-admin dump` is heavy + needs downtime (community, no online dump). For an **additive** load, take a **targeted** backup (pre-state of the few pre-existing nodes you'll mutate) + rely on `data_source="suv.report"` tagging for reversibility — see `backups/suv-track2a1-*/SNAPSHOT_AND_REVERSAL.md`. 2b programs are all-new + link-only, so the mutation surface is tiny.
- **Point-id collisions** — key Qdrant points on a namespaced uuid5 (`"suv_procurement_program|"+title`), never a shared URL.
- **"Name != Identity"** (`[[feedback-entity-resolution]]`) — present enumerated matches for approval; subsidiaries/consortium members are separate entities; never auto-merge. 2b contractors: link-only, no creation (new firms belong to the companies source).
- **Deploy friction** — the `/home/deadpool-ultra/ODIN/OSINT` main checkout is often on other work; build/recreate deployed images from the feature WORKTREE with `docker compose -p osint … --no-build`. `docker-compose.override.yml` is git-tracked.

## Environment facts
- **GPU:** single RTX 5090, one LLM at a time; ingestion LLM+TEI offloaded to the DGX Spark (`192.168.178.39`); `odin-data-ingestion-spark` container runs the scheduler locally. Rebuilding the app container does NOT touch the GPU/Spark.
- **Services up (localhost):** crawl4ai `:11235` (0.8.6), Neo4j HTTP `:7474` (5-community + APOC 5.26; auth in `.env` NEO4J_PASSWORD), Qdrant `:6333` (collection `odin_intel`, 1024-dim; 77 suv_structured company points + the corpus), TEI embed `:8001`, intelligence `:8003`, backend `:8080`.
- **Tests:** `cd services/data-ingestion && uv run pytest` (~1016 pass / 1 GDELT skip after 2a.1) — never bare python. `cd services/intelligence && uv run pytest` (~323) for the read-path.
- **Graph counts (post-2a load):** WEAPON_SYSTEM ~1268 (1229 + 39 new), AIRCRAFT/VESSEL/SATELLITE enriched-or-new from 2a, 75 OPERATES edges, operators (Deutsches Heer/Deutsche Luftwaffe/Deutsche Marine MU, Unterstützungsbereich ORG, Cyber- und Informationsraum MU created). 5573+ ORGANIZATION (Slice-1 companies among them).

## Open items / residual (not blockers for 2b)
- **2b prod load** is the operator-gated step AFTER the 2b PR merges (HUMAN curation of the contractor+subject match report + Neo4j backup, as above).
- **HQ-bridge future-build preflight** (minor, from Slice-1) and **graph-integrity-geo** (owns the geo/duplicate canonicalization) are separate workstreams.
- **Worktree hygiene:** `.claude/worktrees/suv-track2a-equipment` hosted 2a + 2a.1 + 2b-prep (all merged or pushed); it can be `git worktree remove`d once 2b is checked out fresh. Each worktree has a gitignored `.env` copy.

Spec/plan/handoffs for the whole Track 2 line live under `docs/superpowers/{specs,plans}/2026-06-14-suv-*` (companies), `2026-06-16-suv-hq-*` (bridge), `2026-06-18-suv-track2a-*` / `2026-06-18-suv-track2a1-*` (equipment) and `2026-06-18-suv-track2b-*` (this). Source pages + master catalog: `[[reference-hugin-catalog]]`, `[[suv-report-source]]`.
