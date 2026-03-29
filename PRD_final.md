# PRD — Odin OSINT Analytics (Delta auf WorldView)

## 1. Ausgangslage

WorldView ist eine funktionsfähige Tactical Intelligence Platform mit:
- CesiumJS 3D Globe + Google Photorealistic 3D Tiles
- FastAPI Backend mit Proxy + Cache
- LangGraph 3-Agent RAG Pipeline (OSINT → Analyst → Synthesis)
- Live-Daten: Flights (27K+), Satellites (SGP4), Ships (AIS), Earthquakes (USGS)
- Qdrant Vector DB + Redis Cache
- 27 RSS Feeds + GDELT + TLE Collectors
- GLSL Post-Processing (CRT, Night Vision, FLIR)
- 50+ Geopolitical Hotspots Threat Register

Zusätzlich existieren:
- **Sentinel**: RSS Feed Poller mit Obsidian-Integration und Crawler
- **OSINT_MCP**: FastMCP Geo Agent mit 10 Think-Tank-Feeds, Topic Classification, Daily Report

## 2. Enhancement-Ziele (MVP)

| # | Enhancement | Traversals-Parität |
|---|-------------|-------------------|
| E1 | Neo4j Knowledge Graph (Two-Loop: Templates Write, LLM Read) | ✅ |
| E2 | Event Codebook + LLM Classifier + Entity Extractor (1 Call) | ✅ |
| E3 | Ingestion Pipeline: Extract → Classify → Graph Write | ✅ |
| E4 | Docling Document Parsing + Qdrant native Hybrid Search + Reranker | ✅ |
| E5 | Agent Tools: Graph Query, Classify, Qwen3.5 native Vision | ✅ |
| E6 | LLM/Embedding Upgrade: vLLM + Qwen3.5-27B + Qwen3-Embedding | Übertrifft |
| E7 | Graph Explorer Frontend (react-force-graph-2d) | ✅ |
| E8 | Hybrid Vision: YOLOv8m (military detection) + Qwen3.5 (reasoning) | Übertrifft |

## 3. Techstack-Delta

### MVP — Neu hinzukommend
| Komponente | Technologie | Zweck |
|------------|-------------|-------|
| Graph DB | Neo4j Community 5.x | Knowledge Graph, Two-Loop Architecture |
| Doc Parser | Docling 2.80+ | PDF/DOCX/HTML mit Layout-Analyse, TableFormer |
| Hybrid Search | Qdrant native BM25 + Dense + RRF | Serverseitige Fusion, kein rank_bm25 nötig |
| Reranker | Qwen3-Reranker-0.6B | Cross-Encoder Reranking via sentence-transformers |
| Vision (general) | Qwen3.5-27B nativ multimodal | Captioning, OCR, VQA — 0 GB extra VRAM |
| Vision (military) | YOLOv8m fine-tuned + Qwen3.5 Reasoner | Satellite/Aerial: Detect → Crop → Classify → Graph |
| Entity Extraction | LLM Structured Output (JSON) | Erkennt OSINT-Entities die spaCy nicht kann |
| Graph Viz | react-force-graph-2d | Entity Network Explorer im Frontend |

### MVP — Upgrades bestehender Komponenten
| Besteht | Upgrade | Begründung |
|---------|---------|------------|
| Ollama | vLLM | Continuous Batching, AWQ, OpenAI-API, Vision Support |
| Qwen3-32B | Qwen3.5-27B AWQ | Tool-Calling (BFCL 72.2), 201 Sprachen, nativ multimodal |
| nomic-embed-text | Qwen3-Embedding-0.6B | 100+ Sprachen, flexible Dimensionen, MTEB Top-Tier |
| APScheduler (27 RSS) | + 10 Think-Tank Feeds (aus MCP) | Breitere Quellenbasis |
| SQLite (MCP) | Neo4j | Graph-native statt relational |

### Phase Next — Nach MVP
| Komponente | Technologie | Warum nicht MVP |
|------------|-------------|-----------------|
| Deep Crawler | Crawl4AI 0.8+ | RSS reicht für MVP, Crawl4AI braucht Proxy-Infra |
| Telegram | Telethon | API-Credentials, rechtliche Prüfung |
| Multilingual OCR | EasyOCR | Qwen3.5 kann OCR für Hauptsprachen |
| Image Search | CLIP + Qdrant Image Collection | Braucht eigene Vector Collection |
| Geocoding | Nominatim self-hosted + geopy | LLM extrahiert Locations, Globe plottet |
| Auth | JWT + RBAC | Single-User MVP braucht kein Auth |
| Anomaly Detection | Prophet auf Event-Frequenzen | Braucht erstmal historische Daten |

## 4. Neo4j Datenmodell (Yggdrasil)

