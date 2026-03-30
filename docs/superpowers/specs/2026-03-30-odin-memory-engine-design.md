# ODIN Memory Engine — Design Spec

**Datum:** 2026-03-30
**Status:** Approved — ready for implementation
**Service:** `services/memory` (neu)
**Scope:** v1 — IntelFact-Datenmodell + UPDATES/EXTENDS/DERIVES Resolution Loop

---

## 1. Ziel

ODIN behandelt derzeit **Dokumente** (Chunks in Qdrant). Dieses System führt **atomare IntelFacts** als versionierte, quellengebundene Datenpunkte ein. Der Kern-Differenziator: ein LLM-basierter Resolution-Loop, der Widersprüche, Anreicherungen und Inferenzen zwischen Facts erkennt und im Graph abbildet.

Ergebnis: ODIN weiß nicht nur "welche Dokumente über X existieren", sondern "was aktuell über X bekannt ist, woher das Wissen stammt, und was veraltet ist."

---

## 2. Systemarchitektur

### Schichten-Übersicht

```
① Datenquellen
   WEB/DOKUMENTE              FEEDS                      LIVE
   crawl4ai  [v2]             RSS (25+ Quellen)          AISStream WebSocket    → Schiffe
   docling   [v2]             GDELT (7 Themen)           OpenSky REST API       → Flüge [near-realtime poll, 10s]
   Manual Upload              Hotspot-URLs               adsb.fi REST API       → Flüge [near-realtime poll, 10s]
                              CelesTrak TLE (16 Gr.)     USGS GeoJSON           → Erdbeben
                                                         Windy API              → CCTV

② Ingestion (services/data-ingestion)
   HEUTE AKTIV: rss_collector, gdelt_collector, hotspot_updater, tle_updater
   HEUTE IM BACKEND: flight_ws (OpenSky+adsb.fi poll), vessel_ws (AISStream), earthquake fetch
   [v2: flight_poller + vessel_ws → data-ingestion → Redis]
   [v2: earthquake_collector → data-ingestion]
   Text-Pipeline v1: title + summary aus Feed-Metadaten
   Text-Pipeline v2: crawl4ai → Volltext → docling → Validation → Chunker → TEI Embed → POST /ingest

③ Memory Engine — NEU (services/memory :8004)
   Kern: Fact Extraction → Resolution → Idempotenter Write (Neo4j first, Qdrant derived)

④ Intelligence Pipeline (services/intelligence :8003)
   LangGraph agents nutzen POST /recall (memory) für Kontext
   synthesis_node schreibt Assessments via POST /ingest/sync → schließt Lernkreislauf

⑤ Backend (services/backend :8080)
   /ws/flights  → OpenSky + adsb.fi near-realtime poll [v2: Redis-Consumer]
   /ws/vessels  → AISStream WebSocket                  [v2: Redis-Consumer]
   /api/v1/flights     → heute: extern + Redis-Cache   [v2: Redis-only]
   /api/v1/satellites  → heute: extern + Redis-Cache   [v2: Redis-only]
   /api/v1/vessels     → heute: Redis read (kein extern fetch im Handler)
   /api/v1/earthquakes → heute: Backend holt USGS direkt [v2: data-ingestion]
   /api/v1/intel/query → services/intelligence → /recall
   /api/v1/rag/stats   → Qdrant direkt

⑥ Persistence
   Neo4j :7687  IntelFact-Nodes + UPDATES/EXTENDS/DERIVES-Kanten [Source of Truth: is_latest]
   Qdrant :6333 Embeddings (odin_intel) — is_latest derived von Neo4j
   Redis :6379  Live-State (flights/vessels/TLE) + Async-Job-Queue (Resolution-Tasks)
```

---

## 3. Datenmodell

### 3.1 fact_id — Idempotenz-Schlüssel

```
fact_id          = SHA256(entity_id + "||" + normalize(content) + "||" + source_ref)
canonical_fact_id = SHA256(entity_id + "||" + normalize(content))
```

