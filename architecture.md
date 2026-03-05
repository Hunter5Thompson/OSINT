<!-- manifest: project=WorldView | doc_version=1.0 | compatible_with=PRD:1.0 | updated=2026-03-05 -->

# WorldView — Architektur

## Summary (max. 500 Token)

WorldView folgt einer klassischen 3-Tier-Architektur: React/CesiumJS Frontend, FastAPI Backend (Proxy + Intelligence), Qdrant VectorDB + Ollama/vLLM Inference. Alle Services laufen als Docker Container, orchestriert via Docker Compose. Das Backend proxied alle externen APIs (OpenSky, USGS, CelesTrak, AISStream), cached aggressiv (Redis), und betreibt einen LangGraph Multi-Agent RAG-Pipeline mit lokaler Inference. CesiumJS rendert Google Photorealistic 3D Tiles mit GLSL Custom Shaders für Post-Processing. WebSocket für Live-Daten-Push, SSE für Streaming-Intelligence-Output.

---

## System-Übersicht

```
┌─────────────────────────────────────────────────────────────────┐
│                        DOCKER COMPOSE                           │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────┐   │
│  │   Frontend    │   │   Backend    │   │   Intelligence    │   │
│  │  React/Vite   │──▶│   FastAPI    │──▶│   LangGraph       │   │
│  │  CesiumJS     │   │   Proxy      │   │   Multi-Agent     │   │
│  │  TypeScript   │   │   Cache      │   │   RAG Pipeline    │   │
│  │  Port: 5173   │   │   Port: 8000 │   │   (internal)      │   │
│  └──────────────┘   └──────┬───────┘   └────────┬──────────┘   │
│                            │                     │              │
│                    ┌───────┴───────┐     ┌───────┴───────┐      │
│                    │    Redis      │     │    Qdrant     │      │
│                    │    Cache      │     │   VectorDB    │      │
│                    │   Port: 6379  │     │   Port: 6333  │      │
│                    └───────────────┘     └───────────────┘      │
│                                                                 │
│                    ┌───────────────┐     ┌───────────────┐      │
│                    │   Ollama      │     │    vLLM       │      │
│                    │   (dev)       │     │   (prod)      │      │
│                    │   Port: 11434 │     │   Port: 8001  │      │
│                    └───────────────┘     └───────────────┘      │
└─────────────────────────────────────────────────────────────────┘
                            │
                   ┌────────┴────────────────────────┐
                   ▼                                  ▼
        ┌──────────────────┐              ┌──────────────────┐
        │  External APIs   │              │  External APIs   │
        │  (Realtime Data) │              │  (Reference)     │
        │                  │              │                  │
        │  • OpenSky API   │              │  • CelesTrak TLE │
        │  • adsb.fi       │              │  • USGS Quakes   │
        │  • AISStream.io  │              │  • RSS/OSINT     │
        │  • Windy Webcams │              │  • GDELT Events  │
        └──────────────────┘              └──────────────────┘
```

---

## Tech-Stack

| Schicht | Technologie | Version | Begründung |
|---------|------------|---------|------------|
| **Frontend** | React + TypeScript + Vite | React 19, Vite 6 | Type-Safety für komplexe State-Logik, Vite für HMR |
| **3D Engine** | CesiumJS | 1.132+ | Einzige production-grade WebGL Globe-Engine mit 3D Tiles Support |
| **3D Tiles** | Google Photorealistic 3D Tiles | - | Globale photorealistische Abdeckung, $200/mo Free-Tier |
| **Satellite Math** | satellite.js | 5.x | SGP4/SDP4 Orbit-Propagation aus TLE-Daten |
| **Styling** | Tailwind CSS v4 | 4.x | Utility-First, schnelles taktisches UI-Prototyping |
| **Backend** | FastAPI + Pydantic v2 | 0.128+ | Async-First, WebSocket-Support, auto-generierte OpenAPI Docs |
| **Cache** | Redis | 7.x | In-Memory Cache für API-Responses, TTL-basiert |
| **Vector DB** | Qdrant | 1.13+ | Lokale On-Premise VectorDB, REST + gRPC, Filtering |
| **Embeddings** | nomic-embed-text (Ollama) | - | 768-dim, lokal, kostenlos, gute Multilingual-Performance |
| **LLM Inference (dev)** | Ollama | 0.9+ | Einfaches Modell-Management, GPU-Offloading |
| **LLM Inference (prod)** | vLLM | 0.8+ | Continuous Batching, höherer Throughput, OpenAI-kompatible API |
| **LLM Model** | Qwen3-32B (Q8) | - | Beste Balance aus Qualität und VRAM (RTX 5090 32GB) |
| **Agent Framework** | LangGraph | 1.0+ | Stateful Multi-Agent Workflows, Tool-Use, Streaming |
| **Logging** | structlog | 25.x | Structured JSON Logging |
| **Container** | Docker + Docker Compose | v2 | Multi-Container Orchestrierung, GPU-Passthrough |
| **Testing** | pytest + Playwright | - | Backend: pytest, Frontend: Playwright E2E |

