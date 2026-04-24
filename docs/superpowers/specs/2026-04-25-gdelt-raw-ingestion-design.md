# GDELT Raw Files Ingestion — Design Spec

**Date:** 2026-04-25
**Author:** RT + Claude (Opus 4.7)
**Status:** Approved with must-fix edits applied (2026-04-25 review) — ready for implementation plan
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
- **A-lite — Globe Markers** (eng definiert): Events mit CAMEO-Root ∈ {15, 18, 19, 20} (Truppenbewegungen, Angriffe, Gefechte, Mass-Violence) **UNION** Events verlinkt (via Mentions) auf GKG-Docs mit Themes {NUCLEAR, WMD, WEAPONS_*, WEAPONS_PROLIFERATION}. Die Union ist entscheidend: Nuclear-Events fallen oft nicht unter CAMEO-Root-Codes {15,18,19,20}, werden aber via Theme-Override erfasst.

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
│   4. Filter (multi-stage mit Nuclear-Override)                       │
│      4a. tactical_event_ids  = cameo_root ∈ {15,18,19,20}            │
│      4b. gkg_alpha           = themes match α-Set (prefix-aware)     │
│      4c. gkg_nuclear         = themes match {NUCLEAR,WMD,WEAPONS_*}  │
│      4d. nuclear_event_ids   = Mentions where url ∈ gkg_nuclear.urls │
│      4e. final_event_ids     = tactical_event_ids ∪ nuclear_event_ids│
│                                                                      │
│   5. WRITE-Order ist strikt: Parquet MUSS erfolgreich sein, BEVOR    │
│      Neo4j oder Qdrant starten. Neo4j und Qdrant sind unabhängig     │
│      voneinander — Qdrant liest aus Parquet, nicht aus Neo4j.        │
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
2. **Parquet ist Source-of-Truth für den Slice.** Neo4j und Qdrant sind Projektionen. Wenn eine ausfällt, wird sie aus Parquet re-hydriert. **Neo4j und Qdrant sind voneinander entkoppelt** — beide lesen die gleiche Parquet-Quelle.
3. **Per-Stream + Per-Slice-State in Redis.** Nicht nur pro Slice, sondern pro `(slice, stream, store)` — `gdelt:slice:<slice>:events:parquet = done`, `gdelt:slice:<slice>:neo4j = done|partial|pending`. Lücken bleiben sichtbar und replayable.
4. **Atomare Parquet-Writes.** `.parquet.tmp` schreiben, `fsync`, `rename()`, *dann* State `done` setzen. Kein halbes File darf als fertig gelten.

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
// Zeitsemantik: GDELT V2.1DATE ist "observed/indexed"-Zeit (immer vorhanden).
// Das echte Artikel-Publikationsdatum kommt aus V2ExtrasXML <PAGE_PRECISEPUBTIMESTAMP>,
// das ist optional und darf null sein.
MERGE (d:Document:GDELTDocument {doc_id: "gdelt:gkg:20260425121500-42"})
  ON CREATE SET
    d.source = "gdelt_gkg",
    d.url = "https://…",
    d.gdelt_date = datetime(…),           // always present — from V2.1DATE
    d.published_at = null,                // optional — aus <PAGE_PRECISEPUBTIMESTAMP>
    d.tone_positive = 2.1,
    d.tone_negative = -6.3,
    d.tone_polarity = 8.4,
    d.tone_activity = 3.2,
    d.tone_self_group = 1.1,
    d.word_count = 599,
    d.sharp_image_url = "https://…",
    d.quotations = ["…", "…"]                 // Top-3

// Source (bestehend) — wiederverwendet
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

Vor `CREATE CONSTRAINT source_name_unique`: Pflicht-Preflight, sonst knallt die Migration am Altbestand:

