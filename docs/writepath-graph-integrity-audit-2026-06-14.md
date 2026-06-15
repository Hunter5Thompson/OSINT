# ODIN / WorldView — Write-Path & Graph-Integrity Deep Audit

**Date:** 2026-06-14
**Auditor:** Claude (Opus 4.8) — focused deep-dive, distinct from the broad `bug-hunt-log-2026-06-14.md`.
**Scope (narrow, by design):** the ingestion **write path** and **graph integrity** seam only —
`pipeline.py` + feed collectors, the `gdelt_raw/` batch subsystem, `nlm_ingest/` writers, and `graph_integrity/`
(~6 000 LOC). Read-path/frontend/infra were out of scope (covered by the broad hunt + its verification appendix).
**Method:** 6 failure-mode lenses (dual-write atomicity, idempotency/dedup, write determinism/schema/geo, gdelt_raw
recovery/state, NLM provenance + geo-backfill, cross-path integration) → **16 candidate findings**, each then
**adversarially verified per-finding against the real code** (try-to-refute, reproduction-must-hold). The three
highest-impact confirmed findings were additionally hand-checked by the author. No source modified.

## Why this audit exists

The broad "visit every file" hunt scored ~1 real bug per 22 findings (see the Verification Pass in
`bug-hunt-log-2026-06-14.md`): most were dev-defaults or over-rated. The one real bug (`BH-EDGE-WRITE-01`) sat at
**one architectural seam** — the Neo4j↔Qdrant dual-write — and the broad sweep had missed *half* of it (the
`CREATE`-vs-`MERGE` duplication). Conclusion: depth at the right seam beats breadth. This audit drilled that seam.
Signal ratio: **10 of 16 candidates are real defects** (2 High, 8 Medium) + 2 Low + 2 refuted.

## Relationship to the known bug

`BH-EDGE-WRITE-01` (confirmed earlier): live pipeline writes `Event` via `CREATE` (`pipeline.py:519`) while dedup is
Qdrant-point-keyed and the Neo4j write is fail-soft → orphan-vector window + duplicate Events on retry. Several
findings below are **distinct, deeper consequences of that same root** (WP-01, WP-03), not restatements.

---

## Executive Summary — prioritized

