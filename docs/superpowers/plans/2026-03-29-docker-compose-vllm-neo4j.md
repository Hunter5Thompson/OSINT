# Docker Compose Migration: vLLM + TEI + Neo4j — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docker-compose.yml` und `backend/config.py` auf vLLM/TEI/Neo4j migrieren, Ollama entfernen, TASK-100 abschließen und TASK-101 Grundlage legen.

**Architecture:** Drei Dateien werden geändert: `docker-compose.yml` (Ollama→vLLM/TEI/Neo4j), `services/backend/app/config.py` (Ollama-Felder entfernen, vLLM/TEI/Neo4j hinzufügen), `.env.example` (neue Variablen dokumentieren). Backend zieht von Port 8000 auf 8080, da vLLM Port 8000 belegt.

**Tech Stack:** Docker Compose 3.9, vLLM (`vllm/vllm-openai:latest`), TEI (`ghcr.io/huggingface/text-embeddings-inference:120-1.9`), Neo4j 5 Community, FastAPI, pytest, uv

---

## Betroffene Dateien

| Aktion | Datei |
|--------|-------|
| Modify | `docker-compose.yml` |
| Modify | `services/backend/app/config.py` |
| Modify | `.env.example` |
| Create | `services/backend/tests/unit/test_config.py` |

---

## Task 1: Backend `config.py` — Ollama raus, vLLM/TEI/Neo4j rein

**Files:**
- Modify: `services/backend/app/config.py`
- Create: `services/backend/tests/unit/test_config.py`

- [ ] **Schritt 1: Failing Test schreiben**

Erstelle `services/backend/tests/unit/test_config.py`:

```python
"""Unit tests for Settings — verifies vLLM/TEI/Neo4j fields, no Ollama."""

import pytest
from app.config import Settings


class TestSettings:
    def test_vllm_defaults(self) -> None:
        s = Settings()
        assert s.vllm_url == "http://localhost:8000"
        assert s.vllm_model == "models/qwen3.5-27b-awq"

    def test_tei_defaults(self) -> None:
        s = Settings()
        assert s.tei_embed_url == "http://localhost:8001"
        assert s.tei_rerank_url == "http://localhost:8002"

    def test_neo4j_defaults(self) -> None:
        s = Settings()
        assert s.neo4j_url == "bolt://localhost:7687"
        assert s.neo4j_user == "neo4j"
        assert s.neo4j_password == "odin1234"

    def test_no_ollama_fields(self) -> None:
        s = Settings()
        assert not hasattr(s, "ollama_url")
        assert not hasattr(s, "ollama_model")
        assert not hasattr(s, "inference_provider")
        assert not hasattr(s, "embedding_model")
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest tests/unit/test_config.py -v
```

Erwartetes Ergebnis: `FAILED` — `AttributeError` oder `AssertionError` auf vllm/tei/neo4j-Felder.

- [ ] **Schritt 3: `config.py` ersetzen**

Ersetze den kompletten Inhalt von `services/backend/app/config.py`:

```python
"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google / Cesium
    cesium_ion_token: str = ""
    google_maps_api_key: str = ""

    # Flight Data
    opensky_user: str = ""
    opensky_pass: str = ""

    # Ship Data
    aisstream_api_key: str = ""

    # CCTV / Webcams
    windy_api_key: str = ""

    # LLM Inference (vLLM)
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "models/qwen3.5-27b-awq"

    # Embeddings + Reranking (TEI)
    tei_embed_url: str = "http://localhost:8001"
    tei_rerank_url: str = "http://localhost:8002"

    # Neo4j
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "odin1234"

    # Internal Services
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"

    # External APIs
    opensky_api_url: str = "https://opensky-network.org/api/states/all"
    adsb_fi_api_url: str = "https://api.adsb.fi/v2/all"
    usgs_api_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
    )
    celestrak_api_url: str = (
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
    )
    aisstream_ws_url: str = "wss://stream.aisstream.io/v0/stream"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest tests/unit/test_config.py -v
```

Erwartetes Ergebnis: `4 passed`

- [ ] **Schritt 5: Alle Backend-Tests noch grün**