```cypher
// Preflight — Duplicate-Check für :Source
MATCH (s:Source)
WITH s.name AS name, count(*) AS c
WHERE name IS NOT NULL AND c > 1
RETURN name, c ORDER BY c DESC;

// Handler:
//   - 0 Rows → Constraint aktivieren
//   - >0 Rows → Migration BRICHT ab, manuelle Konsolidierung
//               (Duplicate-Sources via MERGE zusammenführen und ihre
//                Relationships umhängen, dann Retry)
```

Dann die Constraints selbst:
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
CREATE INDEX doc_source_gdelt_date IF NOT EXISTS
  FOR (d:Document) ON (d.source, d.gdelt_date);    // gdelt_date immer gefüllt — Index effizient
// Optional separat (wenn Queries auf echtes Publikationsdatum laufen):
// CREATE INDEX doc_published_at FOR (d:Document) ON (d.published_at);
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
  "doc_id": "gdelt:gkg:20260425121500-42",        # canonical, IDENTISCH zum Neo4j doc_id
  "url": "https://…",
  "source_name": "reuters.com",
  "title": first_sentence_or_fallback,
  "themes": ["ARMEDCONFLICT", "KILL", "MILITARY"],
  "persons": ["Putin", "Zelensky"],               # V2.1AllNames top-10
  "organizations": ["NATO", "UN"],
  "locations": [{"name": "Kyiv", "lat": 50.45, "lon": 30.52}],
  "tone_polarity": 8.4,
  "goldstein_linked": -6.5,                       # aus Parquet-Join (pre-materialized)
  "cameo_root_linked": 19,                        # aus Parquet-Join
  "gdelt_date": "2026-04-25T12:15:00Z",           # GDELT-observed time
  "published_at": null,                           # optional, leer wenn nicht aus <PAGE_PRECISEPUBTIMESTAMP>
  "ingested_at": "2026-04-25T12:17:30Z",
  "content_hash": "sha256:…",
  "codebook_type": "conflict.armed"
}

# Point-ID deterministisch aus canonical doc_id:
point_id = uuid5(NAMESPACE_URL, payload["doc_id"])

embed_text = f"{title}\nThemes: {themes_joined}\nActors: {persons_orgs_joined}"[:1500]
# Content-Hash auf embed_text — skip Re-Embed wenn unverändert.
```

**Invariante:** `payload.doc_id` in Qdrant ≡ `d.doc_id` in Neo4j ≡ `doc_id` in GKG-Parquet. Eine Quelle, ein Kanon.

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
│            source_url, codebook_type,
│            filter_reason}  // "tactical" | "nuclear_override"
│
├── gkg/date=2026-04-25/<slice>.parquet
│   schema: {doc_id, url, source_name,
│            gdelt_date,                  // GDELT observed/indexed time
│            published_at,                // optional, nur wenn <PAGE_PRECISEPUBTIMESTAMP> vorhanden
│            themes: list<string>,
│            persons: list<string>,
│            organizations: list<string>,
│            locations: list<struct>,
│            tone: struct,
│            quotations: list<string>,
│            sharp_image_url, word_count,
│            goldstein_linked,            // materialisierter Join-Wert aus Mentions+Events
│            cameo_root_linked,           // materialisierter Join-Wert
│            codebook_type_linked}        // materialisierter Join-Wert
│
└── mentions/date=2026-04-25/<slice>.parquet
    schema: {event_id, mention_url, source_name, mention_time,
             tone, confidence, char_offset}
```

**Materialisierter Join:** Das GKG-Parquet enthält die `*_linked`-Spalten **bereits ausgejoint** zum Zeitpunkt des Filters. Damit ist das GKG-Parquet self-contained für den Qdrant-Writer — Qdrant braucht Neo4j nicht und kann unabhängig rehydriert werden.

**Atomare Writes:** Jede Parquet-Datei wird als `<slice>.parquet.tmp` geschrieben, `fsync`, dann `os.rename(tmp, final)`. Erst nach `rename` wird der Redis-State `done` gesetzt. Ein halbes File existiert nie sichtbar.

Schema-Snapshots als `services/data-ingestion/gdelt_raw/schemas_parquet/*.schema.json` im Repo — Basis für DuckDB-View-Definitionen später.

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

