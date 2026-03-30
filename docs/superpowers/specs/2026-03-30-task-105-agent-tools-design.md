# TASK-105: Agent Tools + Graph Explorer + Vision — Design Spec

**Date:** 2026-03-30
**Status:** Approved
**Blocked by:** TASK-101 (done), TASK-104 (done)
**Blocks:** TASK-106, TASK-107

---

## 1. Executive Summary

Umbau des Intelligence-Service von einer starren 3-Agent-Pipeline (OSINT → Analyst → Synthesis) auf eine **Hybrid ReAct-Architektur**: Ein ReAct-Agent mit Tool-Use (bind_tools/ToolNode) für intelligente, adaptive Recherche, gefolgt von einem deterministischen Synthesis-Node für garantiert strukturierten Report-Output.

Drei neue Tools: `graph_query` (Neo4j NL-Abfrage), `classify` (On-Demand Event-Klassifikation), `vision` (Qwen3.5 multimodal Bildanalyse). Dazu Backend-Endpoints für Graph-Queries und eine standalone EntityExplorer-Komponente im Frontend.

---

## 2. Architecture Decisions

### AD-1: ReAct + Deterministic Synthesis (Option C)

**Decision:** Ein ReAct Research Agent mit Tool-Use + ein nachgeschalteter Synthesis-Node (kein Agent, nur Prompt-Call).

**Why:**
- Qwen3.5-27B-AWQ ist prädestiniert für agentic Tool-Use (Multi-Step Reasoning, Tool-Auswahl)
- Starre Pipeline verschwendet Modell-Kapazität — ein 7B könnte das gleiche
- Kein voller Multi-Agent-Supervisor nötig — kontrollierte Komplexität
- Synthesis-Node garantiert deterministisches Report-Format

**Not chosen:**
- Single Pipeline (Status quo) — verschwendet 27B Modell
- Supervisor + Workers — unnötige Komplexität für 6-7 Tools

### AD-2: Graph Query — Templates mit Free-Cypher Escape-Hatch

**Decision:** 8 vordefinierte Cypher-Templates als Default. Fallback auf LLM-generiertes Cypher nur wenn kein Template matcht, durch alle bestehenden Safety-Layer.

**Why:**
- 90% der Queries sind abgedeckt durch Templates (sicher, schnell, vorhersagbar)
- Flexibilität für unvorhergesehene Queries bleibt erhalten
- Bestehende Security-Infra (validate_cypher_readonly, READ_ACCESS) sichert den Fallback

### AD-3: Vision — Explicit User Input Only

**Decision:** Vision-Tool steht dem ReAct Agent zur Verfügung, wird aber nur bei explizitem Bild-Input genutzt (URL oder lokaler Pfad). Kein Auto-Crawling von Bildern aus Feeds.

**Why:**
- Sauberer Scope für TASK-105 (TASK-107 bringt YOLOv8 + Auto-Pipeline)
- Kein Crawling-/SSRF-/Caching-Overhead
- Gleiche `analyze_image`-Schnittstelle, erweiterbar ohne API-Bruch

### AD-4: Frontend — Standalone MVP mit Click-to-Expand

**Decision:** EntityExplorer.tsx als standalone-Komponente. 2-Hop Default-View mit interaktiver Node-Expansion. Keine CesiumJS/Sidebar-Integration (TASK-106).

**Why:**
- Sichtbarer Wert in TASK-105 ohne UI-Rework-Kosten
- Click-to-Expand löst das "2 Hops zu wenig"-Problem ohne Performance-Explosion
- Backend-Endpoints stehen sowieso für graph_query Tool

---

## 3. Workflow Architecture

### 3.1 New LangGraph Workflow