**normalize(content):** lowercase → strip whitespace → collapse multiple spaces → kein Stemming

Semantik: Gleicher Inhalt aus zwei Quellen → zwei Facts (Provenance erhalten). `canonical_fact_id` verbindet sie für Corroboration-Lookup.

### 3.2 Neo4j Nodes

```cypher
// IntelFact
(:IntelFact {
    fact_id:                String,   // PK — SHA256(entity_id||content||source_ref)
    canonical_fact_id:      String,   // SHA256(entity_id||content) — Cross-Source
    content:                String,   // Atomarer, menschenlesbarer Fakt
    entity_id:              String,   // FK → Entity.entity_id
    fact_type:              String,   // "fact" | "assessment" | "episode"
    domain:                 String,   // "osint"|"sigint"|"humint"|"geoint"|"techint"|"analysis"
    confidence_raw:         Float,    // 0.0–1.0 — Extractor-Output
    confidence_final:       Float,    // nach Corroboration-Boost
    corroboration_count:    Integer,  // Anzahl korroborierender Quellen
    corroboration_sources:  List[String], // Set der source_refs die bereits geboosted haben — Duplikat-Schutz
    source_ref:             String,   // "gdelt:conflict_military"|"rss:bellingcat"|"synthesis_agent/v1"
    source_url:             String?,
    timestamp:              DateTime,
    valid_until:            DateTime?,
    is_latest:              Boolean,  // Source of Truth — Qdrant derived
    model_version:          String,   // "qwen3.5-27b-awq/v1"
    normalizer_version:     String,   // "v1" — Hash-Reproduzierbarkeit
    qdrant_sync_status:     String,   // "pending"|"in_progress"|"done"|"failed_permanent"
    qdrant_sync_worker_id:    String?,
    qdrant_sync_in_progress_at: DateTime?,
    qdrant_sync_retry_count:  Integer,
    qdrant_sync_next_retry_at: DateTime?   // Backoff-Zeitpunkt
})

// Entity
(:Entity {
    entity_id:    String,   // PK — slugified: "pla_rocket_force", "yaogan_cluster_7"
    entity_type:  String,   // "military_unit"|"satellite"|"vessel"|"actor"|"location"|"event"
    display_name: String,
    created_at:   DateTime,
    updated_at:   DateTime
})
```

### 3.3 Neo4j Relationships

```cypher
// Primary Entity-Bezug
(f:IntelFact)-[:ABOUT]->(e:Entity)

// v2: Nebenakteure
(f:IntelFact)-[:MENTIONS]->(e:Entity)

// Resolution-Kanten — alle drei Typen tragen dasselbe Property-Schema:
(new:IntelFact)-[:UPDATES {
    reason:              String,
    resolver_confidence: Float,
    model_version:       String,
    trace_id:            String,
    created_at:          DateTime
}]->(old:IntelFact)
// UPDATES: new widerspricht old → old.is_latest = false

(enriching:IntelFact)-[:EXTENDS { ...same props... }]->(base:IntelFact)
// EXTENDS: enriching ergänzt base → beide is_latest=true

(derived:IntelFact)-[:DERIVES { ...same props... }]->(source:IntelFact)
// DERIVES: logische Inferenz aus 1..n Quellen → derived is_latest=true
```

### 3.4 Neo4j Constraints & Indices

```cypher
CREATE CONSTRAINT unique_fact_id   FOR (f:IntelFact) REQUIRE f.fact_id IS UNIQUE;
CREATE CONSTRAINT unique_entity_id FOR (e:Entity)    REQUIRE e.entity_id IS UNIQUE;
CREATE INDEX fact_entity_latest    FOR (f:IntelFact) ON (f.entity_id, f.is_latest, f.timestamp);
CREATE INDEX fact_canonical        FOR (f:IntelFact) ON (f.canonical_fact_id);
CREATE INDEX fact_sync_status      FOR (f:IntelFact) ON (f.qdrant_sync_status);
```