t+0:19  Polars streaming Parse (explizit Tab-separated, no header):
          events_df = pl.read_csv(
              events_path,
              separator="\t",
              has_header=False,
              new_columns=EVENT_COLUMNS,
              schema_overrides=EVENT_POLARS_SCHEMA,
              ignore_errors=False,          # wir zählen Fehler explizit
          )
          mentions_df = pl.read_csv(mentions_path, separator="\t", has_header=False, ...)
          gkg_df      = pl.read_csv(gkg_path,      separator="\t", has_header=False, ...)

          # Quarantine-Strategie: Malformed rows → /data/gdelt/quarantine/<slice>/<stream>.jsonl
          # parse_error_pct = quarantine_count / total_rows
          # Wenn parse_error_pct > GDELT_MAX_PARSE_ERROR_PCT (default 5%) → skip Slice

t+0:22  Filter (multi-stage mit Nuclear-Override):
          # 4a — Tactical Events (CAMEO-Root-Allowlist)
          tactical_event_ids = events_df.filter(
              pl.col("cameo_root").is_in([15,18,19,20])
          ).get_column("event_id")

          # 4b — GKG Alpha-Filter für Knowledge-Graph-Enrichment
          gkg_alpha = gkg_df.filter(matches_alpha_themes)  # prefix-aware

          # 4c — Nuclear-Override: GKG-Docs mit WMD/Nuclear-Themes
          gkg_nuclear = gkg_df.filter(matches_nuclear_override_themes)
          #   Pattern: NUCLEAR, WMD, WEAPONS_PROLIFERATION, WEAPONS_*

          # 4d — Events via Mentions zu Nuclear-Docs auflösen
          nuclear_event_ids = (
              mentions_df
              .filter(pl.col("mention_url").is_in(gkg_nuclear.get_column("url")))
              .get_column("event_id")
              .unique()
          )

          # 4e — Union: Final Event-ID-Set
          final_event_ids = set(tactical_event_ids) | set(nuclear_event_ids)

          events_filtered = events_df.filter(
              pl.col("event_id").is_in(final_event_ids)
          ).with_columns(
              filter_reason = pl.when(pl.col("event_id").is_in(tactical_event_ids))
                                .then("tactical")
                                .otherwise("nuclear_override")
          )
          mentions_filtered = mentions_df.filter(
              pl.col("event_id").is_in(final_event_ids)
          )
          # gkg_filtered = gkg_alpha ∪ gkg_nuclear  (deduped by doc_id)
          gkg_filtered = pl.concat([gkg_alpha, gkg_nuclear]).unique("doc_id")

          # Materialized Join: pre-compute goldstein_linked / cameo_root_linked
          # für gkg_filtered, damit Qdrant Parquet-only-Quelle hat
          gkg_filtered = gkg_filtered.join(
              mentions_filtered.join(events_filtered, on="event_id")
                               .select(["mention_url", "goldstein", "cameo_root", "codebook_type"]),
              left_on="url", right_on="mention_url", how="left"
          ).rename({"goldstein": "goldstein_linked",
                    "cameo_root": "cameo_root_linked",
                    "codebook_type": "codebook_type_linked"})

t+0:25  WRITE — Parquet ZUERST (atomar, per Stream):
          for (stream, df) in [("events", events_filtered),
                                ("mentions", mentions_filtered),
                                ("gkg", gkg_filtered)]:
              tmp = f"/data/gdelt/{stream}/date={date}/{slice}.parquet.tmp"
              final = tmp.removesuffix(".tmp")
              df.write_parquet(tmp, compression="snappy")
              os.fsync + os.rename(tmp, final)
              redis SET gdelt:slice:<slice>:{stream}:parquet = "done"

t+0:27  WRITE — Neo4j (abhängig von Parquet, NICHT abhängig von Qdrant):
          Vorbedingung: events/gkg/mentions Parquet alle "done"
          neo4j_writer.write_from_parquet(slice)
          ON SUCCESS: redis SET gdelt:slice:<slice>:neo4j = "done"
          ON FAIL:    redis SET gdelt:slice:<slice>:neo4j = "failed:<reason>"
                      redis ZADD gdelt:pending:neo4j <slice_ts> <slice>

