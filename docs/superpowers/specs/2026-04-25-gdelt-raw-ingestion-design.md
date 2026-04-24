# GDELT Raw Files Ingestion — Design Spec

**Date:** 2026-04-25
**Author:** RT + Claude (Opus 4.7)
**Status:** Design approved, ready for implementation plan
**Codename:** Huginn-GDELT (Ingestion-Seite — Huginn = Memory-Rabe)

---

## 1 · Motivation

Der bestehende GDELT-Collector (`services/data-ingestion/feeds/gdelt_collector.py`) nutzt die **DOC API** (`/api/v2/doc/doc`) mit Keyword-Queries. Er schlägt in Produktion systematisch fehl:

- 429 Rate-Limits (GDELT DOC API hat harte Tagescaps)
- Leere Responses (`Expecting value: line 1 column 1 (char 0)`)
- Liefert Artikel-Text, nicht strukturierte Events
- `total_new: 0` seit mehreren Stunden in den Logs

**GDELT bietet parallel dazu Raw Data Files an** — strukturierte CSVs alle 15 Minuten (`http://data.gdeltproject.org/gdeltv2/`), die drei Streams liefern:

- **Events (`export.CSV`)** — CAMEO-codierte Actor-Action-Target-Tripel mit Geo
- **Mentions (`mentions.CSV`)** — Document-zu-Event-Mapping
- **GKG (`gkg.csv`)** — Global Knowledge Graph: Themes, Entities, Quotations, Tone

Diese Raw Files sind **frei** (keine Rate-Limits auf CDN-Downloads), **strukturiert** (keine LLM-Extraction nötig), **geocodiert** (Lat/Long im Feld) und **tagesaktuell** (15-min-Updates).

**Dieses Spec ersetzt den Collector nicht**, sondern **ergänzt** ihn: Die DOC API bleibt für Ad-hoc-Recherche via Agent-Tool. Raw-Ingestion wird die neue Hauptquelle für Event-Knowledge-Graph und selektive Worldview-Marker.

---

## 2 · Scope

### Primäre Use-Cases (confirmed)

- **B — Knowledge-Graph-Enrichment** (Hauptziel): GKG-Entities (Persons/Orgs/Themes/Locations) in Neo4j verdichten, um Agent-Tools robuster zu machen.
- **D — Analytics / Zeitreihen**: Goldstein/Tone pro Region/Thema über Zeit für zukünftige Dashboards. Parquet-Write-Through als Fundament, DuckDB-Analytics-Layer später.
- **A-lite — Globe Markers** (eng definiert): Nur Events mit CAMEO-Root ∈ {15, 18, 19, 20} (Truppenbewegungen, Angriffe, Gefechte, Mass-Violence) **plus** Events verlinkt auf GKG-Docs mit Themes {NUCLEAR, WMD, WEAPONS_PROLIFERATION}.

### Explizit Out-of-Scope

- Breit angelegte Event-Markers (Proteste, Diplomatie, Coercion-only) — zu viel Noise für den Globus.
- Live-Translated-Stream (`masterfilelist-translation.txt`) — Erweiterung möglich in Phase 2.
- Backfill älter als 30 Tage als Default — erreichbar via CLI, aber nicht automatisch.
- Ersetzung des DOC-API-Collectors — bleibt parallel.
- DuckDB-Analytics-UI — Parquet-Write-Through macht es möglich, aber UI ist separates Spec.

---

## 3 · Architektur-Überblick

```
┌──────────────────────────────────────────────────────────────────────┐
│ data-ingestion container (Spark-Node, 128 GB RAM)                    │
│                                                                      │
│   APScheduler  ──15min──▶  gdelt_raw.run_forward()                   │
│       │                                                              │
│       │       ┌──── CLI: odin-ingest-gdelt backfill ──────┐          │
│       ▼       ▼                                                      │
│                                                                      │
│   1. Pending-Scan (Recovery vor neuem Slice)                         │
│      → Redis SortedSet "gdelt:pending:{neo4j,qdrant}"                │
│                                                                      │
│   2. Download (parallel asyncio.gather)                              │
│      → lastupdate.txt + 3× ZIP + MD5-verify                          │
│                                                                      │
│   3. Parse (Polars streaming, schema-hinted)                         │
│      → Events / Mentions / GKG DataFrames                            │
│                                                                      │
│   4. Filter                                                          │
│      Events: cameo_root ∈ {15,18,19,20}                              │
│      GKG:    themes match α-Set (prefix-aware)                       │
│      Mentions: nur zu gefilterten Event-IDs                          │
│                                                                      │
│   5. WRITE (in dieser Reihenfolge, keine Phase danach nicht skipbar) │
│      ┌─ Parquet  ←  persistierte Wahrheit für den Slice              │
│      ├─ Neo4j    ←  Graph-Projektion (re-hydrierbar)                 │
│      └─ Qdrant   ←  Semantic-Retrieval-Projektion (re-hydrierbar)    │
│                                                                      │
│   6. State-Commit                                                    │
│      Redis: gdelt:slice:<slice>:<store> = "done"                     │
│      Redis: gdelt:forward:last_slice:<store> = <slice>               │
└──────────────────────────────────────────────────────────────────────┘
         ▼           ▼           ▼
    ┌────────┐  ┌────────┐  ┌──────────────────────┐
    │ Neo4j  │  │ Qdrant │  │ /data/gdelt/         │
    │        │  │        │  │   events/date=.../*  │
    │        │  │        │  │   gkg/date=.../*     │
    │        │  │        │  │   mentions/date=.../*│
    └────────┘  └────────┘  └──────────────────────┘
                                       │
                                       └─▶ DuckDB (später, zero-migration)
```

