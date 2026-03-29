# CLAUDE.md — WorldView Tactical Intelligence Platform

## Projektübersicht

WorldView ist eine lokal ausführbare Palantir-ähnliche Tactical Intelligence Platform. CesiumJS 3D Globe + FastAPI Backend + LangGraph RAG Pipeline + Qdrant VectorDB.

**Lies zuerst:** `PRD.md` für Requirements, `architecture.md` für Tech-Entscheidungen.

---

## Repo-Struktur

```
services/backend/     → FastAPI Proxy + Cache (Python 3.12+)
services/intelligence/ → LangGraph Multi-Agent RAG (Python 3.12+)
services/data-ingestion/ → Scheduled Feed Collectors (Python 3.12+)
services/frontend/    → React + CesiumJS + TypeScript (Node 22+)
infra/docker/         → Container Configs
tasks/                → Kanban Board (backlog → in-progress → review → done)
```

---

## Kommandos

### Backend
```bash
cd services/backend
uv sync                          # Dependencies installieren
uv run pytest                    # Tests
uv run pytest --cov=app          # Coverage
uv run ruff check app/           # Lint
uv run mypy app/                 # Type-Check
uv run uvicorn app.main:app --reload --port 8000  # Dev Server
```

### Intelligence
```bash
cd services/intelligence
uv sync
uv run pytest
uv run python -m agents.graph.workflow  # Graph testen
```

### Frontend
```bash
cd services/frontend
npm install
npm run dev                      # Vite Dev Server (Port 5173)
npm run build                    # Production Build
npm run lint                     # ESLint
npm run type-check               # tsc --noEmit
npx playwright test              # E2E Tests
```

### Docker
```bash
docker compose up -d             # Alles starten
docker compose logs -f backend   # Logs
docker compose down              # Stoppen
```

---

## Workflow-Regeln

### TDD ist Pflicht
1. Tests ZUERST schreiben (Red)
2. Minimale Implementierung (Green)
3. Refactor

### Task-Workflow
1. Task aus `tasks/backlog/` nehmen
2. Nach `tasks/in-progress/` verschieben
3. Session-Notes aktualisieren
4. Tests schreiben → Code → Tests bestehen
5. Nach `tasks/review/` verschieben

### Commits
```
feat(backend): add flight proxy endpoint
fix(frontend): fix satellite orbit rendering
test(intelligence): add OSINT agent unit tests
docs(architecture): update ADR-007
```

### Branching
```
main                    # Immer deploybar
feature/TASK-XXX-name   # Feature Branches
```

---

## Verbote

- **KEINE API-Keys im Code oder Git** — nur via `.env`
- **KEINE `any` Types in TypeScript** — immer typisieren
- **KEINE CesiumJS Entity API für Bulk-Rendering** — nur imperative Primitives
- **KEINE synchronen HTTP-Calls im Backend** — alles async/await
- **KEINE hardcoded URLs** — alles via config.py / .env
- **KEINE neuen Dependencies ohne Begründung** in Session-Notes
- **KEINE Tests skippen** — `pytest.mark.skip` nur mit TODO und Ticket

---

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
- OpenSky: `https://opensky-network.org/api/states/all` (10s Rate-Limit, Auth optional)
- adsb.fi: `https://api.adsb.fi/v2/all` (kein Auth, aggressive Caching)
- USGS: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson`
- CelesTrak: `https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle`
- AISStream: WebSocket `wss://stream.aisstream.io/v0/stream` (API-Key required)

### LLM-Konfiguration
- vLLM: `http://localhost:8000/v1` mit `models/qwen3.5-27b-awq` (Port 8000)
- TEI Embed: `http://localhost:8001` — Qwen3-Embedding-0.6B (1024 dim)
- TEI Rerank: `http://localhost:8002` — BAAI/bge-reranker-v2-m3
- Backend erreichbar auf Port 8080 (docker compose) oder 8000 (lokale Entwicklung)

### CesiumJS Patterns
- Immer `BillboardCollection` statt `Entity` für Bulk-Rendering
- `CallbackProperty` für smooth tracking ohne React re-renders
- `PostProcessStage` mit Custom GLSL für Filter
- Google 3D Tiles: `Cesium.createGooglePhotorealistic3DTileset()`