t+0:35  WRITE — Qdrant (UNABHÄNGIG von Neo4j — liest eigenständig aus GKG-Parquet):
          Vorbedingung: gkg Parquet "done"  (events/mentions NICHT Pflicht —
                        goldstein_linked/cameo_root_linked sind materialisiert)
          qdrant_writer.embed_and_upsert_from_parquet(slice)
          ON SUCCESS: redis SET gdelt:slice:<slice>:qdrant = "done"
          ON TEI_FAIL: redis SET gdelt:slice:<slice>:qdrant = "pending_embed"
                       redis ZADD gdelt:pending:qdrant <slice_ts> <slice>
          # KEIN "ON NEO4J_FAIL: skip" — Qdrant darf weiterlaufen.

t+0:40  Cleanup /tmp/gdelt/<slice>
        Update summary keys (für Status-Anzeigen):
          gdelt:forward:last_slice:parquet = <slice> (nur wenn alle 3 streams done)
          gdelt:forward:last_slice:neo4j   = <slice> (nur wenn done)
          gdelt:forward:last_slice:qdrant  = <slice> (nur wenn done)

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

Beide Projektionen replayen **unabhängig voneinander** aus Parquet:

```python
# Pro Tick, BEVOR neuer Slice geholt wird:

# Neo4j Recovery
pending_neo4j = redis.zrange("gdelt:pending:neo4j", 0, 9)
for slice_id in pending_neo4j:
    if not parquet_exists_for_slice(slice_id, required=["events","gkg","mentions"]):
        continue  # Parquet selbst noch nicht done — später erneut probieren
    try:
        neo4j_writer.write_from_parquet(slice_id)
        redis.zrem("gdelt:pending:neo4j", slice_id)
        redis.set(f"gdelt:slice:{slice_id}:neo4j", "done")
    except Exception as e:
        log.error("neo4j_recovery_retry_failed", slice=slice_id, error=str(e))

# Qdrant Recovery (INDEPENDENT — braucht nur GKG-Parquet)
pending_qdrant = redis.zrange("gdelt:pending:qdrant", 0, 9)
for slice_id in pending_qdrant:
    if not parquet_exists_for_slice(slice_id, required=["gkg"]):
        continue
    try:
        qdrant_writer.embed_and_upsert_from_parquet(slice_id)
        redis.zrem("gdelt:pending:qdrant", slice_id)
        redis.set(f"gdelt:slice:{slice_id}:qdrant", "done")
    except Exception as e:
        log.error("qdrant_recovery_retry_failed", slice=slice_id, error=str(e))
```

---

## 6 · Error-Handling

| Fehler | Reaktion |
|---|---|
| `lastupdate.txt` 5xx/Timeout | Retry 3× exponential backoff (1s, 4s, 15s), dann skip Tick + metric `gdelt_fetch_failed` |
| MD5-Mismatch nach Download | Retry 1×, dann skip Tick + alert-log (GDELT-CDN-Problem) |
| ZIP korrupt | Siehe "Partial-Slice-Regeln" unten — stream-spezifische Behandlung |
| Polars-Parse: malformed row | In Quarantine schreiben: `/data/gdelt/quarantine/<slice>/<stream>.jsonl`. `parse_error_pct = quarantine_count/total_rows`. Wenn überschritten: stream-State `failed`. |
| Pydantic-Contract-Violation am Writer-Input | Log `skip_row reason=…`, continue |
| Neo4j-Timeout | Retry Transaction 3×, dann: Parquet bleibt (`gdelt:slice:<slice>:<stream>:parquet = done`), Neo4j in pending-set. Recovery-Flow übernimmt. |
| Qdrant/TEI down | Embedding skip, Qdrant in pending-set mit Status `pending_embed`. Recovery-Flow reprobiert. **Neo4j läuft unabhängig weiter.** |
| CLI-Backfill-Crash | Redis-State bleibt → resume via CLI möglich |
| `/tmp` voll | Pre-Flight Disk-Space-Check ≥ 200 MB vor Download, sonst skip + metric |
| Duplicate `GlobalEventID` innerhalb desselben Slices | MERGE-idempotent, kein Problem |

