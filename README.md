# WorldView — Tactical Intelligence Platform

Palantir-like tactical intelligence platform running locally. CesiumJS 3D Globe with Google Photorealistic 3D Tiles, FastAPI backend proxying real-time data feeds, LangGraph multi-agent RAG pipeline with local LLM inference (vLLM + TEI), and Qdrant vector database.

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌───────────────────┐
│   Frontend   │   │   Backend    │   │   Intelligence    │
│  React/Vite  │──▶│   FastAPI    │──▶│   LangGraph       │
│  CesiumJS    │   │   Proxy      │   │   Multi-Agent     │
│  Port: 5173  │   │ Port: 8000*  │   │   RAG Pipeline    │
└──────────────┘   └──────┬───────┘   └────────┬──────────┘
                          │                     │
                   ┌──────┴───────┐     ┌───────┴───────┐
                   │    Redis     │     │    Qdrant     │
                   │    Cache     │     │   VectorDB    │
                   │   Port: 6379 │     │   Port: 6333  │
                   └──────────────┘     └───────────────┘
                   ┌──────────────┐     ┌──────────────┐
                   │    vLLM      │     │ TEI Embed +  │
                   │  OpenAI API  │     │   Reranker   │
                   │   Port:8000  │     │  8001 / 8002 │
                   └──────────────┘     └──────────────┘
```

\* In Docker Compose liegt der Backend-Host-Port bei `8080` (`8080:8000`), weil `8000` auf dem Host für vLLM genutzt wird.

## Features

- **3D Globe** — CesiumJS + Google Photorealistic 3D Tiles
- **Flight Tracking** — OpenSky Network + adsb.fi (27K+ aircraft via BillboardCollection)
- **Satellite Tracking** — CelesTrak TLE + SGP4 propagation (satellite.js)
- **Earthquake Monitor** — USGS M4.5+ feed with magnitude-proportional markers
- **Ship Tracking** — AISStream.io WebSocket with burst pattern
- **GLSL Post-Processing** — CRT scanlines, Night Vision, FLIR/Thermal shaders
- **Intelligence RAG** — LangGraph 3-agent pipeline (OSINT → Analyst → Synthesis)
- **Threat Register** — 50+ geopolitical hotspots with dynamic threat levels
- **Data Ingestion** — Scheduled RSS (27 feeds), GDELT, TLE, hotspot collectors

## Prerequisites

- **Node.js** 22+
- **Python** 3.12+
- **Docker** + Docker Compose
- **uv** (Python package manager) — `pip install uv`
- **GPU** (optional) — NVIDIA GPU for vLLM/TEI inference

## Quick Start

### 1. Environment

```bash
cp .env.example .env
# Edit .env and add your API keys:
#   CESIUM_ION_TOKEN    — from https://ion.cesium.com
#   GOOGLE_MAPS_API_KEY — from Google Cloud Console
#   AISSTREAM_API_KEY   — from https://aisstream.io (optional)
```

### 2. Infrastructure

```bash
./odin.sh doctor
./odin.sh pull 9b-awq          # nur einmal nötig, falls noch nicht lokal vorhanden
./odin.sh up interactive
```

Mode switch (GPU model swap):

```bash
./odin.sh swap ingestion    # Qwen3.5-27B + embed + data-ingestion
./odin.sh swap interactive  # Qwen3.5-9B + reranker + API + UI
```

### 3. Backend

```bash
cd services/backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### 4. Frontend

```bash
cd services/frontend
npm install
npm run dev
```

Open **http://localhost:5173** in Chrome/Chromium.

### Full Stack (Docker)

```bash
./odin.sh up interactive
```

Service Ports (Docker Compose, Host):
- Frontend: `5173`
- Backend: `8080`
- vLLM: `8000` (profile-driven: `vllm-27b` or `vllm-9b`)
- TEI Embed: `8001`
- TEI Rerank: `8002`
- Redis: `6379`
- Qdrant: `6333`
- Neo4j: `7474` (HTTP), `7687` (Bolt)

