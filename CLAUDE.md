# CLAUDE.md — WorldView Tactical Intelligence Platform

## Projekt

Odin OSINT Analytics (Codename: WorldView) — Tactical Intelligence Platform mit CesiumJS 3D Globe, LangGraph Multi-Agent RAG, Real-Time Data Feeds und Knowledge Graph.

## Existing Baseline

```
Frontend:       React 19 + TypeScript + Vite 6 + CesiumJS + Google 3D Tiles + GLSL Shaders
Backend:        FastAPI + Pydantic v2 + httpx + Redis (Port 8080)
Intelligence:   LangGraph ReAct Agent + Synthesis (Port 8003)
Vector DB:      Qdrant (Port 6333, collection: odin_intel, 1024-dim cosine)
Graph DB:       Neo4j 5-community (Port 7474 HTTP, 7687 Bolt)
LLM Interactive: Qwen3.5-9B-AWQ via vLLM (Port 8000) — ReAct + Tool-Calling
LLM Ingestion:  Qwen3.5-27B-GGUF Q6_K via llama.cpp (Port 8000) — Heavy extraction
LLM Transcribe: Voxtral via vLLM (Port 8010) — Audio transcription
Embeddings:     Qwen3-Embedding-0.6B via TEI (Port 8001, 1024 dim)
Live Data:      Flights, Satellites, Ships, Earthquakes, Vessels, Submarine Cables
Ingestion:      27 RSS Feeds + GDELT + TLE + Hotspots + NotebookLM Pipeline
Infra:          Docker Compose (Redis, Qdrant, Neo4j, TEI, vLLM)
```

## Repo-Struktur

```
├── CLAUDE.md
├── PRD.md
├── TASKS.md                        # Single Source of Truth (Task Registry)
├── docker-compose.yml              # Redis, Qdrant, Neo4j, TEI, vLLM (profiles)
├── odin.sh                         # Orchestration: up/swap/down/nlm/doctor/smoke
├── .env.example
│
├── services/
│   ├── backend/                    # FastAPI (Port 8080)
│   │   └── app/
│   │       ├── routers/
│   │       │   ├── flights.py, satellites.py, earthquakes.py, vessels.py
│   │       │   ├── cables.py, hotspots.py
│   │       │   ├── intel.py        # SSE Intelligence Query → intelligence service
│   │       │   ├── rag.py          # Vector search + ingest
│   │       │   └── graph.py        # Neo4j entity lookup
│   │       └── ws/                 # WebSocket (flights, vessels)
│   │
│   ├── intelligence/               # LangGraph ReAct Agent (Port 8003)
│   │   ├── agents/
│   │   │   ├── react_agent.py      # ReAct with tool-calling (vLLM 9B)
│   │   │   ├── synthesis_agent.py  # Final report generation
│   │   │   └── tools/
│   │   │       ├── qdrant_search.py, graph_query.py, gdelt.py, vision.py
│   │   ├── graph/                  # LangGraph workflow + state
│   │   ├── rag/                    # Embedder, chunker, retriever, reranker
│   │   └── codebook/              # Event taxonomy (65+ types)
│   │
│   ├── data-ingestion/             # Feed Collectors + NLM Pipeline
│   │   ├── feeds/
│   │   │   ├── rss_collector.py    # 27 RSS feeds
│   │   │   ├── gdelt_collector.py  # 7 GDELT queries
│   │   │   ├── tle_updater.py      # 16 CelesTrak satellite groups
│   │   │   └── hotspot_updater.py  # 50+ geopolitical hotspots
│   │   ├── nlm_ingest/             # NotebookLM → Neo4j pipeline
│   │   │   ├── cli.py              # odin-ingest-nlm CLI
│   │   │   ├── export.py           # Phase 1: NotebookLM export
│   │   │   ├── transcribe.py       # Phase 2: Voxtral transcription
│   │   │   ├── extract.py          # Phase 3: Qwen + Claude extraction
│   │   │   ├── ingest_neo4j.py     # Phase 4: Neo4j write
│   │   │   ├── schemas.py, state.py, write_templates.py
│   │   │   └── prompts/            # Versioned extraction prompts
│   │   ├── pipeline.py             # RSS → vLLM extract → Neo4j + Qdrant
│   │   └── scheduler.py            # APScheduler entry point
│   │
│   └── frontend/                   # React + CesiumJS (Port 5173)
│       └── src/components/
│           ├── globe/, layers/, shaders/, ui/
│
└── docs/
    ├── CONTAINER-STATUS.md         # Working configs + known issues
    ├── workflows/                  # Operational workflows
    ├── superpowers/plans/          # Implementation plans
    └── superpowers/specs/          # Design specifications
```

## Hardware-Constraint

**Einzige GPU: NVIDIA RTX 5090 (32 GB VRAM)**

Nur ein LLM gleichzeitig. Swap via `odin.sh` oder manuell. Siehe `docs/CONTAINER-STATUS.md` für exakte Configs und bekannte Issues.