### Drei kritische Invarianten

1. **Write-Path ist deterministisch.** Parser → Pydantic-Contract-Validation → Cypher-Template. Kein LLM involviert. (CLAUDE.md-Pflicht.)
2. **Parquet ist Source-of-Truth für den Slice.** Neo4j und Qdrant sind Projektionen. Wenn eine ausfällt, wird sie aus Parquet re-hydriert.
3. **Per-Slice-State in Redis.** `gdelt:slice:<slice>:<store>` statt nur `last_slice` — Lücken in der Mitte bleiben sichtbar und replayable.

---

## 4 · Datenmodell

### 4.1 Neo4j Schema-Delta

**Stable Contracts (expensive to change later — migration plan required before changing):**

| Element | Format | Warum stabil |
|---|---|---|
| `event_id` | `"gdelt:event:<GlobalEventID>"` | GlobalEventID ist GDELTs stabiler PK. Direkter Durchreichen statt künstlichem Composite-Key. |
| `doc_id` | `"gdelt:gkg:<GKGRecordID>"` | GKGRecordID ist stabil, in GDELT-Doku garantiert. |
| Secondary-Labels | `:GDELTEvent`, `:GDELTDocument` | Erlauben scoped Constraints ohne Altbestand-Migration. |
| Entity MERGE-Key | `(normalized_name, type)` | News-Entities sind unscharf, harte IDs wären fragil. Später Resolver möglich. |

**Node-Writes (alle MERGE, idempotent):**

```cypher
// Events — PK + Secondary-Label
MERGE (e:Event:GDELTEvent {event_id: "gdelt:event:1300904663"})
  ON CREATE SET
    e.source = "gdelt",
    e.cameo_code = "193",
    e.cameo_root = 19,
    e.quad_class = 4,
    e.goldstein = -6.5,
    e.avg_tone = -4.2,
    e.num_mentions = 12,
    e.num_sources = 8,
    e.num_articles = 11,
    e.date_added = datetime("2026-04-25T12:15:00Z"),
    e.fraction_date = 2026.3164,
    e.actor1_code = "MIL", e.actor1_name = "MILITARY",
    e.actor2_code = "REB", e.actor2_name = "REBELS",
    e.source_url = "https://…",
    e.codebook_type = "conflict.armed"       // via CAMEO-Mapping
  ON MATCH SET
    e.num_mentions = 12,                      // update, kann wachsen
    e.num_sources = 8,
    e.num_articles = 11

// GKG Documents — PK + Secondary-Label
MERGE (d:Document:GDELTDocument {doc_id: "gdelt:gkg:20260425121500-42"})
  ON CREATE SET
    d.source = "gdelt_gkg",
    d.url = "https://…",
    d.published_at = datetime(…),
    d.tone_positive = 2.1,
    d.tone_negative = -6.3,
    d.tone_polarity = 8.4,
    d.tone_activity = 3.2,
    d.tone_self_group = 1.1,
    d.word_count = 599,
    d.sharp_image_url = "https://…",
    d.quotations = ["…", "…"]                 // Top-3

// Source (bestehend) — gewiederverwendet
MERGE (s:Source {name: "reuters.com"})
  ON CREATE SET s.quality_tier = "unverified", s.updated_at = datetime()

// Themes — neu
MERGE (t:Theme {theme_code: "ARMEDCONFLICT"})
  ON CREATE SET t.category = "conflict"       // overlay: conflict|crisis|nuclear|cyber|…

// Entities (natural key via normalisiertem Display-Namen)
// normalized_name = lowercase + collapse whitespace + strip non-alphanum-Zeichen
// Beispiel: "Vladimir Putin" → "vladimir putin", "NATO (Alliance)" → "nato alliance"
// NICHT: Token-Drop oder Stopword-Removal — das wäre Entity-Resolution, nicht Normalisierung.
MERGE (p:Entity {normalized_name: "vladimir putin", type: "PERSON"})
  ON CREATE SET
    p.name = "Vladimir Putin",
    p.aliases = ["Putin", "Wladimir Putin"],
    p.first_seen = datetime(),
    p.confidence = 0.8
  ON MATCH SET p.last_seen = datetime()

// Locations — mit Point-Property für echten Geo-Index
MERGE (l:Location {feature_id: "-3365797"})
  ON CREATE SET
    l.name = "Kyiv",
    l.country_code = "UA",
    l.lat = 50.4501, l.lon = 30.5234,
    l.geo = point({latitude: 50.4501, longitude: 30.5234, crs: "wgs-84"})
```