| ID | Sev | Class | Subsystem | One-line |
|----|-----|-------|-----------|----------|
| **WP-01** | **High** | DATA_LOSS | live pipeline | Neo4j-outage tick commits vector+Redis but **no graph node**; Qdrant-keyed dedup then **permanently** blocks the retry → silent permanent loss + phantom live event |
| **WP-02** | **High** | DATA_LOSS | gdelt_raw | One row with an empty `GKGRecordID` **null-poisons the whole slice's** Documents+Mentions+Qdrant batch; permanent loss while state shows a false-recoverable "pending" |
| WP-03 | Medium | DUPLICATION | live pipeline | Deferred **batch** Qdrant upsert + `CREATE` Event widens the dup window from 1 item to a whole batch (≤50) on crash/transient |
| WP-04 | Medium | DUPLICATION | cross-path | RSS writes **lowercase** entity type, NLM writes **UPPERCASE** → one real entity becomes **two nodes**; name-only MATCHes fan out to all (hits core RAG quality) |
| WP-05 | Medium | CORRUPTION | live pipeline (geo) | Multi-country document → **every** event geo-stamped to the **first** location's country centroid (wrong-country on the globe) |
| WP-06 | Medium | CORRUPTION | gdelt collector (time) | Collector reads `seendate` then **discards** it → all GDELT Events `time_basis='ingested'`; CHRONIK histogram mis-buckets + re-ingest drift |
| WP-07 | Medium | CORRUPTION | graph_integrity (geo) | Name-keyed incident `Location` **collides** distinct incidents at different coords; `ON CREATE`-only freezes first coords; metric still counts "located" |
| WP-08 | Medium | correctness | read-path vs write-path | `ev.timestamp` is **never written** by any write-path → `/graph/events(/geo)` + intel graph tool return null timestamps and `ORDER BY … DESC` is a no-op |
| WP-09 | Medium | SILENT_SKIP | gdelt_raw | `MENTIONS` edges silently dropped when the citing article never became a theme-matched `Document`; no metric (spec'd `gdelt_mentions_written_total` absent) |
| WP-10 | Medium | SILENT_SKIP | gdelt_raw | Hard crash (OOM/SIGKILL) between parquet `last_slice` advance and pending-enqueue **strands a 15-min slice**; recovery never re-touches it |
| WP-11 | Low | CORRUPTION | gdelt geo | Literal `0,0` → **null-island** `Location` collapses geoless events onto one shared node, counted as "located" (shared by live writer + backfill) |
| WP-12 | Low | SILENT_SKIP | gdelt_raw | Fallback parser (`ignore_errors=True`) null-coerces type-corrupt cells; quarantine is tab-count-only so `parse_error_pct` undercounts; rows silently vanish |
| ~~L6-a~~ | — | refuted | graph_integrity | Geo-backfill "no-op" thesis **false** — it genuinely repairs pre-geo-transform events; only the docstring rationale is wrong (Low doc nit) |
| ~~L2-a~~ | — | refuted | rss collector | "Google-News token rotates every run → duplicates" — **empirically false**, tokens are stable across fetches; dedup works |

---

## CONFIRMED findings (detail)

### WP-01 — Neo4j-outage tick: permanent silent loss of the graph node + phantom live event · **High / DATA_LOSS** · (lens L1-a)
**Where:** `pipeline.py:319-327` (fail-soft Neo4j), `:329-344` (Redis xadd proceeds), `:346-353` (enrichment returned), `:547-553` (`_write_to_neo4j` raises **raw httpx** via `raise_for_status`); `feeds/gdelt_collector.py:152-158` (Qdrant-keyed dedup), `:178-189` (only `Extraction*` caught, then embed), `:214-218` (batch upsert); `feeds/rss_collector.py` identical.
**Mechanism:** A Neo4j outage surfaces inside `_write_to_neo4j` as a *raw* `httpx.*` error — **not** an `ExtractionTransientError`/`ExtractionConfigError`. The bare `except Exception` at `pipeline.py:326` swallows it (log only), so `process_item` returns a full enrichment dict (no failure signal) and the Redis event has already fired. Back in the collector, the two `except Extraction*` clauses don't match, so embed + Qdrant upsert commit the vector. Dedup keys solely on the Qdrant `point_id` (`sha256(title|url)`), with no Neo4j check and no reconciliation job anywhere.
**Reproduction (holds):** Neo4j down for one tick → vector lands in `odin_intel` + Redis event broadcast to the live frontend, graph node absent. Next tick: `qdrant.retrieve` finds the point → `continue` → `process_item` is **never re-invoked** → the Event/Document/Entity nodes are **permanently** missing.
**Why it matters / not by-design:** This is the *inverse and worse* outcome of `BH-EDGE-WRITE-01`: there the failure was a transient orphan-vector + duplicate node; here it's **permanent** loss plus a phantom live-stream event the graph has no record of. No code path heals it.
**Fix direction:** propagate `_write_to_neo4j` failures as a transient signal the collector treats like the other transients (`continue` **without** appending the PointStruct, so the Qdrant dedup key is never minted); and/or write graph-first/gate Qdrant on Neo4j success + `MERGE` the Event on a stable key; add a Qdrant↔Neo4j reconciliation sweep; don't emit the Redis event until the graph write succeeds.

### WP-02 — One empty `GKGRecordID` null-poisons the entire slice's docs/mentions/vectors · **High / DATA_LOSS** · (lens L4-a)
**Where:** `gdelt_raw/parser.py:59` (`null_values=[""]` keeps the null key), `filter.py:93` (`.unique(subset=["gkg_record_id"])` — no `drop_nulls`), `:118-120` (`map_elements` yields `doc_id=null`), `:135` (`n_unique` invariant counts null → passes), `writers/neo4j_writer.py:202` (fail-fast `model_validate` list-comp raises on `doc_id=None`), `writers/qdrant_writer.py:145` (`uuid5(NAMESPACE_URL, None)` → TypeError), `run.py:143-170` + `recovery.py:42-62`.
**Mechanism (verified link-by-link):** strict/fallback parser keep an empty leading `GKGRecordID` as polars `null` (no quarantine; gate checks tab-count only). `unique()` + the `n_unique` invariant both treat `null` as a value → nothing filters/trips. `map_elements` yields `doc_id=null`, survives the parquet round-trip. The Neo4j writer's fail-fast comprehension raises `ValidationError` on `doc_id=None` **before** any doc is written; the Qdrant writer's `uuid5(…, None)` raises `TypeError` before its single end-of-loop upsert. `run.py` advances `last_slice[parquet]` independently and only the *Events* for that slice persist — **all** that slice's `GKGDocument`s, `FROM_SOURCE`/`ABOUT`/`MENTIONS` edges, and Qdrant GKG vectors are lost. `recovery.py` re-reads the same poisoned parquet, re-fails, and leaves the slice in `pending` → **state shows "recoverable" but loss is permanent**.
**Severity rationale:** High not Critical — requires a GKG row with an empty `GKGRecordID` (a malformed-record condition; real-world frequency unverified). The structural defect is unambiguous: a single such row silently destroys that slice's matched-document corpus across both stores, forever.
**Fix direction:** quarantine null/empty keys at the parse gateway (count them into `parse_error_pct`); add `.drop_nulls(subset=["gkg_record_id"])` before `filter.py:93` and tighten the invariant to assert `doc_id` null-count == 0; make the writer comprehensions skip-and-log invalid rows instead of fail-fast; guard `qdrant_point_id_for_doc` against `None`. Add a fixture test with one empty leading `GKGRecordID`.

### WP-03 — Deferred batch Qdrant upsert amplifies the duplicate window to a whole batch · Medium / DUPLICATION · (lens L1-b, extends BH-EDGE-WRITE-01)
**Where:** `feeds/gdelt_collector.py:142-219` (per-item `process_item` at `:170`, dedup at `:153`, **single** post-loop upsert at `:214-218`; per-query `except` at `:239`); `feeds/rss_collector.py:260-342`; `pipeline.py:319-327` + `:519` (`CREATE`). Batch widths: GDELT `maxrecords=50`, RSS `MAX_ENTRIES_PER_FEED=15`.
**Mechanism:** the `points` list accumulates across the whole query while `process_item` commits a *per-item* Neo4j tx + Redis xadds, all **before** the one post-loop `qdrant.upsert`. Because Event is `CREATE` (not `MERGE`) and dedup is Qdrant-keyed, any item whose point never reaches Qdrant becomes a **permanent** duplicate on the next re-fetch. Two triggers hold: (1) process kill (OOM/deploy/restart) between the last per-item Neo4j commit and the post-loop upsert; (2) the **unguarded** `qdrant.retrieve` dedup call mid-loop throwing → caught only by the per-query `except` → the entire accumulated batch is discarded. Blast radius = up to 50 (GDELT) / 15 (RSS), strictly larger than the per-item KNOWN window.
**Fix direction:** make Event idempotent — `MERGE` on a deterministic id (`content_hash` already computed) instead of `CREATE` (fixes the KNOWN window *and* this one); upsert each point inside the loop right after its side effects; wrap the `qdrant.retrieve` dedup call; log unflushed-point count on the except path.

### WP-04 — Cross-path Entity key split (lowercase RSS vs UPPERCASE NLM) fragments the graph · Medium / DUPLICATION · (lens L3-c)
**Where:** `pipeline.py:248-251` (lowercase enum), `:465-481` (normalize gated off, `MERGE {name,type}`); `config.py:124` (`entity_type_normalize: bool = False`); `nlm_ingest/schemas.py:10-14` (`EntityType` UPPERCASE Literal), `write_templates.py:16` (`MERGE {name,type}`), `:70/:113-114` (name-only MATCH/RELATION templates); backend read-path `routers/graph.py` (name-only MATCH); `migrations/neo4j_duplicate_merge.cypher:4-11` (acknowledges ~414 multi-type conflict groups, out of scope).
**Mechanism (verified):** RSS provably writes lowercase types (strict json_schema enum, normalizer **default OFF**); NLM provably writes UPPERCASE via the Pydantic Literal. Both key `Entity` on `{name, type}`, so `"organization"` and `"ORGANIZATION"` are **distinct nodes**. There is **no uniqueness constraint** on `Entity` (only an index on a `normalized_name` property nothing populates). Worse than the candidate stated: a name-only `MATCH … MERGE` executes for **every** matching node, so edges attach to *all* same-name nodes and read-path `INVOLVES`/neighbor queries return rows for each.
**Why it matters:** silently fragments the knowledge graph's core Entity layer on every RSS run (re-dirtying the one-shot merge migration), corrupting relationship attachment and read-path entity lookups — the platform's central RAG-quality concern.
**Fix direction:** make entity-type canonicalization **unconditional** on the RSS write path (flip `entity_type_normalize` default to True / remove the flag — the lowercase enum is fully covered by `LEGACY_ENTITY_TYPE_MAP`); add a `Entity` uniqueness/node-key constraint after a one-time merge; fix the `entity_name_type` index to reference a written property; include `type` in name-only MATCHes where known.

### WP-05 — Multi-country document: every Event geo-stamped to the first location's country centroid · Medium / CORRUPTION · (lens L3-a)
**Where:** `pipeline.py:510` (`doc_country = next(...)` — first truthy country, LLM-arbitrary order), `:511-545` (per-event loop stamps that one country onto **every** event), `build_event_geo_fragment` `:29-51`; `_RESPONSE_SCHEMA` events `:225-240` / locations `:257-268` carry **no event↔location association**.
**Mechanism:** the extraction schema has no per-event location and the `locations` array has no event linkage, so `_write_to_neo4j` collapses it to one `doc_country` and stamps `OCCURRED_AT → that country's centroid` onto all events. A "Russia strikes Kyiv + US sanctions Iran" document plots **both** events at whichever country the LLM emitted first.
**Scope:** only multi-country documents are affected (single-country docs are correct); the fragment honestly self-labels `geo_basis=country_centroid`/`geo_precision=country`, but the *country itself* is wrong for all-but-one event.
**Fix direction:** only geo-stamp when the document resolves to exactly one distinct country; otherwise leave the event geoless (honest `located:0`). Better: extend the extraction schema so each event carries its own country, then call `build_event_geo_fragment` per event.

### WP-06 — GDELT live collector discards `seendate`; all GDELT Events anchored to ingest moment · Medium / CORRUPTION · (lens L3-b)
**Where:** `feeds/gdelt_collector.py:160` (reads `seendate`), `:170-177` (`process_item` omits all time args), `:203` (stored Qdrant-only as `seen_date`); `pipeline.py:282-284` (time kwargs default None), `:71-84` (`_resolve_timeline` falls back to `'ingested'`), `:519-536` (CREATE stamps `timeline_at`); contrast `feeds/rss_collector.py:284-303` (RSS **does** forward `published_at`).
**Mechanism:** the ArtList JSON carries a per-article `seendate`, but the collector routes it only into the Qdrant payload, never the timeline path. With `occurred/observed/published` all None and the optional LLM `timestamp` field normally absent (the model only sees the title), `_resolve_timeline` returns `(ingested_at, 'ingested')`. The CHRONIK histogram buckets on `ev.timeline_at`, so a GDELT article indexed days earlier lands in the ingest-day bucket and **re-ingested content drifts to ever-later buckets**.
**Fix direction:** normalize `seendate` → ISO-8601 and forward it as `observed_at` (precedence 2 already honored) → Events carry `time_basis='observed'` anchored to GDELT's seen-date. Fall back to `'ingested'` only on empty/malformed dates (never fabricate). Caveat: `seendate` is index time, not publication time — an approximation, but strictly better than `now()`.

### WP-07 — Name-keyed incident `Location` collides distinct incidents, freezes first coords · Medium / CORRUPTION · (lens L5-b)
**Where:** `graph_integrity/loc_key.py:19-22` (`incident_key` drops coords when a name is present), `geo_incident.py:16-30` (`WIRE_INCIDENT_LOCATION` writes lat/lon `ON CREATE` only); mirrored on the backend write path `backend/app/cypher/incident_write.py:23-28` + vendored `_loc_key.py:16-19`; metric that hides it `graph_integrity/report.py:35`.
**Mechanism:** `incident_key` drops coordinates from the identity key whenever the incident has a non-empty location string, and both MERGE templates write coords `ON CREATE` only (no `ON MATCH`). Two distinct incidents sharing a location slug but at different coordinates MERGE onto the **same** `:Location`; the second silently inherits the first's coords. The constraint is on `Incident.id` only (not `Location.loc_key`), so the MERGE matches rather than erroring, and `report.py` GEO_COVERAGE still counts it as "located" — the mis-location is invisible to the acceptance metric and **re-running the backfill never repairs it** (`ON CREATE` never re-fires).
**Scope (conditional):** the live auto-promoter is **not** a trigger (all detectors emit `location=""` → coords-bearing key). Reachable via admin `POST /_admin/trigger` (free-text location) and the `geo_incident` backfill over legacy Incident nodes carrying a location value.
**Fix direction:** make the Location identity key coordinate-bearing even when a name is present (`incident:<slug>@<lat>,<lon>`); apply in both `loc_key.py` and the vendored `_loc_key.py`; add a `Location.loc_key` uniqueness constraint + an audit query flagging coord-disagreement.

### WP-08 — `ev.timestamp` is never written → null timestamps + no-op ordering on read endpoints · Medium / correctness · (lens L6-b)
**Where:** read-path `backend/app/routers/graph.py:135-136/143-144/189-192` and `intelligence/agents/tools/graph_templates.py:51-92` all `RETURN ev.timestamp` / `ORDER BY ev.timestamp DESC`. **No** write-path sets a `timestamp` property on `:Event` (confirmed by grep: live pipeline writes `timeline_at` at `pipeline.py:523`; GDELT writer writes `timeline_at` at `neo4j_writer.py:35/49`). The only `.timestamp` writes are `r.timestamp` on `SPOTTED_AT` relationships (military aircraft) — different label.
**Mechanism:** `ev.timestamp` resolves to **null for every Event**. (A) `ORDER BY ev.timestamp DESC` over an all-null key has no tiebreak → the LIMIT-capped "most recent N events" is arbitrary storage order, not newest-first. (B) Returned `timestamp` is always null. The correct reader exists in parallel: `timeline.py` uses `ev.timeline_at`. The same mismatch in the intelligence graph tool widens the blast radius to the synthesis agent.
**Fix direction:** replace `ev.timestamp` → `ev.timeline_at` in all three `graph.py` reads and in `graph_templates.py`; update `test_cypher_validation.py:24` which encodes the wrong ordering; add a CI grep forbidding `ev.timestamp` on read templates.

### WP-09 — gdelt_raw `MENTIONS` edges silently dropped, no metric · Medium / SILENT_SKIP · (lenses L4-c + L2-b + L6-c, consolidated)
*(Triangulated independently by three lenses.)*
**Where:** `gdelt_raw/writers/neo4j_writer.py:87-95` (`MERGE_MENTION` starts `MATCH (d:Document {url:$doc_url})`), `:165-179` (`write_mentions` discards `tx.run` result — no count/log); `filter.py:93/100/139` (GKG `Document`s kept by **theme**, mentions kept by **event-id** — orthogonal criteria); `transform.py:117`. `Document` is MERGEd on `doc_id` (`:53-66`), `url` only an indexed property (`migrations/phase2_indexes.cypher:9-10`).
**Mechanism:** mentions are scoped by surviving event_ids; a `Document` exists only for the article subset whose GKG record passed the theme allowlist (and GKG/mentions are separate GDELT files with imperfect overlap). For a mention whose article was not theme-matched, the leading `MATCH` binds **zero rows**, the chained `MERGE` is a clean no-op, the tx commits, **no edge, no error, no log**. Idempotent replay never recovers it. The spec wanted a `gdelt_mentions_written_total` metric (design doc line 689) that is not implemented.
**Verified nuances:** the "unindexed Document.url" sub-claim is **refuted** (`doc_url` index exists). Primary provenance is **not** lost — the Event still carries `e.source_url` + `num_mentions`; only corroborating-article breadth is. The "URL tracking-param drift" reproduction (L2-b) is **wrong** — GDELT keys both streams on identical raw URLs within a slice. Real loss mechanism = theme-filter disjointness.
**Fix direction (observability-first, filtering is by-design):** capture `result.consume().counters.relationships_created` in `write_mentions`, warn with a `mentions_without_doc` count, emit the spec'd `gdelt_mentions_written_total` + a `…_dropped_no_document_total`. *Optionally* promote GKG records referenced by surviving-event mentions into the Document set, or MERGE a deliberate stub Document — but reconcile with the `doc_id`-keyed uniqueness model first.

### WP-10 — Hard crash strands a 15-minute gdelt_raw slice with no auto-recovery · Medium / SILENT_SKIP · (lens L1-c)
**Where:** `gdelt_raw/run.py:143-144` (parquet `last_slice` advance — standalone Redis SET), `:153-170` (`add_pending` only inside `except`), `:187-190` (forward gate is purely `get_last_slice("parquet")`); `recovery.py:36/51` (replay iterates only the pending sorted-sets); `state.py:52-67` (non-atomic separate Redis writes); `neo4j_writer.py:145-152` (multi-roundtrip tx = the crash window).
**Mechanism:** `set_last_slice("parquet", S)` commits **before** any external-store attempt; the `add_pending` recovery hooks only run on a Python-level exception. A `SIGKILL`/OOM/container-stop during the Neo4j writer's network round-trips lands *after* the parquet advance and *before* `add_pending`, leaving S absent from both pending sets. `replay_pending` only scans those sets, and the new-slice gate is purely the parquet pointer → the next tick reports `gdelt_no_new_slice` and never re-touches S. Only a manual backfill recovers it.
**Severity rationale:** Medium — needs a hard ungraceful kill in a short window (ordinary exceptions *are* correctly routed to `add_pending`, proven by `test_gdelt_forward.py:120-131`), and the parquet truth-layer survives on disk (recoverable, just missing from Neo4j/Qdrant). OOM kills are plausible on this memory-/VRAM-constrained single box.
**Fix direction:** write-ahead-intent — `add_pending("neo4j"/"qdrant", S)` *before* the external write, `remove_pending` on success; and/or make the forward gate honor `is_slice_fully_done` and re-enqueue incomplete slices; add a reconcile that flags `last_slice(parquet)` ahead of `last_slice(neo4j/qdrant)`.

## LOW / hardening

### WP-11 — GDELT `0,0` null-island Locations collapse geoless events onto a shared node · Low / CORRUPTION · (lens L5-a)
**Where:** `graph_integrity/geo_gdelt.py:49-63` (`build_geo_row` None-only guard) + `:28-37` (`BACKFILL_OCCURRED_AT`); `gdelt_raw/ids.py:34-36` (`build_location_id('','','')` → shared `'gdelt:loc::'`); `gdelt_raw/parser.py:59` (`null_values=[""]` → literal `0` survives as `0.0`); `gdelt_raw/transform.py:62-63` (lat/long not `fill_null`'d). **The live writer is `neo4j_writer.py:107-121` `location_params_for`, which also guards only None** — `gdelt_raw/geo.py:18-21` (the function that drops `0,0`) is **dead code** with no non-test callers.
**Mechanism:** when GDELT emits literal `0.0/0.0` with empty FeatureID/Country/Fullname, the parser yields float `0.0` (not null), the None-only guard passes it, `build_location_id('','','')` returns the single key `'gdelt:loc::'`, and the MERGE wires **every** such event to one (0,0) node — plotted in the Gulf of Guinea and counted as "located".
**Verified correction:** the candidate's framing ("backfill contradicts a live-writer contract that drops 0,0") is **wrong** — that guard is dead code; the live writer has the **identical** gap, so the backfill introduces no new corruption. Hence Low, and shared (not backfill-specific). GDELT's standard "no geo" (`ActionGeo_Type=0`) emits empty → null → correctly dropped, so the trigger is the narrow "resolved-to-0/0-with-no-ids" case.
**Fix direction:** add `if lat==0.0 and lon==0.0: return None` to **both** `build_geo_row` and `location_params_for`; make `build_location_id` refuse an all-empty id tuple; delete or wire-up the dead `geo.py` builder; exclude `(0,0)` from `report.py` GEO_COVERAGE.

### WP-12 — Fallback parser null-coerces type-corrupt cells; quarantine undercounts · Low / SILENT_SKIP · (lens L4-b)
**Where:** `gdelt_raw/parser.py:78-82` (tab-count-only validity), `:99-107` (re-parse `ignore_errors=True`), `:44-48` (`parse_error_pct` excludes null-coerced rows); `gdelt_raw/filter.py:77/84-88`; `run.py:70` + `config.py:18` (5% gate).
**What holds:** the fallback quarantines purely on tab count, so a row with the right tab count but a non-integer token in a typed column is re-parsed with `ignore_errors=True` and the bad cell is null-coerced; such rows are **not** counted in `parse_error_pct`, so the 5% gate can't see them. A null-coerced `event_root_code` silently excludes a possibly-tactical event from `tactical_ids`; a null `global_event_id` row is silently dropped.
**What was refuted:** the headline `int(None)` crash does **not** occur — a null-id row never survives `is_in(final_ids)` (null → exclude), and polars `map_elements` skips null inputs without invoking the lambda. So this is SILENT_SKIP, not a slice-wide crash.
**Fix direction (defensive only):** count post-parse nulls in key typed columns into `quarantine_count`/`parse_error_pct`; drop/quarantine null-id rows with a log line before `apply_filters`; add a parser test for the correct-tab-count-but-corrupt-token case.

## REFUTED / non-issues (documented for honesty)

- **L6-a — geo-backfill is a "no-op" → REFUTED.** The thesis that `WHERE NOT OCCURRED_AT` matches ~0 events is false: the write-path geo wiring landed **the same day** (2026-06-14); all GDELT events ingested *before* that are geoless in Neo4j despite valid `action_geo` in the raw export, so the backfill genuinely repairs them. Only residual: the docstring justifies the re-fetch with a wrong reason ("parquet is geo-stripped") — the real reason is "those slices predate the geo-carrying transform." **Low doc nit.**
- **L2-a — RSS Google-News redirect token rotates every run → REFUTED (non-issue).** Tested live three times with different clients: tokens byte-for-byte identical (only a constant `?oc=5`). The Google News token is a stable deterministic encoding of the destination URL, so `point_id` is stable and unchanged articles are correctly skipped. Residual (much narrower): if Google ever re-mints a token for the same article, link-based dedup would miss it — defense-in-depth only, not "every run."

---

## Cross-cutting themes (root causes)

1. **The dual-write seam has no atomicity, no Event idempotency key, and dedup keyed on the wrong store.** `Event` is `CREATE` (`pipeline.py:519`), dedup is Qdrant-point-keyed, the Neo4j write is fail-soft, and Qdrant is written *after* (deferred to a batch). This single design choice is the root behind **WP-01, WP-03, and the KNOWN `BH-EDGE-WRITE-01`**. One change — `MERGE` Event on `content_hash` + write-ahead/reconcile + propagate Neo4j failures as transients — closes all three.
2. **Two GDELT ingestion systems with divergent schemas.** Live pipeline `:Event` (`CREATE`, url-keyed `Document`) vs `gdelt_raw` `:Event:GDELTEvent` (`MERGE event_id`, doc_id-keyed `Document`). The read-path and `graph_integrity` assume one shape; this underlies **WP-08, WP-09**, and the entity/identity confusion in **WP-04**.
3. **Silent skips with no metric are systemic on the write-path** (**WP-08, WP-09, WP-10, WP-12**). A 0-rows no-op for "intentionally not ingested" is indistinguishable from genuine loss. The `gdelt_raw` spec even named metrics (`gdelt_mentions_written_total`) that were never implemented.
4. **Geo correctness is fragile and self-masking** (**WP-05, WP-07, WP-11**). Country-centroid coarseness, name-keyed `Location` collision, and `(0,0)` null-island all corrupt the globe/CHRONIK silently while `report.py` GEO_COVERAGE reports success — the acceptance metric hides the very defects it should catch.

## Suggested remediation order (report-only — no fixes applied)

1. **WP-01 + WP-03 + KNOWN** together: `MERGE` Event on `content_hash`, propagate Neo4j failures as transients, reconcile job. *(One coherent change; highest payoff.)*
2. **WP-02**: null-key quarantine at the gdelt_raw parse gateway (prevents permanent slice loss).
3. **WP-04**: flip `entity_type_normalize` default on + `Entity` uniqueness constraint (core RAG quality).
4. **WP-08**: `ev.timestamp` → `ev.timeline_at` on all read templates (cheap, user-visible).
5. **WP-05 / WP-06 / WP-07 / WP-11**: geo-correctness batch (single-country guard, forward `seendate`, coord-bearing incident key, `0,0` guard) — fits the `graph-integrity-tranche2` workstream.
6. **WP-09 / WP-10 / WP-12**: gdelt_raw observability + crash-window hardening (write-ahead-intent, mention metrics, parser quarantine counting).

*Deep audit artifact — generated read-only. Every confirmed finding carries a reproduction that held against the
current code on branch `feature/graph-integrity-tranche2-spec`; the three High/headline findings were additionally
hand-verified by the author. No platform source was modified.*