```bash
uv run pytest -v
```

Erwartetes Ergebnis: Alle bestehenden Tests grün. Falls `test_health.py` fehlschlägt wegen fehlender Ollama-Verbindung — das ist erwartet in isolierter Umgebung ohne laufende Services.

- [ ] **Schritt 6: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git add services/backend/app/config.py services/backend/tests/unit/test_config.py
git commit -m "feat(backend): migrate config from Ollama to vLLM/TEI/Neo4j

Remove ollama_url, ollama_model, inference_provider, embedding_model.
Add vllm_url/vllm_model (port 8000), tei_embed_url (8001),
tei_rerank_url (8002), neo4j_url/neo4j_user/neo4j_password."
```

---

## Task 2: `.env.example` aktualisieren

**Files:**
- Modify: `.env.example`

- [ ] **Schritt 1: `.env.example` lesen**

```bash
cat /home/deadpool-ultra/ODIN/OSINT/.env.example
```

- [ ] **Schritt 2: Neue Variablen einfügen**

Füge am Anfang von `.env.example` (nach dem Header, vor den bestehenden API-Key-Einträgen) ein:

```bash
# ─── Inference Stack ───────────────────────────────────────────────────────
# Pfad zum lokalen Modell-Verzeichnis (für vLLM Volume-Mount)
MODELS_PATH=/home/deadpool-ultra/ODIN/models

# ─── Neo4j ─────────────────────────────────────────────────────────────────
NEO4J_PASSWORD=odin1234

# ─── HuggingFace ───────────────────────────────────────────────────────────
# Optional — erhöht Download-Rate-Limit für TEI-Modelle
HF_TOKEN=
```

Entferne gleichzeitig alle Zeilen die auf `OLLAMA_` referenzieren falls vorhanden.

- [ ] **Schritt 3: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git add .env.example
git commit -m "chore: update .env.example for vLLM/TEI/Neo4j stack"
```

---

## Task 3: `docker-compose.yml` — kompletter Ersatz

**Files:**
- Modify: `docker-compose.yml`

> **Achtung Port-Konflikt:** vLLM belegt Host-Port 8000. Das Backend zieht auf 8080. Frontend VITE_API_URL wird entsprechend auf 8080 gesetzt.

- [ ] **Schritt 1: Compose-Syntax vorab validieren (Referenz)**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
docker compose config --quiet 2>&1 | head -5
```

Ergibt Baseline — nach der Änderung erneut ausführen.

- [ ] **Schritt 2: `docker-compose.yml` komplett ersetzen**

```yaml
version: "3.9"

