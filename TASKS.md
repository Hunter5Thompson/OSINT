# ODIN/WorldView — Task Registry (Single Source of Truth)
#
# Letzte Aktualisierung: 2026-03-30
# Dieses Dokument ersetzt:
#   - tasks/backlog/TASK-001..015 (archiviert)
#   - TASKS_final.md (ersetzt)
#   - TASK-007_vision.md (ersetzt)
#
# Prinzipien:
# - Ein Dokument, ein Nummernraum, ein Tech-Stack
# - MVP-Tasks (001-015) als kompakte Referenz
# - Enhancement-Tasks (100-107) mit vollen Specs
# - Jeder Task ist ein self-contained Briefing für Sonnet/Haiku

---

# ══════════════════════════════════════════
# TECH STACK — CANONICAL VALUES
# ══════════════════════════════════════════
# Bei Widersprüchen zwischen Docs gilt DIESER Block.
# Alle config.py, .env, docker-compose.yml MÜSSEN diese Werte spiegeln.

```
LLM:
  Server:     vLLM (kein Ollama)
  Model:      Qwen/Qwen3.5-27B-AWQ
  Port:       8000
  Served-As:  qwen3.5-27b
  VRAM:       ~17.6 GB (gpu-memory-utilization 0.55)

Embedding:
  Server:     TEI-kompatibles Interface (sentence-transformers oder TEI)
  Model:      Qwen/Qwen3-Embedding-0.6B
  Port:       8001
  Endpoint:   POST /embed  {"inputs": "text"} → list[list[float]]
  Dimension:  1024
  VRAM:       ~1.2 GB

Reranker:
  Model:      BAAI/bge-reranker-v2-m3 (TEI) oder Qwen/Qwen3-Reranker-0.6B (CrossEncoder)
  Port:       8002

Vector DB:
  Qdrant:     Port 6333/6334
  Collection: odin_v2 (dense 1024 + sparse BM25)

Graph DB:
  Neo4j:      5-community
  Ports:      7474 (HTTP), 7687 (Bolt)
  Auth:       neo4j/odin_yggdrasil

Cache:
  Redis:      Port 6379

Backend:
  FastAPI:    Port 8080 (docker) / 8000 (lokal)

Frontend:
  Vite+React: Port 5173
  CesiumJS:   Google 3D Tiles + Fallback
```

---

# ══════════════════════════════════════════
# MVP TASKS (001–015) — Referenz
# ══════════════════════════════════════════
# Ursprünglich mit Ollama/nomic-embed/768dim spezifiziert.
# Stack wurde auf vLLM/TEI/1024dim migriert (siehe TASK-100).
# Volle Specs archiviert in tasks/backlog/.

| Task | Titel | Status | Anmerkungen |
|------|-------|--------|-------------|
| 001 | Repo Setup + Docker Compose | DONE | uv workspaces, Redis+Qdrant, GPU-Passthrough |
| 002 | FastAPI Backend Skeleton | DONE | Health, ProxyService, CORS, structlog |
| 003 | Flight Data Proxy (OpenSky+adsb.fi) | DONE | Fallback, Cache, Military-Filter |
| 004 | Earthquake Proxy (USGS) | DONE | M4.5+ Feed, 5min Cache |
| 005 | Satellite TLE Proxy (CelesTrak) | DONE | SGP4, 1h Cache, Kategorisierung |
| 006 | RAG System (Qdrant+Embedding) | DONE | Chunker, Embedder, Retriever, Batch |
| 007 | LangGraph Multi-Agent Pipeline | DONE | OSINT+Analyst+Synthesis, SSE Streaming |
| 008 | Intel API Endpoint (SSE) | DONE | POST /intel/query, History |
| 009 | CesiumJS Globe + Layers | DONE | Flight, Satellite, Earthquake, Dead-Reckoning |
| 010 | GLSL Post-Processing | DONE | CRT, Night Vision, FLIR Shaders |
| 011 | Tactical C2 UI | DONE | OperationsPanel, IntelPanel, ClockBar |
| 012 | Data Ingestion (RSS+GDELT) | DONE | 50+ Feeds, APScheduler, Hotspot Updater |
| 013 | Docker Compose Integration Test | DONE | Full stack health, E2E |
| 014 | Intelligence Pipeline Hardening | PARTIAL | A: Tool Sandboxing ❌, B: Write/Read Sep ❌, C: Lineage ❌ |
| 015 | Hugin — Sentinel-2 Collector | TESTED | Live-Test OK (Element84 STAC), Code nicht implementiert |

### TASK-014 Offene Teile

**Teil A — Agent Tool Sandboxing:**
- Jeder Agent bekommt explizite Tool-List (osint: web_search/rss/gdelt, analyst: qdrant_search, synthesis: read-only)
- LangGraph Interrupt vor nicht-lesbaren Actions
- Tests beweisen Tool-Isolation

**Teil B — Write/Read Separation:**
- `intelligence/rag/indexer.py` → `data-ingestion/` verschieben
- Intelligence-Service verliert Qdrant-Write-Zugriff
- Interner Endpoint `POST /internal/ingest`

**Teil C — Data Lineage:**
- `SourceRef` Pydantic-Model (doc_id, source, title, relevance_score)
- `IntelAnalysis.sources_used`: `list[str]` → `list[SourceRef]`
- Propagation durch Retriever → Synthesis → API → Frontend

### TASK-015 Status

Element84 STAC live getestet (2026-03-29), Endpoint funktioniert.
CDSE degraded (Timeout). Implementierung der `sentinel_collector.py` steht noch aus.
Phasen: 1 (Catalog+Thumbnail), 2 (Download+Cache+API), 3 (S-1 SAR, Phase Next).

---

# ══════════════════════════════════════════
# TASK-100: vLLM Migration + Embedding Upgrade
# ══════════════════════════════════════════
# Aufwand: 0.5 Tage | Blocked by: nichts | Blocks: alles
# Status: DONE ✅

