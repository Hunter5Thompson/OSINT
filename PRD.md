# PRD — Odin OSINT Analytics (WorldView Tactical Intelligence Platform)

## Projektvision

WorldView löst das Problem, dass taktische Lagebilder entweder proprietär und teuer (Palantir Gotham) oder fragmentiert über Dutzende Einzelquellen verstreut sind. Die Lösung fusioniert öffentlich zugängliche Echtzeit-Datenfeeds auf einem photorealistischen 3D-Globus mit KI-gestützter Intelligence-Analyse — vollständig lokal ausführbar auf Consumer-GPU-Hardware.

---

## Nutzer

### Primär: Albert (Einzelentwickler/Analyst)
- AI Engineer mit RTX 5090, Ubuntu, Linux
- Kennt CesiumJS, FastAPI, LangGraph, Docker, vLLM
- Will: Geopolitische Lagebilder erstellen, OSINT-Analyse, Intelligence Briefings

### Sekundär: Power-User/Forscher
- Installiert über Docker Compose, bringt eigene API-Keys mit
- Will: Situational Awareness Dashboard für spezifische Regionen

---

## Baseline — Funktionale Requirements (erfüllt)

### Globe & Visualisierung
| # | Requirement | Status |
|---|-------------|--------|
| REQ-001 | 3D Globe mit CesiumJS + Google Photorealistic 3D Tiles (>30 FPS) | DONE |
| REQ-002 | Flugdaten-Layer (OpenSky + adsb.fi, >5K gleichzeitig, Dead-Reckoning) | DONE |
| REQ-003 | Satelliten-Tracking (CelesTrak TLE + SGP4, ~9K aktive Satelliten) | DONE |
| REQ-004 | Erdbeben-Layer (USGS M4.5+ der letzten 7 Tage) | DONE |
| REQ-005 | GLSL Post-Processing (CRT, Night Vision, FLIR) | DONE |
| REQ-009 | Tactical C2 UI (Layer-Toggles, Shader-Selector, Intel-Panel, ClockBar) | DONE |

### Backend & Infrastruktur
| # | Requirement | Status |
|---|-------------|--------|
| REQ-006 | FastAPI Backend Proxy mit Caching (<200ms, 60s TTL) | DONE |
| REQ-007 | RAG-System (Qdrant + LLM, <10s Query-Response) | DONE |
| REQ-008 | Multi-Agent Intelligence Pipeline (LangGraph OSINT→Analyst→Synthesis, SSE) | DONE |
| REQ-010 | Docker Compose Deployment | DONE |

### Erweiterte Layer (v1.1 → erfüllt)
| # | Requirement | Status |
|---|-------------|--------|
| REQ-011 | Militärische ADS-B Flugverfolgung (ICAO-Type-Lookup) | DONE |
| REQ-012 | AIS Schiffsdaten (Digitraffic REST, 18K+ Vessels) | DONE |
| REQ-015 | Geopolitische Hotspots (50+ mit Threat-Level, Mention-basiert) | DONE |
| NEW | Submarine Cable Layer (709 Cables, 1908 Landing Points) | DONE |
| NEW | NASA Black Marble Night Imagery | DONE |

### Nicht implementiert (bewusst depriorisiert)
| # | Requirement | Grund |
|---|-------------|-------|
| REQ-013 | CCTV-Overlay | Datenschutz, geringer OSINT-Wert |
| REQ-014 | Straßenverkehr-Simulation | Kein Intelligence-Mehrwert |
| REQ-020 | WebSocket Push | Polling mit Cache reicht |
| REQ-022 | Wargaming-Integration | Separate Thesis |

---

## Evolution — Enhancement-Delta auf WorldView

### Ausgangslage

WorldView ist eine funktionsfähige Platform mit:
- CesiumJS 3D Globe + Google Photorealistic 3D Tiles
- FastAPI Backend mit Proxy + Cache
- LangGraph 3-Agent RAG Pipeline (OSINT → Analyst → Synthesis)
- Live-Daten: Flights (27K+), Satellites (SGP4), Ships (AIS), Earthquakes (USGS)
- Qdrant Vector DB + Redis Cache
- 27 RSS Feeds + GDELT + TLE Collectors
- GLSL Post-Processing (CRT, Night Vision, FLIR)
- 50+ Geopolitical Hotspots Threat Register

### Enhancement-Ziele (MVP)

| # | Enhancement | Status |
|---|-------------|--------|
| E1 | Neo4j Knowledge Graph (Two-Loop: Templates Write, LLM Read) | DONE |
| E2 | Event Codebook + LLM Classifier + Entity Extractor (1 Call) | DONE |
| E3 | Ingestion Pipeline: Extract → Classify → Graph Write | DONE |
| E4 | Qdrant native Hybrid Search + Reranker | PARTIAL (Hybrid offen) |
| E5 | Agent Tools: Graph Query, Classify, Vision | DONE |
| E6 | LLM/Embedding Upgrade: vLLM + Qwen3.5 + Qwen3-Embedding | DONE |
| E7 | NotebookLM → Knowledge Graph Pipeline | DONE |
| E8 | ReAct Agent mit Tool-Calling (vLLM 9B) | DONE |

### Techstack-Delta