---

## Datenmodell

### Externe Datenquellen

```python
# ── Flight Data (OpenSky / adsb.fi) ──
class Aircraft(BaseModel):
    icao24: str                    # ICAO 24-bit address
    callsign: str | None
    latitude: float
    longitude: float
    altitude_m: float
    velocity_ms: float
    heading: float
    vertical_rate: float
    on_ground: bool
    last_contact: datetime
    is_military: bool = False      # Derived from ICAO prefix DB
    aircraft_type: str | None      # ICAO type designator

# ── Satellite Data (CelesTrak TLE → SGP4) ──
class Satellite(BaseModel):
    norad_id: int
    name: str
    tle_line1: str
    tle_line2: str
    category: str                  # "active", "military", "weather", "gps"
    inclination_deg: float         # Derived from TLE
    period_min: float

# ── Earthquake Data (USGS GeoJSON) ──
class Earthquake(BaseModel):
    id: str
    latitude: float
    longitude: float
    depth_km: float
    magnitude: float
    place: str
    time: datetime
    tsunami: bool

# ── Ship Data (AISStream.io) ──
class Vessel(BaseModel):
    mmsi: int
    name: str | None
    latitude: float
    longitude: float
    speed_knots: float
    course: float
    ship_type: int
    destination: str | None

# ── Geopolitical Hotspot ──
class Hotspot(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    region: str
    threat_level: Literal["CRITICAL", "HIGH", "ELEVATED", "MODERATE"]
    description: str
    last_updated: datetime
    sources: list[str]
```

### RAG Datenmodell

```python
# ── Intelligence Document (für Qdrant) ──
class IntelDocument(BaseModel):
    doc_id: str
    source: str                    # "rss", "gdelt", "manual", "osint"
    title: str
    content: str
    region: str | None
    hotspot_ids: list[str]
    published_at: datetime
    ingested_at: datetime
    embedding: list[float] | None  # 768-dim nomic-embed-text

# ── Intelligence Query Result ──
class IntelAnalysis(BaseModel):
    query: str
    agent_chain: list[str]         # ["osint_agent", "analyst_agent", "synthesis_agent"]
    sources_used: list[str]
    analysis: str
    confidence: float
    threat_assessment: str | None
    timestamp: datetime
```

---

## API-Design

### REST Endpoints (FastAPI)

```
GET  /api/v1/health                    → HealthResponse
GET  /api/v1/config                    → ClientConfig (Cesium token, layer defaults)

# ── Data Layers ──
GET  /api/v1/flights                   → list[Aircraft]       (cached 10s)
GET  /api/v1/flights/military          → list[Aircraft]       (adsb.fi military filter)
GET  /api/v1/satellites                → list[Satellite]      (cached 1h, TLE data)
GET  /api/v1/earthquakes               → list[Earthquake]     (cached 5min)
GET  /api/v1/vessels                   → list[Vessel]         (cached 60s)
GET  /api/v1/hotspots                  → list[Hotspot]
GET  /api/v1/hotspots/{id}             → Hotspot + context

# ── Intelligence ──
POST /api/v1/intel/query               → SSE stream IntelAnalysis
POST /api/v1/intel/hotspot/{id}        → SSE stream IntelAnalysis
GET  /api/v1/intel/history             → list[IntelAnalysis]

# ── RAG Management ──
POST /api/v1/rag/ingest                → IngestResult (Feed-URL oder Dokument)
GET  /api/v1/rag/sources               → list[Source]
GET  /api/v1/rag/stats                 → RAGStats (doc count, collection info)

# ── WebSocket ──
WS   /ws/flights                       → Live aircraft position stream
WS   /ws/vessels                       → AIS burst pattern (20s on, 60s cache)
```

### Error-Handling-Konvention

```python
class APIError(BaseModel):
    error: str
    detail: str | None = None
    code: str  # "UPSTREAM_TIMEOUT", "RATE_LIMITED", "MODEL_ERROR", etc.
    timestamp: datetime
```