## Kontext
WorldView nutzt aktuell Ollama mit Qwen3-32B (Port 11434).
Die gesamte LLM-Kommunikation läuft bereits über OpenAI-kompatible API.
Migration ist eine Config-Änderung, kein Code-Refactor.

## Deliverables
1. vLLM installiert und Qwen3.5-27B-AWQ served auf Port 8000
2. `.env.example` und `services/backend/app/config.py` aktualisiert
3. Embedding-Server: Qwen3-Embedding-0.6B via TEI-kompatiblem Interface auf Port 8001
4. Smoke-Test: bestehender Intel-Endpoint funktioniert mit neuem Model

## Spezifikation

**vLLM starten (Shell, nicht Docker):**
```bash
pip install vllm
vllm serve Qwen/Qwen3.5-27B-AWQ \
  --quantization awq \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.55 \
  --port 8000 \
  --served-model-name qwen3.5-27b
```
`gpu-memory-utilization 0.55` = ~17.6 GB, lässt Headroom für Embedding + Vision.

**Embedding-Server (separater Prozess):**
```python
# scripts/embedding_server.py
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI
import uvicorn

app = FastAPI()
model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B", device="cuda")

@app.post("/embed")
async def embed(request: dict):
    """TEI-kompatibles Interface: {"inputs": "text"} oder {"inputs": ["text1", "text2"]}"""
    inputs = request["inputs"]
    if isinstance(inputs, str):
        inputs = [inputs]
    vectors = model.encode(inputs, normalize_embeddings=True)
    return vectors.tolist()  # list[list[float]]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

**Config-Änderungen:**
```python
# services/backend/app/config.py
class Settings(BaseSettings):
    LLM_BASE_URL: str = "http://localhost:8000/v1"       # war: OLLAMA_BASE_URL
    LLM_MODEL: str = "qwen3.5-27b"                       # war: qwen3-32b
    EMBEDDING_URL: str = "http://localhost:8001/embed"     # NEU
    EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-0.6B"   # war: nomic-embed-text
    EMBEDDING_DIM: int = 1024                              # TEI: Qwen3-Embedding-0.6B (1024 dim)
```

**Qdrant Collection Migration:**
Neue Collection `odin_v2` mit Qwen3-Embedding Dimensionen anlegen.
Alte Collection `odin` behalten bis validiert.

## Tests
- Bestehender `POST /api/v1/intel/query` funktioniert mit vLLM
- Embedding-Server returned Vektoren mit korrekter Dimension (1024)
- Response-Qualität Spot-Check (3 Fragen manuell vergleichen)

## Dependencies
```
vllm                      # System-Level
sentence-transformers>=3.0 # für Embedding-Server
```

---

# ══════════════════════════════════════════
# TASK-101: Neo4j + Two-Loop Graph Architecture
# ══════════════════════════════════════════
# Aufwand: 3-4 Tage | Blocked by: TASK-100 | Blocks: TASK-103, TASK-104
# Status: DONE ✅ (committed 2026-03-30, 69 tests)

## Kontext
WorldView hat keinen Knowledge Graph. Wir fügen Neo4j hinzu mit zwei
klar getrennten Pfaden: WRITE (deterministische Templates) und READ (LLM-generiertes Cypher).

## Deliverables
1. Neo4j in `docker-compose.yml`
2. `graph/` Package: client, models, write_templates, read_queries, migrations
3. Two-Loop Architektur implementiert
4. Tests gegen Testcontainer

## Spezifikation

### docker-compose.yml Ergänzung
```yaml
neo4j:
  image: neo4j:5-community
  ports:
    - "7474:7474"
    - "7687:7687"
  environment:
    NEO4J_AUTH: neo4j/odin_yggdrasil
    NEO4J_PLUGINS: '["apoc"]'
    NEO4J_dbms_memory_heap_max__size: 1G
  volumes:
    - neo4j_data:/data
```

### graph/models.py — Pydantic Models
```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal
from uuid import uuid4

class Entity(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    type: Literal["person", "organization", "location", "weapon_system",
                  "satellite", "vessel", "aircraft", "military_unit"]
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)

class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    summary: str = ""
    timestamp: datetime
    codebook_type: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1, default=0.5)

class Source(BaseModel):
    url: str
    name: str
    credibility_score: float = Field(ge=0, le=1, default=0.5)

class ExtractionResult(BaseModel):
    """LLM Structured Output für Entity/Event Extraction."""
    entities: list[Entity]
    events: list[Event]
    locations: list[dict]  # {"name": "Jiuquan", "country": "China"}
```

### graph/write_templates.py — WRITE PATH (deterministisch, kein LLM-Cypher!)
```python
"""
Deterministische Cypher Templates für Graph-Writes.
Das LLM extrahiert DATEN (JSON) → Pydantic validiert → Templates schreiben.
KEIN LLM-generiertes Cypher auf dem Write-Path.
"""

UPSERT_ENTITY = """
MERGE (e:Entity {name: $name, type: $type})
SET e.aliases = $aliases,
    e.confidence = $confidence,
    e.last_seen = datetime()
ON CREATE SET e.id = $id, e.first_seen = datetime()
RETURN e.id
"""

CREATE_EVENT = """
CREATE (ev:Event {
  id: $id, title: $title, summary: $summary,
  timestamp: datetime($timestamp),
  codebook_type: $codebook_type,
  severity: $severity, confidence: $confidence
})
RETURN ev.id
"""

LINK_ENTITY_EVENT = """
MATCH (e:Entity {name: $entity_name})
MATCH (ev:Event {id: $event_id})
MERGE (ev)-[:INVOLVES]->(e)
"""

LINK_EVENT_SOURCE = """
MERGE (s:Source {url: $url})
SET s.name = $source_name, s.last_fetched = datetime()
WITH s
MATCH (ev:Event {id: $event_id})
MERGE (ev)-[:REPORTED_BY]->(s)
"""

