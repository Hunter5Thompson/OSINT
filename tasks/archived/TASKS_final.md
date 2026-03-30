# Odin Enhancement Tasks — v2 (Intelligence Upgrade)
#
# ABHÄNGIGKEIT: Setzt TASK-001 bis TASK-015 (Backlog) voraus — MVP muss stehen.
# NUMMERIERUNG: TASK-100 bis TASK-106 (kein Konflikt mit Backlog-Tasks)
#
# Prinzipien:
# - Jeder Task ist ein self-contained Briefing für Sonnet/Haiku
# - vLLM überall, kein Ollama
# - Two-Loop Graph: LLM extrahiert Daten → Templates schreiben | LLM generiert Cypher → Validation → Read
# - Qdrant native BM25 statt separate rank_bm25 Library
# - Qwen3.5 multimodal statt separate Florence-2 für Basis-Vision
# - MVP-fokussiert: Telegram/Crawl4AI in Phase Next, nicht MVP

---

# ══════════════════════════════════════════
# TASK-100: vLLM Migration + Embedding Upgrade
# ══════════════════════════════════════════
# Aufwand: 0.5 Tage | Blocked by: nichts | Blocks: alles

## Kontext
WorldView nutzt aktuell Ollama mit Qwen3-32B (Port 11434).
Die gesamte LLM-Kommunikation läuft bereits über OpenAI-kompatible API.
Migration ist eine Config-Änderung, kein Code-Refactor.

## Deliverables
1. vLLM installiert und Qwen3.5-27B-AWQ served auf Port 8000
2. `.env.example` und `services/backend/app/config.py` aktualisiert
3. Embedding-Server: Qwen3-Embedding-0.6B via sentence-transformers auf Port 8001
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
        """
        Input: Rohtext (Nachricht, Artikel, Telegram-Post)
        Output: ExtractionResult mit Events, Entities, Locations

        System Prompt enthält:
        - Event Codebook Zusammenfassung (alle Typen mit Beschreibung)
        - Output Format (JSON Schema von ExtractionResult)
        - Anweisung: "Extract ALL entities (persons, orgs, locations, weapons,
          satellites, vessels, military units) and classify the event type."

        Response Format: JSON mode (response_format={"type": "json_object"})
        """
        response = await self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": f"Source: {source_url}\n\nText: {text}"}
            ],
            temperature=0.1,  # Niedrig für konsistente Extraktion
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

Das LLM kennt diese Entities aus dem Training. Structured Output + Pydantic
Validation gibt uns die gleiche Typsicherheit wie NER, aber mit besserem Recall.

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
# Neue Collection mit Dense + Sparse Vektoren
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

Beim Ingest: Jeder Chunk bekommt BEIDE Vektoren:
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

Das ist der gesamte Hybrid Search Code. ~15 Zeilen. Qdrant erledigt BM25, IDF,
RRF Fusion serverseitig. Kein eigener BM25-Index, kein eigener Fusion-Code.

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
# Aufwand: 4-5 Tage | Blocked by: TASK-101, TASK-104 | Blocks: TASK-106

## Kontext
WorldView hat LangGraph mit 3 Agents und 4 Tools.
Wir erweitern um: graph_query, classify, und vision Tool.
Plus Frontend: Graph Explorer Komponente.

VEREINFACHUNG für Vision: Qwen3.5 ist nativ multimodal —
es kann Bilder direkt verarbeiten. Für Basis-Vision (Captioning, OCR, VQA)
brauchen wir KEIN separates Florence-2. Nur YOLOv8 für spezialisierte
Military Equipment Detection (die Qwen nicht kann).

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
    # Qwen3.5 über vLLM mit Vision Support
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

Wenn spezialisierte Military Equipment Detection nötig ist → YOLOv8 on-demand
laden (Phase Next nach TASK-106). Für den MVP reicht Qwen3.5 Vision.

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
# PHASE NEXT (nach MVP)
# ══════════════════════════════════════════
# Nicht im MVP, aber geplant und in PRD dokumentiert:

| Feature | Warum später | Aufwand |
|---------|-------------|---------|
| Crawl4AI Deep Crawler | RSS Feeds reichen für MVP, Deep Crawl braucht Proxy-Infra | 1 Woche |
| Telegram Adapter | Braucht API-Credentials, rechtliche Prüfung | 3 Tage |
| YOLOv8 Military Detection | Qwen3.5 Vision reicht für Basics, YOLO braucht Fine-Tune-Daten | 2 Wochen |
| EasyOCR multilingual | Qwen3.5 kann OCR nativ für Hauptsprachen | 2 Tage |
| CLIP Semantic Image Search | Braucht eigene Qdrant Collection für Bild-Embeddings | 1 Woche |
| MCP Server (überarbeitet) | Nice-to-have für Claude Code Integration | 3 Tage |
| Obsidian Bridge (aus Sentinel) | Persönliches Feature, nicht Demo-relevant | 2 Tage |
| Geocoding (Nominatim self-hosted) | LLM extrahiert Location-Namen, Frontend plottet auf Globe | 1 Woche |
| Auth (JWT + RBAC) | Single-User MVP braucht kein Auth | 3 Tage |
| Anomaly Detection (Prophet) | Braucht erstmal genug historische Daten | 2 Wochen |

---

# ══════════════════════════════════════════
# ZUSAMMENFASSUNG
# ══════════════════════════════════════════

```
TASK-100: vLLM + Embedding Upgrade           0.5 Tage   → Blocks: alles
    ↓
TASK-101: Neo4j + Two-Loop Graph             3-4 Tage   ┐
TASK-102: Event Codebook + Extractor         2-3 Tage   ┘ parallel
    ↓
TASK-103: Ingestion Pipeline → Graph         3-4 Tage
    ↓
TASK-104: Hybrid Search + Docling            3-4 Tage
    ↓
TASK-105: Agent Tools + Graph Explorer       4-5 Tage
    ↓
TASK-106: Demo + Polish                      2-3 Tage
                                             ─────────
                                             ~19-24 Tage
                                             = 4-5 Wochen bei Abenden/WE
```

Gesamte neue Dependencies (über WorldView hinaus):
```
vllm                        # LLM Serving
sentence-transformers>=3.0  # Embedding + Reranker
neo4j>=5.23                 # Graph DB Driver
openai>=1.40                # vLLM Client (OpenAI-kompatibel)
docling[vlm,easyocr]>=2.80  # Document Parsing
pyyaml>=6.0                 # Event Codebook
react-force-graph-2d        # Frontend Graph Viz
```

7 neue Dependencies. Das ist schlank.
