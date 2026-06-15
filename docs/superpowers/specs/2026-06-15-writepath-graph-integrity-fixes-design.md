# Design Spec — Write-Path & Graph-Integrity Fixes

**Date:** 2026-06-15
**Author:** RT + Claude (Opus 4.8)
**Source of findings:** `docs/writepath-graph-integrity-audit-2026-06-14.md` (WP-01..WP-12)
**Status:** design — pending implementation plan (writing-plans, starting with T1)

## Goal

Close the verified write-path / graph-integrity defects (2 High, 8 Medium) found in the deep audit, **without
re-introducing** the retry/consistency holes. Every tranche delivers: (1) a forward write-path fix (TDD, the audit's
reproduction becomes the red test), and (2) an **idempotent repair migration for existing prod data where feasible**.
Where existing corruption cannot be cleanly repaired (per-event country, original GDELT seen-date), the data is
explicitly marked **re-ingestion-only / accepted** plus a detection query, never silently left as "fixed".

## Non-goals

- Consolidating the two GDELT ingestion systems (live pipeline vs `gdelt_raw`) into one schema — out of scope; each
  path is fixed in place.
- The ~414 multi-type entity conflict groups left for manual review by `neo4j_duplicate_merge.cypher` — stay manual.
- Per-event location extraction-schema redesign (WP-05 "better" option) — noted as a future option, not in this scope.
- The two refuted findings: L2-a (Google-News token, non-issue) — no work. L6-a residual is a one-line docstring fix
  folded into T4.

## Tranches & order

**T1 → T2 → T3 → T5 → T4.** T4 (geo) is last because its repairs carry the most data-rewrite risk; T5 before T4 makes
the raw-replay/reconcile base robust before geo repairs run over the corpus. Each tranche = its own feature branch off
`main` + PR; this spec lands first.

| Tranche | Defects | Theme | Sev |
|---------|---------|-------|-----|
| T1 | WP-01, WP-03, KNOWN BH-EDGE-WRITE-01 | live-pipeline dual-write seam | High |
| T2 | WP-02, WP-12 | gdelt_raw parse-gateway integrity | High |
| T3 | WP-04, WP-08 | entity canonicalization + read-path anchor | Medium |
| T5 | WP-09, WP-10 | gdelt_raw robustness & observability | Medium |
| T4 | WP-05, WP-06, WP-07, WP-11 (+report, +L6-a) | geo correctness (4 acceptance blocks) | Medium |

---

## T1 — Live-pipeline dual-write seam (WP-01, WP-03, KNOWN)

**Files:** `services/data-ingestion/pipeline.py`, `feeds/gdelt_collector.py`, `feeds/rss_collector.py`.

### Problem (verified)
`_write_to_neo4j` posts to `/db/neo4j/tx/commit` and **only logs** transaction errors — the tx endpoint returns
**HTTP 200 with an `errors[]` array**, so `resp.raise_for_status()` (`pipeline.py:553`) does not catch Cypher/tx
failures; `pipeline.py:554-556` just `log.warning("neo4j_write_errors")`. `process_item` additionally wraps the whole
call in `try/except Exception: log.error` (`pipeline.py:319-327`), swallowing even httpx errors. The collector then
proceeds to Redis xadd + Qdrant upsert. Event is `CREATE` (`pipeline.py:519`) and dedup is Qdrant-point-keyed, so the
outcomes are: orphan vector + duplicate Events on retry (KNOWN), batch-amplified duplication on crash (WP-03), and —
worst — **permanent graph-node loss** when the Qdrant point commits while Neo4j failed and the Qdrant-keyed dedup then
blocks the retry forever (WP-01).

### Forward fix (Approach: Key + Signal + Reconcile)