### 3.5 Qdrant Payload

```json
{
  "id": "<fact_id>",
  "vector": [1024 floats],
  "payload": {
    "fact_id":            "sha256...",
    "canonical_fact_id":  "sha256...",
    "entity_id":          "pla_rocket_force",
    "is_latest":          true,
    "domain":             "osint",
    "confidence_final":   0.85,
    "corroboration_count": 2,
    "fact_type":          "fact",
    "source_ref":         "rss:csis",
    "timestamp":          "2026-01-15T...",
    "valid_until":        null
  }
}
```

Payload-Indices: `entity_id`, `canonical_fact_id`, `is_latest`, `domain`, `confidence_final`, `timestamp`

**Konsistenz-Garantie:** Neo4j ist Source of Truth für `is_latest`. Qdrant-Update erfolgt immer *nach* erfolgreichem Neo4j-Write via Outbox-Worker.

---

## 4. API-Schema

### 4.1 POST /ingest/sync

Synchron. Max 2000 Zeichen pro Item. Wartet auf Extraction + Resolution.

**Header:** `Idempotency-Key: <uuid>` (optional)

Semantik: Server speichert `(idempotency_key, request_body_hash) → response` für 24h in Redis.
Bei erneutem Request mit gleichem Key: wenn `SHA256(body)` übereinstimmt → cached Response zurück.
Wenn `SHA256(body)` abweicht → **409 Conflict** (`{"error": "idempotency_key_body_mismatch"}`).
Dadurch ist es sicher, denselben Key bei Netzwerkfehlern zu wiederholen, ohne falsche Responses zu riskieren.

**Request:**
```json
{
  "items": [
    {
      "content":    "string (max 2000 Zeichen)",
      "source_ref": "gdelt:conflict_military",
      "source_url": "https://...",
      "domain":     "osint",
      "entity_id":  "pla_rocket_force"
    }
  ]
}
```

**Response 200:**
```json
{
  "ingest_id": "uuid",
  "facts": [
    {
      "fact_id":           "sha256...",
      "canonical_fact_id": "sha256...",
      "content":           "PLA Rocket Force expanded to 7 brigades",
      "entity_id":         "pla_rocket_force",
      "confidence_raw":    0.82,
      "confidence_final":  0.85,
      "corroboration_count": 1,
      "resolution": {
        "relation":            "UPDATES",
        "target_fact_id":      "sha256...",
        "reason":              "Newer source reports restructuring to 7 brigades",
        "resolver_confidence": 0.91,
        "model_version":       "qwen3.5-27b-awq/v1",
        "trace_id":            "uuid"
      }
    }
  ]
}
```

### 4.2 POST /ingest

Async. Bulk. Kein Größenlimit.

**Header:** `Idempotency-Key: <uuid>` (optional, gleiche Semantik wie /ingest/sync)

**Request:** identische Struktur wie `/ingest/sync`, mit folgenden Grenzen:
- Max **500 Items** pro Request (sonst 413) — Schutz vor Request-Überflutung
- Kein `content`-Größenlimit pro Item (im Gegensatz zu `/ingest/sync` mit 2000 Zeichen)
- Schema-Fehler (fehlendes `content`, ungültiger `domain`) → **400** (synchron, vor Queuing)

**Response 202:**
```json
{ "ingest_id": "uuid", "status": "pending", "item_count": 42 }
```

**Fehler-Trennung:** Input-Validierung → 4xx (synchron). Verarbeitungsfehler (vLLM, Neo4j) → nur in `GET /ingest/{id}` als `status: "failed_permanent" + error_code`.

### 4.3 GET /ingest/{ingest_id}

```json
{
  "ingest_id":       "uuid",
  "status":          "pending | processing | done | failed_permanent",
  "facts_extracted": 12,
  "facts_stored":    10,
  "error_code":      null,
  "error":           null
}
```

### 4.4 POST /recall