```
User Query (+ optional image_url)
    │
    ▼
┌─────────────────────────────────────────┐
│  ReAct Research Agent                   │
│  Model: Qwen3.5-27B-AWQ via vLLM       │
│  Temperature: 0.3                       │
│                                         │
│  Tools (bind_tools):                    │
│  ├── semantic_search    (Qdrant RAG)    │
│  ├── graph_query        (Neo4j)         │
│  ├── classify           (Codebook)      │
│  ├── analyze_image      (Qwen3.5 VLM)  │
│  ├── gdelt_query        (GDELT API)     │
│  └── rss_fetch          (RSS feeds)     │
│                                         │
│  Guards:                                │
│  ├── max_tool_calls: 8                  │
│  ├── max_iterations: 5                  │
│  ├── tool_timeout: 15s per call         │
│  └── total_timeout: 60s                 │
│                                         │
│  Loop: Think → Act → Observe → Repeat   │
│  Exit: Agent calls "final_answer" or    │
│        guard limit reached              │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Synthesis Node (deterministic)         │
│  Model: Qwen3.5-27B-AWQ                │
│  Temperature: 0.1                       │
│                                         │
│  Input: ReAct agent's accumulated       │
│         findings + tool results         │
│                                         │
│  Output (fixed format):                 │
│  ├── executive_summary: str             │
│  ├── key_findings: list[str]            │
│  ├── threat_assessment: enum            │
│  ├── confidence: float                  │
│  ├── sources_used: list[str]            │
│  ├── tool_trace: list[ToolCall]         │
│  └── recommended_actions: list[str]     │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Fallback Guard                         │
│  If ReAct fails (timeout, error loop):  │
│  → Fall back to legacy linear pipeline  │
│    (OSINT → Analyst → Synthesis)        │
│  → Log reason for fallback              │
└─────────────────────────────────────────┘
```

### 3.2 AgentState (updated)

```python
class AgentState(TypedDict):
    # Input
    query: str
    image_url: str | None           # NEW: optional image for vision

    # ReAct
    messages: Annotated[list[BaseMessage], add_messages]
    tool_calls_count: int           # NEW: guard counter
    iteration: int                  # NEW: guard counter

    # Output (populated by Synthesis)
    synthesis: str
    executive_summary: str          # NEW
    key_findings: list[str]         # NEW
    threat_assessment: str
    confidence: float
    sources_used: list[str]
    agent_chain: list[str]
    tool_trace: list[dict]          # NEW: observability
    error: str | None
```

### 3.3 Legacy Fallback

The existing linear pipeline (osint_node → analyst_node → synthesis_node) bleibt als Fallback erhalten. Wird aktiviert wenn:
- ReAct Agent `max_iterations` erreicht ohne `final_answer`
- Unrecoverable Error im Tool-Loop
- Explicit flag `use_legacy=True` im Request

---

## 4. Tool Specifications

### 4.1 graph_query — Neo4j Knowledge Graph Tool

```python
@tool
async def query_knowledge_graph(question: str) -> str:
    """Query the Neo4j knowledge graph. Use for entity relationships,
    event timelines, connection networks, and co-occurrence analysis.

    Args:
        question: Natural language question about entities or events
    """
```

**Template Router:**

| # | Template | Intent Pattern | Cypher |
|---|----------|---------------|--------|
| 1 | entity_lookup | "find/who is/what is [entity]" | `MATCH (e:Entity {name: $name}) RETURN e` |
| 2 | one_hop | "connected to/related to [entity]" | `MATCH (e:Entity)-[r]-(n) WHERE e.name = $name RETURN ...` |
| 3 | two_hop_network | "network of/connections around [entity]" | `MATCH path = (e:Entity)-[*1..2]-(n) WHERE e.name = $name RETURN ... LIMIT 50` |
| 4 | events_by_entity | "events involving/about [entity]" | `MATCH (e:Entity)-[:INVOLVES]-(ev:Event) WHERE e.name = $name RETURN ... ORDER BY ev.timestamp DESC` |
| 5 | event_timeline | "events in [region/time]" | `MATCH (ev:Event)-[:OCCURRED_AT]-(l:Location) WHERE ... RETURN ... ORDER BY ev.timestamp` |
| 6 | co_occurring | "entities that appear together with [entity]" | `MATCH (e:Entity)-[:INVOLVES]-(ev:Event)-[:INVOLVES]-(other:Entity) WHERE e.name = $name RETURN ...` |
| 7 | source_backed | "sources for/evidence of [event/entity]" | `MATCH (ev:Event)-[:REPORTED_BY]-(s:Source) WHERE ... RETURN ...` |
| 8 | top_connected | "most connected/important entities" | `MATCH (e:Entity)-[r]-() RETURN e, count(r) as degree ORDER BY degree DESC LIMIT $limit` |

**Routing Logic:**
1. LLM-based intent classification (Qwen3.5, temperature 0, max_tokens 100)
2. Input: question + template descriptions
3. Output: `{template_id: str, params: dict, confidence: float}`
4. If confidence < 0.7 → Free Cypher fallback

