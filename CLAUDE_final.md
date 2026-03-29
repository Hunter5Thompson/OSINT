# CLAUDE.md

## Projekt
Odin OSINT Analytics (Codename: WorldView) — Tactical Intelligence Platform mit CesiumJS 3D Globe, LangGraph Multi-Agent RAG, Real-Time Data Feeds und Knowledge Graph. Evolutionäres Enhancement eines bestehenden, funktionierenden Systems.

## Existing Baseline (was bereits läuft)
```
Frontend:       React 19 + TypeScript + Vite 6 + CesiumJS + Google 3D Tiles + GLSL Shaders
Backend:        FastAPI + Pydantic v2 + httpx + Redis
Intelligence:   LangGraph 3-Agent Pipeline (OSINT → Analyst → Synthesis)
Vector DB:      Qdrant (mit nativer BM25 Sparse Vector Support seit 1.15.2)
LLM:            Qwen3.5-27B-AWQ via vLLM (Port 8000) — UPGRADE von Qwen3-32B/Ollama
Embeddings:     Qwen3-Embedding-0.6B (512 dim) — UPGRADE von nomic-embed-text
Live Data:      Flights (OpenSky/adsb.fi), Satellites (CelesTrak SGP4), Ships (AISStream), Earthquakes (USGS)
Ingestion:      27 RSS Feeds + 10 Think-Tank-Feeds, GDELT, TLE, Hotspot Collectors (APScheduler)
Infra:          Docker Compose (Redis, Qdrant, Neo4j)
Vision:         Hybrid — Qwen3.5 nativ multimodal (general) + YOLOv8m fine-tuned (military detection)
```

## Repo-Struktur (bestehend + 🆕 Erweiterungen)
```
odin/
├── CLAUDE.md
├── PRD.md
├── docker-compose.yml             # erweitert um Neo4j
├── .env.example
├── scripts/
│   └── embedding_server.py        # 🆕 Qwen3-Embedding FastAPI
│
├── services/
│   ├── backend/                   # FastAPI — BESTEHT
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py          # 🔄 LLM_BASE_URL statt OLLAMA_BASE_URL
│   │   │   ├── models/
│   │   │   ├── routers/
│   │   │   │   ├── flights.py     # BESTEHT
│   │   │   │   ├── satellites.py  # BESTEHT
│   │   │   │   ├── vessels.py     # BESTEHT
│   │   │   │   ├── earthquakes.py # BESTEHT
│   │   │   │   ├── hotspots.py    # BESTEHT
│   │   │   │   ├── intel.py       # BESTEHT
│   │   │   │   ├── rag.py         # BESTEHT → 🔄 + Docling Upload
│   │   │   │   └── graph.py       # 🆕 Neo4j Query + Entity Endpoints
│   │   │   ├── services/
│   │   │   │   ├── graph_service.py    # 🆕 Neo4j Two-Loop
│   │   │   │   ├── docling_service.py  # 🆕 Document Parsing
│   │   │   │   └── ...                 # bestehende Services
│   │   │   └── ws/
│   │   └── tests/
│   │
│   ├── frontend/                  # React + CesiumJS — BESTEHT
│   │   └── src/components/
│   │       ├── globe/             # BESTEHT
│   │       ├── layers/            # BESTEHT
│   │       ├── shaders/           # BESTEHT
│   │       ├── ui/                # BESTEHT
│   │       └── graph/             # 🆕 Entity Explorer
│   │
│   ├── intelligence/              # LangGraph — BESTEHT + ERWEITERT
│   │   ├── agents/
│   │   │   ├── osint_agent.py     # BESTEHT
│   │   │   ├── analyst_agent.py   # BESTEHT
│   │   │   ├── synthesis_agent.py # BESTEHT
│   │   │   └── tools/
│   │   │       ├── web_search.py    # BESTEHT
│   │   │       ├── rss_fetch.py     # BESTEHT
│   │   │       ├── qdrant_search.py # BESTEHT
│   │   │       ├── gdelt.py         # BESTEHT
│   │   │       ├── graph_query.py   # 🆕 Neo4j Read-Path Tool
│   │   │       ├── classify.py      # 🆕 Event Classification Tool
│   │   │       └── vision.py        # 🆕 Qwen3.5 native Vision Tool
│   │   ├── graph/                 # LangGraph Workflow — BESTEHT
│   │   └── rag/
│   │       ├── embedder.py        # 🔄 → Qwen3-Embedding-0.6B
│   │       ├── chunker.py         # 🔄 + OSINT-aware + Docling
│   │       ├── indexer.py         # BESTEHT
│   │       ├── retriever.py       # 🔄 → Qdrant native Hybrid + Reranker
│   │       ├── reranker.py        # 🆕 Qwen3-Reranker-0.6B
│   │       └── docling_ingest.py  # 🆕 Docling Integration
│   │
│   └── data-ingestion/            # Feed Collectors — BESTEHT + ERWEITERT
│       ├── feeds/
│       │   ├── rss_collector.py     # BESTEHT (27 Feeds)
│       │   ├── gdelt_collector.py   # BESTEHT
│       │   ├── tle_collector.py     # BESTEHT
│       │   ├── hotspot_collector.py # BESTEHT
│       │   └── thinktank_feeds.py   # 🆕 aus OSINT_MCP (10 Feeds)
│       ├── pipeline.py              # 🆕 LLM Extract → Neo4j Write → Qdrant Embed
│       └── scheduler.py             # BESTEHT
│
├── graph/                         # 🆕 Yggdrasil
│   ├── client.py                  # Async Neo4j Driver
│   ├── models.py                  # Entity, Event, Source, Location, MilitaryAsset
│   ├── write_templates.py         # WRITE: Deterministische Cypher Templates
│   ├── read_queries.py            # READ: LLM→Cypher + Validation + Self-Heal
│   └── migrations/
│       └── init_constraints.py
│
├── vision/                        # 🆕 Mímir — Hybrid Vision Pipeline
│   ├── detector.py                # YOLOv8m fine-tuned (military objects)
│   ├── hybrid_pipeline.py         # Detect (YOLO) → Crop → Reason (Qwen3.5) → Graph
│   └── training/
│       └── finetune_yolo.py       # Fine-Tuning Script für xView/DOTA
│
├── codebook/                      # 🆕 Event Taxonomy
│   ├── event_codebook.yaml        # 50+ Event Types
│   └── extractor.py               # Kombinierter Classifier + Entity Extractor (1 LLM-Call)
│
├── libs/common/                   # 🆕 Shared
│   ├── config.py
│   ├── logging.py
│   └── models.py                  # ExtractionResult, etc.
│
├── tasks/{backlog,in-progress,review,done}/
└── docs/
```