```json
{
  "query":          "Current PLA Rocket Force capabilities",
  "entity_id":      "pla_rocket_force",
  "domain":         "osint",
  "min_confidence": 0.6,
  "top_k":          10
}
```

**Response 200:**
```json
{
  "facts": [
    {
      "fact_id":            "sha256...",
      "content":            "PLA Rocket Force expanded to 7 brigades after 2025 restructuring",
      "entity_id":          "pla_rocket_force",
      "score":              0.923,
      "confidence_final":   0.85,
      "corroboration_count": 2,
      "source_ref":         "rss:csis",
      "timestamp":          "2026-01-15T...",
      "is_latest":          true,
      "relations": {
        "updates_out":  ["sha256..."],
        "updated_by":   [],
        "extends_out":  [],
        "extends_in":   ["sha256..."],
        "derives_out":  ["sha256..."],
        "derived_from": []
      }
    }
  ]
}
```

### 4.5 GET /entity/{entity_id}

v1: Stub — gibt `entity_id + fact_count` zurück.
v2: Vollständiges Dossier mit `static_facts` (confidence ≥ 0.6, is_latest, valid_until=null) und `dynamic_facts` (letzte 30 Tage oder valid_until gesetzt).

### 4.6 GET /health

```json
{ "status": "ok" }
```

---

## 5. Resolution-Flow (intern, pro extrahiertem Fact)

```
new_fact (content, entity_id, confidence_raw, source_ref, domain)
    │
    ├─ fact_id           = SHA256(entity_id + "||" + normalize(content) + "||" + source_ref)
    ├─ canonical_fact_id = SHA256(entity_id + "||" + normalize(content))
    │
    ├─▶ Idempotenz — zweistufig:
    │   Stufe 1 (Advisory): MATCH (f:IntelFact {fact_id}) → Existiert? → SKIP
    │     Optimierung, reduziert unnötige Embedding/LLM-Calls
    │     Nicht race-condition-sicher (concurrent writes möglich)
    │   Stufe 2 (Primärschutz): MERGE (f:IntelFact {fact_id}) in der Write-Transaktion
    │     UNIQUE CONSTRAINT auf fact_id → DB wirft ConstraintViolationError bei Duplikat
    │     Implementierung: ConstraintViolationError catchen → als SKIP behandeln, kein Fehler
    │
    ├─▶ TEI Embed :8001 → vector (1024-dim)
    │
    ├─▶ Qdrant semantic search:
    │   Query A: top-10, filter {entity_id, is_latest: true}
    │   Query B: top-3,  filter {canonical_fact_id}  ← Corroboration-Lookup
    │
    │   Corroboration-Regeln (Feedback-Loop-Prävention):
    │       confidence_final = confidence_raw   // Startwert
    │       Für jeden Treffer t in Query B:
    │         Boost gilt NUR wenn t.source_ref ≠ new_fact.source_ref
    │         UND new_fact.source_ref ∉ t.corroboration_sources  (Set auf IntelFact-Node)
    │       Einmalig pro (fact_id × corroborating_source_ref):
    │         confidence_final = min(confidence_final + 0.1, 1.0)  // +0.1 pro Quelle
    │         new_fact.corroboration_count += 1                     // +1 pro Quelle (gleicher Schritt)
    │         new_fact.corroboration_sources.add(t.source_ref)
    │         t.corroboration_count += 1  (Neo4j-Update, qdrant_sync_status=pending)
    │         t.corroboration_sources.add(new_fact.source_ref)
    │       Kein erneuter Boost bei Reingest derselben source_ref
    │
    ├─▶ Resolver (vLLM) — NUR wenn max(candidates.score) > 0.75:
    │   Input:  new_fact_content + top-5 candidates (content + source_ref + confidence_final)
    │   Output: { relation, target_fact_id, reason, resolver_confidence,
    │              model_version, trace_id }
    │
    │   UPDATES (resolver_confidence ≥ 0.7):
    │   ┌─ BEGIN TRANSACTION ──────────────────────────────────────────────────┐
    │   │  MATCH (old {fact_id: target_id})                                    │
    │   │  SET old.is_latest = false                                            │
    │   │  SET old.qdrant_sync_status = "pending"                               │
    │   │  MERGE (new:IntelFact {fact_id}) SET new += {...props...}             │
    │   │  // UNIQUE constraint → ConstraintViolationError bei Duplikat → SKIP  │
    │   │  MERGE (new)-[:ABOUT]->(entity)                                       │
    │   │  CREATE (new)-[:UPDATES {reason, resolver_confidence, ...}]->(old)   │
    │   │  SET new.qdrant_sync_status = "pending"                               │
    │   └─ END TRANSACTION ────────────────────────────────────────────────────┘
    │
    │   EXTENDS:
    │   ┌─ BEGIN TRANSACTION ──────────────────────────────────────────────────┐
    │   │  MERGE (new:IntelFact {fact_id}) SET new += {...props...}             │
    │   │  CREATE (new)-[:ABOUT]->(entity)                                      │
    │   │  CREATE (new)-[:EXTENDS {reason, resolver_confidence, ...}]->(target)│
    │   │  SET new.qdrant_sync_status = "pending"                               │
    │   └─ END TRANSACTION ────────────────────────────────────────────────────┘
    │
    │   DERIVES:
    │   ┌─ BEGIN TRANSACTION ──────────────────────────────────────────────────┐
    │   │  MERGE (new:IntelFact {fact_id}) SET new += {...props...}             │
    │   │  CREATE (new)-[:ABOUT]->(entity)                                      │
    │   │  CREATE (new)-[:DERIVES {reason, resolver_confidence, ...}]->(target)│
    │   │  SET new.qdrant_sync_status = "pending"                               │
    │   └─ END TRANSACTION ────────────────────────────────────────────────────┘
    │
    │   NONE oder resolver_confidence < 0.7:
    │   ┌─ BEGIN TRANSACTION ──────────────────────────────────────────────────┐
    │   │  MERGE (new:IntelFact {fact_id}) SET new += {...props...}             │
    │   │  CREATE (new)-[:ABOUT]->(entity)                                      │
    │   │  SET new.qdrant_sync_status = "pending"                               │
    │   └─ END TRANSACTION ────────────────────────────────────────────────────┘
    │
    └─▶ Qdrant-Sync via Outbox-Worker (Redis Queue)
```