**Relationships:**

```cypher
(:Document)-[:MENTIONS {                    // zu Event — aus Mentions.csv
  tone: -6.1, confidence: 100, char_offset: 1664
}]->(:Event)

(:Document)-[:MENTIONS {                    // zu Entity — aus V2EnhancedPersons/Orgs
  char_offset: 1290
}]->(:Entity)

(:Document)-[:MENTIONS {                    // zu Location — aus V2EnhancedLocations
  count: 2
}]->(:Location)

(:Document)-[:ABOUT {count: 3}]->(:Theme)   // aus V2EnhancedThemes (neu, additiv)

(:Document)-[:FROM_SOURCE]->(:Source)       // bestehende Rel
(:Event)-[:OCCURRED_AT]->(:Location)        // bestehende Rel
(:Event)-[:INVOLVES {role: "actor1"|"actor2"}]->(:Entity)  // role-Prop neu
```

### 4.2 CAMEO → codebook_type Mapping

```python
# Mapping aller potentiell relevanten CAMEO-Roots.
# Die Tabelle ist breiter als der aktuelle Filter (Allowlist {15,18,19,20}),
# damit Widening auf 14/17 später nur eine Config-Änderung ist.
CAMEO_ROOT_TO_CODEBOOK: dict[int, str] = {
    14: "civil.protest",            # aktuell NICHT in GDELT_CAMEO_ROOT_ALLOWLIST
    15: "posture.military",         # Truppenbewegungen, Mobilmachung        ← aktiv
    17: "conflict.coercion",        # aktuell NICHT in Allowlist (Sanctions)
    18: "conflict.assault",         # Angriffe, Attentate, Kidnap             ← aktiv
    19: "conflict.armed",           # Gefechte, Kleinwaffen, Artillerie       ← aktiv
    20: "conflict.mass_violence",   # Massaker, WMD, Ethnische Säuberung      ← aktiv
}
# Roots ohne Eintrag → Event wird durch α-Filter verworfen (codebook_type never set).
# Roots mit Eintrag aber außerhalb Allowlist → werden aktuell nicht ingested;
# das Mapping existiert damit Allowlist-Widening eine reine Config-Änderung bleibt.
```

### 4.3 Constraints + Indexes (Staged Rollout)

**Phase 1 — GDELT-Scoped Constraints (Teil des GDELT-Rollouts):**
```cypher
CREATE CONSTRAINT gdelt_event_id_unique IF NOT EXISTS
  FOR (e:GDELTEvent) REQUIRE e.event_id IS UNIQUE;

CREATE CONSTRAINT gdelt_doc_id_unique IF NOT EXISTS
  FOR (d:GDELTDocument) REQUIRE d.doc_id IS UNIQUE;

CREATE CONSTRAINT source_name_unique IF NOT EXISTS
  FOR (s:Source) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT theme_code_unique IF NOT EXISTS
  FOR (t:Theme) REQUIRE t.theme_code IS UNIQUE;
```

**Phase 2 — Performance-Indexes (additiv, null-risk):**
```cypher
CREATE INDEX event_source_date IF NOT EXISTS
  FOR (e:Event) ON (e.source, e.date_added);
CREATE INDEX event_cameo_root IF NOT EXISTS
  FOR (e:Event) ON (e.cameo_root);
CREATE INDEX event_codebook_type IF NOT EXISTS
  FOR (e:Event) ON (e.codebook_type);
CREATE INDEX doc_source_published IF NOT EXISTS
  FOR (d:Document) ON (d.source, d.published_at);
CREATE INDEX doc_url IF NOT EXISTS
  FOR (d:Document) ON (d.url);
CREATE INDEX entity_name_type IF NOT EXISTS
  FOR (e:Entity) ON (e.normalized_name, e.type);
CREATE POINT INDEX location_geo IF NOT EXISTS
  FOR (l:Location) ON (l.geo);
```