LINK_EVENT_LOCATION = """
MERGE (l:Location {name: $location_name})
SET l.country = $country, l.lat = $lat, l.lon = $lon
WITH l
MATCH (ev:Event {id: $event_id})
MERGE (ev)-[:OCCURRED_AT]->(l)
"""
```

### graph/read_queries.py — READ PATH (LLM-generiertes Cypher mit Safety Net)
```python
"""
LLM generiert Cypher für Read-Queries.
Safety: Schema-Kontext + Few-Shot + Syntax-Validation + Self-Healing + READ-ONLY.
"""

SCHEMA_CONTEXT = """
Graph Schema:
- (:Entity {id, name, type, aliases, confidence, first_seen, last_seen})
- (:Event {id, title, summary, timestamp, codebook_type, severity, confidence})
- (:Source {url, name, credibility_score, last_fetched})
- (:Location {name, country, lat, lon})

Relationships:
- (Event)-[:INVOLVES]->(Entity)
- (Event)-[:REPORTED_BY]->(Source)
- (Event)-[:OCCURRED_AT]->(Location)
- (Event)-[:CLASSIFIED_AS]->(EventType)
- (Entity)-[:ASSOCIATED_WITH]->(Entity)
"""

FEW_SHOT_EXAMPLES = [
    ("Which entities are involved in drone attacks?",
     "MATCH (e:Entity)<-[:INVOLVES]-(ev:Event) WHERE ev.codebook_type = 'military.drone_attack' RETURN DISTINCT e.name, e.type, count(ev) AS events ORDER BY events DESC"),
    ("Show me events in Ukraine in the last 7 days",
     "MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location) WHERE l.country = 'Ukraine' AND ev.timestamp > datetime() - duration('P7D') RETURN ev.title, ev.codebook_type, ev.severity, l.name ORDER BY ev.timestamp DESC"),
    ("What sources reported about satellite launches?",
     "MATCH (s:Source)<-[:REPORTED_BY]-(ev:Event) WHERE ev.codebook_type STARTS WITH 'space.satellite' RETURN s.name, s.url, count(ev) AS reports ORDER BY reports DESC"),
    ("How are Entity X and Entity Y connected?",
     "MATCH path = shortestPath((a:Entity {name: $entity_a})-[*..4]-(b:Entity {name: $entity_b})) RETURN path"),
    ("What happened at Jiuquan?",
     "MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location {name: 'Jiuquan'}) RETURN ev.title, ev.timestamp, ev.codebook_type ORDER BY ev.timestamp DESC LIMIT 10"),
]

import re

def validate_cypher_readonly(cypher: str) -> bool:
    """Reject write operations. Only MATCH/RETURN/WITH/WHERE/ORDER/LIMIT allowed."""
    # Block all known write/admin keywords including CALL, LOAD CSV, FOREACH
    write_keywords = r'\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD\s+CSV|FOREACH)\b'
    if re.search(write_keywords, cypher, re.IGNORECASE):
        return False
    # Block multi-statement injection via semicolons
    if ';' in cypher:
        return False
    return True

async def query_graph_nl(question: str, llm_client, graph_client, max_retries: int = 3) -> dict:
    """
    Natural Language → Cypher → Execute → Summarize.
    Self-healing loop: bei Syntax-Fehler wird Cypher regeneriert.
    """
    cypher = await llm_client.generate_cypher(question, SCHEMA_CONTEXT, FEW_SHOT_EXAMPLES)

    if not validate_cypher_readonly(cypher):
        return {"error": "Write operations not allowed in read queries"}

    for attempt in range(max_retries):
        try:
            results = await graph_client.run_query(cypher, read_only=True)
            summary = await llm_client.summarize_graph_results(question, results)
            return {"answer": summary, "cypher": cypher, "raw_results": results}
        except Exception as e:
            if attempt < max_retries - 1:
                cypher = await llm_client.fix_cypher(cypher, str(e), SCHEMA_CONTEXT)
            else:
                return {"error": f"Failed after {max_retries} attempts: {e}", "last_cypher": cypher}
```

### graph/client.py — Async Neo4j Wrapper
```python
from neo4j import AsyncGraphDatabase
import neo4j

class GraphClient:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self._driver.close()

    async def run_query(self, cypher: str, params: dict = None, read_only: bool = False) -> list[dict]:
        if read_only:
            # Enforce read-only via Neo4j session access_mode
            async with self._driver.session(
                default_access_mode=neo4j.READ_ACCESS,
            ) as session:
                result = await session.run(cypher, params or {})
                return [dict(record) async for record in result]
        else:
            async with self._driver.session() as session:
                result = await session.run(cypher, params or {})
                return [dict(record) async for record in result]

    async def write_entity(self, entity: Entity) -> str:
        result = await self.run_query(UPSERT_ENTITY, entity.model_dump())
        return result[0]["e.id"]

    async def write_event(self, event: Event, entities: list[Entity],
                          source_url: str, source_name: str) -> str:
        event_id = (await self.run_query(CREATE_EVENT, event.model_dump()))[0]["ev.id"]
        for entity in entities:
            await self.run_query(LINK_ENTITY_EVENT,
                {"entity_name": entity.name, "event_id": event_id})
        await self.run_query(LINK_EVENT_SOURCE,
            {"url": source_url, "source_name": source_name, "event_id": event_id})
        return event_id
```

## Tests
```
test_neo4j_connection
test_write_entity_via_template
test_write_event_with_linked_entities
test_upsert_idempotent
test_read_query_nl_generates_valid_cypher (mocked LLM)
test_read_query_rejects_write_operations
  → MUSS testen: CREATE, MERGE, DELETE, SET, CALL apoc.*,
    LOAD CSV, FOREACH, Semicolon-Injection, DETACH DELETE