---

## 6. Outbox-Worker (Qdrant-Sync)

Verhindert Drift zwischen Neo4j und Qdrant. Läuft als Background-Task in `services/memory`.

```
Fehlerklassen:
    TRANSIENT  → Qdrant temporär nicht erreichbar, Netzwerk-Timeout
                 → retry mit Backoff, zählt gegen retry_count
    PERMANENT  → Payload-Schema ungültig, fact_id nicht in Neo4j auffindbar
                 → sofort Dead-Letter, kein Retry

Claiming-Protokoll:
    MATCH (f:IntelFact {qdrant_sync_status: "pending"})
    WHERE f.qdrant_sync_retry_count < 5
      AND (f.qdrant_sync_next_retry_at IS NULL    // Erstverarbeitung: null = sofort
           OR f.qdrant_sync_next_retry_at <= now())  // Retry: Backoff-Fenster abgelaufen
    SET f.qdrant_sync_status = "in_progress"
        f.qdrant_sync_worker_id = worker_id
        f.qdrant_sync_in_progress_at = now()
    RETURN f LIMIT 50

    → Für jeden Fact:
        Qdrant upsert (fact_id, vector, payload)
        Neo4j SET f.qdrant_sync_status = "done"

    → Bei TRANSIENT-Fehler:
        backoff = min(2^retry_count * 5s + jitter(0–2s), 300s)
        SET f.qdrant_sync_status = "pending"
            f.qdrant_sync_retry_count += 1
            f.qdrant_sync_next_retry_at = now() + backoff

    → Bei PERMANENT-Fehler oder retry_count ≥ 5:
        SET f.qdrant_sync_status = "failed_permanent"
        → Log ERROR mit fact_id, letzter Fehler, retry-Historie
        → (optional v2: Dead-Letter-Queue in Redis für manuelle Inspektion)

Reconcile-Job (Fallback): alle 60s
    MATCH (f:IntelFact {qdrant_sync_status: "in_progress"})
    WHERE f.qdrant_sync_in_progress_at < now() - 120s  // stale lock
    SET f.qdrant_sync_status = "pending"
        f.qdrant_sync_worker_id = null
        f.qdrant_sync_next_retry_at = now()
```