### 6.1 Partial-Slice-Regeln (präzise pro Stream)

**Redis-State pro Slice + Stream + Store:**
```
gdelt:slice:<slice>:events:parquet    = done | failed
gdelt:slice:<slice>:gkg:parquet       = done | failed
gdelt:slice:<slice>:mentions:parquet  = done | failed
gdelt:slice:<slice>:neo4j             = done | partial | pending | failed:<reason>
gdelt:slice:<slice>:qdrant            = done | pending_embed | failed:<reason>
```

**Downstream-Regeln:**

| Vorbedingung verletzt | Konsequenz |
|---|---|
| `events:parquet` missing/failed | **Keine Event-Writes** in Neo4j (Knoten + Relationships). Mentions können nicht auf Events joinen → Mentions-Writes übersprungen. GKG darf trotzdem als `:Document` geschrieben werden (standalone, ohne `MENTIONS→Event` Edges). Slice-State `neo4j = partial`. |
| `mentions:parquet` missing/failed | GKG + Events dürfen geschrieben werden. Aber **keine `(:Document)-[:MENTIONS]->(:Event)` Edges**. Slice-State `neo4j = partial`. |
| `gkg:parquet` missing/failed | Events + Mentions werden geschrieben. Aber **kein GKG-Enrichment** (Document/Theme/Entity-Nodes) und **keine Qdrant-Writes** für diesen Slice. Slice-State `neo4j = partial`, `qdrant = skipped`. |
| Alle 3 Streams `parquet = done` | Vollständig. Nach erfolgreichem Neo4j + Qdrant: Slice-State `done`. |

**Sichtbarkeit für Operations:**
```
odin-ingest-gdelt status --slice 20260425121500
# Output:
#   Streams:  events ✓  gkg ✗  mentions ✓
#   Neo4j:    partial (gkg missing — no document/theme enrichment)
#   Qdrant:   skipped (requires gkg)
#   Parquet:  2/3 streams present
```

Ein Slice wird **niemals fälschlich als komplett markiert**. "Done" erfordert explizit alle drei Streams + beide Projektionen erfolgreich.

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
test_parser_uses_tab_separator         # explizit separator="\t", has_header=False
test_malformed_rows_go_to_quarantine   # broken UTF-8 / schema-mismatch → quarantine jsonl
test_gdelt_filter.py                   # Multi-stage filter inkl. Nuclear-Override
test_nuclear_theme_override_keeps_event_outside_cameo_allowlist   # KRITISCH
test_gdelt_theme_matching.py           # prefix-aware: CRISISLEX_* matcht CRISISLEX_T03_DEAD
test_gdelt_cameo_mapping.py            # 14,15,17,18,19,20 → codebook_type vollständig
test_gdelt_id_generation.py            # "gdelt:event:42", "gdelt:gkg:20260425121500-42"
test_qdrant_point_id_is_deterministic_from_doc_id                  # uuid5(NAMESPACE_URL, doc_id)
test_gdelt_entity_normalization.py     # "Vladimir Putin" → ("vladimir putin", "PERSON")
test_gdelt_location_point.py           # lat/lon → point(crs:"wgs-84")
test_gdelt_state.py                    # Per-Stream + Per-Slice + Summary Redis-Keys
```

### 7.3 Component Tests (Fake Clients)
```
test_parquet_written_before_external_stores           # write-order invariant
test_incomplete_tmp_parquet_is_not_marked_done        # atomic write: .tmp → rename → done
test_pending_store_replay_from_parquet                # KRITISCH — recovery-arch
test_store_state_not_advanced_on_failure              # state nur bei success
test_qdrant_can_upsert_when_neo4j_failed_but_parquet_exists   # Qdrant-Neo4j-Decoupling
test_qdrant_payload_uses_canonical_doc_id             # "gdelt:gkg:..." in Neo4j + Qdrant identisch
test_qdrant_pending_embed_when_tei_down               # degraded mode
test_qdrant_embedding_text_deterministic              # stable hash
test_qdrant_content_hash_skips_reembed                # no wasted TEI calls
test_neo4j_merge_is_idempotent                        # 2× Input, 1× Node-Count
test_source_node_reused                               # (:Source) MERGE, kein Dup
test_theme_node_reused
test_corrupt_mentions_does_not_create_document_event_edges   # partial-slice Regel
test_partial_slice_is_not_marked_fully_done                  # partial ≠ done
test_gkg_parquet_contains_materialized_join_fields           # goldstein_linked etc.
```

### 7.4 Contract Tests (Neo4j Schema)
```
test_constraints_created_idempotently
test_gdelt_event_constraint_rejects_duplicate_event_id
test_gdelt_doc_constraint_rejects_duplicate_doc_id
test_source_constraint_preflight_detects_duplicate_sources   # blocks migration
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