```cypher
// Node Types
(:Entity {id, name, type, aliases, confidence, first_seen, last_seen})
  // type ∈ [person, organization, location, weapon_system, satellite, vessel, aircraft, military_unit]
(:Event {id, title, summary, timestamp, codebook_type, severity, confidence})
(:Source {url, name, credibility_score, last_fetched})
(:Location {name, country, lat, lon})

// Vision-specific Nodes
(:MilitaryAsset {vehicle_type, category, last_seen})
(:Detection {timestamp, confidence, status, context, image_source, location})

// Relationships
(:Event)-[:INVOLVES]->(:Entity)
(:Event)-[:REPORTED_BY]->(:Source)
(:Event)-[:OCCURRED_AT]->(:Location)
(:Entity)-[:ASSOCIATED_WITH {type, confidence}]->(:Entity)
(:Detection)-[:IDENTIFIED]->(:MilitaryAsset)
(:Detection)-[:DETECTED_AT]->(:Location)
(:Event)-[:VISUAL_EVIDENCE]->(:Detection)

// Constraints + Indexes
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (ev:Event) REQUIRE ev.id IS UNIQUE;
CREATE CONSTRAINT source_url IF NOT EXISTS FOR (s:Source) REQUIRE s.url IS UNIQUE;
CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name);
CREATE INDEX event_timestamp IF NOT EXISTS FOR (ev:Event) ON (ev.timestamp);
CREATE INDEX event_type IF NOT EXISTS FOR (ev:Event) ON (ev.codebook_type);
```

## 5. Graph-Architektur (Two-Loop)

### WRITE PATH (Ingestion → Graph)
```
Feed-Item
  → LLM: extract(text) → JSON {entities, events, locations}  (Structured Output)
  → Pydantic: ExtractionResult.model_validate(json)
  → Deterministic Cypher Templates (write_templates.py)
  → Neo4j MERGE/CREATE
```
**Kein LLM-generiertes Cypher.** Templates sind statisch, Parameter kommen aus Pydantic.

### READ PATH (Query → Graph)
```
Natural Language Question
  → System Prompt: Schema + 5 Few-Shot NL→Cypher Paare
  → LLM generiert Cypher
  → Validation: validate_cypher_readonly() — Regex blockt CREATE/MERGE/DELETE/SET
  → Execute: READ-ONLY Transaction
  → Bei Fehler: Error Message → LLM → Retry (max 3)
  → Success: LLM summariert Ergebnisse als Antwort
```

## 6. Event Codebook (Auszug)

```yaml
military: [armed_clash, troop_movement, air_strike, drone_attack,
           naval_engagement, missile_launch, military_exercise, arms_transfer]
space:    [satellite_launch, orbit_maneuver, space_debris_event,
           reconnaissance_satellite, ASAT_test]
cyber:    [data_breach, state_sponsored_hack, infrastructure_disruption,
           disinformation_campaign, ransomware_attack]
political:[election, coup_attempt, sanctions_imposed, sanctions_lifted,
           treaty_signed, diplomatic_incident, protest, government_change]
infrastructure: [bridge_destroyed, power_grid_failure, port_blockade,
                 airport_closure, pipeline_disruption, communication_outage]
humanitarian:   [refugee_movement, famine_crisis, epidemic_outbreak,
                 natural_disaster, civilian_casualties]
economic: [trade_embargo, currency_crisis, supply_chain_disruption,
           energy_price_shock, nationalization]
```

## 7. VRAM-Budget (RTX 5090, 32 GB)

```
Modus A — Agent + Analysis + Vision (Default):
  vLLM: Qwen3.5-27B AWQ INT4        ~16 GB
  Qwen3-Embedding-0.6B               ~1.2 GB
  Qwen3-Reranker-0.6B                ~1.2 GB (on-demand)
  YOLOv8m (military fine-tuned)       ~2 GB (persistent)
  Vision Reasoning: Qwen3.5            0 GB (already loaded)
  ────────────────────────────────────────────
  Total: ~20.4 GB | Headroom: ~11.6 GB ✅

Modus B — Batch Classification (Hot-Swap):
  vLLM: Qwen3.5-35B-A3B FP16         ~7 GB
  Qwen3-Embedding-0.6B                ~1.2 GB
  YOLOv8m                              ~2 GB
  ────────────────────────────────────────────
  Total: ~10.2 GB | Headroom: ~21.8 GB ✅
```

## 8. Risiken

| Risiko | Mitigation |
|--------|------------|
| Neo4j bricht bestehende Qdrant-Flows | Parallel betreiben: Neo4j = Graph, Qdrant = Vektoren |
| vLLM-Migration bricht LangGraph Config | OpenAI-kompatible API, nur base_url + model ändern |
| Embedding-Wechsel erfordert Re-Index | Neue Qdrant Collection, alte behalten bis validiert |
| LLM-generiertes Cypher halluziniert | READ-ONLY + Validation + Self-Heal + Few-Shot |
| YOLOv8 Fine-Tuning braucht annotierte Daten | xView + DOTA v2 + FAIR1M frei verfügbar |
| YOLOv8 AGPL-3.0 Lizenz | Für internes Tool ok, bei Kommerzialisierung RT-DETR (Apache) evaluieren |
| Entity Extraction via LLM unvollständig | Confidence Score + Human-in-the-Loop Flag bei <0.5 |

## 9. Neue Dependencies (über WorldView hinaus)

```
vllm                         # LLM Serving
sentence-transformers>=3.0   # Embedding + Reranker
neo4j>=5.23                  # Graph DB Driver
openai>=1.40                 # vLLM Client
docling[vlm,easyocr]>=2.80   # Document Parsing
pyyaml>=6.0                  # Event Codebook
ultralytics>=8.2             # YOLOv8 Military Detection (AGPL-3.0)
Pillow>=10.0                 # Image Processing
react-force-graph-2d ^1.25   # Frontend Graph Viz
```

**8 Python + 1 Frontend Dependencies. YOLOv8 ist AGPL — für MVP als internes Tool akzeptabel.**