**Free Cypher Fallback Guards:**
1. Schema-Whitelist in Prompt: Labels (`Entity`, `Event`, `Source`, `Location`, `Document`), Relationships (`INVOLVES`, `REPORTED_BY`, `OCCURRED_AT`, `MENTIONS`), Properties (explicit list)
2. `validate_cypher_readonly()` — keyword blocklist (existing)
3. `GraphClient.run_query(read_only=True)` — Neo4j session-level READ_ACCESS
4. Forced `LIMIT 100` injection if no LIMIT present
5. Query timeout: 5s
6. No semicolons allowed

**Observability fields:**
```python
{
    "mode": "template" | "fallback",
    "template_id": str | None,
    "confidence": float,
    "cypher": str,           # the executed query
    "validator_passed": bool,
    "duration_ms": int,
    "result_count": int
}
```

### 4.2 classify — On-Demand Event Classification

```python
@tool
async def classify_event(
    text: str,
    context: str = ""
) -> str:
    """Classify a piece of text using the intelligence event codebook.
    Returns event type, severity, confidence, and extracted entities.

    Args:
        text: The text to classify (headline, paragraph, or article)
        context: Optional context about the source or region
    """
```

**Implementation:**
- Reuses existing `IntelligenceExtractor` from `codebook/extractor.py`
- Returns structured result: event_type (dotted notation), severity, confidence, entities
- Max input: 4000 chars (existing limit)
- Temperature: 0 (deterministic)

### 4.3 analyze_image — Qwen3.5 Multimodal Vision

```python
@tool
async def analyze_image(
    image_url: str,
    question: str = "Describe this image in detail. Identify objects, text, locations, and any intelligence-relevant features."
) -> str:
    """Analyze an image using Qwen3.5 multimodal vision.
    Use for satellite imagery, document photos, maps, or any visual content.

    Args:
        image_url: HTTPS URL or whitelisted local path to the image
        question: Specific question about the image content
    """
```

**Security Guards:**
- URL validation: only `https://` or whitelisted local paths (`/tmp/odin/images/`, configurable)
- Content-Type check: must be `image/*` (HEAD request before download)
- Max file size: 10 MB
- Max dimensions: 4096x4096
- Download timeout: 10s
- No redirects to private/internal networks (SSRF protection via blocked IP ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`)
- Fallback: clear error message if image can't be loaded, agent continues without vision

**vLLM Call:**
```python
response = await llm_client.chat.completions.create(
    model=settings.vllm_model,
    messages=[{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_data_url}},
            {"type": "text", "text": question}
        ]
    }],
    max_tokens=1000,
    temperature=0.2
)
```

### 4.4 Existing Tools (refactored to bind_tools)

| Tool | Current | Change |
|------|---------|--------|
| `semantic_search` | `qdrant_search.py` — called directly | Refactor to `@tool`, use `enhanced_search()` |
| `gdelt_query` | `gdelt_query.py` — `@tool` exists | Keep, verify bind_tools compatibility |
| `rss_fetch` | `rss_fetch.py` — `@tool` exists | Keep, verify bind_tools compatibility |
| `web_search` | Stub | Remove stub + remove from `tools/__init__.py` exports |

---

## 5. ReAct Guards & Observability

### 5.1 Hard Guards

```python
REACT_GUARDS = {
    "max_tool_calls": 8,          # total tool invocations per query
    "max_iterations": 5,          # think-act-observe loops
    "tool_timeout_s": 15,         # per individual tool call
    "total_timeout_s": 60,        # entire ReAct loop
    "max_token_budget": 8000,     # max tokens in accumulated context
}
```

**Guard enforcement:**
- After each tool call: increment `tool_calls_count` in state
- Router checks: if `tool_calls_count >= max_tool_calls` → force transition to Synthesis
- Timeout: asyncio.wait_for on each tool call + overall workflow
- On guard trigger: log reason, pass accumulated results to Synthesis anyway

### 5.2 Observability (Phase 1 — Logging)

Every tool call produces a trace entry:

```python
@dataclass
class ToolTrace:
    request_id: str              # UUID per query
    tool_name: str
    tool_args: dict
    result_summary: str          # first 200 chars
    duration_ms: int
    success: bool
    error: str | None
    timestamp: datetime
