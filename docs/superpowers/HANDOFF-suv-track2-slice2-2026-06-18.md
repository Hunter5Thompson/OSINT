# HANDOFF — SUV Track 2 Slice 2 (Procurements + Equipment)

**Date:** 2026-06-18 · **For:** the next instance starting Slice 2 · **Base:** `main` (post-#55, has Slice 1 + HQ bridge). Auto-memory `[[suv-track2-slice2-procurements-equipment]]` + `[[suv-report-source]]` carry the same facts and load each session.

## TL;DR — where to start
Slice 1 (Companies) is **SHIPPED + LIVE + DEPLOYED**. Slice 2 = the **two remaining suv.report structured DBs** (procurements + equipment), **NOT started**. Begin with a **walking-skeleton** (prove crawl4ai deterministically extracts the two pages, like Slice 1's 77/77 company proof), then **Brainstorm → Spec → Plan → subagent-driven-development** with two-stage reviews per task + an explicit **adversarial gate-bypass review**. Reuse the Slice-1 machinery wholesale.

## DONE (live in prod, merged to main)
- **Slice 1 Companies** (PR #53 + #54 merged): module `services/data-ingestion/suv_structured/` (`schemas`, `fetch`, `parse` [deterministic, no LLM], `countries`, `write_templates`, `match_report`, `build_companies`, `cli` = `odin-suv-structured fetch|parse|build|backfill-hq`). **77 companies written** to Neo4j (3 enriched in-place: Rheinmetall/KNDS/Diehl Defence via curated canonicalize aliases; 74 new `Entity{type:"ORGANIZATION"}`, `data_source="suv.report"`, `sector="defense"`) + **77 Qdrant profiles** (`source=suv_structured`, `source_type=dataset`, `provider=suv.report`, credibility 0.78 read-side). Read-path verified live (ReAct query "Hensoldt" → SUV profile top hit, `sources_used=["suv.report"]`).
- **HQ Location Bridge** (PR #55 merged): `HEADQUARTERED_IN` links the 77 companies to existing `Entity{type:"LOCATION"}` (Germany/Netherlands). **77 edges live** (Germany 76, NL 1). Reversible bridge to LOCATION (NOT a COUNTRY ontology). Reversal: `MATCH ()-[r:HEADQUARTERED_IN {data_source:"suv.report"}]->() DELETE r`.
- **Deploy:** intelligence image rebuilt (corpus_policy admits `suv_structured/dataset`); data-ingestion-spark image rebuilt post-#55 (LOCATION template + `backfill-hq` live in the running `odin-data-ingestion-spark` container).

## Slice 2 scope
- **Sources (suv.report):** `/modernisierungsvorhaben/` (~40 procurement/modernization projects — Leopard 2, Puma: Stückzahl, Kosten, Status, Auslieferung) · `/category/datenbank/ausruestung/` (Hauptwaffensysteme / equipment).
- **Proposed graph model (DECIDE in brainstorm, not fixed):** company `-[PRODUCES]->` equipment · country/org `-[PROCURES|OPERATES]->` equipment · equipment `-[IN_CATEGORY]->` capability · a procurement-program node tying company+country+equipment+Stückzahl/Kosten/Status. Plus source-backed Qdrant profiles for equipment/procurement.
- **🔑 KEY DECISION (the crux):** the graph ALREADY has **1192 `Entity{type:"WEAPON_SYSTEM"}` nodes** + the event-codebook taxonomy. **LINK to existing WEAPON_SYSTEM entities** (entity-resolution + the hard `--approved-matches` gate), do NOT blindly create new ones — same "Name != Identity" + HQ-bridge "link existing, don't duplicate" lesson. NEW relation types (PRODUCES/PROCURES/OPERATES) go through the taxonomy + write-template contract → **coordinate with the `intel-codebook-curator` agent** (event_codebook.yaml + schemas.py + write_templates are one coherent system). `nlm_ingest`'s RELATION_TEMPLATES is key-locked → SUV relations live in `suv_structured/write_templates.py` (as in Slice 1).

## Proven workflow (do this)
1. **Walking-skeleton spike** (not TDD): `curl POST localhost:11235/md {"url":<page>,"f":"fit"}` → confirm the procurement/equipment fields are deterministically extractable. GO/NO-GO gate.
2. **superpowers:brainstorming** → spec to `docs/superpowers/specs/`; user reviews + approves; commit.
3. **superpowers:writing-plans** → bite-sized TDD plan to `docs/superpowers/plans/`.
4. **superpowers:subagent-driven-development** in an isolated git worktree off main: per task = sonnet implementer (TDD red→green) + **spec-review + quality-review (BOTH, never skip — `[[feedback-never-skip-reviews]]`)** + fix-loops; opus final-holistic; then a PR. CI must be green.
5. **Operational run** = a gated, dry-run-default CLI (like `backfill-hq`): present the enumerated entity matches to the user for curation (`[[feedback-entity-resolution]]`), Neo4j backup if writes are risky, then `--apply`.

## Reusable assets + patterns (copy from Slice 1)
- Deterministic crawl4ai parse (no LLM, no GPU), Pydantic schemas, `profile_text` helper.
- The **hard `--approved-matches` merge gate** (`match_report.py`: build_match_report is canonicalize-aware; load_approved rejects unsafe approvals; resolve_build_inputs name-authoritative + duplicate-write_name guard; detect_drift re-derives at build time).
- **canonicalize-aware matching** (`canonicalize.py` curated aliases → enrich existing entities in-place; add Slice-2 weapon-system aliases there if needed).
- corpus_policy `analysis` lane already admits `suv_structured/dataset` (intelligence, deployed).
- Qdrant: `provenance_fields(source_type="dataset", provider="suv.report")`, NO credibility in payload, point-id = uuid5 on `slug(name)` / full normalized name (NEVER on a shared URL — point-id collision gotcha), TEI embed `POST {tei_embed_url}/embed`.
- Neo4j HTTP tx writer pattern (`build_companies.write_neo4j` / `backfill_hq._run_read`): base64 basic-auth, `POST {neo4j_http_url}/db/neo4j/tx/commit`, raise on `data["errors"]`.

## Gotchas / lessons (hard-won)
- **Gate logic needs an explicit adversarial "try-to-bypass" review** — a real gate-bypass (AND-short-circuit on a shared key) slipped past TWO per-task reviews AND the holistic in Slice 1; only an adversarial pass caught it. Do this for any gate.
- **Point-id / join keys must be unique** — the SUV parser gives every row the same directory URL; key on name, never URL.
- **"Name != Identity"** — present enumerated match candidates for human approval; never auto-merge ambiguous; subsidiaries (Airbus D&S, MBDA Deutschland, Lufthansa Technik) are SEPARATE entities, not aliases of the parent.
- **NEVER `>` a tracked file** (a skeleton spike once clobbered `.gitignore`). Read+append.
- **Deploy friction (important):** the main checkout `/home/deadpool-ultra/ODIN/OSINT` is frequently on OTHER active work (e.g. a worldview-UX branch at the time of writing) — do NOT switch its branch. To rebuild a deployed image, build+recreate from your feature WORKTREE with `docker compose -p osint --profile <profile> build/up --no-build --no-deps <service>`. `docker-compose.override.yml` IS git-tracked (present in worktrees). compose reads `.env` from the **compose-file dir = the worktree ROOT** → copy `/home/deadpool-ultra/ODIN/OSINT/.env` to `<worktree>/.env` (gitignored) before any compose up.

## Environment facts
- **GPU constraint:** single RTX 5090, one LLM at a time. Ingestion LLM+TEI offloaded to the **DGX Spark** (`192.168.178.39`); the `odin-data-ingestion-spark` container (compose project `osint`, service `data-ingestion-spark`, profile `interactive-spark`) runs the scheduler locally but calls the Spark for LLM. Rebuilding/recreating the app container does NOT touch the GPU/Spark (no swap).
- **Services up (localhost):** crawl4ai `:11235`, Neo4j HTTP `:7474` (auth, password in `.env` `NEO4J_PASSWORD`), Qdrant `:6333` (collection `odin_intel`, 1024-dim), TEI embed `:8001`, intelligence `:8003`, backend `:8080`.
- **Tests:** `cd services/data-ingestion && uv run pytest` (NOT bare python3 — deps in uv venv). Full data-ingestion suite is ~965 passed / 1 pre-existing GDELT-integration skip. `cd services/intelligence && uv run pytest` for read-path.
- **Graph counts (for entity-resolution scale):** 5573 ORGANIZATION, 6254 LOCATION, **1192 WEAPON_SYSTEM**, 1026 MILITARY_UNIT, 7 COUNTRY (conflict-zones only).

## Open items / residual risks (not blockers for Slice 2, but know them)
- **HQ-bridge future-build risk (Codex, minor):** normal SUV `build` runs use the LOCATION template without the backfill's exactly-1 preflight; `WITH c, co LIMIT 1` prevents fan-out but would silently pick an arbitrary node if a 2nd Germany `Entity{LOCATION}` ever appears. Resolve via a shared HQ-target preflight or the canonical-country model.
- **graph-integrity-geo** workstream owns the geo duplication (Germany as LOCATION×1 + :Location label + ORGANIZATION + "Deutschland") + the eventual canonical COUNTRY model; the HQ bridge is re-pointable when it lands.
- **Worktree hygiene:** `.claude/worktrees/{suv-hq-bridge, suv-track2-skeleton}` are merged + can be `git worktree remove`d (each has a gitignored `.env` copy).

## Decisions to honor
- Deterministic extraction (no LLM on the write path); Two-Loop discipline (deterministic templates, `$param` binding, no LLM-Cypher, MATCH-only for endpoints you must not create).
- TDD mandatory; two-stage review per task + adversarial gate review; never skip.
- Link to existing entities (WEAPON_SYSTEM, companies, countries-via-LOCATION-bridge); curated approved merges only.

Spec/plan/handoff for Slice 1 + the bridge are under `docs/superpowers/{specs,plans}/2026-06-14-*` and `2026-06-16-suv-hq-location-bridge-*`. Source pages + master catalog: `[[reference-hugin-catalog]]`.