```
Modus A — Agent + Analysis + Vision (Default):
  vLLM: Qwen3.5-27B AWQ INT4      ~16 GB (gpu-memory-utilization 0.55)
  Qwen3-Embedding-0.6B             ~1.2 GB (sentence-transformers)
  Qwen3-Reranker-0.6B              ~1.2 GB (on-demand)
  YOLOv8m (military fine-tuned)     ~2 GB (persistent neben LLM)
  Vision Reasoning: Qwen3.5          0 GB (already loaded)
  ─────────────────────────────
  Total: ~20.4 GB | Headroom: ~11.6 GB

Modus B — Batch Classification (Hot-Swap):
  vLLM: Qwen3.5-35B-A3B FP16       ~7 GB (3B aktiv)
  Qwen3-Embedding-0.6B              ~1.2 GB
  YOLOv8m                            ~2 GB (persistent)
  ─────────────────────────────
  Total: ~10.2 GB | Headroom: ~21.8 GB

Modus C — Aktuell verifiziert (2026-04-03):
  vLLM 9B-AWQ (interactive)        ~19 GB (gpu-memory-utilization 0.50)
  TEI Embed                         ~1.7 GB
  ─────────────────────────────
  Total: ~20.7 GB | Headroom: ~11.3 GB

Modus D — Ingestion (llama.cpp):
  llama.cpp Qwen 27B GGUF Q6_K    ~25 GB
  TEI Embed                         ~1.7 GB
  ─────────────────────────────
  Total: ~26.7 GB | Headroom: ~5.3 GB

Modus E — NotebookLM Transcription:
  vLLM Voxtral                     ~21 GB (gpu-memory-utilization 0.55)
  ─────────────────────────────
  Total: ~21 GB | Headroom: ~11 GB (kein TEI nötig)
```

## Kommandos

### Orchestration (odin.sh)
```bash
./odin.sh up ingestion       # Core + vLLM-27B + data-ingestion
./odin.sh up interactive     # Core + vLLM-9B + intelligence + backend + frontend
./odin.sh swap ingestion     # Stop active, start ingestion
./odin.sh nlm up|down|run    # Voxtral für NotebookLM
./odin.sh doctor             # Setup validieren
./odin.sh smoke              # Health checks
```

### Backend
```bash
cd services/backend
uv sync && uv run pytest
uv run ruff check app/
uv run uvicorn app.main:app --reload --port 8080
```

### Intelligence
```bash
cd services/intelligence
uv sync && uv run pytest
uv run uvicorn main:app --host 0.0.0.0 --port 8003
```

### Data Ingestion
```bash
cd services/data-ingestion
uv sync && uv run pytest
odin-ingest-nlm status|run|export|transcribe|extract|ingest
```

### Frontend
```bash
cd services/frontend
npm install && npm run dev    # Port 5173
npm run build && npm run lint && npm run type-check
```

## Graph-Architektur (Two-Loop)

```
WRITE PATH: Feed → LLM JSON Extract → Pydantic → Cypher Templates → Neo4j
READ PATH:  NL Question → LLM Tool Call → Qdrant/Neo4j Search → Synthesis
```

**KRITISCH:** Kein LLM-generiertes Cypher auf dem Write-Path! Nur deterministische Templates.

## Workflow-Regeln

### TDD ist Pflicht
1. Tests ZUERST schreiben (Red)
2. Minimale Implementierung (Green)
3. Refactor

### Commits
```
feat(backend): add flight proxy endpoint
fix(frontend): fix satellite orbit rendering
test(intelligence): add OSINT agent unit tests
```

### Branching
```
main                    # Immer deploybar
feature/TASK-XXX-name   # Feature Branches
```

## Verbote

- **KEINE API-Keys im Code oder Git** — nur via `.env`
- **KEINE `any` Types in TypeScript** — immer typisieren
- **KEINE CesiumJS Entity API für Bulk-Rendering** — nur imperative Primitives
- **KEINE synchronen HTTP-Calls im Backend** — alles async/await
- **KEINE hardcoded URLs** — alles via config.py / .env
- **KEIN LLM-generiertes Cypher auf dem Write-Path** — nur Templates!
- **KEINE Write-Operationen im Read-Path** — READ-ONLY!
- **KEINE Neo4j-Queries ohne Parameter-Binding**
- **KEINE Tests skippen** — `pytest.mark.skip` nur mit TODO und Ticket

## Session-Ende-Protokoll

Vor Session-Ende IMMER:

1. Alle Tests laufen lassen → Ergebnis notieren
2. Lint + Type-Check → Ergebnis notieren
3. Task Session-Notes aktualisieren:
   - Was wurde erledigt?
   - Welche Tests bestehen/fehlen?
   - Welche Dateien wurden geändert?
   - Was ist der nächste Schritt?
4. Git commit mit aussagekräftiger Message

---

## Kontext für Agenten

### Datenquellen-APIs
- OpenSky: `https://opensky-network.org/api/states/all` (10s Rate-Limit)
- adsb.fi: `https://api.adsb.fi/v2/all` (kein Auth)
- USGS: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson`
- CelesTrak: `https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle`
- AISStream: WebSocket `wss://stream.aisstream.io/v0/stream` (API-Key)

### LLM-Konfiguration
- vLLM 9B (interactive): `http://localhost:8000/v1` — model `qwen3.5`
- llama.cpp 27B (ingestion): `http://localhost:8000/v1` — model `model.gguf`
- Voxtral (transcribe): `http://localhost:8010/v1` — model `voxtral`
- TEI Embed: `http://localhost:8001/embed` — 1024 dim
- TEI Rerank: `http://localhost:8002` — BAAI/bge-reranker-v2-m3

### CesiumJS Patterns
- `BillboardCollection` statt `Entity` für Bulk-Rendering
- `CallbackProperty` für smooth tracking ohne React re-renders
- `PostProcessStage` mit Custom GLSL für Filter
- Google 3D Tiles: `Cesium.createGooglePhotorealistic3DTileset()`

### TEI auf RTX 5090 (Blackwell)
- IMMER `ghcr.io/huggingface/text-embeddings-inference:120-1.9` (sm_120)
- `latest` ist sm_80 und crasht!