services:

  # ═══ VLLM (LLM Inference — startet zuerst, allein auf GPU) ═══
  vllm:
    image: vllm/vllm-openai:latest
    ports:
      - "8000:8000"
    environment:
      - VLLM_FLASH_ATTN_VERSION=2
    volumes:
      - ${MODELS_PATH:-/home/deadpool-ultra/ODIN/models}:/models
    command: >
      --model /models/qwen3.5-27b-awq
      --max-model-len 32768
      --gpu-memory-utilization 0.85
      --enforce-eager
      --enable-auto-tool-choice
      --tool-call-parser qwen3_coder
      --reasoning-parser qwen3
      --port 8000
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 10
      start_period: 120s
    restart: unless-stopped

  # ═══ TEI EMBED (startet erst wenn vLLM healthy) ═══
  tei-embed:
    image: ghcr.io/huggingface/text-embeddings-inference:120-1.9
    ports:
      - "8001:80"
    volumes:
      - tei-embed-cache:/data
    command: --model-id Qwen/Qwen3-Embedding-0.6B --dtype float16
    environment:
      - HF_TOKEN=${HF_TOKEN:-}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    depends_on:
      vllm:
        condition: service_healthy
    restart: unless-stopped

  # ═══ TEI RERANK (startet erst wenn vLLM healthy) ═══
  tei-rerank:
    image: ghcr.io/huggingface/text-embeddings-inference:120-1.9
    ports:
      - "8002:80"
    volumes:
      - tei-rerank-cache:/data
    command: --model-id BAAI/bge-reranker-v2-m3 --dtype float16
    environment:
      - HF_TOKEN=${HF_TOKEN:-}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    depends_on:
      vllm:
        condition: service_healthy
    restart: unless-stopped

  # ═══ NEO4J ═══
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-odin1234}
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_memory_heap_max__size: 1G
    volumes:
      - neo4j-data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -q http://localhost:7474 -O /dev/null && echo ok"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    restart: unless-stopped

  # ═══ BACKEND (FastAPI) — Host-Port 8080, Container intern 8000 ═══
  # Port-Konflikt: vLLM belegt Host-Port 8000.
  # Lösung: 8080:8000 — kein Dockerfile-Change nötig.
  backend:
    build:
      context: ./services/backend
      dockerfile: Dockerfile
    ports:
      - "8080:8000"
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - VLLM_URL=http://vllm:8000
      - TEI_EMBED_URL=http://tei-embed:8001
      - TEI_RERANK_URL=http://tei-rerank:8002
      - NEO4J_URL=bolt://neo4j:7687
    volumes:
      - ./services/backend/app:/app/app
    depends_on:
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    restart: unless-stopped

  # ═══ INTELLIGENCE (LangGraph RAG Pipeline) ═══
  intelligence:
    build:
      context: ./services/intelligence
      dockerfile: Dockerfile
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - VLLM_URL=http://vllm:8000
      - TEI_EMBED_URL=http://tei-embed:8001
      - TEI_RERANK_URL=http://tei-rerank:8002
      - NEO4J_URL=bolt://neo4j:7687
    depends_on:
      tei-embed:
        condition: service_started
      tei-rerank:
        condition: service_started
      neo4j:
        condition: service_healthy
    restart: unless-stopped

  # ═══ DATA INGESTION (Scheduled Feeds) ═══
  data-ingestion:
    build:
      context: ./services/data-ingestion
      dockerfile: Dockerfile
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - TEI_EMBED_URL=http://tei-embed:8001
    depends_on:
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    restart: unless-stopped

  # ═══ FRONTEND ═══
  frontend:
    build:
      context: ./services/frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    environment:
      - VITE_API_URL=http://localhost:8080
    volumes:
      - ./services/frontend/src:/app/src
    depends_on:
      - backend

  # ═══ REDIS ═══
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ═══ QDRANT ═══
  qdrant:
    image: qdrant/qdrant:v1.13.2
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant-data:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis-data:
  qdrant-data:
  neo4j-data:
  tei-embed-cache:
  tei-rerank-cache:
```

- [ ] **Schritt 3: Compose-Syntax validieren**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
docker compose config --quiet
```

Erwartetes Ergebnis: Kein Output, Exit-Code 0. Bei Fehler: YAML-Syntax prüfen.

- [ ] **Schritt 4: vLLM Docker Image — sm_120 Compatibility Check**

```bash
docker run --rm --gpus all vllm/vllm-openai:latest python -c \
  "import torch; print(torch.cuda.get_device_capability())"
```

Erwartetes Ergebnis: `(12, 0)` — sm_120 bestätigt.

Falls Ergebnis `RuntimeError` oder falsches compute cap:
- vLLM-Service aus docker-compose.yml auskommentieren
- vLLM weiterhin als externer Host-Prozess starten (bestehende Methode aus `~/ODIN/`)
- Den Rest der Compose-Datei (TEI, Neo4j, etc.) normal nutzen

- [ ] **Schritt 5: Commit**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git add docker-compose.yml
git commit -m "feat(infra): replace Ollama with vLLM/TEI/Neo4j in docker-compose

- vLLM on port 8000 with RTX 5090 Blackwell GPU config
- TEI Embed (port 8001) + TEI Rerank (port 8002) depend on vLLM healthcheck
- Neo4j 5 Community on port 7474/7687 with APOC plugin
- Backend moved from port 8000 to 8080 (port conflict with vLLM)
- Ollama service and ollama-data volume removed
- Startup order enforced via healthchecks to respect VRAM budget"
```

---

## Task 4: Smoke Test — Services starten und verifizieren

> Dieser Task benötigt laufende Hardware (GPU). Falls vLLM Docker sm_120 nicht unterstützt, Schritt 1 überspringen und vLLM manuell starten, dann ab Schritt 2 weitermachen.

- [ ] **Schritt 1: Nur Infrastructure-Services starten (kein GPU nötig)**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
docker compose up -d redis qdrant neo4j
docker compose ps
```