**Phase 3 — Legacy-Migration (SEPARATES Spec, NICHT Blocker):**
- Bestehende 10'164 Documents bekommen `doc_id = "rss:<sha256(url)>"` / `"nlm:<notebook_id>"` / `"legacy:<uuid>"`
- Dedup-Check vor Aktivierung der globalen `:Document` Unique-Constraint
- Dedup-Query:
  ```cypher
  MATCH (d:Document) WHERE d.doc_id IS NOT NULL
  WITH d.doc_id AS id, count(*) AS c WHERE c > 1
  RETURN id, c ORDER BY c DESC;
  ```

### 4.4 Qdrant Schema (nur GKG-Docs, Collection `odin_intel`)

```python
payload = {
  "source": "gdelt_gkg",
  "doc_id": "gkg-20260425121500-42",
  "url": "https://…",
  "source_name": "reuters.com",
  "title": first_sentence_or_fallback,
  "themes": ["ARMEDCONFLICT", "KILL", "MILITARY"],
  "persons": ["Putin", "Zelensky"],               # V2.1AllNames top-10
  "organizations": ["NATO", "UN"],
  "locations": [{"name": "Kyiv", "lat": 50.45, "lon": 30.52}],
  "tone_polarity": 8.4,
  "goldstein_linked": -6.5,                       # via Mention verlinktes Event
  "cameo_root_linked": 19,
  "published": "2026-04-25T12:15:00Z",
  "ingested_at": "2026-04-25T12:17:30Z",
  "content_hash": "sha256:…",
  "codebook_type": "conflict.armed"
}

embed_text = f"{title}\nThemes: {themes_joined}\nActors: {persons_orgs_joined}"[:1500]
# Content-Hash auf embed_text — skip Re-Embed wenn unverändert.
```

### 4.5 Parquet Schema

```
/data/gdelt/
├── events/date=2026-04-25/<slice>.parquet
│   schema: {event_id, cameo_code, cameo_root, quad_class, goldstein,
│            avg_tone, num_mentions, num_sources, num_articles,
│            date_added, fraction_date,
│            actor1_code, actor1_name, actor1_country,
│            actor2_code, actor2_name, actor2_country,
│            action_geo_lat, action_geo_lon, action_geo_country,
│            source_url, codebook_type}
├── gkg/date=2026-04-25/<slice>.parquet
│   schema: {doc_id, url, source_name, published, themes: list<string>,
│            persons: list<string>, organizations: list<string>,
│            locations: list<struct>, tone: struct, quotations: list<string>,
│            sharp_image_url, word_count}
└── mentions/date=2026-04-25/<slice>.parquet
    schema: {event_id, mention_url, source_name, mention_time,
             tone, confidence, char_offset}
```

Schema-Snapshots als `gdelt_raw/schemas/parquet_*.schema.json` im Repo — Basis für DuckDB-View-Definitionen später.

**Storage-Budget:** ~4 MB/Tag events + 50 MB/Tag gkg + 6 MB/Tag mentions ≈ **20 GB/Jahr** komprimiert (snappy).

---

## 5 · Datenfluss

### 5.1 Forward-Tick (alle 15 min)