#### Neu hinzukommend
| Komponente | Technologie | Zweck |
|------------|-------------|-------|
| Graph DB | Neo4j Community 5.x | Knowledge Graph, Two-Loop Architecture |
| Hybrid Search | Qdrant native BM25 + Dense + RRF | Serverseitige Fusion |
| Reranker | BAAI/bge-reranker-v2-m3 via TEI | Cross-Encoder Reranking |
| Entity Extraction | LLM Structured Output (JSON) | OSINT-Entities die spaCy nicht kann |
| NLM Pipeline | Voxtral + Qwen + Claude hybrid | NotebookLM Podcast → Knowledge Graph |
| Audio Transcription | Voxtral via vLLM | Think-Tank Podcast Transcription |

#### Upgrades bestehender Komponenten
| Besteht | Upgrade | Begründung |
|---------|---------|------------|
| Ollama | vLLM + llama.cpp | Continuous Batching, AWQ, Tool-Calling |
| Qwen3-32B | Qwen3.5-27B/9B | Tool-Calling, 201 Sprachen, multimodal |
| nomic-embed-text | Qwen3-Embedding-0.6B | 100+ Sprachen, 1024 dim, MTEB Top-Tier |
| 27 RSS Feeds | 27 Feeds (12 gefixt) + SUV | Breitere + funktionsfähige Quellenbasis |

---

## Neo4j Datenmodell (Yggdrasil)

```cypher
// Node Types
(:Entity {id, name, type, aliases, confidence, first_seen, last_seen})
  // type ∈ [person, organization, location, weapon_system, satellite, vessel, aircraft, military_unit]
(:Event {id, title, summary, timestamp, codebook_type, severity, confidence})
(:Source {url, name, quality_tier, last_fetched})
(:Document {notebook_id, title, source, type, updated_at})
(:Claim {statement_hash, statement, type, polarity, confidence, temporal_scope, extraction_model, prompt_version})
(:Location {name, country, lat, lon})

// Relationships
(:Event)-[:INVOLVES]->(:Entity)
(:Event)-[:REPORTED_BY]->(:Source)
(:Event)-[:OCCURRED_AT]->(:Location)
(:Entity)-[:ASSOCIATED_WITH {type, confidence}]->(:Entity)
(:Document)-[:FROM_SOURCE]->(:Source)
(:Claim)-[:EXTRACTED_FROM]->(:Document)
(:Claim)-[:INVOLVES]->(:Entity)

// Constraints
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (ev:Event) REQUIRE ev.id IS UNIQUE;
CREATE CONSTRAINT source_url IF NOT EXISTS FOR (s:Source) REQUIRE s.url IS UNIQUE;
CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name);
CREATE INDEX event_timestamp IF NOT EXISTS FOR (ev:Event) ON (ev.timestamp);
CREATE INDEX event_type IF NOT EXISTS FOR (ev:Event) ON (ev.codebook_type);
```

## Graph-Architektur (Two-Loop)

### WRITE PATH (Ingestion → Graph)
```
Feed-Item
  → LLM: extract(text) → JSON {entities, events, locations}
  → Pydantic: ExtractionResult.model_validate(json)
  → Deterministic Cypher Templates (write_templates.py)
  → Neo4j MERGE/CREATE
```
**Kein LLM-generiertes Cypher.** Templates sind statisch, Parameter kommen aus Pydantic.

### READ PATH (Query → Graph)
```
Natural Language Question
  → ReAct Agent: Tool Call (qdrant_search, graph_query, gdelt)
  → Tool Results → Synthesis Agent
  → Structured Intelligence Report
```

---

## Event Codebook (Auszug)

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

---

## Nicht-funktionale Anforderungen

- **Performance**: Globe >30 FPS mit allen Layern auf RTX 5090 / 64GB RAM
- **Latenz**: Backend API <200ms p95, RAG Query <10s p95
- **Sicherheit**: API-Keys nur in .env, nie im Frontend; alle externen Calls über Proxy
- **Verfügbarkeit**: Graceful degradation wenn externe APIs ausfallen
- **GPU**: Single RTX 5090 (32 GB), nur ein LLM gleichzeitig

---

## Scope-Ausschlüsse

- Kein Multi-User-Auth (Single-User-System)
- Keine Cloud-Deployment (rein lokal)
- Kein Mobile (Desktop-First)
- Keine proprietären Daten (nur öffentliche Feeds)

---

## Risiken

| Risiko | Mitigation |
|--------|------------|
| Neo4j bricht bestehende Qdrant-Flows | Parallel: Neo4j = Graph, Qdrant = Vektoren |
| vLLM Encoder-Profiling OOM auf 5090 | llama.cpp GGUF als stabiler Fallback |
| LLM-generiertes Cypher halluziniert | READ-ONLY + Validation + Self-Heal |
| Entity Extraction unvollständig | Confidence Score + Claude Review für Low-Conf |
| NotebookLM Cookie-Auth fragil | Manueller Re-Login, klare CLI-Fehlermeldungen |
| RSS-Feeds veralten | Audit + Google News Proxies als Fallback |
| Qwen3.5 Template-Bug mit ToolMessages | HumanMessage-Adapter nach Tool-Results |

---

## Phase Next

| Feature | Technologie | Priorität |
|---------|-------------|-----------|
| Briefing Room (zweite View) | React, eigenes UI-Design | HOCH |
| Events auf Globe plotten | Geo-kodierte Events als Marker | MITTEL |
| Entity Resolution (Fuzzy Dedup) | LLM Disambiguation | MITTEL |
| Docling Document Upload | Docling 2.80+ | MITTEL |
| Deep Crawler | Crawl4AI | NIEDRIG |
| Telegram Adapter | Telethon | NIEDRIG |
| Anomaly Detection | Prophet auf Event-Frequenzen | NIEDRIG |
| Fine-Tuning 9B für ODIN | Unsloth Studio | BEI BEDARF |