## Project Structure

```
services/
├── backend/          FastAPI proxy + cache (Python)
│   ├── app/
│   │   ├── main.py           App + middleware + health
│   │   ├── config.py         Pydantic Settings (.env)
│   │   ├── models/           Pydantic v2 data models
│   │   ├── routers/          REST API endpoints
│   │   ├── services/         Business logic + external API clients
│   │   └── ws/               WebSocket handlers
│   └── tests/
├── frontend/         React + CesiumJS + Tailwind (TypeScript)
│   └── src/
│       ├── components/
│       │   ├── globe/        Viewer, 3D Tiles, click handler
│       │   ├── layers/       Flight, Satellite, Earthquake, Ship, CCTV
│       │   ├── shaders/      CRT, Night Vision, FLIR (GLSL)
│       │   └── ui/           Operations, Intel, Threats, Clock, Status
│       ├── hooks/            Data fetching hooks
│       ├── services/         API client + WebSocket manager
│       └── types/            Shared TypeScript types
├── intelligence/     LangGraph multi-agent RAG pipeline
│   ├── agents/               OSINT, Analyst, Synthesis agents
│   │   └── tools/            web_search, rss_fetch, qdrant_search, gdelt
│   ├── graph/                LangGraph state + workflow + nodes
│   └── rag/                  Embedder, chunker, indexer, retriever
└── data-ingestion/   Scheduled feed collectors
    ├── feeds/                RSS, GDELT, TLE, hotspot collectors
    └── scheduler.py          APScheduler cron jobs
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/config` | Client config (Cesium token) |
| GET | `/api/v1/flights` | Aircraft positions (cache configurable, default 30s) |
| GET | `/api/v1/flights/military` | Military aircraft filter |
| GET | `/api/v1/satellites` | Satellite TLE data (cached 1h) |
| GET | `/api/v1/earthquakes` | M4.5+ earthquakes (cached 5min) |
| GET | `/api/v1/vessels` | Ship positions (cached 60s) |
| GET | `/api/v1/hotspots` | Geopolitical hotspots |
| POST | `/api/v1/intel/query` | Intelligence analysis (SSE stream) |
| POST | `/api/v1/rag/ingest` | Ingest document into RAG |
| WS | `/ws/flights` | Live flight stream |
| WS | `/ws/vessels` | Live vessel stream |

## Development

```bash
# Backend
cd services/backend
uv run pytest                    # Tests
uv run ruff check app/           # Lint
uv run mypy app/                 # Type check

# Frontend
cd services/frontend
npm run lint                     # ESLint
npm run type-check               # tsc --noEmit
npm run build                    # Production build
```

## Agent Handover

- Bugfix history and rationale: `docs/bugfix-log.md`

## Data Sources

| Source | Data | Rate Limit |
|--------|------|------------|
| [OpenSky Network](https://opensky-network.org) | Flight positions | 10s (auth optional) |
| [adsb.fi](https://api.adsb.fi) | Flight positions (fallback) | No auth |
| [CelesTrak](https://celestrak.org) | Satellite TLE data | Daily refresh |
| [USGS](https://earthquake.usgs.gov) | Earthquakes M4.5+ | 5min |
| [AISStream](https://aisstream.io) | Ship AIS data | API key required |
| [GDELT](https://api.gdeltproject.org) | Global event data | 15min |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript, Vite 6, Tailwind CSS v4 |
| 3D Engine | CesiumJS 1.132+, Google Photorealistic 3D Tiles |
| Satellite Math | satellite.js (SGP4/SDP4) |
| Backend | FastAPI, Pydantic v2, httpx, Redis |
| Intelligence | LangGraph, LangChain, vLLM, Qwen3.5-27B-AWQ |
| Vector DB | Qdrant |
| Embeddings | Qwen3-Embedding-0.6B (1024 dim, TEI) |
| Container | Docker Compose |

## License

Private project — not for redistribution.