## 13 · Review-Historie

### 2026-04-25 — Must-Fix-Review (6 kritische + 5 kleinere Fixes)

1. **Qdrant `doc_id` canonical** — war inkonsistent zwischen Neo4j (`gdelt:gkg:<id>`) und Qdrant (`gkg-<id>`). Jetzt überall `gdelt:gkg:<GKGRecordID>`. Point-ID deterministisch via `uuid5(NAMESPACE_URL, doc_id)`.
2. **Nuclear-Override in Filter-Flow** — war nur im Scope beschrieben, aber nicht im Filter implementiert. Neuer Multi-Stage-Filter mit expliziter UNION: `tactical_event_ids ∪ nuclear_event_ids`. `filter_reason`-Column im Parquet.
3. **Qdrant von Neo4j entkoppelt** — "ON NEO4J_FAIL: qdrant skip" entfernt. Qdrant liest unabhängig aus GKG-Parquet mit materialisiertem Join (`goldstein_linked`, `cameo_root_linked`).
4. **Source-Constraint mit Preflight** — Duplicate-Check gegen Altbestand Pflicht vor `CREATE CONSTRAINT source_name_unique`.
5. **Polars-Parser explizit** — `separator="\t"`, `has_header=False`, `ignore_errors=False`, Malformed rows → Quarantine-JSONL.
6. **Partial-Slice-State präzise** — Per-Stream State: `events:parquet`, `gkg:parquet`, `mentions:parquet`. Klare Downstream-Regeln für jeden Fehlfall.
7. **`published_at` Semantik gefixt** — `gdelt_date` als always-present observed-time, `published_at` nullable (aus `<PAGE_PRECISEPUBTIMESTAMP>`).
8. **Atomare Parquet-Writes** — `.parquet.tmp` + `fsync` + `rename`, erst dann State `done`.
9. **Path-Konsistenz** — `gdelt_raw/schemas_parquet/` überall einheitlich.
10. **Typo "gewiederverwendet" → "wiederverwendet"**.
11. **Double-Negative "keine Phase danach nicht skipbar"** entfernt, durch klare Aussage ersetzt.

---

## 14 · Referenzen

- GDELT 2.0 Announcement: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- GDELT Event Codebook: http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
- GDELT GKG Codebook: http://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf
- CAMEO Event Codes: https://www.gdeltproject.org/data/lookups/CAMEO.eventcodes.txt
- Bestehender Collector: `services/data-ingestion/feeds/gdelt_collector.py` (bleibt für DOC-API)
- Bestehende Neo4j-Schema (2026-04-25): 10345 Events, 10164 Documents, 6335 Entities, 0 Constraints
- CLAUDE.md Regel: Kein LLM-generiertes Cypher auf Write-Path ✓ (GDELT ist bereits strukturiert)