1. **Surface Neo4j failures (the decisive change).** Introduce `Neo4jWriteError`. In `_write_to_neo4j`:
   - wrap the httpx call so connect/timeout/5xx raise `Neo4jWriteError` (not raw httpx);
   - **also raise `Neo4jWriteError(errors)` when `errors != []`** (`pipeline.py:555`) instead of only warning — Neo4j
     tx errors are HTTP-200 bodies, this is the load-bearing correction.
2. **Stop swallowing in `process_item` — for the T1 paths.** `process_item` re-raises `Neo4jWriteError` to the caller
   and skips the Redis xadd (no phantom live event) **when called with `raise_on_write_error=True`**.
   > **Compatibility decision (explicit).** `process_item` has 14 callers; only `gdelt_collector` and `rss_collector`
   > are in T1 scope. To avoid changing the error behavior of the other 12 collectors in this tranche, `process_item`'s
   > **default stays legacy fail-soft** (`raise_on_write_error=False` → log + swallow, as today). The **T1 collectors
   > MUST pass `raise_on_write_error=True`**, and **only those paths satisfy the dual-write guarantee** of this tranche.
   > Migrating the remaining collectors to propagate-by-default is explicit future work, not part of T1. (Non-T1
   > callers are unaffected; a non-`Neo4jWriteError` exception is still logged-and-swallowed for every caller.)
3. **Collector skips Qdrant on Neo4j failure.** In both `gdelt_collector` and `rss_collector`, catch `Neo4jWriteError`
   in the same place as the existing transient handlers and `continue` **without appending the `PointStruct`** — so the
   Qdrant-point dedup key is never minted and the next tick retries cleanly (mirrors the existing embed-`HTTPError`
   `continue` pattern).