test_self_healing_retries_on_syntax_error (mocked LLM)
test_few_shot_examples_execute_against_test_data
```

## Dependencies
```
neo4j>=5.23
```

---

# ══════════════════════════════════════════
# TASK-102: Event Codebook + LLM Classifier + Entity Extractor
# ══════════════════════════════════════════
# Aufwand: 2-3 Tage | Blocked by: TASK-100 | Blocks: TASK-103
# Parallel zu: TASK-101
# Status: DONE ✅ (committed 2026-03-30, 81 tests)

## Kontext
OSINT_MCP hat 5 Keyword-Listen für Topic-Classification. Wir bauen:
1. Professionelles Event Codebook (YAML, 50+ Typen)
2. LLM Zero-Shot Classifier (via vLLM, JSON Structured Output)
3. LLM Entity Extractor (ersetzt spaCy NER — besser für OSINT-Entities wie
   Waffensysteme, Satelliten, Militäreinheiten die nicht in spaCy's Trainingsdaten sind)

## Deliverables
1. `codebook/event_codebook.yaml`
2. `codebook/classifier.py` — Event Classification via Structured Output
3. `codebook/extractor.py` — Entity + Location Extraction via Structured Output
4. Tests mit gemocktem vLLM Response

## Spezifikation

### Classifier + Extractor in EINEM LLM-Call
Statt zwei separate Calls (classify + extract) machen wir EINEN Call
mit Structured Output. Das spart Latenz und Tokens.

```python
from openai import AsyncOpenAI

class IntelligenceExtractor:
    """Kombinierter Classifier + Entity Extractor.
    Ein LLM-Call, ein JSON-Output, Pydantic-validiert."""

    def __init__(self, base_url: str = "http://localhost:8000/v1", model: str = "qwen3.5-27b"):
        self.client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
        self.model = model
        self.codebook = load_codebook("codebook/event_codebook.yaml")

    async def extract(self, text: str, source_url: str = "") -> ExtractionResult:
        response = await self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": f"Source: {source_url}\n\nText: {text}"}
            ],
            temperature=0.1,
        )
        raw = json.loads(response.choices[0].message.content)
        return ExtractionResult.model_validate(raw)
```

### Warum LLM-Extraktion statt spaCy NER:
spaCy's `xx_ent_wiki_sm` erkennt "Berlin" und "NATO", aber NICHT:
- "Yaogan-44" (chinesischer Aufklärungssatellit)
- "PLA Strategic Support Force" (Militäreinheit)
- "DF-27" (Hyperschallrakete)
- "Admiral Kuznetsov" (Flugzeugträger)

## Tests
```
test_codebook_loads_all_categories
test_extract_military_event (mocked: "Russian forces launched drone attack on Odessa")
test_extract_space_event (mocked: "China launched Yaogan-44 from Jiuquan")
test_extract_returns_valid_pydantic_model
test_extract_unknown_event_defaults_to_other
test_confidence_below_threshold
test_batch_extract_concurrent
```

## Dependencies
```
openai>=1.40         # AsyncOpenAI Client für vLLM
pyyaml>=6.0
```

---

# ══════════════════════════════════════════
# TASK-103: Ingestion Pipeline — Extract → Graph Write
# ══════════════════════════════════════════
# Aufwand: 3-4 Tage | Blocked by: TASK-101, TASK-102 | Blocks: TASK-104
# Status: DONE ✅ (committed 2026-03-30, 43 tests)

## Kontext
WorldView hat 27 RSS Feeds + GDELT + TLE via APScheduler.
Nach dem Fetch passiert aktuell: Redis Cache + Qdrant Embed.
Wir schalten DAZWISCHEN: LLM Extract → Neo4j Write.
Plus: 10 Think-Tank-Feeds aus OSINT_MCP absorbieren.

## Deliverables
1. `services/data-ingestion/pipeline.py` — Post-Fetch Orchestrator
2. `services/data-ingestion/feeds/thinktank_feeds.py` — 10 Feeds migriert
3. Integration in bestehenden `scheduler.py`
4. Redis Stream Publishing für Frontend-Updates

## Spezifikation

### pipeline.py — Orchestrator
```python
async def process_item(
    item: FeedItem,
    extractor: IntelligenceExtractor,   # aus TASK-102
    graph: GraphClient,                  # aus TASK-101
    qdrant: QdrantClient,                # bestehend
    redis: Redis,                        # bestehend
):
    """
    1. extractor.extract(item.title + " " + item.summary, item.url)
       → ExtractionResult (Entities, Events, Locations)
    2. Für jeden Event:
       graph.write_event(event, entities, source_url, source_name)
       → Deterministische Templates, kein LLM-Cypher
    3. Embed in Qdrant (dense + BM25 sparse) für RAG
    4. Publish to Redis Stream "events:new" für Frontend Live-Update
    """
```

### Qdrant Hybrid Collection Setup
```python
from qdrant_client import models

qdrant.create_collection(
    collection_name="odin_v2",
    vectors_config={
        "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
    },
)
```

### Ingest: Dense-Vektor vorberechnen, BM25 serverseitig
```python
from qdrant_client.http.models import PointStruct, SparseVector
import httpx

# Dense vector: vorberechnet via Embedding-Server (TEI auf Port 8001)
async def get_dense_vector(text: str) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(settings.EMBEDDING_URL, json={"inputs": text})
        return resp.json()[0]  # TEI returns list[list[float]]

dense_vec = await get_dense_vector(chunk_text)