```
t+0:00  Pending-Scan:
          ZRANGE gdelt:pending:neo4j  0 -1 LIMIT 10
          ZRANGE gdelt:pending:qdrant 0 -1 LIMIT 10
        Für jeden pending slice: Re-hydrate aus Parquet
          (siehe 5.3 — Recovery-Flow)

t+0:10  GET lastupdate.txt → 3 Zeilen parsen (events/mentions/gkg)
        Vergleiche MD5 gegen Redis gdelt:forward:last_md5:*
        SKIP wenn identisch (GDELT hat sich nicht bewegt)

t+0:12  Parallel-Download (asyncio.gather):
          events.zip, mentions.zip, gkg.zip
        MD5-Verify vs. masterfilelist.

t+0:18  Unzip → /tmp/gdelt/<slice>/

t+0:19  Polars streaming Parse:
          events_df = pl.read_csv(…, schema_overrides=EVENT_POLARS_SCHEMA)
          mentions_df = pl.read_csv(…)
          gkg_df = pl.read_csv(…, schema_overrides=GKG_POLARS_SCHEMA)

t+0:22  Filter:
          events_df.filter(pl.col("cameo_root").is_in([15,18,19,20]))
          gkg_df.filter(matches_alpha_themes)            # prefix-aware
          mentions_df.filter(event_id in filtered_event_ids)

t+0:25  WRITE — Parquet ZUERST:
          parquet_writer.write_partition(events_df, mentions_df, gkg_df, slice_ts)
          redis SET gdelt:slice:<slice>:parquet = "done"

t+0:27  WRITE — Neo4j:
          neo4j_writer.write_batch(events, gkg_docs, mentions)
          ON SUCCESS: redis SET gdelt:slice:<slice>:neo4j = "done"
          ON FAIL:    redis SET gdelt:slice:<slice>:neo4j = "failed:<reason>"
                      redis ZADD gdelt:pending:neo4j <slice_ts> <slice>

t+0:35  WRITE — Qdrant:
          qdrant_writer.embed_and_upsert(gkg_docs)
          ON SUCCESS: redis SET gdelt:slice:<slice>:qdrant = "done"
          ON TEI_FAIL: redis SET gdelt:slice:<slice>:qdrant = "pending_embed"
                       redis ZADD gdelt:pending:qdrant <slice_ts> <slice>
          ON NEO4J_NEEDED_BUT_FAILED: qdrant skip für diesen Slice

t+0:40  Cleanup /tmp/gdelt/<slice>
        Update summary keys:
          gdelt:forward:last_slice:parquet = <slice>
          gdelt:forward:last_slice:neo4j   = <slice> (nur wenn success)
          gdelt:forward:last_slice:qdrant  = <slice> (nur wenn success)

t+0:41  LOG metrics: events=412 gkg=87 mentions=1203 elapsed=41s
        prometheus: gdelt_last_slice_timestamp_seconds=<epoch>
```

### 5.2 Backfill-Flow (CLI-triggered)

```
odin-ingest-gdelt backfill --from 2026-03-25 --to 2026-04-24
  ↓
Plan: 31 days × 96 slices/day = 2976 slices
Job ID: backfill-2026-04-25-a3f2
Redis: gdelt:backfill:a3f2:total = 2976
       gdelt:backfill:a3f2:state = running
       gdelt:backfill:a3f2:pending = SortedSet of slice_ids

ThreadPool(4) workers:
  Jeder Worker:
    ZPOPMIN gdelt:backfill:a3f2:pending
    Run forward-flow für diesen slice (mit slice-specific state keys)
    HINCRBY gdelt:backfill:a3f2:progress 1

Forward-scheduler läuft parallel weiter (unabhängige state keys).

Ctrl+C oder Crash:
  Redis state bleibt erhalten.
  Resume: odin-ingest-gdelt resume backfill-2026-04-25-a3f2
```

### 5.3 Recovery-Flow (Pending-Replay)

```python
# Pro Tick, BEVOR neuer Slice geholt wird:
pending_neo4j = redis.zrange("gdelt:pending:neo4j", 0, 9)  # max 10 pro Tick
for slice_id in pending_neo4j:
    # Parquet ist vorhanden (Invariante: Parquet wurde VOR Neo4j geschrieben)
    events = pl.read_parquet(f"/data/gdelt/events/date={date}/{slice_id}.parquet")
    gkg    = pl.read_parquet(f"/data/gdelt/gkg/date={date}/{slice_id}.parquet")
    mentions = pl.read_parquet(f"/data/gdelt/mentions/date={date}/{slice_id}.parquet")
    try:
        neo4j_writer.write_batch(events, gkg, mentions)
        redis.zrem("gdelt:pending:neo4j", slice_id)
        redis.set(f"gdelt:slice:{slice_id}:neo4j", "done")
    except Exception as e:
        log.error("recovery_retry_failed", slice=slice_id, error=str(e))
        # Bleibt im pending-set, nächster Tick probiert wieder
```

---

## 6 · Error-Handling

| Fehler | Reaktion |
|---|---|
| `lastupdate.txt` 5xx/Timeout | Retry 3× exponential backoff (1s, 4s, 15s), dann skip Tick + metric `gdelt_fetch_failed` |
| MD5-Mismatch nach Download | Retry 1×, dann skip Tick + alert-log (GDELT-CDN-Problem) |
| ZIP korrupt | Skip File, andere 2 weiter. Slice-State: `partial` |
| Polars-Parse in Zeile N | Log row N, continue. Max `GDELT_MAX_PARSE_ERROR_PCT` (default 5%) — wenn überschritten: skip Slice |
| Pydantic-Contract-Violation am Writer-Input | Log `skip_row reason=…`, continue |
| Neo4j-Timeout | Retry Transaction 3×, dann: Parquet bleibt (`gdelt:slice:<slice>:parquet = done`), Neo4j in pending-set. Recovery-Flow übernimmt. |
| Qdrant/TEI down | Embedding skip, Qdrant in pending-set mit Status `pending_embed`. Recovery-Flow reprobiert. |
| CLI-Backfill-Crash | Redis-State bleibt → resume via CLI möglich |
| `/tmp` voll | Pre-Flight Disk-Space-Check ≥ 200 MB vor Download, sonst skip + metric |
| Duplicate `GlobalEventID` innerhalb desselben Slices | MERGE-idempotent, kein Problem |