Erwartetes Ergebnis: `redis`, `qdrant`, `neo4j` im Status `running (healthy)`.

- [ ] **Schritt 2: Neo4j Health prüfen**

```bash
curl -s http://localhost:7474 | python3 -c "import sys,json; d=json.load(sys.stdin); print('Neo4j OK:', d.get('neo4j_version', d))"
```

Erwartetes Ergebnis: `Neo4j OK: 5.x.x`

- [ ] **Schritt 3: vLLM starten (Docker oder extern)**

**Option A — Docker (wenn sm_120 Check in Task 3 bestanden):**
```bash
docker compose up -d vllm
docker compose logs -f vllm --until=120s | grep -E "healthy|error|ready|Uvicorn"
```

**Option B — Extern (Fallback):**
```bash
cd ~/ODIN && VLLM_FLASH_ATTN_VERSION=2 venv/bin/vllm serve models/qwen3.5-27b-awq \
  --max-model-len 32768 --gpu-memory-utilization 0.85 --enforce-eager \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
  --port 8000 &
```

Erwartetes Ergebnis (beide Optionen): `curl http://localhost:8000/health` → `{"status":"ok"}`

- [ ] **Schritt 4: TEI Services starten**

```bash
docker compose up -d tei-embed tei-rerank
sleep 30
```

```bash
curl -s http://localhost:8001/health && echo " — TEI Embed OK"
curl -s http://localhost:8002/health && echo " — TEI Rerank OK"
```

Erwartetes Ergebnis:
```
{"ok":true} — TEI Embed OK
{"ok":true} — TEI Rerank OK
```

- [ ] **Schritt 5: Quick Funktionstest Embed + Rerank**

```bash
curl -s http://localhost:8001/embed \
  -H "Content-Type: application/json" \
  -d '{"inputs": "geopolitical risk assessment"}' | \
  python3 -c "import sys,json; v=json.load(sys.stdin); print(f'Embed OK: {len(v[0])} dims')"
```

Erwartetes Ergebnis: `Embed OK: 1024 dims`

```bash
curl -s http://localhost:8002/rerank \
  -H "Content-Type: application/json" \
  -d '{"query": "sanctions", "texts": ["Russia oil sanctions", "wheat trade routes"]}' | \
  python3 -c "import sys,json; r=json.load(sys.stdin); print(f'Rerank OK: {len(r)} results')"
```

Erwartetes Ergebnis: `Rerank OK: 2 results`

- [ ] **Schritt 6: Backend + Intelligence starten**

```bash
docker compose up -d backend intelligence data-ingestion
sleep 10
curl -s http://localhost:8080/api/v1/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('Backend OK:', d['status'])"
```

Erwartetes Ergebnis: `Backend OK: ok`

- [ ] **Schritt 7: Abschliessenden Commit mit Smoke-Test-Ergebnis**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
# TASK-100 + TASK-101 Status in Backlog-Task updaten
# (Manuell: Session-Notes in tasks/backlog/ setzen)
git add -A
git commit -m "chore: TASK-100 complete, TASK-101 foundation ready

All services verified:
- vLLM /health OK
- TEI Embed 1024-dim OK
- TEI Rerank OK
- Neo4j reachable on 7474/7687
- Backend /health OK on port 8080"
```

---

## Bekannte Risiken

| Risiko | Wahrscheinlichkeit | Mitigation |
|--------|-------------------|------------|
| vLLM Docker Image kein sm_120 | Mittel | Task 3, Schritt 4: Fallback auf externen Prozess |
| VRAM OOM wenn vLLM + TEI gleichzeitig | Niedrig (Healthcheck-Reihenfolge) | TEI erst nach vLLM-Healthcheck starten |
| Neo4j APOC Plugin Download schlägt fehl | Niedrig | `NEO4J_PLUGINS` entfernen, APOC manuell installieren |