point = PointStruct(
    id=uuid4().hex,
    vector={
        "dense": dense_vec,
        # BM25 sparse: Qdrant berechnet IDF serverseitig bei Query,
        # für Ingest muss tokenisiert werden oder Fastembed genutzt werden.
        # Variante A: Qdrant Server-Side Inference (requires Fastembed integration)
        # Variante B: Eigene BM25 Tokenisierung → SparseVector(indices=..., values=...)
    },
    payload={"text": chunk_text, "source": url, "event_type": event.codebook_type, ...}
)
```

### Kontext-Dateien die der Agent lesen MUSS:
- `services/data-ingestion/scheduler.py`
- `services/data-ingestion/feeds/rss_collector.py`
- `graph/client.py` + `graph/write_templates.py` (aus TASK-101)
- `codebook/extractor.py` (aus TASK-102)

## Tests
```
test_process_item_writes_event_to_neo4j
test_process_item_writes_entities_linked
test_process_item_embeds_in_qdrant_with_both_vectors
test_process_item_publishes_redis_stream
test_thinktank_feeds_integrated_in_scheduler
test_deduplication_no_double_events
```

## Dependencies
Keine neuen — alles aus TASK-100, TASK-101, TASK-102.

---

# ══════════════════════════════════════════
# TASK-104: Hybrid Search + Docling + Reranker
# ══════════════════════════════════════════
# Aufwand: 3-4 Tage | Blocked by: TASK-103 | Blocks: TASK-105
# VEREINFACHUNG: Qdrant native BM25 statt rank_bm25 Library!
# Status: DONE ✅ Phase 1 (committed 2026-03-30, 99 tests). Phase 2 (hybrid sparse) offen.

## Kontext
WorldView hat einen RAG-Stack in `services/intelligence/rag/`.
Wir erweitern um: Docling Document Parsing, Qdrant native Hybrid Search,
und Qwen3-Reranker.

## Deliverables
1. `services/intelligence/rag/docling_ingest.py` — Docling Integration
2. `services/intelligence/rag/retriever.py` — ERWEITERT: Qdrant native Hybrid Search
3. `services/intelligence/rag/reranker.py` — Qwen3-Reranker-0.6B
4. `services/backend/app/routers/rag.py` — ERWEITERT: `/ingest` mit Docling
5. Tests

## Spezifikation

### Hybrid Search — Qdrant-native (KEIN rank_bm25 nötig!)
```python
async def hybrid_search(query: str, k: int = 10) -> list[SearchResult]:
    """
    Qdrant Query API macht Dense + Sparse + RRF serverseitig.
    Wir müssen nur die Prefetch-Config definieren.
    """
    results = await qdrant.query_points(
        collection_name="odin_v2",
        prefetch=[
            models.Prefetch(
                query=models.Document(text=query, model="Qwen/Qwen3-Embedding-0.6B"),
                using="dense",
                limit=k * 2,
            ),
            models.Prefetch(
                query=models.Document(text=query, model="Qdrant/bm25"),
                using="bm25",
                limit=k * 2,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=k * 2,  # Overfetch für Reranker
    )
    # Rerank
    reranked = await reranker.rerank(query, results.points, top_k=k)
    return reranked
```

### Docling Ingest
```python
from docling.document_converter import DocumentConverter

class DoclingIngester:
    def __init__(self):
        self.converter = DocumentConverter()

    async def ingest(self, file_path: str) -> list[dict]:
        result = self.converter.convert(file_path)
        chunks = []
        for item in result.document.iterate_items():
            if item.label in ("table", "figure"):
                chunks.append({"text": item.export_to_markdown(), "type": item.label})
            else:
                chunks.append({"text": item.text, "type": "text"})
        return chunks
```

### Reranker
```python
from sentence_transformers import CrossEncoder

class OdinReranker:
    def __init__(self, model_name="Qwen/Qwen3-Reranker-0.6B"):
        self.model = CrossEncoder(model_name, device="cuda")

    async def rerank(self, query: str, points: list, top_k: int = 10) -> list:
        pairs = [(query, p.payload["text"]) for p in points]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(points, scores), key=lambda x: x[1], reverse=True)
        return [p for p, s in ranked[:top_k]]
```

## Tests
```
test_hybrid_search_returns_results_from_both_vectors
test_docling_parses_pdf_with_tables
test_docling_parses_html
test_reranker_reorders_results
test_full_pipeline_ingest_then_search
```

## Dependencies
```
docling[vlm,easyocr]>=2.80
sentence-transformers>=3.0   # für Reranker (CrossEncoder)
# KEIN rank_bm25 nötig!
```

---

# ══════════════════════════════════════════
# TASK-105: Agent Tools + Graph Explorer + Vision
# ══════════════════════════════════════════
# Aufwand: 4-5 Tage | Blocked by: TASK-101, TASK-104 | Blocks: TASK-106, TASK-107
# Status: DONE ✅ (committed 2026-03-30, 155 intelligence + 17 backend tests)

## Kontext
WorldView hat LangGraph mit 3 Agents und 4 Tools.
Wir erweitern um: graph_query, classify, und vision Tool.
Plus Frontend: Graph Explorer Komponente.

VEREINFACHUNG für Vision: Qwen3.5 ist nativ multimodal —
es kann Bilder direkt verarbeiten. Für Basis-Vision (Captioning, OCR, VQA)
brauchen wir KEIN separates Florence-2. Nur YOLOv8 für spezialisierte
Military Equipment Detection (TASK-107).

## Deliverables
1. `services/intelligence/agents/tools/graph_query.py` — Neo4j Read-Path als Tool
2. `services/intelligence/agents/tools/classify.py` — On-Demand Classification
3. `services/intelligence/agents/tools/vision.py` — Bild-Analyse via Qwen3.5 multimodal
4. `services/backend/app/routers/graph.py` — Graph Query Endpoints
5. `services/frontend/src/components/graph/EntityExplorer.tsx`
6. Tests

## Spezifikation

### graph_query Tool für LangGraph
```python
@tool
async def query_knowledge_graph(question: str) -> str:
    """Query the Neo4j knowledge graph with a natural language question.
    Use this when you need to find relationships between entities,
    track event timelines, or explore connections."""
    result = await query_graph_nl(question, llm_client, graph_client)
    if "error" in result:
        return f"Graph query failed: {result['error']}"
    return result["answer"]
```

### Vision Tool — Qwen3.5 multimodal (kein Florence-2 nötig für Basics!)
```python
@tool
async def analyze_image(image_path: str, question: str = "Describe this image in detail") -> str:
    """Analyze an image using Qwen3.5 multimodal capabilities.
    Can answer questions about image content, identify objects, read text."""
    import base64
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    response = await llm_client.chat.completions.create(
        model="qwen3.5-27b",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": question}
            ]
        }]
    )
    return response.choices[0].message.content