**Metrics (Prometheus):**
```
gdelt_slices_processed_total{mode="forward|backfill", store="neo4j|qdrant|parquet"}
gdelt_slice_duration_seconds{stage="download|parse|filter|write_parquet|write_neo4j|write_qdrant"}
gdelt_events_written_total
gdelt_gkg_docs_written_total
gdelt_mentions_written_total
gdelt_last_slice_timestamp_seconds{store="neo4j|qdrant|parquet"}
gdelt_pending_slices{store="neo4j|qdrant"}
gdelt_fetch_errors_total{reason="…"}
gdelt_parse_rows_skipped_total{reason="…"}
```

---

## 7 · Testing-Strategie

### 7.1 pytest-Marker
```ini
[pytest]
markers =
    integration: requires local dev-compose services
    live: touches external GDELT CDN
    slow: backfill or performance tests

# CI:       pytest -m "not integration and not live"
# Nightly:  pytest -m "integration"
# Release:  pytest -m "live"
```

### 7.2 Unit Tests (no network, no services)
```
test_gdelt_schemas.py                  # Pydantic models, edge cases
test_gdelt_parser.py                   # Polars parse fixtures
test_gdelt_filter.py                   # CAMEO + theme filter logic
test_gdelt_theme_matching.py           # prefix-aware: CRISISLEX_* matcht CRISISLEX_T03_DEAD
test_gdelt_cameo_mapping.py            # 14,15,17,18,19,20 → codebook_type vollständig
test_gdelt_id_generation.py            # ID-Determinismus: build_event_id(42) == "gdelt:event:42"
test_gdelt_entity_normalization.py     # "Vladimir Putin" → ("vladimir putin", "PERSON")
test_gdelt_location_point.py           # lat/lon → point(crs:"wgs-84")
test_gdelt_state.py                    # Per-Slice + Summary Redis-Keys
```

### 7.3 Component Tests (Fake Clients)
```
test_parquet_written_before_external_stores           # write-order invariant
test_pending_store_replay_from_parquet                # KRITISCH — recovery-arch
test_store_state_not_advanced_on_failure              # state nur bei success
test_qdrant_pending_embed_when_tei_down               # degraded mode
test_qdrant_embedding_text_deterministic              # stable hash
test_qdrant_content_hash_skips_reembed                # no wasted TEI calls
test_neo4j_merge_is_idempotent                        # 2× Input, 1× Node-Count
test_source_node_reused                               # (:Source) MERGE, kein Dup
test_theme_node_reused
```

### 7.4 Contract Tests (Neo4j Schema)
```
test_constraints_created_idempotently
test_gdelt_event_constraint_rejects_duplicate_event_id
test_gdelt_doc_constraint_rejects_duplicate_doc_id
test_event_has_secondary_label_gdelt_event
test_document_has_secondary_label_gdelt_document
test_location_geo_point_is_written
test_source_relation_from_document_exists
```

### 7.5 Integration Tests (`-m integration`, local compose)
```
test_full_forward_tick_against_real_stores   # Fixture-Slice, nicht live-GDELT
test_backfill_resume_after_simulated_crash
```

### 7.6 Analytics-Smoke
```
test_duckdb_can_read_partitioned_parquet     # Parquet-Schema-Drift-Guard
```

### 7.7 Live (`-m live`, manuell/nightly)
```
test_live_gdelt_lastupdate_endpoint
```

### 7.8 Pydantic vs Polars — klare Arbeitsteilung
Polars macht Bulk-Parsing mit Schema-Hints (schnell, Column-weise).
Pydantic nur an zwei Stellen:
- Single-row-Validation beim Writer-Übergabepunkt (Contract Enforcement)
- Test-Fixtures mit bekannten Edge-Cases (Golden-Set-Assertion)

**NICHT** Pydantic über 135k GKG-rows pro Tag iterieren — das wäre CPU-Sabotage.

