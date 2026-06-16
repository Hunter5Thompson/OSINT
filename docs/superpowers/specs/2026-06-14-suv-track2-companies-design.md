# SUV Track 2 — Slice 1: Defense Companies → Graph + Qdrant

**Date:** 2026-06-14
**Status:** Design approved (with review corrections folded in); ready for implementation plan.
**Author:** RT + Claude
**Related:** [[reference_suv_source]] (Track 1 merged PR #41), `infra_atlas` (structured-data precedent), entity-resolution policy ("Name != Identity").

---

## 1. Goal & Scope

Ingest the curated **defense-industry company directory** from `suv.report/sicherheits-und-verteidigungsindustrie/` (~77 companies: HQ, employees, revenue, products) into ODIN as:

- **Neo4j graph enrichment** — companies as `Entity{type:"ORGANIZATION"}`, enriched in-place, plus a `HEADQUARTERED_IN` relation.
- **Qdrant semantic profiles** — one searchable profile per company, reachable by the ReAct agent's `qdrant_search` tool.

**This is Slice 1 of Track 2.** Out of scope (later slices): the procurement/modernization dataset, the weapon-systems database, `PRODUCES` relations, any UI/almanac surface, map lat/lon for companies.

### Success criteria
1. `seeds/suv_companies.yaml` exists, git-committed, human-reviewed, holds ~77 validated company records.
2. Re-running the builder is deterministic, GPU-free, idempotent (no duplicate nodes/points on re-run).
3. The ReAct agent can answer a company question (e.g. *"Standort und Umsatz von Hensoldt?"*) from the Qdrant profile via the analysis lane.
4. Graph query `MATCH (c:Entity{type:"ORGANIZATION"})-[:HEADQUARTERED_IN]->(co:Entity{type:"COUNTRY"})` returns SUV companies linked to existing country nodes.
5. No existing entity properties or aliases are clobbered; merges happen only via the hard `--approved-matches` gate (a curated, approved `match_report.yaml`).

---

## 2. Architecture — 4 isolated stages

```
fetch.py        crawl4ai (HTTP service, JS-rendered) → rendered markdown of the directory
   ↓
extract.py      LLM (vLLM 9B, already loaded) → List[Company]  (Pydantic-validated, batched if needed)
   ↓
seeds/suv_companies.yaml   ← git-committed, HUMAN-REVIEWED          ★ quality gate (neutralizes LLM hallucination)
   ↓
build_companies.py   deterministic (NO LLM, NO GPU) → Neo4j templates + Qdrant profile points
```

New module: `services/data-ingestion/suv_structured/` mirroring `infra_atlas`/`nlm_ingest` conventions:

```
suv_structured/
  __init__.py
  schemas.py          # Pydantic Company model
  fetch.py            # crawl4ai HTTP render (reuses feeds/_fulltext_fetch pattern)
  extract.py          # LLM markdown → List[Company]
  write_templates.py  # deterministic Cypher for SUV (HEADQUARTERED_IN) — separate from nlm_ingest
  build_companies.py  # deterministic graph + qdrant writer; dry-run + --approved-matches gate
  cli.py              # odin-suv-structured: fetch | extract | build [--dry-run|--approved-matches]
  seeds/
    suv_companies.yaml
```

### Why this shape
- crawl4ai handles the JS/AJAX-rendered directory (the data is **not** in static HTML; it loads via `admin-ajax.php`). crawl4ai's `/md` runs a headless browser server-side → JS is rendered. **Walking-skeleton task verifies this returns the 77 companies** before anything else is built; fallback would be reverse-engineering the admin-ajax action.
- The committed YAML snapshot is the human review checkpoint and makes the **write path LLM-free and reproducible** (Two-Loop discipline: no LLM-generated Cypher on the write path).
- crawl4ai is consumed **as an HTTP service** (`POST {settings.crawl4ai_url}/md`), exactly like `_fulltext_fetch._crawl4ai_md` — **no new Python/browser dependency** is introduced.

---

## 3. Data model — enrich `Entity`, do not duplicate

**Decision:** Keep companies in the generic `Entity{name, type:"ORGANIZATION"}` model. **No `:Company` label** — the ReAct `graph_query` tool and `/graph/search` operate uniformly over `:Entity`; a second label would fragment queries. *(Review-confirmed: correct for the current graph.)*

The builder enriches in place:
- Trim/normalize each SUV name via `canonicalize_entity` (it preserves the original spelling in `aliases`).
- **MATCH** an existing `Entity` by canonical name (case-insensitive). If found → enrich. If not → `MERGE` a new `Entity{type:"ORGANIZATION"}`.
- Enrichment uses **targeted `SET` of named properties only** — never `SET e = {...}` and never clearing `aliases`:
  - `hq_country`, `employees`, `revenue_eur`, `founded`, `website`, `products` (list), `sector:"defense"`, `suv_url`, `data_source:"suv.report"`, `suv_extracted_at`.
  - `aliases` is **appended + deduplicated** (mirrors `canonicalize.py:127` semantics), never overwritten.

### Entity-resolution gate — MANDATORY (not optional)
`canonicalize.py:15` is deliberately **no fuzzy/semantic matching**; unknown names pass through unchanged. So it will **not** match `"Rheinmetall AG"` → existing `"Rheinmetall"` for us. Therefore the builder MUST:
1. Run `--dry-run` first, producing an **enumerated match report** as a YAML artifact (`match_report.yaml`): for each SUV company → `decision: match|new|ambiguous`, the proposed `existing_name`/`elementId` (or candidates for ambiguous), and an `approved: false` field.
2. **Hard, machine-checkable gate (not just process discipline):** the real build runs **only** with `--approved-matches path/to/match_report.yaml`. Without it the build refuses (no writes). With it, the build:
   - writes only entries where `approved: true`;
   - refuses/aborts if any entry is still `ambiguous` or `approved: false` that it was asked to act on;
   - re-derives matches from current data and aborts if they diverge from the approved report (so a stale approval can't silently write the wrong merges).
3. Ambiguous/alias cases (e.g. `Rheinmetall AG` vs `Rheinmetall`) are surfaced for curation — a confirmed alias gets added to `canonicalize.py`'s `_ALIAS_GROUPS` (or an explicit per-run override map) so the match is deterministic on the real run and future runs.

This honors the "Name != Identity, only curated alias merges, present enumerated list for approval" policy and makes the approval a technical sperre, not a convention.

---

## 4. Relations — `HEADQUARTERED_IN` only this slice

- **`HEADQUARTERED_IN`** — a **new deterministic template in `suv_structured/write_templates.py`** (NOT `nlm_ingest`): `Entity{ORGANIZATION}` → `Entity{type:"COUNTRY"}`, via **MATCH-only** for the country (never MERGE → no phantom countries, consistent with the write-path rule). If the country entity does not exist, the relation is skipped (logged), not fabricated.
  - **Why not `nlm_ingest/write_templates.py:RELATION_TEMPLATES`:** that dict is key-locked to `nlm_ingest.schemas.RelationType` by `test_nlm_relations.py:56` (`set(RelationType) == set(RELATION_TEMPLATES.keys())`). Adding `HEADQUARTERED_IN` there breaks the test unless we also extend `RelationType` + the NLM extraction prompt + NLM tests. We only do that if NLM should *itself* extract HEADQUARTERED_IN — out of scope here. SUV keeps its own template.
- **Products are a property (`products: [...]`)**, not a `PRODUCES` relation. WeaponSystem nodes with real data arrive in the weapons slice; creating stubs now = phantom/low-quality nodes (YAGNI).

### Documented query expectation (Slice 1)
> Manufacturer questions ("Wer baut den Leopard 2?") are answered in Slice 1 via **Qdrant profiles + the `products` property**, NOT via graph traversal. The `(Company)-[:PRODUCES]->(WeaponSystem)` traversal becomes available only after the weapons slice.

### Geo caveat (documented non-goal)
`/graph/search` derives lat/lon by `OPTIONAL MATCH (e)-[…|HEADQUARTERED_IN]->(l:Location)` (`graph.py:233`) — it joins to a `:Location` node, **not** `Entity{COUNTRY}`. Our `HEADQUARTERED_IN → Entity{COUNTRY}` is fine for traversal but will **not** light up company lat/lon on the map. Map coordinates for companies are **out of scope for Slice 1**; if wanted later, either extend the read query or build a Country↔Location bridge.

---

## 5. Qdrant — agent-queryable profiles

One point per company in `odin_intel` (1024-dim, TEI embed at `:8001`):

- **Vector:** embedding of the profile `content` (name + aliases + HQ + revenue + employees + products + short description).
- **Point id:** deterministic uint64 derived from the canonical `suv_url` (same approach as `fulltext_point_id`) → idempotent re-runs.
- **Payload (write-side facts only):**
  ```python
  {
    "source": "suv_structured",
    **provenance_fields(source_type="dataset", provider="suv.report"),  # source_type, provider
    "ingested_at": <caller-set ISO8601>,
    "title": company_name,
    "content": <profile text>,
    "entities": [{"name": company_name}],
    "url": suv_url,
    "content_hash": <sha256 of content>,
  }
  ```
- **NO `credibility` field.** Per `provenance.py:1`, write-side provenance = facts; credibility is read-side. `suv.report` is already a read-side provider override = `0.78` (`credibility.py:60`), so the analysis lane scores it correctly without us writing anything.
- Optionally add `"suv_structured": "suv.report"` to `provenance.DATASET_PROVIDERS` for single-source consistency.

### Read-path enablement (cross-service — `services/intelligence`)
The agent currently **cannot** see this source. `rag/corpus_policy.py` must open — but carefully, because the current `validate_lane` checks identity and type **independently** (`:111-114`):

```python
identity = r.get("source") in ANALYSIS_SOURCES or bool(r.get("notebook_id"))
type_ok  = st is None or st in _ANALYSIS_TYPES
ok = identity and type_ok
```

Naively doing `_ANALYSIS_TYPES += "dataset"` is a **leak**: `{source:"rss", source_type:"dataset"}` would pass (identity True via rss, type_ok True via dataset). And many real dataset collectors (firms/usgs/… via `base.py:118`) stamp `source_type:"dataset"`.

**Correct change — validate the `source ↔ source_type` *pair*:**
1. `ANALYSIS_SOURCES` (`:18`) `+= "suv_structured"` (opens `analysis_filter()` `:39` — the broad first barrier).
2. Replace the flat `_ANALYSIS_TYPES` set with a canonical **source→expected-source_type map** for the analysis lane:
   - `"rss" → "rss"`, `"rss_fulltext" → "rss"` (verified `fulltext_collector.py:79`), `"suv_structured" → "dataset"`;
   - NLM via `notebook_id` → expected `"notebooklm"` (or legacy `None`).
   `validate_lane` then requires `st is None or st == expected[source]` — so the pair must be coherent.

This **drops** `rss/dataset` and `suv_structured/rss`, **keeps** `rss/rss`, `rss_fulltext/rss`, `suv_structured/dataset`, NLM/`notebooklm`. It also stays at least as strict as today (e.g. `rss/gdelt` still dropped — no regression to the existing AC-2 behavior).

Tests required: filter test (suv_structured point retrievable) **and** explicit lane-guard tests that **drop `rss/dataset` and `suv_structured/rss`** while keeping the valid pairs above.

---

## 6. Provenance & credibility summary

- Write side (this slice): `source_type:"dataset"`, `provider:"suv.report"`, `ingested_at` — via `provenance_fields`. Snapshot YAML + `suv_url` are the auditable origin.
- Read side (already in place): `suv.report → 0.78` in `credibility.py`; analysis-lane tier-boost uses it once the lane is opened.

---

## 7. Packaging / wiring (must ship with the module)

- `pyproject.toml [project.scripts]` (`:37`): add `odin-suv-structured = "suv_structured.cli:cli"`.
- `pyproject.toml [tool.hatch.build.targets.wheel].include`: add `"suv_structured/**/*.py"` and `"suv_structured/seeds/*.yaml"`.
- `Dockerfile` (`:25` COPY block): add `COPY services/data-ingestion/suv_structured/ suv_structured/`.
- **No new runtime dependency** — crawl4ai/docling reached via HTTP (`settings.crawl4ai_url`); TEI via HTTP; Neo4j/Qdrant clients already present.
- `.vscode`/workspace/test-panel: ensure the new module's tests are discoverable (per the "tests always visible" rule).

---

## 8. TDD plan (tests first, red → green)

- `schemas.py`: Company model validation (required name; numeric coercion for revenue/employees; products list).
- `extract.py`: fixture rendered-markdown → `List[Company]`; malformed rows rejected, not silently dropped to garbage.
- `seeds` roundtrip: extract → YAML dump → reload equals.
- `build_companies.py` against mock Neo4j/Qdrant:
  - in-place enrich (MATCH path) does **targeted SET**, appends+dedups aliases, clobbers nothing;
  - NEW path MERGEs `Entity{ORGANIZATION}`;
  - `HEADQUARTERED_IN` (SUV template) is MATCH-only (skips + logs when country absent);
  - idempotent re-run (no dup points/relations);
  - `--dry-run` writes nothing and emits the `match_report.yaml` artifact;
  - **gate:** build without `--approved-matches` refuses (no writes); build with a report still containing `ambiguous`/`approved: false` entries refuses those; build aborts when re-derived matches diverge from the approved report.
- Qdrant payload: no `credibility` key; provenance fields present; deterministic point id.
- `corpus_policy` (intelligence service): filter test (suv_structured retrievable) **+ pair lane-guard tests** that drop `rss/dataset` and `suv_structured/rss` and keep `rss/rss`, `rss_fulltext/rss`, `suv_structured/dataset`, NLM/`notebooklm` — plus a regression test that `rss/gdelt` is still dropped.

---

## 9. Implementation order (locked)

1. **crawl4ai walking-skeleton** — confirm the HTTP render returns the ~77 companies (else pivot to admin-ajax). Gate for everything else.
2. **Tests red** — schemas, extract, builder, corpus_policy.
3. **`suv_structured/` module** — fetch, extract, schemas, build (green), + packaging wiring.
4. **Qdrant analysis-lane enablement** — `corpus_policy` pair-validation change + tests.
5. **Merge gate** — `--dry-run` emits `match_report.yaml`; human curates/approves it; the real run requires `--approved-matches <report>` (hard gate) and writes graph + Qdrant.

---

## 10. Open questions / risks

- **crawl4ai JS render sufficiency** (resolved by step 1 walking-skeleton).
- **LLM context size**: the full directory markdown may exceed the 9B context → `extract.py` may paginate into batches and concatenate validated results.
- **Country naming**: SUV HQ country strings (German: "Deutschland") must map to the existing `Entity{COUNTRY}` names used in the graph (likely English) — a small country-name normalization map may be needed for the `HEADQUARTERED_IN` MATCH; unmatched → relation skipped (logged), surfaced in the dry-run report.