HTTP Status Codes:
- 200: Erfolg
- 202: Intelligence-Query gestartet (SSE stream follows)
- 429: Rate-Limited (extern oder intern)
- 502: Upstream-API nicht erreichbar (graceful degradation)
- 503: Inference-Service nicht verfügbar

---

## Sicherheitsarchitektur

### Auth-Flow
Kein User-Auth (Single-User-System). Backend erfordert keine Authentifizierung.

### API-Key Management
```
.env (gitignored):
├── CESIUM_ION_TOKEN=...           # Google 3D Tiles via Cesium Ion
├── GOOGLE_MAPS_API_KEY=...        # Direct 3D Tiles access
├── OPENSKY_USER=...               # Optional, erhöht Rate-Limits
├── OPENSKY_PASS=...
├── AISSTREAM_API_KEY=...          # AISStream.io WebSocket
├── WINDY_API_KEY=...              # Webcam thumbnails
└── VLLM_API_KEY=...               # Falls vLLM mit Auth
```

**Regel:** Kein API-Key wird jemals ans Frontend geliefert. Alle externen Calls gehen über `/api/v1/*`.

### Datenverschlüsselung
- At-Rest: Nicht erforderlich (lokaler Betrieb, keine sensitiven Daten)
- In-Transit: Lokales Netzwerk, kein TLS intern; externe Calls über HTTPS

### Input Validation
- Pydantic v2 für alle Request/Response-Modelle
- Query-Parameter über Annotated Types mit Constraints
- Intel-Queries: Max 2000 Zeichen, kein Prompt-Injection-Filter (lokales System)