```

### EntityExplorer.tsx
- `react-force-graph-2d` für Netzwerk-Visualisierung
- API: `GET /api/v1/graph/entity/{name}/neighborhood?depth=2`
- Click auf Node → Detail Panel + Timeline
- Neuer Tab in bestehendem UI neben Intel/Threats

### Backend Endpoints
```python
# services/backend/app/routers/graph.py
@router.get("/entity/{name}/neighborhood")
async def get_entity_neighborhood(name: str, depth: int = 2):
    """Returns entity + connected nodes within N hops."""

@router.post("/query")
async def query_graph(body: GraphQueryRequest):
    """Natural language → Cypher → Results."""

@router.get("/events/recent")
async def recent_events(hours: int = 24, event_type: str = None):
    """Recent events, optional filter by codebook type."""
```

## Tests
```
test_graph_query_tool_returns_answer
test_vision_tool_describes_image (mocked vLLM)
test_entity_neighborhood_api_returns_graph
test_graph_query_api_rejects_write_operations
```

## Dependencies
```
react-force-graph-2d: "^1.25"   # Frontend
# Vision: kein neues Backend-Package, nutzt bestehenden vLLM + openai Client
```

---

# ══════════════════════════════════════════
# TASK-106: Demo-Szenario + Polish
# ══════════════════════════════════════════
# Aufwand: 2-3 Tage | Blocked by: TASK-105 | Blocks: nichts
# Status: DONE ✅ (committed 2026-03-30, scope C+ demo UI integration)

## Kontext
Alle Kernkomponenten stehen. Jetzt: End-to-End Demo mit echten Daten,
README Update, und Cleanup.

## Deliverables
1. Demo-Szenario: "Chinese Space Intelligence" End-to-End
2. README.md komplett überarbeitet
3. Langfuse Tracing verifiziert
4. Screenshot/GIF für Portfolio

## Demo-Szenario
```
1. System startet: vLLM + Neo4j + Qdrant + Redis + FastAPI + Frontend
2. Scheduler crawlt Think-Tank-Feeds + bestehende 27 RSS Feeds
3. IntelligenceExtractor klassifiziert: "space.satellite_launch" Event
   und extrahiert Entities: "Yaogan-44", "Jiuquan", "PLA SSF"
4. Neo4j Write via Templates: Event → Entities → Location → Source
5. Qdrant erhält Dense + BM25 Vektoren für RAG
6. CesiumJS Globe zeigt Jiuquan mit Event-Marker (bestehende Layer erweitert)
7. Agent Query: "What Chinese military satellites were launched recently?"
   → graph_query Tool → Cypher → Neo4j → Results
   → semantic_search Tool → Qdrant Hybrid → Context
   → Synthesis → Antwort mit Quellen
8. Graph Explorer zeigt Entity-Netzwerk: Yaogan-44 ↔ PLA SSF ↔ Jiuquan
```

## README.md Struktur
- Project Vision (2 Sätze)
- Architecture Diagram (ASCII)
- Screenshot/GIF
- Quick Start (5 Schritte)
- Tech Stack Tabelle
- API Endpoints
- Demo Use Case
- Roadmap (Phase Next)

---

# ══════════════════════════════════════════
# TASK-107: Hybrid Vision — YOLOv8 Detector + Qwen3.5 Reasoner
# ══════════════════════════════════════════
# Aufwand: 5-7 Tage | Blocked by: TASK-105 | Blocks: nichts
# Parallel zu: TASK-106
# Status: OFFEN

## Kontext
Qwen3.5 Vision (aus TASK-105) kann Bilder beschreiben und Fragen beantworten,
aber es kann KEINE militärischen Fahrzeuge in Satellitenbildern zuverlässig
erkennen — die Trainingsdaten fehlen. YOLOv8 erreicht nach Fine-Tuning auf
Aerial/Satellite-Datensätzen mAP@0.5 von 0.79+ für Militärfahrzeuge und
F1=0.958 auf SAR-Daten. Die Hybrid-Pipeline kombiniert beides:
YOLOv8 detektiert → Qwen3.5 reasoned.

## Deliverables
1. `vision/detector.py` — YOLOv8 Military Object Detection
2. `vision/hybrid_pipeline.py` — Orchestrator: Detect → Crop → Reason
3. `vision/training/` — Fine-Tuning Script + Datensatz-Download
4. `services/backend/app/routers/vision.py` — Vision API Endpoints
5. `services/intelligence/agents/tools/vision.py` — ERWEITERT um Detector
6. Integration: Detektierte Objekte → Neo4j als :MilitaryAsset Entities
7. Tests

## Spezifikation

### Hybrid-Pipeline Architektur
```
Satellitenbild / Aerial Image
    ↓
┌─────────────────────────────────────────────┐
│  YOLOv8m (fine-tuned)  — ~2 GB VRAM        │
│  Erkennt: Bounding Boxes + Klasse + Conf    │
│  z.B. "tank (0.87)", "SAM_system (0.72)"   │
└────────────────┬────────────────────────────┘
                 ↓
    Für jede Detection mit confidence > 0.5:
                 ↓
┌─────────────────────────────────────────────┐
│  Crop + Context Window (2x BBox)            │
│  → Qwen3.5 Vision (already loaded, 0 GB)   │
│  Prompt: "This cropped satellite image      │
│  shows a detected [class]. Identify the     │
│  specific type, assess operational status,  │
│  and note any tactical context."            │
└────────────────┬────────────────────────────┘
                 ↓
    Structured Output → Neo4j + Qdrant + Frontend