`IntelFact` bekommt zusätzlich: `qdrant_sync_next_retry_at: DateTime?`

---

## 7. Error Handling

| Fehlerquelle | Verhalten |
|---|---|
| Extractor (vLLM) timeout | 503 für /sync · async: status=failed · keine Facts gespeichert · retry-safe |
| Resolver (vLLM) Fehler | Fact wird mit NONE gespeichert · Resolution-Retry via Queue |
| Neo4j Write-Fehler | Gesamter Fact-Ingest abgebrochen · Transaktion rollback · idempotent bei Retry |
| Qdrant Write-Fehler nach Neo4j | `qdrant_sync_status=pending` bleibt · Outbox-Worker übernimmt · kein Datenverlust |
| Input-Validierungsfehler (Schema, Übergröße) | 400/413 synchron · vor jeder Verarbeitung |
| Idempotency-Key bekannt, gleicher Body | Cached Response (200/202) aus Redis · kein Re-Processing |
| Idempotency-Key bekannt, anderer Body | 409 Conflict · `error: idempotency_key_body_mismatch` |

---

## 8. Implementierungs-Scope

### v1 (dieser Zyklus)

- `services/memory` FastAPI-Service mit allen Endpoints
- IntelFact-Extraktion via vLLM
- Resolution-Loop (UPDATES/EXTENDS/DERIVES/NONE)
- Neo4j-Write (transaktional) + Qdrant-Sync (Outbox-Worker)
- `POST /recall` Hybrid Search
- `GET /entity/{id}` Stub
- Neo4j Constraints + Indices
- docker-compose: `services/memory :8004`, healthcheck, depends_on
- `services/intelligence`: osint_node nutzt `/recall`, synthesis_node schreibt via `/ingest/sync`
- `services/data-ingestion`: Collector-Output an `/ingest` (async)

### v2 (nächster Zyklus)

- crawl4ai + docling in Ingestion-Pipeline
- `GET /entity/{id}` vollständig (Static + Dynamic Profile)
- `[:MENTIONS]` für Nebenakteure
- earthquake_collector.py in data-ingestion
- flight_poller + vessel_ws → data-ingestion → Redis
- `/api/v1/flights`, `/api/v1/satellites`, `/api/v1/vessels` → Redis-only

### Technische Schulden (explizit)

- flight_ws + vessel_ws im Backend produzieren Live-State (soll nach data-ingestion)
- `/api/v1/flights` + `/api/v1/satellites` fetchen extern + cachen (soll Redis-only)
- `/api/v1/earthquakes` im Backend (soll data-ingestion-Job)

---

## 9. Abhängigkeiten

| Service | Abhängigkeit |
|---|---|
| services/memory | Neo4j :7687, Qdrant :6333, Redis :6379, vLLM :8000, TEI Embed :8001 |
| services/intelligence | services/memory :8004 (neu) |
| services/data-ingestion | services/memory :8004 (neu) |
| services/backend | services/intelligence :8003 (bestehend) |

---

## 10. Offene Entscheidungen (nicht in v1)

- `normalize(content)` Version 2 (Stemming, Transliteration) → normalizer_version ermöglicht spätere Migration ohne Hash-Bruch
- Langfuse-Integration für Extraction + Resolution Tracing (trace_id ist bereits im Schema)
- Obsidian-Export: EntityProfiles als Markdown-Notes mit Backlinks