### CORS / CSP
```python
CORSMiddleware(
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Architekturentscheidungen (ADRs)

### ADR-001: CesiumJS statt Three.js + Globe
- **Status**: Akzeptiert
- **Kontext**: 3D Globe mit photorealistischen Tiles benötigt
- **Entscheidung**: CesiumJS mit Google Photorealistic 3D Tiles
- **Begründung**: CesiumJS ist die einzige production-grade Library mit nativem 3D Tiles 1.1 Support, WGS84-Präzision, und imperativen Rendering-Primitives (BillboardCollection, PointPrimitiveCollection) für 27K+ Entities bei 60 FPS. Three.js + 3d-tiles-renderer wäre möglich, aber weniger ausgereift.
- **Alternativen**: Three.js + 3DTilesRendererJS (verworfen: weniger Entity-Management-Features), MapLibre GL (verworfen: kein echtes 3D)
- **Konsequenzen**: (+) Bewährte Engine, große Community. (-) Bundle-Size ~3MB, proprietäre Cesium Ion Integration.

### ADR-002: FastAPI statt Node.js Backend
- **Status**: Akzeptiert
- **Kontext**: Backend braucht Proxy, Cache, WebSocket, und AI-Pipeline
- **Entscheidung**: FastAPI (Python)
- **Begründung**: Albert's Stack ist Python-zentriert (LangGraph, Qdrant, Ollama). FastAPI liefert async WebSocket + SSE out-of-the-box. Kein Kontext-Switch zwischen Backend und AI-Pipeline nötig.
- **Alternativen**: Express.js (verworfen: AI-Stack ist Python), Django (verworfen: zu schwergewichtig)
- **Konsequenzen**: (+) Einheitlicher Python-Stack. (-) Vite-Proxy nötig für Frontend-Dev.

### ADR-003: LangGraph statt Simple Chain
- **Status**: Akzeptiert
- **Kontext**: Intelligence-Pipeline braucht Multi-Step-Reasoning mit Tool-Use
- **Entscheidung**: LangGraph StateGraph mit 3 Agenten (OSINT, Analyst, Synthesis)
- **Begründung**: LangGraph ermöglicht Conditional Routing (ist Web-Recherche nötig?), State-Persistence (Checkpointer), und Human-in-the-Loop (Interrupt). Simple Chains können keine iterative Recherche.
- **Alternativen**: LangChain LCEL (verworfen: kein State Management), CrewAI (verworfen: weniger Kontrolle)
- **Konsequenzen**: (+) Volle Kontrolle über Agent-Orchestrierung. (-) Höhere Komplexität.

### ADR-004: Qdrant statt ChromaDB
- **Status**: Akzeptiert
- **Kontext**: Vector Store für RAG-Pipeline
- **Entscheidung**: Qdrant (Docker)
- **Begründung**: Production-grade, REST + gRPC API, Payload-Filtering (nach Region, Datum, Source), persistenter Storage. Albert betreibt es bereits in der GISA RAG-as-a-Service Platform.
- **Alternativen**: ChromaDB (verworfen: weniger Filtering-Features), pgvector (verworfen: extra PostgreSQL-Dependency)
- **Konsequenzen**: (+) Robustes Filtering, bekannter Stack. (-) Extra Container.

### ADR-005: Imperative CesiumJS Primitives statt Entities
- **Status**: Akzeptiert
- **Kontext**: 27.000+ Flugzeuge gleichzeitig rendern
- **Entscheidung**: BillboardCollection, PointPrimitiveCollection, PolylineCollection
- **Begründung**: CesiumJS Entities erzeugen pro Entity ein Property-System mit Change-Tracking. Bei 27K Entities = massive GC-Pressure. Imperative Collections sind 10x performanter. Dead-Reckoning zwischen API-Updates interpoliert Positionen auf der GPU.
- **Alternativen**: CesiumJS Entity API (verworfen: Performance-Limit bei ~5K Entities)
- **Konsequenzen**: (+) 60 FPS mit 27K Entities. (-) Mehr manueller Code, kein React-State-Sync.

### ADR-006: GLSL PostProcessStage statt CSS Filter
- **Status**: Akzeptiert
- **Kontext**: CRT/NV/FLIR visuelle Filter
- **Entscheidung**: CesiumJS PostProcessStage mit Custom GLSL Fragment Shaders
- **Begründung**: CSS Filter (wie im Prototype) funktionieren, aber CesiumJS PostProcessStage operiert direkt auf dem WebGL Framebuffer — korrekte Scanlines, phosphor-glow, thermal palette mit Zugriff auf Depth Buffer und Scene-Daten. Professionelleres Ergebnis.
- **Alternativen**: CSS filter (verworfen: kein Depth-Buffer-Zugriff), Three.js EffectComposer (verworfen: nicht in CesiumJS integrierbar)
- **Konsequenzen**: (+) Pixel-perfekte Filter mit GPU-Zugriff. (-) GLSL-Kenntnisse nötig.

---

## Dateistruktur

```
worldview/
├── CLAUDE.md                       # Agent-Instruktionen
├── PRD.md                          # Product Requirements
├── architecture.md                 # Dieses Dokument
├── features.json                   # Feature-Tracker
├── decisions.md                    # Entscheidungslog
├── docker-compose.yml              # Orchestrierung
├── .env.example                    # API-Key Template
│
├── services/
│   ├── backend/                    # FastAPI Backend
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── app/
│   │   │   ├── main.py             # FastAPI App + Middleware
│   │   │   ├── config.py           # Pydantic Settings
│   │   │   ├── models/             # Pydantic Models
│   │   │   │   ├── flight.py
│   │   │   │   ├── satellite.py
│   │   │   │   ├── earthquake.py
│   │   │   │   ├── vessel.py
│   │   │   │   ├── hotspot.py
│   │   │   │   └── intel.py
│   │   │   ├── routers/            # API Endpoints
│   │   │   │   ├── flights.py
│   │   │   │   ├── satellites.py
│   │   │   │   ├── earthquakes.py
│   │   │   │   ├── vessels.py
│   │   │   │   ├── hotspots.py
│   │   │   │   ├── intel.py
│   │   │   │   └── rag.py
│   │   │   ├── services/           # Business Logic
│   │   │   │   ├── flight_service.py
│   │   │   │   ├── satellite_service.py
│   │   │   │   ├── cache_service.py
│   │   │   │   └── proxy_service.py
│   │   │   └── ws/                 # WebSocket Handlers
│   │   │       ├── flight_ws.py
│   │   │       └── vessel_ws.py
│   │   └── tests/
│   │       ├── unit/
│   │       └── integration/
│   │
│   ├── intelligence/               # LangGraph RAG Pipeline
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── agents/
│   │   │   ├── osint_agent.py      # Web-Recherche, RSS, GDELT
│   │   │   ├── analyst_agent.py    # Analyse + Threat Assessment
│   │   │   ├── synthesis_agent.py  # Report-Synthese
│   │   │   └── tools/
│   │   │       ├── web_search.py
│   │   │       ├── rss_fetch.py
│   │   │       ├── qdrant_search.py
│   │   │       └── gdelt_query.py
│   │   ├── graph/
│   │   │   ├── state.py            # AgentState TypedDict
│   │   │   ├── workflow.py         # StateGraph Definition
│   │   │   └── nodes.py            # Node-Funktionen
│   │   ├── rag/
│   │   │   ├── embedder.py         # nomic-embed-text via Ollama
│   │   │   ├── indexer.py          # Qdrant Ingestion Pipeline
│   │   │   ├── retriever.py        # Hybrid Search (Dense + Sparse)
│   │   │   └── chunker.py          # Semantic Chunking
│   │   └── tests/
│   │
│   ├── data-ingestion/             # Scheduled Data Feeds
│   │   ├── Dockerfile
│   │   ├── feeds/
│   │   │   ├── rss_collector.py    # 170+ RSS Feeds
│   │   │   ├── gdelt_collector.py  # GDELT Event DB
│   │   │   ├── tle_updater.py      # CelesTrak Daily TLE Refresh
│   │   │   └── hotspot_updater.py  # Hotspot Threat-Level Refresh
│   │   └── scheduler.py            # APScheduler Cron-Jobs
│   │
│   └── frontend/                   # React + CesiumJS
│       ├── Dockerfile
│       ├── package.json
│       ├── vite.config.ts
│       ├── index.html
│       ├── src/
│       │   ├── App.tsx
│       │   ├── main.tsx
│       │   ├── index.css           # Tailwind + tactical theme
│       │   ├── components/
│       │   │   ├── globe/
│       │   │   │   ├── GlobeViewer.tsx         # Cesium Viewer init
│       │   │   │   ├── GoogleTiles.tsx         # 3D Tiles loading
│       │   │   │   └── EntityClickHandler.tsx  # Click-to-track
│       │   │   ├── layers/
│       │   │   │   ├── FlightLayer.tsx         # Imperative BillboardCollection
│       │   │   │   ├── SatelliteLayer.tsx      # SGP4 propagation
│       │   │   │   ├── EarthquakeLayer.tsx     # Pulsing markers
│       │   │   │   ├── TrafficLayer.tsx        # Road vehicles
│       │   │   │   ├── ShipLayer.tsx           # AIS vessels
│       │   │   │   └── CCTVLayer.tsx           # Webcam markers
│       │   │   ├── shaders/
│       │   │   │   ├── CRTShader.glsl          # CRT scanline PostProcess
│       │   │   │   ├── NightVisionShader.glsl  # NV phosphor green
│       │   │   │   └── FLIRShader.glsl         # Thermal palette
│       │   │   └── ui/
│       │   │       ├── OperationsPanel.tsx      # Layer/shader controls
│       │   │       ├── IntelPanel.tsx           # Intelligence display
│       │   │       ├── ThreatRegister.tsx       # Hotspot list
│       │   │       ├── ClockBar.tsx             # Multi-timezone
│       │   │       └── StatusBar.tsx            # Data freshness
│       │   ├── hooks/
│       │   │   ├── useCesium.ts
│       │   │   ├── useFlights.ts
│       │   │   ├── useSatellites.ts
│       │   │   └── useIntel.ts
│       │   ├── services/
│       │   │   ├── api.ts                      # Fetch wrapper
│       │   │   └── websocket.ts                # WS connection manager
│       │   └── types/
│       │       └── index.ts                    # Shared TypeScript types
│       └── public/
│           └── assets/
│
├── infra/
│   └── docker/
│       ├── nginx.conf              # Reverse Proxy (optional)
│       └── qdrant-config.yaml
│
├── data/                           # Persistent volumes
│   ├── qdrant/
│   ├── redis/
│   └── models/                     # Ollama model cache
│
├── tasks/                          # Kanban Task-Board
│   ├── backlog/
│   ├── in-progress/
│   ├── review/
│   └── done/
│
├── docs/
│   ├── external-docs.md            # Dokumentations-Links
│   ├── architecture/
│   └── decisions/
│
└── tests/
    └── contract/                   # API Contract Tests
```

---

## Context7 Dokumentations-Referenzen

Für jeden Task sollen Agenten diese Dokumentationen konsultieren:

| Komponente | Context7 Library ID | Fokus |
|---|---|---|
| CesiumJS | `/cesiumgs/cesium` | 3D Tiles, CustomShader, BillboardCollection, PostProcessStage |
| CesiumJS Learn | `/websites/cesium_learn_cesiumjs` | Tutorials, Sandcastle Examples |
| FastAPI | `/websites/fastapi_tiangolo` | WebSocket, SSE, Background Tasks, Middleware |
| LangGraph | `/websites/langchain_oss_python_langgraph` | StateGraph, Agentic RAG, Tool-Use, Streaming |
| Qdrant | `/websites/qdrant_tech` | Collection Management, Filtering, Hybrid Search |
| satellite.js | `/shashwatak/satellite-js` | SGP4 Propagation, TLE Parsing, ECI/ECF Conversion |