```

- Stored in `tool_trace` list in AgentState
- Included in final response
- Logged via structlog with request_id correlation
- **Phase 2 (TASK-106+):** Langfuse integration for full trace visualization

### 5.3 System Prompt (ReAct Agent)

```
You are a geopolitical intelligence analyst with access to specialized tools.

Your job is to answer intelligence queries by gathering information from
multiple sources, analyzing patterns, and identifying threats.

Available tools:
- semantic_search: Search the intelligence knowledge base (Qdrant RAG)
- query_knowledge_graph: Query entity relationships and event timelines (Neo4j)
- classify_event: Classify text using the intelligence event codebook
- analyze_image: Analyze images (satellite, documents, maps) — only if image provided
- gdelt_query: Search recent global events via GDELT
- rss_fetch: Fetch articles from RSS feeds

Guidelines:
- Start with semantic_search or query_knowledge_graph for existing intelligence
- Use gdelt_query for recent/breaking events not yet in the knowledge base
- Use classify_event when you need to categorize an event precisely
- Use analyze_image ONLY when an image URL is provided in the query
- Cross-reference findings from multiple sources when possible
- Stop when you have sufficient evidence — do not use tools unnecessarily
- Maximum {max_tool_calls} tool calls allowed
```

---

## 6. Backend Endpoints

### 6.1 New Router: `services/backend/app/routers/graph.py`

Registered as `app.include_router(graph.router, prefix="/api/v1")` in `main.py`.
All endpoints below are relative to `/api/v1/graph/`.

```
GET  /api/v1/graph/entity/{name}      → Entity details + properties
GET  /api/v1/graph/neighbors/{name}   → 1-hop neighbors (for EntityExplorer expand)
GET  /api/v1/graph/network/{name}     → 2-hop network (for EntityExplorer initial view)
GET  /api/v1/graph/events             → Events with filters (entity, region, time_range)
GET  /api/v1/graph/search             → Full-text entity search (autocomplete)
```

**Query params (all endpoints):**
- `limit: int = 50` (max 200)
- `entity_type: str | None` — filter by type

**Response format:**
```python
class GraphNode(BaseModel):
    id: str
    name: str
    type: str
    properties: dict

class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str
    properties: dict

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_count: int
```

### 6.2 Updated: Intelligence Query Endpoints

**Two separate services, two separate endpoints:**

| Service | Endpoint | Purpose |
|---------|----------|---------|
| Intelligence (internal, port 8080) | `POST /query` | Direct LangGraph invocation |
| Backend (external, port 8000) | `POST /api/v1/intel/query` | SSE proxy to Intelligence service |

The Backend proxies to Intelligence — only the request/response models change:

```python
# Intelligence Service — POST /query
class QueryRequest(BaseModel):
    query: str                     # max 2000 chars
    region: str | None = None
    image_url: str | None = None   # NEW: optional image for vision
    use_legacy: bool = False       # NEW: force legacy pipeline

class QueryResponse(BaseModel):
    query: str
    executive_summary: str         # NEW
    key_findings: list[str]        # NEW
    analysis: str                  # synthesis text (backward compat)
    threat_assessment: str
    confidence: float
    sources_used: list[str]
    agent_chain: list[str]
    tool_trace: list[dict]         # NEW: observability
    timestamp: str
    mode: str                      # NEW: "react" | "legacy"
```

Backend `intel.py` passes through `image_url` and `use_legacy` to Intelligence service.

---

## 7. Frontend: EntityExplorer.tsx

### 7.1 Component Spec

**Dependency:** `react-force-graph-2d` (^1.25)

**Props:**
```typescript
interface EntityExplorerProps {
  initialEntity?: string;        // entity name to start with
  apiBaseUrl?: string;           // default: /api/v1/graph
}
```

**Features (MVP):**
- Force-directed graph visualization (react-force-graph-2d)
- Initial view: 2-hop network from `GET /graph/network/{name}`
- Click-to-expand: click node → `GET /graph/neighbors/{name}` → add new nodes/edges
- Double-click to collapse expanded nodes
- Node colors by entity type (Person=blue, Organization=green, Location=red, Event=orange, etc.)
- Node size by degree (more connections = larger)
- Hover tooltip: entity name + type + key properties
- One type filter dropdown (filter visible nodes by entity type)
- Search input: entity name autocomplete via `GET /graph/search?q=...`

**Not in scope (TASK-106):**
- CesiumJS sidebar integration
- Timeline slider
- Advanced filtering
- Export/share

### 7.2 File Structure

```
services/frontend/src/components/graph/
├── EntityExplorer.tsx          # Main component
├── GraphCanvas.tsx             # react-force-graph-2d wrapper
├── EntitySearch.tsx            # Autocomplete search input
├── NodeTooltip.tsx             # Hover tooltip
├── types.ts                   # GraphNode, GraphEdge, etc.
└── graph.module.css            # Styles
```

---

## 8. File Changes Summary

### New Files

```
services/intelligence/
├── agents/
│   ├── react_agent.py              # ReAct agent with bind_tools
│   └── tools/
│       ├── graph_query.py          # NL→Cypher tool (templates + fallback)
│       ├── graph_templates.py      # 8 Cypher templates + intent router
│       ├── classify.py             # On-demand event classification
│       └── vision.py               # Qwen3.5 multimodal image analysis
├── graph/
│   └── schema_whitelist.py         # Labels, rels, properties for free Cypher
└── tests/
    ├── test_react_agent.py         # ReAct workflow tests
    ├── test_graph_query.py         # Template routing + fallback tests
    ├── test_classify.py            # Classification tool tests
    └── test_vision.py              # Vision tool tests (mocked)