### 7.9 Fixture-Set
```
tests/fixtures/gdelt/
├── slice_20260425_full.export.CSV       # Mini-Slice, 10 events, cameo_root 15/18/19/20
├── slice_20260425_full.gkg.csv          # 5 gkg docs, verschiedene themes
├── slice_20260425_full.mentions.CSV     # Passend dazu
├── slice_malformed.export.CSV           # Broken row → skip expected
├── slice_unicode_edge.gkg.csv           # ä/ö/ü/中文 in themes/names
└── gdelt_master_sample.txt              # Mini-masterfilelist für Download-Mocks
```

---

## 8 · CLI-Interface

Spiegelt `odin-ingest-nlm`-Pattern:

```bash
odin-ingest-gdelt status           # last_slice pro Store, pending-Count, Tages-Counts
odin-ingest-gdelt forward          # Ein manueller Forward-Tick (Debug)
odin-ingest-gdelt backfill --from 2026-03-25 --to 2026-04-24
odin-ingest-gdelt resume <job_id>  # Backfill nach Crash fortsetzen
odin-ingest-gdelt doctor           # Alle Deps: CDN, Neo4j, Qdrant, TEI, Disk
odin-ingest-gdelt config           # Config-Dump
```

Implementation: `click`-basiert, gleicher Style wie `nlm_ingest/cli.py`. Entry in `pyproject.toml`:
```toml
[project.scripts]
odin-ingest-gdelt = "gdelt_raw.cli:main"
```

---

## 9 · Modul-Struktur

```
services/data-ingestion/
├── gdelt_raw/                       # NEU
│   ├── __init__.py
│   ├── cli.py                       # click CLI (status/forward/backfill/resume/doctor)
│   ├── config.py                    # Pydantic Settings — GDELT_*
│   ├── downloader.py                # lastupdate + ZIP fetch + MD5-verify
│   ├── parser.py                    # Polars streaming Parse (Events, Mentions, GKG)
│   ├── filter.py                    # CAMEO + Theme filter (alpha/delta modes)
│   ├── cameo_mapping.py             # CAMEO root → codebook_type
│   ├── theme_matching.py            # Prefix-aware theme matcher
│   ├── normalize.py                 # Entity name normalization
│   ├── schemas.py                   # Pydantic: Event, GKGDoc, Mention (contract-level)
│   ├── polars_schemas.py            # pl.Schema hints für Bulk-Parse
│   ├── ids.py                       # build_event_id, build_doc_id, build_location_id
│   ├── state.py                     # Redis per-slice + summary state
│   ├── run.py                       # run_forward(), run_backfill(), run_recovery()
│   ├── writers/
│   │   ├── __init__.py
│   │   ├── neo4j_writer.py          # Cypher-Templates, batched MERGE
│   │   ├── qdrant_writer.py         # TEI-embed + upsert (content_hash skip)
│   │   └── parquet_writer.py        # Polars write_parquet, date-partitioned
│   ├── migrations/
│   │   └── phase1_constraints.cypher
│   └── schemas_parquet/
│       ├── events.schema.json
│       ├── gkg.schema.json
│       └── mentions.schema.json
├── feeds/gdelt_raw_collector.py     # dünner Scheduler-Wrapper → gdelt_raw.run_forward()
└── tests/test_gdelt_*.py            # siehe Testing-Section
```

---

## 10 · Config-Delta

### 10.1 `.env.example` (additiv)
```bash
# GDELT Raw Files Ingestion
GDELT_BASE_URL=http://data.gdeltproject.org/gdeltv2
GDELT_FORWARD_INTERVAL_SECONDS=900
GDELT_DOWNLOAD_TIMEOUT=60
GDELT_MAX_PARSE_ERROR_PCT=5
GDELT_PARQUET_PATH=/data/gdelt
GDELT_FILTER_MODE=alpha                    # alpha | delta (Hotspot-Focus)
GDELT_CAMEO_ROOT_ALLOWLIST=15,18,19,20
GDELT_THEME_ALLOWLIST=ARMEDCONFLICT,KILL,CRISISLEX_*,TERROR,TERROR_*,MILITARY,NUCLEAR,WMD,WEAPONS_*,WEAPONS_PROLIFERATION,SANCTIONS,CYBER_ATTACK,ESPIONAGE,COUP,HUMAN_RIGHTS_ABUSES,REFUGEE,DISPLACEMENT
GDELT_BACKFILL_PARALLEL_SLICES=4
GDELT_BACKFILL_DEFAULT_DAYS=30
```