## Hardware-Constraint
**Einzige GPU: NVIDIA RTX 5090 (32 GB VRAM)**

```
Modus A — Agent + Analysis + Vision (Default):
  vLLM: Qwen3.5-27B AWQ INT4      ~16 GB (gpu-memory-utilization 0.55)
  Qwen3-Embedding-0.6B             ~1.2 GB (sentence-transformers)
  Qwen3-Reranker-0.6B              ~1.2 GB (on-demand)
  YOLOv8m (military fine-tuned)     ~2 GB (persistent neben LLM)
  Vision Reasoning: Qwen3.5          0 GB (already loaded)
  ─────────────────────────────
  Total: ~20.4 GB | Headroom: ~11.6 GB ✅

Modus B — Batch Classification (Hot-Swap):
  vLLM: Qwen3.5-35B-A3B FP16       ~7 GB (3B aktiv)
  Qwen3-Embedding-0.6B              ~1.2 GB
  YOLOv8m                            ~2 GB (persistent)
  ─────────────────────────────
  Total: ~10.2 GB | Headroom: ~21.8 GB ✅
```

## Kommandos
```bash
docker compose up -d redis qdrant neo4j

vllm serve Qwen/Qwen3.5-27B-AWQ \
  --quantization awq --max-model-len 32768 \
  --gpu-memory-utilization 0.55 --port 8000 \
  --served-model-name qwen3.5-27b

python scripts/embedding_server.py --port 8001

cd services/backend && uv run uvicorn app.main:app --reload --port 9000
cd services/frontend && npm run dev
```

## Graph-Architektur (Two-Loop)
```
WRITE PATH: Feed → LLM JSON Extract → Pydantic → Cypher Templates → Neo4j
READ PATH:  NL Question → LLM Cypher Gen → Syntax Validation → Self-Heal → READ-ONLY → Answer
```

## Verbote
- [ ] Bestehende Features brechen
- [ ] GPU-Modelle persistent laden ohne VRAM-Check
- [ ] LLM-generiertes Cypher auf dem Write-Path (nur Templates!)
- [ ] Write-Operationen im Read-Path (READ-ONLY!)
- [ ] Neo4j-Queries ohne Parameter-Binding
- [ ] Bestehende API-Endpoints umbenennen
- [ ] Secrets in Code committen

## Upgrade-Pfade
| Bestehendes | Wird zu | Warum |
|---|---|---|
| Ollama + Qwen3-32B | vLLM + Qwen3.5-27B AWQ | Tool-Calling, native Vision, weniger VRAM |
| nomic-embed-text | Qwen3-Embedding-0.6B | 100+ Sprachen, MTEB Top-Tier |
| Basic RAG | Qdrant native Hybrid Search (BM25+Dense+RRF) + Reranker | Serverseitige Fusion |
| 27 RSS Feeds | + 10 Think-Tank-Feeds + Docling Upload | Breitere Quellenbasis |
| Keine Graph-Persistenz | Neo4j Knowledge Graph (Two-Loop) | Entity Resolution, Link Analysis |
| Keine Vision | Hybrid: YOLOv8m (military detection) + Qwen3.5 (reasoning) | Satellitenbilder, Militärfahrzeuge, taktische Lagebeurteilung |
| Keine Entity Extraction | LLM Structured Output (1 Call) | Erkennt Yaogan-44, PLA SSF, DF-27 |
| 5 Topic-Keywords (MCP) | 50+ Event Codebook + LLM Classifier | Professionelle Taxonomie |

## Phase Next (nach MVP)
Crawl4AI Deep Crawler, Telegram Adapter, EasyOCR (Sprachen die Qwen3.5 schlecht kann),
CLIP Semantic Image Search, MCP Server, Obsidian Bridge, Nominatim Geocoding,
JWT Auth + RBAC, Anomaly Detection (Prophet)
