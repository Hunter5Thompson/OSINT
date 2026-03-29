# Design: Docker Compose Migration — vLLM + TEI + Neo4j

**Date:** 2026-03-29
**Tasks:** TASK-100 (abschließen) + TASK-101 (Grundlage)
**Scope:** 3 Dateien — `docker-compose.yml`, `services/backend/app/config.py`, `.env.example`

---

## Kontext

WorldView nutzt in `docker-compose.yml` noch Ollama als LLM-Backend. Die Service-Configs (`intelligence/config.py`, `data-ingestion/config.py`, `entity_extractor.py`) wurden bereits auf vLLM (Port 8000) + TEI Embed (Port 8001) + TEI Rerank (Port 8002) migriert. Neo4j fehlt in der Compose-Datei komplett, obwohl `entity_extractor.py` bereits darauf schreibt.

Ziel: Compose-Datei und Backend-Config in den gleichen Zustand bringen wie die übrigen Service-Configs.

---

## Änderung 1: `docker-compose.yml`

### Entfernt
- `ollama` Service
- `ollama-data` Volume

### Hinzugefügt

**vLLM** (`vllm/vllm-openai:latest`, Port 8000)
- Volume-Mount: `${MODELS_PATH:-/home/deadpool-ultra/ODIN/models}:/models`
- GPU: `nvidia`, count `all`
- Command: `--model /models/qwen3.5-27b-awq --max-model-len 32768 --gpu-memory-utilization 0.85 --enforce-eager --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 --port 8000`
- Healthcheck: `GET http://localhost:8000/health` — interval 30s, retries 10, start_period 120s
- `VLLM_FLASH_ATTN_VERSION=2` als Environment-Variable

**TEI Embed** (`ghcr.io/huggingface/text-embeddings-inference:120-1.9`, Port 8001)
- `depends_on: vllm: condition: service_healthy` — startet erst nach vLLM-Healthcheck
- Command: `--model-id Qwen/Qwen3-Embedding-0.6B --dtype float16`
- Volume: `tei-embed-cache:/data`
- GPU: `nvidia`, count `all`

**TEI Rerank** (`ghcr.io/huggingface/text-embeddings-inference:120-1.9`, Port 8002)
- `depends_on: vllm: condition: service_healthy`
- Command: `--model-id BAAI/bge-reranker-v2-m3 --dtype float16`
- Volume: `tei-rerank-cache:/data`
- GPU: `nvidia`, count `all`

**Neo4j** (`neo4j:5-community`, Port 7474/7687)
- `NEO4J_AUTH: neo4j/odin1234`
- `NEO4J_PLUGINS: '["apoc"]'`
- `NEO4J_dbms_memory_heap_max__size: 1G`
- Volume: `neo4j-data:/data`
- Healthcheck: `wget -q http://localhost:7474 -O /dev/null`

### Startup-Reihenfolge (VRAM-kritisch)
```
neo4j, redis, qdrant    → parallel (kein GPU)
vllm                    → wartet auf nichts, startet allein
tei-embed, tei-rerank   → depends_on vllm (service_healthy)
intelligence            → depends_on tei-embed, tei-rerank, neo4j (service_started)
backend, data-ingestion → depends_on redis, qdrant
frontend                → depends_on backend
```

### Bekanntes Risiko
`vllm/vllm-openai:latest` muss sm_120 (RTX 5090 Blackwell) unterstützen.
Fallback: vLLM als externer Host-Prozess, TEI/Neo4j laufen in Compose.
Test: `docker run --gpus all vllm/vllm-openai:latest --help` vor erstem `docker compose up`.

### Environment-Variable-Updates in bestehenden Services
Alle Services erhalten aktualisierte Env-Vars (Ollama-Referenzen entfernt):
- `VLLM_URL=http://vllm:8000`
- `TEI_EMBED_URL=http://tei-embed:8001`
- `TEI_RERANK_URL=http://tei-rerank:8002`
- `NEO4J_URL=bolt://neo4j:7687`

---

## Änderung 2: `services/backend/app/config.py`

### Entfernt
- `inference_provider: str = "ollama"`
- `ollama_model: str = "qwen3:32b"`
- `ollama_url: str = "http://localhost:11434"`
- `vllm_model: str = "Qwen/Qwen3-32B"` (falsches Modell)
- `embedding_model: str = "nomic-embed-text"`
- `vllm_url: str = "http://localhost:8001"` (falsche Port — war TEI, nicht vLLM)

### Hinzugefügt
```python
# LLM Inference
vllm_url: str = "http://localhost:8000"
vllm_model: str = "models/qwen3.5-27b-awq"

# Embeddings + Reranking
tei_embed_url: str = "http://localhost:8001"
tei_rerank_url: str = "http://localhost:8002"

# Neo4j
neo4j_url: str = "bolt://localhost:7687"
neo4j_user: str = "neo4j"
neo4j_password: str = "odin1234"
```

Defaults sind localhost (für lokale Entwicklung außerhalb Docker).
In Docker werden diese via `environment:` in docker-compose.yml überschrieben.

---

## Änderung 3: `.env.example`

Neue Einträge:
```
# Model path for vLLM volume mount
MODELS_PATH=/home/deadpool-ultra/ODIN/models

# Neo4j
NEO4J_PASSWORD=odin1234

# HuggingFace (optional, erhöht TEI Download-Rate-Limit)
HF_TOKEN=
```

---

## Nicht geändert

- `intelligence/config.py` — bereits korrekt
- `data-ingestion/config.py` — bereits korrekt
- `entity_extractor.py` — bereits korrekt
- Alle Router/Services in `services/backend/app/routers/`

---

## Erfolgskriterien

1. `docker compose up` startet ohne Fehler
2. `curl http://localhost:8000/health` → 200 (vLLM)
3. `curl http://localhost:8001/health` → 200 (TEI Embed)
4. `curl http://localhost:8002/health` → 200 (TEI Rerank)
5. `curl http://localhost:7474` → Neo4j Browser erreichbar
6. Bestehende Backend-Tests grün (`uv run pytest`)
7. vLLM-Healthcheck grün bevor TEI startet (Compose-Log zeigt korrekten Start-Order)