services/backend/
├── app/routers/graph.py            # Graph REST endpoints
└── tests/unit/test_graph_router.py # Router tests

services/frontend/src/components/graph/
├── EntityExplorer.tsx
├── GraphCanvas.tsx
├── EntitySearch.tsx
├── NodeTooltip.tsx
├── types.ts
└── graph.module.css
```

### Modified Files

```
services/intelligence/
├── agents/tools/__init__.py        # Remove web_search, add new tool exports
├── agents/tools/qdrant_search.py   # Refactor to @tool compatible
├── agents/tools/web_search.py      # DELETE (stub, replaced by real tools)
├── graph/workflow.py               # New ReAct workflow + legacy fallback
├── graph/state.py                  # Updated AgentState
├── config.py                       # ReAct guard settings
├── main.py                         # Updated /query endpoint
└── pyproject.toml                  # Add openai, Pillow dependencies

services/backend/
├── app/main.py                     # Register graph router
└── app/routers/intel.py            # Updated request/response models
```

---

## 9. Testing Strategy

### Unit Tests (TDD)

| Area | Tests | Focus |
|------|-------|-------|
| Graph Templates | ~15 | Intent routing, parameter extraction, template selection |
| Graph Query Fallback | ~10 | Free Cypher generation, validation, LIMIT injection |
| Classify Tool | ~8 | Codebook integration, edge cases, confidence filtering |
| Vision Tool | ~10 | URL validation, SSRF protection, size limits, mock VLM |
| ReAct Agent | ~12 | Tool selection, guard enforcement, fallback trigger |
| Graph Router | ~10 | All endpoints, filters, pagination, error handling |
| **Total new** | **~65** | |

### Integration Tests

- ReAct workflow end-to-end with mocked tools
- Legacy fallback trigger verification
- Graph endpoint → Neo4j round-trip (requires running Neo4j)

### Regression

- Current test suite across all services must remain green
- Synthesis output format unchanged (backward compat)

---

## 10. Dependencies

### Python (intelligence service)

Existing explicit dependencies (in pyproject.toml):
- `langgraph` / `langchain-core` / `langchain-openai` — supports bind_tools/ToolNode
- `neo4j` — already installed
- `httpx` — already installed (for vision URL download)

**New explicit dependencies to add to pyproject.toml:**
- `openai>=1.40` — for vLLM multimodal API calls (vision tool). Currently used transitively via langchain-openai but must be explicit for direct usage.
- `Pillow>=10.0` — for image dimension validation in vision tool. Not currently in dependency tree.

### Frontend

```bash
npm install react-force-graph-2d@^1.25
```

One new dependency.

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Qwen3.5 tool-calling quality | ReAct loops or wrong tools | Max iterations guard + legacy fallback |
| Free Cypher hallucination | Wrong/dangerous queries | 3-layer defense: validator + READ_ACCESS + timeout |
| Vision SSRF | Internal network access | IP range blocklist + no redirects |
| ReAct latency (multi-step) | Slow responses | Total timeout 60s, tool budget 8 calls |
| Force-graph performance | Browser lag on large graphs | LIMIT 50 default + lazy expansion |
| vLLM multimodal support | Image processing might fail | Graceful fallback, agent continues without vision |