```

### VRAM-Budget
```
Qwen3.5-27B AWQ:          ~17.6 GB (bereits geladen)
Qwen3-Embedding-0.6B:      ~1.2 GB
YOLOv8m:                    ~2 GB
──────────────────────────────────
Total:                     ~20.8 GB / 32 GB ✅
Headroom:                  ~11.2 GB
```

### vision/detector.py
```python
from ultralytics import YOLO
from PIL import Image
from pydantic import BaseModel

class Detection(BaseModel):
    class_name: str
    confidence: float
    bbox: list[float]  # [x1, y1, x2, y2] normalized
    crop_path: str | None = None

class MilitaryDetector:
    def __init__(self, model_path: str = "models/yolov8m-military.pt"):
        self.model = YOLO(model_path)

    async def detect(self, image_path: str, conf_threshold: float = 0.5) -> list[Detection]:
        results = self.model(image_path, conf=conf_threshold)
        detections = []
        for r in results:
            for box in r.boxes:
                detections.append(Detection(
                    class_name=r.names[int(box.cls)],
                    confidence=float(box.conf),
                    bbox=box.xyxyn.tolist()[0],
                ))
        return detections

    async def detect_and_crop(self, image_path: str, output_dir: str = "/tmp/crops") -> list[Detection]:
        """Detect + save cropped regions for Qwen3.5 reasoning."""
        img = Image.open(image_path)
        detections = await self.detect(image_path)
        for i, det in enumerate(detections):
            x1, y1, x2, y2 = det.bbox
            w, h = img.size
            pad_x, pad_y = (x2-x1) * 0.5, (y2-y1) * 0.5
            crop = img.crop((
                max(0, int((x1-pad_x)*w)), max(0, int((y1-pad_y)*h)),
                min(w, int((x2+pad_x)*w)), min(h, int((y2+pad_y)*h))
            ))
            crop_path = f"{output_dir}/det_{i}_{det.class_name}.jpg"
            crop.save(crop_path)
            det.crop_path = crop_path
        return detections
```

### vision/hybrid_pipeline.py
```python
class HybridVisionPipeline:
    def __init__(self, detector: MilitaryDetector, llm_client, graph_client):
        self.detector = detector
        self.llm = llm_client
        self.graph = graph_client

    async def analyze_satellite_image(
        self, image_path: str, source_url: str = "", location_name: str = ""
    ) -> list[dict]:
        """Full pipeline: Detect → Crop → Reason → Graph Write"""
        detections = await self.detector.detect_and_crop(image_path)

        results = []
        for det in detections:
            reasoning = await self.llm.chat.completions.create(
                model="qwen3.5-27b",
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"file://{det.crop_path}"}},
                        {"type": "text", "text": f"""This cropped satellite/aerial image shows a detected {det.class_name} (confidence: {det.confidence:.2f}).
Analyze and respond in JSON:
{{"vehicle_type": "specific type e.g. T-72B3, S-400, Type 055",
  "category": "armor|artillery|air_defense|naval|aircraft|logistics|infrastructure",
  "operational_status": "operational|damaged|destroyed|unknown",
  "tactical_context": "brief description of surroundings and tactical significance",
  "count": 1}}"""}
                    ]
                }],
                temperature=0.1,
            )
            analysis = json.loads(reasoning.choices[0].message.content)
            analysis["detection"] = det.model_dump()

            await self.graph.run_query(
                """
                MERGE (a:MilitaryAsset {vehicle_type: $vehicle_type})
                SET a.category = $category, a.last_seen = datetime()
                WITH a
                CREATE (d:Detection {
                    timestamp: datetime(),
                    confidence: $confidence,
                    status: $status,
                    context: $context,
                    image_source: $source,
                    location: $location
                })
                CREATE (d)-[:IDENTIFIED]->(a)
                """,
                {
                    "vehicle_type": analysis["vehicle_type"],
                    "category": analysis["category"],
                    "confidence": det.confidence,
                    "status": analysis["operational_status"],
                    "context": analysis["tactical_context"],
                    "source": source_url,
                    "location": location_name,
                }
            )
            results.append(analysis)

        return results
```

### Fine-Tuning Setup
```python
# vision/training/finetune_yolo.py
from ultralytics import YOLO

# Datensätze (frei verfügbar):
# - xView: 60 Klassen, ~1M Objekte, Satellitenperspektive
# - DOTA v2: Aerial Object Detection, 18 Klassen inkl. Fahrzeuge
# - FAIR1M: Militärfahrzeuge, Flugzeuge, Schiffe aus Satelliten

model = YOLO("yolov8m.pt")
results = model.train(
    data="military_dataset.yaml",
    epochs=100,
    imgsz=1024,
    batch=8,
    device=0,
    name="yolov8m-military",
    patience=20,
    augment=True,
)
# Output: runs/detect/yolov8m-military/weights/best.pt
# → Kopieren nach models/yolov8m-military.pt
```

### Neo4j Schema-Erweiterung
```cypher
(:MilitaryAsset {vehicle_type, category, last_seen})
(:Detection {timestamp, confidence, status, context, image_source, location})

(:Detection)-[:IDENTIFIED]->(:MilitaryAsset)
(:Detection)-[:DETECTED_AT]->(:Location)
(:Event)-[:VISUAL_EVIDENCE]->(:Detection)

CREATE CONSTRAINT military_asset IF NOT EXISTS
  FOR (a:MilitaryAsset) REQUIRE a.vehicle_type IS UNIQUE;