### 10.2 `docker-compose.yml` (Delta)
```yaml
services:
  data-ingestion:
    volumes:
      - gdelt_parquet:/data/gdelt
      # + bestehende mounts
    environment:
      - GDELT_BASE_URL=${GDELT_BASE_URL}
      - GDELT_PARQUET_PATH=${GDELT_PARQUET_PATH}
      - GDELT_FILTER_MODE=${GDELT_FILTER_MODE:-alpha}
      - GDELT_CAMEO_ROOT_ALLOWLIST=${GDELT_CAMEO_ROOT_ALLOWLIST}
      - GDELT_THEME_ALLOWLIST=${GDELT_THEME_ALLOWLIST}
      # + bestehende env

volumes:
  gdelt_parquet:
    driver: local
```

### 10.3 `services/data-ingestion/pyproject.toml`
```toml
[project.dependencies]
polars = "^1.0"
pyarrow = "^17.0"
# + bestehende

[project.scripts]
odin-ingest-gdelt = "gdelt_raw.cli:main"
odin-ingest-nlm = "nlm_ingest.cli:main"
```

### 10.4 `services/data-ingestion/scheduler.py`
```python
scheduler.add_job(
    gdelt_raw.run.run_forward,
    "interval",
    seconds=int(os.getenv("GDELT_FORWARD_INTERVAL_SECONDS", 900)),
    id="gdelt_forward",
    max_instances=1,
    coalesce=True,
)
```

### 10.5 `odin.sh` (Delta)
```bash
./odin.sh gdelt status
./odin.sh gdelt backfill 30
```

---

## 11 · Rollout-Plan

### Phase 1 — Dev (Woche 1)
1. Module-Skelett + Unit-Tests (TDD, red first)
2. Downloader + Parser + Filter (grün)
3. Parquet-Writer (grün)
4. Neo4j-Writer + Cypher-Templates (grün)
5. Qdrant-Writer (grün)
6. State-Management + Recovery-Flow (grün)

### Phase 2 — Integration (Woche 2)
7. Scheduler-Hook
8. Integration-Tests gegen Dev-Compose (mit Fixture-Slices)
9. CLI komplett
10. Constraints + Indexes deployed (Phase 1 + 2)

### Phase 3 — Rollout (Woche 2-3)
11. 30-Tage-Backfill starten (CLI, Spark-Node, ~6-8h Laufzeit)
12. Forward-Scheduler aktiviert
13. Monitoring-Dashboard (Prometheus-Metriken)
14. Smoke-Tests nach 24h, 48h, 7 Tage

### Phase 4 — später (separate Specs)
- Legacy-Document-Migration (globale `:Document` Constraints)
- DuckDB-Analytics-Layer
- A-lite Globe-Marker-Backend-Endpoint + Frontend-Layer
- B-Use-Case: Agent-Tool-Integration (bereits vorhandene Tools profitieren sofort via codebook_type)

---

## 12 · Offene Entscheidungen vor Implementation-Plan

Keine — alle Architektur-Entscheidungen sind getroffen:

- ✅ Approach 3 (Module + CLI, im data-ingestion container, Spark-Node)
- ✅ Polars als Parser
- ✅ 30-Tage-Default-Backfill + On-Demand-CLI
- ✅ Filter-Modus α (mit config-flag für δ)
- ✅ Option 2 Hybrid für GKG (Neo4j + Qdrant)
- ✅ CAMEO-Filter: {15,18,19,20} + Nuclear-Theme-Override, kein Goldstein-Schwellwert
- ✅ ID-Strategie: harte `event_id`/`doc_id` für GDELT, natural key für Entity
- ✅ Secondary-Labels `:GDELTEvent`/`:GDELTDocument`
- ✅ Staged-Constraint-Rollout (Scoped zuerst, Legacy separat)
- ✅ Write-Order: Parquet → Neo4j → Qdrant
- ✅ Per-Slice-State in Redis + Summary-Keys
- ✅ Prefix-aware Theme-Matching
- ✅ Polars für Bulk, Pydantic für Contracts

---

## 13 · Referenzen

- GDELT 2.0 Announcement: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- GDELT Event Codebook: http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
- GDELT GKG Codebook: http://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf
- CAMEO Event Codes: https://www.gdeltproject.org/data/lookups/CAMEO.eventcodes.txt
- Bestehender Collector: `services/data-ingestion/feeds/gdelt_collector.py` (bleibt für DOC-API)
- Bestehende Neo4j-Schema (2026-04-25): 10345 Events, 10164 Documents, 6335 Entities, 0 Constraints
- CLAUDE.md Regel: Kein LLM-generiertes Cypher auf Write-Path ✓ (GDELT ist bereits strukturiert)