4. **Idempotent Event key.** Replace `CREATE (ev:Event …)` (`pipeline.py:519`) with `MERGE (ev:Event {event_key})`,
   `ON CREATE SET` for immutable fields (incl. `timeline_at`/`time_basis`), and `MERGE (d)-[:DESCRIBES]->(ev)`.
   - `event_key = sha256(f"{content_hash}|{codebook_type}|{norm_title}")[:24]`, where
     `norm_title = re.sub(r"\s+", " ", title.strip()).lower()[:200]` (**trim → whitespace-collapse → lowercase → max
     length** so minor LLM title variations don't fork new Events; the truncation bound is fixed in the spec).
   - `content_hash` is the same `sha256(title|url)` already computed in the collectors — thread it into `process_item`
     so the Event key and the Qdrant dedup key share a root.
5. **WP-03 batch window.** Wrap the currently-unguarded `qdrant.retrieve` dedup call (`gdelt_collector.py:153`,
   `rss_collector.py:271`) so a transient Qdrant fault doesn't discard the whole accumulated batch. With Event now
   `MERGE`, a re-fetched/reprocessed article converges instead of forking — the batch-amplified duplication self-heals.

### Repair migration
- **Constraint:** `CREATE CONSTRAINT event_key_unique IF NOT EXISTS FOR (ev:Event) REQUIRE ev.event_key IS UNIQUE`
  (unique constraints allow NULLs, so `gdelt_raw` `:Event:GDELTEvent` nodes without an `event_key` are unaffected),
  applied **after** a one-time dedup.
- **Backfill scope (explicit):** backfill `event_key` **only on live-pipeline `:Event` nodes that are NOT also
  `:GDELTEvent`** — `:GDELTEvent` nodes keep their own `event_id` identity and are out of scope. The dedup then merges
  existing live-pipeline duplicates onto the surviving key. For **orphan/undocumented** `:Event` nodes (no `:Document`,
  missing properties needed for the key): a **dry-run count first**, then either skip them or mint a clearly-marked
  lossy key from the properties that do exist — never implicitly re-key "all `:Event`". Preflight (count duplicate
  groups) before the constraint so it cannot fail-hard.
- **Orphan reconcile (marked LOSSY).** A CLI in the `graph_integrity` tooling style that scans Qdrant points whose
  `content_hash`/`url` has no matching Neo4j `Document`/`Event` and re-runs extraction **from the stored payload title**
  (idempotent via `event_key`). This is **best-effort / lossy** — Qdrant carries only the title, not the full text, so
  re-extraction is weaker than the original. The forward fix is the decisive part; the reconcile only heals already-
  orphaned vectors.

### Tests (red first)
- Neo4j tx returns `errors[]` (HTTP 200) → `process_item` raises `Neo4jWriteError`; collector does **not** upsert the
  point; next tick re-attempts (dedup does not trip).
- Same article reprocessed twice → exactly one `:Event` (MERGE convergence).
- `norm_title` variations ("  Foo  Bar ", "foo bar") → same `event_key`.
- Redis event is **not** emitted when the Neo4j write fails.

### Acceptance
A Neo4j-down tick writes neither a vector nor a duplicate; once Neo4j recovers the item ingests exactly once; no
`:Event` is ever created via `CREATE`; `event_key_unique` holds.

---

## T2 — gdelt_raw parse-gateway integrity (WP-02, WP-12)

**Files:** `gdelt_raw/parser.py`, `gdelt_raw/filter.py`, `gdelt_raw/writers/neo4j_writer.py`,
`gdelt_raw/writers/qdrant_writer.py`. (**All** null/quarantine/parse-gateway logic is consolidated here — T5 touches
`write_mentions` only for an observability counter and carries no parser changes and no null/quarantine logic, to avoid
duplicated parser/writer logic.)

### Problem (verified)
A single GKG row with an empty `GKGRecordID` survives as polars `null` (`null_values=[""]`, tab-count-only quarantine),
passes `unique()` + the `n_unique` invariant (null counted as a value), yields `doc_id=null`, then the fail-fast writer
comprehension (`neo4j_writer.py:202`) and `uuid5(NAMESPACE_URL, None)` (`qdrant_writer.py:145`) raise **before** the
batch write — so the whole slice's Documents + Mentions + Qdrant vectors are lost while state shows a false-recoverable
"pending" (WP-02). Separately, the fallback parser (`ignore_errors=True`) null-coerces type-corrupt cells in
tab-count-valid rows; those nulls are not in `quarantine_count`, so `parse_error_pct` undercounts and rows silently
vanish via `is_in` (WP-12).

### Forward fix
1. **Quarantine null/empty keys at the gateway**, on **both** strict and fallback parse paths: divert rows with
   null/empty `gkg_record_id` (and `global_event_id` for events/mentions) to the quarantine JSONL, drop them from the
   DataFrame, and **count them into `parse_error_pct`** so the 5% gate (`run.py:70`) can see them.
2. **Defense-in-depth in filter:** `.drop_nulls(subset=["gkg_record_id"])` before the `unique()` at `filter.py:93`;
   tighten the post-join invariant (`filter.py:135`) to also assert `doc_id` null-count == 0.
3. **Writers skip-and-log instead of fail-fast:** wrap each `model_validate` in the writer comprehensions in try/except,
   count rejects, continue — one bad row cannot block a whole slice. Guard `qdrant_point_id_for_doc` against `None`.
4. **WP-12 (folded in):** after the fallback re-parse, count post-parse nulls in key typed columns
   (`global_event_id`, `event_root_code`) into `quarantine_count` (or a `type_coerced_count`) and drop/quarantine
   null-id rows with a structured log line rather than letting them silently vanish.

### Repair
No bad data was written (the failure mode is loss, not corruption), but slices may be **stranded** (parquet on disk,
stores incomplete). Repair = the shared **"replay incomplete slices"** command (see T5/WP-10) re-processing slices whose
parquet exists but whose `neo4j`/`qdrant` store-state ≠ "done".

### Tests (red first)
- GKG fixture with one empty leading `GKGRecordID` → the bad row is quarantined, **all valid rows** still write to Neo4j
  + Qdrant, `parse_error_pct` reflects the bad row.
- Fallback path with a correct-tab-count-but-corrupt typed token → counted in quarantine, not silently dropped.

### Acceptance
A single malformed key never destroys a slice's batch; `parse_error_pct` accounts for null-coerced/quarantined rows.

---

## T3 — Entity canonicalization + read-path anchor (WP-04, WP-08)

**Files:** `services/data-ingestion/config.py`, `canonicalize.py`, `pipeline.py`;
`services/backend/app/routers/graph.py`, `services/intelligence/agents/tools/graph_templates.py`,
`services/intelligence/tests/test_cypher_validation.py`.

### WP-04 — entity key split (lowercase RSS vs UPPERCASE NLM)
**Forward:** flip `entity_type_normalize` default to **True** (`config.py:124`) so the RSS path canonicalizes its
lowercase enum types (via `canonicalize.py` / `LEGACY_ENTITY_TYPE_MAP`) to the canonical UPPERCASE set **before** the
`MERGE (e:Entity {name,type})` (`pipeline.py:480`). Add a **composite unique constraint on `(name, type)`** **after** a
pre-dedupe — **not** a node-key/existence constraint (CLAUDE.md runs **Neo4j 5 Community**, which does not cleanly
support node-key/existence). Verify at implementation that the running Community version supports *composite* unique
constraints; if it does not, key Entities on a derived single `entity_key` property with a plain unique constraint
instead. Fix the `entity_name_type` index to reference a property that is actually written.
**Repair:** re-run the existing `migrations/neo4j_entity_type_canonicalization.cypher` +
`migrations/neo4j_duplicate_merge.cypher` (idempotent). Because the write-path now normalizes, the migration is not
re-dirtied. The ~414 multi-type conflict groups remain manual (unchanged).
**Tests:** an RSS `"organization"` entity and an NLM `"ORGANIZATION"` entity with the same name resolve to **one** node;
the constraint rejects a second case-variant.

### WP-08 — read-path reads `ev.timestamp` which no write-path sets
**Forward (API-compatible):** no write-path sets `:Event.timestamp`; the anchor is `ev.timeline_at`. In `graph.py`
(`:135-136/143-144/189-192`) and `graph_templates.py` (`:51-92`):
- `WITH …, coalesce(ev.timeline_at, ev.timestamp, ev.date_added) AS timestamp … ORDER BY timestamp DESC` — return the
  **coalesced** value (so existing frontend/clients keep a populated field — **no breaking rename**) **and sort on that
  same coalesced value**, not on `ev.timeline_at` alone: legacy nodes that carry only `ev.timestamp`/`ev.date_added`
  would null-sort if ordered by `timeline_at`.
Update `test_cypher_validation.py:24` (it encodes the wrong `ev.timestamp` ordering). Add a CI grep forbidding
`ORDER BY ev.timestamp` on read templates.
**Repair:** none — `timeline_at` is already correct on nodes.
**Tests:** `/graph/events` and `/graph/events/geo` return non-null `timestamp` in descending coalesced-timestamp order
for seeded events, including a legacy node that has only `ev.timestamp`/`ev.date_added` (verifies the fallback sorts
correctly).

---

## T5 — gdelt_raw robustness & observability (WP-09, WP-10)

**Files:** `gdelt_raw/writers/neo4j_writer.py`, `gdelt_raw/run.py`, `gdelt_raw/state.py`, `gdelt_raw/recovery.py`.

### WP-09 — silent MENTIONS drops, no metric
`write_mentions` (`neo4j_writer.py:165-179`) calls `tx.run(MERGE_MENTION, …)` and discards the result; a mention whose
article never became a theme-matched `Document` produces a clean zero-row no-op (by-design filtering — not changed).
**Forward (observability only):** distinguish three outcomes — do **not** treat `relationships_created == 0` as a drop
(it is also 0 on replay and when the edge already exists). Detect a genuine drop by whether the leading
`MATCH (d:Document …) MATCH (e:GDELTEvent …)` bound **zero rows** (e.g. have the statement `RETURN count(d) AS d_found,
count(e) AS e_found`, or a found-flag) — that is the only "no resolvable Document/Event" signal. Counters per slice:
- `written` (created) from `summary.counters.relationships_created` (via `await result.consume()`);
- `dropped_no_document` / `dropped_no_event` incremented **only** when the corresponding MATCH bound nothing;
- `existing/merged` (matched but edge already present) logged separately/optionally.
Emit `gdelt_mentions_written_total` + `gdelt_mentions_dropped_no_document_total` + a structured warning on drops. Do
**not** add a stub-Document fallback (would defeat the theme filter).

### WP-10 — hard-crash strands a slice
`set_last_slice("parquet", S)` (`run.py:144`) is committed before any store write, and `add_pending` runs **only inside
the except** (`run.py:160/170`); a SIGKILL between the two strands the slice (absent from both pending sets, never
re-touched).
**Forward (write-ahead-intent — keep parquet as download gate):**
- The parquet checkpoint stays the **download gate** exactly as today (deliberately store-independent so a down store
  doesn't force re-downloads — `run.py:136-138`). **Do not** gate `forward()` on `is_slice_fully_done`.
- Set `add_pending("neo4j", S)` / `add_pending("qdrant", S)` **before** their respective try-blocks (write-ahead intent),
  and `remove_pending(...)` on success — so a crash mid-write leaves S in the pending set for `replay_pending`
  regardless of whether the except handler ran.
- **Replay/reconcile is driven by store-done/pending state** (not by the forward gate): add a reconcile that flags any
  slice where `last_slice("parquet")` is ahead of `last_slice("neo4j")`/`last_slice("qdrant")`, and the shared
  **"replay incomplete slices"** command (also used by T2 repair).
**Tests:** simulate process death between the parquet advance and the store write (e.g. assert the pending entry exists
*before* the external write) → slice is in pending → `replay_pending` re-processes it.

---

## T4 — Geo correctness (last; 4 acceptance blocks)

**Files:** `pipeline.py`, `feeds/gdelt_collector.py`, `graph_integrity/geo_gdelt.py`, `geo_incident.py`, `loc_key.py`,
`gdelt_raw/writers/neo4j_writer.py`, `gdelt_raw/ids.py`, `graph_integrity/report.py`, backend `_loc_key.py`.
**WP-07 and WP-11 repairs require hard dry-run counts before any rewrite.**

### Block A — geo-stamping (WP-05)
**Forward:** only stamp `OCCURRED_AT` when the document resolves to **exactly one distinct ISO2 country**
(`len({resolve_iso2(l['country']) for l in locations}) == 1`) — multiple place names within the **same** country stay
centroid-stampable. Otherwise leave events geoless (honest `located:0`).
**Repair:** existing wrong-country edges cannot be re-derived (per-event country was never captured) →
**re-ingestion-only / accepted**, plus a detection query flagging multi-country docs whose events share one centroid.

### Block B — timeline observed_at (WP-06)
**Forward:** in `gdelt_collector`, normalize `seendate` (e.g. `20260610T120000Z` → ISO-8601) and forward it as
`observed_at` in the `process_item` call; `_resolve_timeline` already honors `observed_at` at precedence 2 →
`time_basis='observed'`. Empty/malformed `seendate` → fall back to `ingested` (never fabricate).
**Repair:** existing GDELT events' real seen-date is not in Neo4j → **re-ingestion-only / accepted**. *Optional stretch:*
backfill `timeline_at` from the Qdrant `seen_date` payload by `content_hash` match.

### Block C — loc_key rekey (WP-07)
**Forward:** `incident_key(name, lat, lon)` must include coordinates **even when a name is present** —
`incident:{slug(name)}@{lat:.3f},{lon:.3f}` (`loc_key.py:19-22` currently drops lat/lon when a name exists). Apply
identically in the vendored backend `_loc_key.py` (the existing parity test enforces sync). Add a `Location.loc_key`
uniqueness constraint.
**Repair:** migration to re-key/split collided incident Locations + an audit query flagging Locations whose lat/lon
disagree with an attached incident's coords — **dry-run counts first**.
**Tests:** two same-name/different-coord incidents → different `loc_key`.

### Block D — null-island + honest metric (WP-11, report.py, L6-a)
**Forward:** add `if lat == 0.0 and lon == 0.0: return None` to **both** `graph_integrity/geo_gdelt.build_geo_row` and
`gdelt_raw/writers/neo4j_writer.location_params_for` (the live writer has the identical gap; the `0,0` guard in
`gdelt_raw/geo.py` is dead code). Make `build_location_id` refuse an all-empty id tuple (no shared `'gdelt:loc::'` key).
Delete or wire-up the dead `geo.py` builder. Make `report.py` GEO_COVERAGE exclude `(0,0)` Locations from the "located"
count and flag coord-disagreement. Fix the misleading `geo_gdelt.py` docstring rationale (L6-a — the real reason older
slices are geoless is they predate the geo-carrying transform, not "parquet is geo-stripped").
**Repair:** null-island node cleanup (delete/rewire the shared `(0,0)` node) — **dry-run counts first**.
**Tests:** a literal `0/0` raw row → `None` from both `build_geo_row` and `location_params_for`; two empty-id rows do
not share a `loc_key`.

---

## Cross-cutting

- **TDD (mandatory):** each forward fix starts red — the audit's reproduction sequence becomes the failing test, then
  minimal green, then refactor.
- **Review (mandatory):** two-stage review per tranche (spec-compliance + quality) and the `graph-rag-auditor` agent on
  any write-template / read/write-separation change. No shortcuts.
- **Migrations:** idempotent, preflight-guarded, following the existing `migrations/` + `gdelt_raw/migrations/apply.py`
  pattern; every repair is re-runnable. Constraints (`event_key_unique`, `Entity`, `Location.loc_key`) are applied only
  **after** their dedup/cleanup repair, with a duplicate-count preflight so they cannot fail-hard.
- **Branching:** one feature branch off `main` + PR per tranche; this spec lands first. Order T1 → T2 → T3 → T5 → T4.
- **Deploy:** WP-08 = backend bind-mount/restart **plus** an intelligence image rebuild (it also edits
  `intelligence/agents/tools/graph_templates.py`); ingestion fixes (T1/T2/T4/T5) = ingestion image rebuild; migrations
  run via `apply.py`. **No GPU swap required.**
- **Re-ingestion-only data (explicit):** WP-05 wrong-country edges and WP-06 mis-anchored GDELT timestamps for existing
  rows are not cleanly repairable; they are documented as re-ingestion-only with detection queries, never silently
  claimed fixed.

## Risks

- **Constraint application on dirty data** (`event_key_unique`, `Entity`, `Location.loc_key`) fails if duplicates remain
  → every constraint is gated behind its repair + a count preflight (mirrors `apply.py`'s Source-dup preflight).
- **T1 behavior change:** moving from fail-soft-swallow to propagate-and-skip means a sustained Neo4j outage now skips
  items (retried next tick) instead of half-writing — intended, but operators should expect "skipped" logs during an
  outage instead of silent partial writes.
- **T4 repairs rewrite live geo data** → dry-run counts + idempotent migrations + T4 sequenced last.
- **Reconcile is lossy** (title-only re-extraction) → forward fix is the real guarantee; reconcile only heals legacy
  orphans.

## Open items for the implementation plan (writing-plans, T1 first)
- Exact module for `Neo4jWriteError` (new `pipeline` exception alongside `ExtractionTransientError`).
- Whether the orphan-reconcile CLI lives under `graph_integrity/` or `feeds/`.
- The **name** of the `norm_title` max-length constant (value is fixed at **200**, see T1 — naming only).