```

## Tests
```
test_yolo_loads_model
test_detect_returns_bboxes (auf Testbild mit bekannten Objekten)
test_detect_and_crop_saves_files
test_hybrid_pipeline_full (mocked LLM + mocked Neo4j)
test_hybrid_writes_military_asset_to_neo4j
test_api_endpoint_detect_military
test_agent_tool_detect_military_objects
test_vram_budget_yolo_plus_qwen (assert total < 22 GB)
```

## Dependencies
```
ultralytics>=8.2   # YOLOv8 (AGPL-3.0 — für MVP/PoC ok, bei Kommerzialisierung evaluieren)
Pillow>=10.0       # Image Processing (wahrscheinlich schon vorhanden)
```

---

# ══════════════════════════════════════════
# PHASE NEXT (nach Enhancement-Tasks)
# ══════════════════════════════════════════

| Feature | Warum später | Aufwand |
|---------|-------------|---------|
| Crawl4AI Deep Crawler | RSS Feeds reichen für MVP, Deep Crawl braucht Proxy-Infra | 1 Woche |
| Telegram Adapter | Braucht API-Credentials, rechtliche Prüfung | 3 Tage |
| EasyOCR multilingual | Qwen3.5 kann OCR nativ für Hauptsprachen | 2 Tage |
| CLIP Semantic Image Search | Braucht eigene Qdrant Collection für Bild-Embeddings | 1 Woche |
| MCP Server (überarbeitet) | Nice-to-have für Claude Code Integration | 3 Tage |
| Obsidian Bridge (aus Sentinel) | Persönliches Feature, nicht Demo-relevant | 2 Tage |
| Geocoding (Nominatim self-hosted) | LLM extrahiert Location-Namen, Frontend plottet auf Globe | 1 Woche |
| Auth (JWT + RBAC) | Single-User MVP braucht kein Auth | 3 Tage |
| Anomaly Detection (Prophet) | Braucht erstmal genug historische Daten | 2 Wochen |
| Sentinel-1 SAR | Komplexe Prozessierung, Auth nötig (CDSE S3) | 2 Wochen |

---

# ══════════════════════════════════════════
# ZUSAMMENFASSUNG + DEPENDENCY GRAPH
# ══════════════════════════════════════════

```
MVP (001-013): ████████████████████ DONE
TASK-014:      ██░░░░░░░░░░░░░░░░░░ PARTIAL (A/B/C offen)
TASK-015:      █░░░░░░░░░░░░░░░░░░░ TESTED (Code fehlt)

Enhancement Pipeline:

TASK-100: vLLM + Embedding Upgrade           0.5 Tage   → Blocks: alles     [DONE ✅]
    ↓
TASK-101: Neo4j + Two-Loop Graph             3-4 Tage   ┐                   [DONE ✅]
TASK-102: Event Codebook + Extractor         2-3 Tage   ┘ parallel          [DONE ✅]
    ↓
TASK-103: Ingestion Pipeline → Graph         3-4 Tage                       [DONE ✅]
    ↓
TASK-104: Hybrid Search + Docling            3-4 Tage                       [DONE ✅ Phase 1]
    ↓
TASK-105: Agent Tools + Graph Explorer       4-5 Tage                       [DONE ✅]
    ↓
TASK-106: Demo + Polish                      2-3 Tage   ┐                   [DONE ✅]
TASK-107: Hybrid Vision (YOLOv8)             5-7 Tage   ┘ parallel          [OFFEN]
    ↓
TASK-108: Submarine Cable Layer              1-2 Tage                       [OFFEN]
TASK-109: Flights Performance (Caching)      1-2 Tage                       [OFFEN]
```

## Gesamte neue Dependencies (über MVP hinaus)
```
# Python
vllm                        # LLM Serving
sentence-transformers>=3.0  # Embedding + Reranker
neo4j>=5.23                 # Graph DB Driver
openai>=1.40                # vLLM Client (OpenAI-kompatibel)
docling[vlm,easyocr]>=2.80  # Document Parsing
pyyaml>=6.0                 # Event Codebook
ultralytics>=8.2            # YOLOv8 (TASK-107, AGPL-3.0)
Pillow>=10.0                # Image Processing

# Frontend
react-force-graph-2d ^1.25  # Graph Viz
```
8 Python + 1 Frontend Dependencies.

---

# ══════════════════════════════════════════
# TASK-108: Submarine Cable Layer
# ══════════════════════════════════════════
# Aufwand: 1-2 Tage | Blocked by: nichts | Blocks: nichts
# Status: OFFEN

## Kontext
Unterwasser-Glasfaserkabel sind kritische OSINT-Infrastruktur.
TeleGeography stellt einen öffentlichen GeoJSON-Datensatz zur Verfügung.

## Deliverables
1. `services/frontend/src/components/layers/CableLayer.tsx` — CesiumJS Polyline-Rendering
2. `services/frontend/src/hooks/useCables.ts` — Datenlader (statisch oder API)
3. Toggle im OperationsPanel ("CABLES")
4. Kabel-Klick zeigt Name, Eigentümer, Kapazität, Landing Points

## Datenquelle
- TeleGeography Submarine Cable Map: https://github.com/telegeography/www.submarinecablemap.com
- Format: GeoJSON (cables.json + landing-points.json)
- Lizenz: Public domain für die Geodaten

---

# ══════════════════════════════════════════
# TASK-109: Flights Performance — Redis Caching + Smooth Rendering
# ══════════════════════════════════════════
# Aufwand: 1-2 Tage | Blocked by: nichts | Blocks: nichts
# Status: OFFEN

## Kontext
Flights-Layer hat ~486ms TTFB weil das Backend bei jedem Request
OpenSky/adsb.fi live proxied. Bei 10s Polling fühlt sich das träge an.

## Deliverables
1. Backend: Redis-Cache mit 10s TTL für Flight-Daten
2. Backend: Server-Side Bounding-Box Filter (nur sichtbare Region)
3. Frontend: Interpolation zwischen Polling-Updates (dead reckoning via heading+speed)
4. Optional: WebSocket statt Polling für Push-basierte Updates

## Optionen für Datenquellen
- OpenSky Network (aktuell, 10s Rate-Limit, optional Auth)
- adsb.fi (schneller, kein Auth, aggressives Caching)
- ADS-B Exchange (kommerziell, sehr schnell, API-Key nötig)
