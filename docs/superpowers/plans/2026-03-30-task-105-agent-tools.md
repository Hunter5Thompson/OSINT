# TASK-105: Agent Tools + Graph Explorer + Vision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the linear 3-agent pipeline with a ReAct agent + deterministic Synthesis, add graph_query/classify/vision tools, a Graph REST API, and a standalone EntityExplorer frontend component.

**Architecture:** Single ReAct research agent (Qwen3.5-27B via vLLM, bind_tools/ToolNode) with 6 tools makes autonomous tool-use decisions. Synthesis node (temperature 0.1) produces structured intelligence reports. Legacy pipeline retained as fallback. Backend exposes Neo4j graph data via REST for frontend EntityExplorer (react-force-graph-2d).

**Tech Stack:** LangGraph (ReAct), langchain-core (@tool, bind_tools, ToolNode), vLLM (OpenAI-compatible API), Neo4j 5, Qdrant, FastAPI, React 19, react-force-graph-2d, Tailwind CSS 4

**Spec:** `docs/superpowers/specs/2026-03-30-task-105-agent-tools-design.md`

---

## File Structure

### New Files

```
services/intelligence/
├── agents/react_agent.py               # ReAct agent: LLM + bind_tools + guard logic
├── agents/tools/graph_query.py         # NL→Cypher tool (template router + fallback)
├── agents/tools/graph_templates.py     # 8 Cypher query templates + intent router
├── agents/tools/classify.py            # On-demand event classification via codebook
├── agents/tools/vision.py              # Qwen3.5 multimodal image analysis
├── graph/schema_whitelist.py           # Labels, relationships, properties for free Cypher prompt
└── tests/
    ├── test_graph_templates.py
    ├── test_graph_query.py
    ├── test_classify.py
    ├── test_vision.py
    └── test_react_agent.py

services/backend/
├── app/routers/graph.py                # GET endpoints for graph exploration
├── app/models/graph.py                 # GraphNode, GraphEdge, GraphResponse
└── tests/unit/test_graph_router.py

services/frontend/src/components/graph/
├── types.ts                            # GraphNode, GraphEdge TypeScript types
├── GraphCanvas.tsx                     # react-force-graph-2d wrapper
├── NodeTooltip.tsx                     # Hover tooltip
├── EntitySearch.tsx                    # Autocomplete search input
├── EntityExplorer.tsx                  # Main orchestrator component
└── graph.module.css                    # Styles
```

### Modified Files

```
services/intelligence/
├── pyproject.toml                      # Add openai, Pillow
├── config.py                           # Add ReAct guard settings
├── graph/state.py                      # Extended AgentState
├── graph/workflow.py                   # ReAct workflow + legacy fallback
├── agents/tools/__init__.py            # Updated exports
├── agents/tools/web_search.py          # DELETE
├── main.py                             # Updated /query endpoint

services/backend/
├── app/main.py                         # Register graph router
├── app/config.py                       # Add neo4j settings access
├── app/models/intel.py                 # Add image_url, use_legacy, new response fields
├── app/routers/intel.py                # Pass through new fields
```

---

## Task 1: Dependencies & Config

**Files:**
- Modify: `services/intelligence/pyproject.toml:6-20`
- Modify: `services/intelligence/config.py:1-34`
- Test: `services/intelligence/tests/test_workflow.py` (existing, verify still passes)

- [ ] **Step 1: Add new dependencies to pyproject.toml**

In `services/intelligence/pyproject.toml`, add `openai` and `Pillow` to the dependencies list:

```toml
dependencies = [
    "langgraph>=0.3.0",
    "langchain-core>=0.3.0",
    "langchain-community>=0.3.0",
    "langchain-openai>=0.3.0",
    "qdrant-client>=1.13.0",
    "httpx>=0.28.0",
    "structlog>=25.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "neo4j>=5.23",
    "pyyaml>=6.0",
    "openai>=1.40",
    "Pillow>=10.0",
]
```

- [ ] **Step 2: Install dependencies**

Run:
```bash
cd services/intelligence && uv sync
```
Expected: resolves and installs openai + Pillow

- [ ] **Step 3: Add ReAct guard settings to config.py**

In `services/intelligence/config.py`, add after line 21 (`enable_graph_context`):

```python
    # ReAct agent guards
    react_max_tool_calls: int = 8
    react_max_iterations: int = 5
    react_tool_timeout_s: int = 15
    react_total_timeout_s: int = 60
    # Vision
    vision_max_file_size_mb: int = 10
    vision_max_dimension: int = 4096
    vision_download_timeout_s: int = 10
    vision_allowed_local_paths: list[str] = ["/tmp/odin/images/"]
```

- [ ] **Step 4: Run existing tests to verify no breakage**

Run: `cd services/intelligence && uv run pytest tests/ -v`
Expected: all 99 tests pass

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/pyproject.toml services/intelligence/config.py
git commit -m "feat(intelligence): add openai, Pillow deps and ReAct guard config for TASK-105"
```

---

## Task 2: Extended AgentState + Schema Whitelist

**Files:**
- Modify: `services/intelligence/graph/state.py`
- Create: `services/intelligence/graph/schema_whitelist.py`

- [ ] **Step 1: Write test for extended AgentState**

Create assertions in a temporary check — the real tests come in Task 7. For now, verify the state compiles:

```bash
cd services/intelligence && uv run python -c "
from graph.state import AgentState
# Verify new fields exist in annotations
ann = AgentState.__annotations__
assert 'image_url' in ann, 'missing image_url'
assert 'tool_calls_count' in ann, 'missing tool_calls_count'
assert 'tool_trace' in ann, 'missing tool_trace'
assert 'executive_summary' in ann, 'missing executive_summary'
assert 'key_findings' in ann, 'missing key_findings'
print('AgentState OK')
"
```
Expected: FAIL — fields don't exist yet

- [ ] **Step 2: Update AgentState**

Replace `services/intelligence/graph/state.py` with:

```python
"""LangGraph agent state definition."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State shared between all agents in the intelligence pipeline."""

    # Input
    query: str
    image_url: str | None

    # ReAct loop
    messages: Annotated[list[BaseMessage], add_messages]
    tool_calls_count: int
    iteration: int

    # Legacy pipeline (kept for fallback)
    osint_results: list[dict[str, str]]
    analysis: str

    # Output (populated by Synthesis)
    synthesis: str
    executive_summary: str
    key_findings: list[str]
    threat_assessment: str
    confidence: float
    sources_used: list[str]
    agent_chain: list[str]
    tool_trace: list[dict]
    error: str | None
```

- [ ] **Step 3: Run the check again**

Expected: `AgentState OK`

- [ ] **Step 4: Create schema whitelist**

Create `services/intelligence/graph/schema_whitelist.py`:

```python
"""Neo4j schema whitelist for free Cypher generation.

Used in graph_query fallback mode — the LLM prompt includes these
so it only references labels/relationships/properties that exist.
"""

LABELS = ("Entity", "Event", "Source", "Location", "Document")

RELATIONSHIPS = ("INVOLVES", "REPORTED_BY", "OCCURRED_AT", "MENTIONS")

ENTITY_PROPERTIES = (
    "name", "type", "aliases", "confidence",
    "first_seen", "last_seen", "id",
)

EVENT_PROPERTIES = (
    "id", "title", "summary", "timestamp",
    "codebook_type", "severity", "confidence",
)

SOURCE_PROPERTIES = ("url", "name", "last_fetched")

LOCATION_PROPERTIES = ("name", "country", "lat", "lon")

DOCUMENT_PROPERTIES = ("url", "title", "source", "updated_at")


def schema_prompt_block() -> str:
    """Return a text block describing the Neo4j schema for LLM prompts."""
    return f"""\
Neo4j Schema:
  Node labels: {', '.join(LABELS)}
  Relationships: {', '.join(RELATIONSHIPS)}
  Entity properties: {', '.join(ENTITY_PROPERTIES)}
  Event properties: {', '.join(EVENT_PROPERTIES)}
  Source properties: {', '.join(SOURCE_PROPERTIES)}
  Location properties: {', '.join(LOCATION_PROPERTIES)}
  Document properties: {', '.join(DOCUMENT_PROPERTIES)}

Rules:
  - ONLY use labels, relationships, and properties listed above
  - Always include LIMIT (max 100)
  - No semicolons, no write operations
  - Use parameterized values ($param) for user-provided strings"""
```

- [ ] **Step 5: Verify existing tests still pass**

Run: `cd services/intelligence && uv run pytest tests/ -v`
Expected: all 99 tests pass (state backward compat — new fields are optional in TypedDict)

- [ ] **Step 6: Commit**

```bash
git add services/intelligence/graph/state.py services/intelligence/graph/schema_whitelist.py
git commit -m "feat(intelligence): extend AgentState with ReAct fields and add Neo4j schema whitelist"
```

---

## Task 3: Graph Query Templates + Intent Router

**Files:**
- Create: `services/intelligence/agents/tools/graph_templates.py`
- Test: `services/intelligence/tests/test_graph_templates.py`

- [ ] **Step 1: Write failing tests for template selection and LIMIT injection**

Create `services/intelligence/tests/test_graph_templates.py`:

```python
"""Tests for Cypher query templates and intent routing."""

import pytest

from agents.tools.graph_templates import (
    TEMPLATES,
    select_template,
    inject_limit,
    build_cypher_from_template,
)


class TestTemplateRegistry:
    def test_eight_templates_registered(self):
        assert len(TEMPLATES) == 8

    def test_all_templates_have_required_keys(self):
        for tid, t in TEMPLATES.items():
            assert "cypher" in t, f"{tid} missing cypher"
            assert "description" in t, f"{tid} missing description"
            assert "params" in t, f"{tid} missing params"

    def test_all_templates_are_readonly(self):
        from graph.read_queries import validate_cypher_readonly
        for tid, t in TEMPLATES.items():
            assert validate_cypher_readonly(t["cypher"]), f"{tid} failed readonly check"


class TestSelectTemplate:
    def test_entity_lookup_by_exact_match(self):
        result = select_template("entity_lookup", {"name": "PLA SSF"})
        assert result is not None
        cypher, params = result
        assert "$name" in cypher
        assert params["name"] == "PLA SSF"

    def test_unknown_template_returns_none(self):
        result = select_template("nonexistent_template", {})
        assert result is None

    def test_events_by_entity(self):
        result = select_template("events_by_entity", {"name": "Yaogan-44"})
        assert result is not None
        cypher, params = result
        assert "INVOLVES" in cypher
        assert params["name"] == "Yaogan-44"

    def test_top_connected_default_limit(self):
        result = select_template("top_connected", {})
        assert result is not None
        _, params = result
        assert params["limit"] == 20


class TestInjectLimit:
    def test_adds_limit_when_missing(self):
        cypher = "MATCH (n) RETURN n"
        assert "LIMIT 100" in inject_limit(cypher)

    def test_preserves_existing_limit(self):
        cypher = "MATCH (n) RETURN n LIMIT 50"
        result = inject_limit(cypher)
        assert "LIMIT 50" in result
        assert result.count("LIMIT") == 1

    def test_case_insensitive_detection(self):
        cypher = "MATCH (n) RETURN n limit 25"
        result = inject_limit(cypher)
        assert result.count("LIMIT") + result.count("limit") == 1


class TestBuildCypherFromTemplate:
    def test_entity_lookup_fills_params(self):
        cypher, params = build_cypher_from_template("entity_lookup", {"name": "NATO"})
        assert params["name"] == "NATO"
        assert "$name" in cypher

    def test_two_hop_network_has_limit(self):
        cypher, _ = build_cypher_from_template("two_hop_network", {"name": "Iran"})
        assert "LIMIT" in cypher

    def test_invalid_template_raises(self):
        with pytest.raises(KeyError):
            build_cypher_from_template("does_not_exist", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/intelligence && uv run pytest tests/test_graph_templates.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement graph_templates.py**

Create `services/intelligence/agents/tools/graph_templates.py`:

```python
"""Cypher query templates for the graph_query tool.

Template-first approach: 8 predefined queries cover ~90% of use cases.
Each template has parameterized Cypher ($name, $limit etc.) — no string interpolation.
"""

from __future__ import annotations

import re

TEMPLATES: dict[str, dict] = {
    "entity_lookup": {
        "description": "Find an entity by name — returns properties and type",
        "cypher": (
            "MATCH (e:Entity {name: $name}) "
            "RETURN e.name AS name, e.type AS type, e.aliases AS aliases, "
            "e.confidence AS confidence, e.first_seen AS first_seen, e.last_seen AS last_seen"
        ),
        "params": ["name"],
        "defaults": {},
    },
    "one_hop": {
        "description": "Find all entities and events directly connected to an entity",
        "cypher": (
            "MATCH (e:Entity {name: $name})-[r]-(n) "
            "RETURN e.name AS source, type(r) AS relationship, "
            "n.name AS target, labels(n)[0] AS target_type "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 50},
    },
    "two_hop_network": {
        "description": "Find the 2-hop connection network around an entity",
        "cypher": (
            "MATCH path = (e:Entity {name: $name})-[*1..2]-(n) "
            "UNWIND relationships(path) AS r "
            "WITH startNode(r) AS s, type(r) AS rel, endNode(r) AS t "
            "RETURN DISTINCT s.name AS source, rel AS relationship, "
            "t.name AS target, labels(t)[0] AS target_type "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 50},
    },
    "events_by_entity": {
        "description": "Find events involving a specific entity, ordered by time",
        "cypher": (
            "MATCH (e:Entity {name: $name})<-[:INVOLVES]-(ev:Event) "
            "RETURN ev.title AS title, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp, "
            "ev.confidence AS confidence "
            "ORDER BY ev.timestamp DESC "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 20},
    },
    "event_timeline": {
        "description": "Find events at a location or in a region, ordered by time",
        "cypher": (
            "MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location) "
            "WHERE l.name CONTAINS $location OR l.country CONTAINS $location "
            "RETURN ev.title AS title, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp, "
            "l.name AS location, l.country AS country "
            "ORDER BY ev.timestamp DESC "
            "LIMIT $limit"
        ),
        "params": ["location"],
        "defaults": {"limit": 30},
    },
    "co_occurring": {
        "description": "Find entities that co-occur with a given entity in the same events",
        "cypher": (
            "MATCH (e:Entity {name: $name})<-[:INVOLVES]-(ev:Event)-[:INVOLVES]->(other:Entity) "
            "WHERE other.name <> $name "
            "RETURN other.name AS entity, other.type AS type, "
            "count(ev) AS shared_events "
            "ORDER BY shared_events DESC "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 20},
    },
    "source_backed": {
        "description": "Find sources that reported on events involving an entity",
        "cypher": (
            "MATCH (e:Entity {name: $name})<-[:INVOLVES]-(ev:Event)-[:REPORTED_BY]->(s:Source) "
            "RETURN ev.title AS event, s.name AS source, s.url AS url, "
            "ev.timestamp AS timestamp "
            "ORDER BY ev.timestamp DESC "
            "LIMIT $limit"
        ),
        "params": ["name"],
        "defaults": {"limit": 20},
    },
    "top_connected": {
        "description": "Find the most connected entities by relationship count",
        "cypher": (
            "MATCH (e:Entity)-[r]-() "
            "RETURN e.name AS entity, e.type AS type, count(r) AS connections "
            "ORDER BY connections DESC "
            "LIMIT $limit"
        ),
        "params": [],
        "defaults": {"limit": 20},
    },
}


def select_template(
    template_id: str, params: dict
) -> tuple[str, dict] | None:
    """Select a template by ID and merge params with defaults.

    Returns (cypher, merged_params) or None if template_id not found.
    """
    template = TEMPLATES.get(template_id)
    if template is None:
        return None

    merged = dict(template["defaults"])
    merged.update(params)
    return template["cypher"], merged


def build_cypher_from_template(template_id: str, params: dict) -> tuple[str, dict]:
    """Build Cypher from a template. Raises KeyError if template not found."""
    result = select_template(template_id, params)
    if result is None:
        raise KeyError(f"Unknown template: {template_id}")
    return result


def inject_limit(cypher: str, default_limit: int = 100) -> str:
    """Add LIMIT clause if the query doesn't already have one."""
    if re.search(r"\bLIMIT\b", cypher, re.IGNORECASE):
        return cypher
    return f"{cypher.rstrip().rstrip(';')} LIMIT {default_limit}"
```

- [ ] **Step 4: Run tests**

Run: `cd services/intelligence && uv run pytest tests/test_graph_templates.py -v`
Expected: all 15 tests pass

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/agents/tools/graph_templates.py services/intelligence/tests/test_graph_templates.py
git commit -m "feat(intelligence): add 8 Cypher query templates with intent routing for graph_query tool"
```

---

## Task 4: graph_query Tool

**Files:**
- Create: `services/intelligence/agents/tools/graph_query.py`
- Test: `services/intelligence/tests/test_graph_query.py`

- [ ] **Step 1: Write failing tests**

Create `services/intelligence/tests/test_graph_query.py`:

```python
"""Tests for graph_query tool — template routing + free Cypher fallback."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.tools.graph_query import (
    route_to_template,
    execute_graph_query,
    _format_results,
)


class TestRouteToTemplate:
    def test_returns_template_for_known_patterns(self):
        result = route_to_template("entity_lookup", {"name": "NATO"})
        assert result is not None
        assert result["mode"] == "template"
        assert result["template_id"] == "entity_lookup"

    def test_returns_none_for_unknown_pattern(self):
        result = route_to_template("unknown_intent", {})
        assert result is None


class TestFormatResults:
    def test_formats_list_of_dicts(self):
        rows = [
            {"name": "NATO", "type": "organization"},
            {"name": "EU", "type": "organization"},
        ]
        text = _format_results(rows)
        assert "NATO" in text
        assert "EU" in text

    def test_empty_results(self):
        text = _format_results([])
        assert "no results" in text.lower()

    def test_truncates_long_results(self):
        rows = [{"data": "x" * 500} for _ in range(20)]
        text = _format_results(rows, max_rows=5)
        # Should only include 5 rows
        assert text.count("data") <= 6  # header + 5 rows


class TestExecuteGraphQuery:
    @pytest.mark.asyncio
    async def test_template_mode_calls_graph_client(self):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = [{"name": "PLA", "type": "organization"}]

        result = await execute_graph_query(
            template_id="entity_lookup",
            params={"name": "PLA"},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_called_once()
        call_kwargs = mock_client.run_query.call_args
        assert call_kwargs.kwargs.get("read_only") is True
        assert "PLA" in result

    @pytest.mark.asyncio
    async def test_fallback_validates_readonly(self):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = []

        # This should be rejected by validate_cypher_readonly
        result = await execute_graph_query(
            cypher="CREATE (n:Test) RETURN n",
            params={},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_not_called()
        assert "rejected" in result.lower() or "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_fallback_injects_limit(self):
        mock_client = AsyncMock()
        mock_client.run_query.return_value = []

        await execute_graph_query(
            cypher="MATCH (n:Entity) RETURN n",
            params={},
            graph_client=mock_client,
        )

        call_args = mock_client.run_query.call_args
        executed_cypher = call_args.args[0] if call_args.args else call_args.kwargs.get("cypher", "")
        assert "LIMIT" in executed_cypher

    @pytest.mark.asyncio
    async def test_no_graph_client_returns_error(self):
        result = await execute_graph_query(
            template_id="entity_lookup",
            params={"name": "test"},
            graph_client=None,
        )
        assert "not available" in result.lower() or "no graph" in result.lower()

    @pytest.mark.asyncio
    async def test_query_timeout_handled(self):
        mock_client = AsyncMock()
        mock_client.run_query.side_effect = TimeoutError("query timed out")

        result = await execute_graph_query(
            template_id="entity_lookup",
            params={"name": "test"},
            graph_client=mock_client,
        )
        assert "failed" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_semicolon_in_free_cypher_rejected(self):
        mock_client = AsyncMock()

        result = await execute_graph_query(
            cypher="MATCH (n) RETURN n; DROP INDEX foo",
            params={},
            graph_client=mock_client,
        )

        mock_client.run_query.assert_not_called()
        assert "rejected" in result.lower() or "blocked" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/intelligence && uv run pytest tests/test_graph_query.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement graph_query.py**

Create `services/intelligence/agents/tools/graph_query.py`:

```python
"""graph_query tool — NL→Cypher via templates with free Cypher fallback.

Template-first: route_to_template picks a predefined query.
Fallback: LLM-generated Cypher, guarded by validate_cypher_readonly + LIMIT injection.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from langchain_core.tools import tool

from agents.tools.graph_templates import (
    TEMPLATES,
    build_cypher_from_template,
    inject_limit,
    select_template,
)
from graph.read_queries import validate_cypher_readonly

log = structlog.get_logger(__name__)

# Lazy singleton — set by the workflow before agent invocation
_graph_client = None


def set_graph_client(client: Any) -> None:
    """Set the module-level GraphClient for the tool to use."""
    global _graph_client
    _graph_client = client


def route_to_template(
    template_id: str, params: dict
) -> dict | None:
    """Try to select a template. Returns routing metadata or None."""
    result = select_template(template_id, params)
    if result is None:
        return None
    cypher, merged_params = result
    return {
        "mode": "template",
        "template_id": template_id,
        "cypher": cypher,
        "params": merged_params,
    }


async def execute_graph_query(
    template_id: str | None = None,
    cypher: str | None = None,
    params: dict | None = None,
    graph_client: Any = None,
) -> str:
    """Execute a graph query via template or free Cypher.

    Args:
        template_id: If set, use this template with params.
        cypher: If set (and no template_id), use as free Cypher (validated).
        params: Query parameters.
        graph_client: Neo4j GraphClient instance. Falls back to module-level.

    Returns:
        Formatted text result for the agent.
    """
    client = graph_client or _graph_client
    if client is None:
        return "Graph database not available. Cannot query knowledge graph."

    params = params or {}
    start = time.monotonic()
    mode = "template"
    tid = template_id

    try:
        if template_id:
            query_cypher, merged_params = build_cypher_from_template(template_id, params)
        elif cypher:
            mode = "fallback"
            tid = None
            # Guard 1: readonly validation
            if not validate_cypher_readonly(cypher):
                log.warning("graph_query_rejected", cypher=cypher[:200], reason="readonly_check")
                return "Query rejected: contains write operations or unsafe patterns."
            # Guard 2: inject LIMIT if missing
            query_cypher = inject_limit(cypher)
            merged_params = params
        else:
            return "No query specified. Provide a template_id or cypher string."

        rows = await client.run_query(query_cypher, merged_params, read_only=True)
        duration_ms = int((time.monotonic() - start) * 1000)

        log.info(
            "graph_query_executed",
            mode=mode,
            template_id=tid,
            duration_ms=duration_ms,
            result_count=len(rows),
        )

        return _format_results(rows)

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.warning("graph_query_failed", mode=mode, template_id=tid, error=str(e), duration_ms=duration_ms)
        return f"Graph query failed: {e}"


def _format_results(rows: list[dict], max_rows: int = 15) -> str:
    """Format Neo4j result rows as readable text for the agent."""
    if not rows:
        return "No results found in the knowledge graph."

    truncated = rows[:max_rows]
    lines = []
    for row in truncated:
        parts = [f"{k}: {v}" for k, v in row.items() if v is not None]
        lines.append("  " + " | ".join(parts))

    result = "[Knowledge Graph Results]\n" + "\n".join(lines)
    if len(rows) > max_rows:
        result += f"\n  ... ({len(rows) - max_rows} more rows)"
    return result


@tool
async def query_knowledge_graph(question: str) -> str:
    """Query the Neo4j knowledge graph. Use for entity relationships,
    event timelines, connection networks, and co-occurrence analysis.

    Args:
        question: Natural language question about entities or events.
    """
    # For now, use a simple keyword-based template matcher.
    # Phase 2 will add LLM-based intent classification.
    template_id, params = _match_intent(question)

    if template_id:
        return await execute_graph_query(template_id=template_id, params=params)
    else:
        # No template matched — fallback to LLM-generated Cypher
        return await _free_cypher_fallback(question)


def _match_intent(question: str) -> tuple[str | None, dict]:
    """Simple keyword-based intent matching. Returns (template_id, params) or (None, {})."""
    q = question.lower().strip()

    # Extract quoted entity names or capitalize words as entity candidates
    import re
    quoted = re.findall(r'"([^"]+)"', question)
    entity = quoted[0] if quoted else ""

    # If no quoted entity, try to find a proper noun (capitalized word not at start)
    if not entity:
        words = question.split()
        proper_nouns = [w for w in words[1:] if w[0].isupper()] if len(words) > 1 else []
        entity = " ".join(proper_nouns) if proper_nouns else ""

    if any(kw in q for kw in ("most connected", "top entities", "most important", "highest degree")):
        return "top_connected", {}

    if any(kw in q for kw in ("timeline", "events in", "events at")):
        location = entity or question.split("in ")[-1].split("at ")[-1].strip(" ?.")
        return "event_timeline", {"location": location}

    if any(kw in q for kw in ("co-occur", "appear together", "related entities", "co-occurring")):
        if entity:
            return "co_occurring", {"name": entity}

    if any(kw in q for kw in ("sources for", "evidence", "reported by", "source")):
        if entity:
            return "source_backed", {"name": entity}

    if any(kw in q for kw in ("events involving", "events about", "events for")):
        if entity:
            return "events_by_entity", {"name": entity}

    if any(kw in q for kw in ("network", "2-hop", "connections around")):
        if entity:
            return "two_hop_network", {"name": entity}

    if any(kw in q for kw in ("connected to", "related to", "neighbors of", "linked to")):
        if entity:
            return "one_hop", {"name": entity}

    if any(kw in q for kw in ("who is", "what is", "find entity", "look up")):
        if entity:
            return "entity_lookup", {"name": entity}

    # Generic entity query — if we have an entity name, try entity_lookup
    if entity:
        return "entity_lookup", {"name": entity}

    return None, {}


async def _free_cypher_fallback(question: str) -> str:
    """Generate Cypher via LLM when no template matches.

    Uses schema whitelist in prompt, validates output through all safety layers.
    """
    from graph.schema_whitelist import schema_prompt_block

    try:
        from openai import AsyncOpenAI
        from config import settings

        client = AsyncOpenAI(base_url=settings.llm_base_url, api_key="not-needed")
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": (
                    "You are a Cypher query generator for Neo4j. "
                    "Generate a single READ-ONLY Cypher query to answer the user's question.\n\n"
                    f"{schema_prompt_block()}\n\n"
                    "Return ONLY the Cypher query, no explanation."
                )},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=300,
        )
        cypher = (response.choices[0].message.content or "").strip()
        if not cypher:
            return f"Could not generate a graph query for: '{question}'."

        return await execute_graph_query(cypher=cypher, params={})

    except Exception as e:
        log.warning("free_cypher_fallback_failed", error=str(e))
        return f"Graph query generation failed: {e}"
```

- [ ] **Step 4: Run tests**

Run: `cd services/intelligence && uv run pytest tests/test_graph_query.py -v`
Expected: all 10 tests pass

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/agents/tools/graph_query.py services/intelligence/tests/test_graph_query.py
git commit -m "feat(intelligence): add graph_query tool with template routing and fallback guards"
```

---

## Task 5: classify Tool

**Files:**
- Create: `services/intelligence/agents/tools/classify.py`
- Test: `services/intelligence/tests/test_classify.py`

- [ ] **Step 1: Write failing tests**

Create `services/intelligence/tests/test_classify.py`:

```python
"""Tests for classify_event tool."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.tools.classify import classify_event, _format_extraction_result
from codebook.extractor import IntelligenceExtractionResult, ExtractedEventRaw, ExtractedEntityRaw


class TestFormatExtractionResult:
    def test_formats_events_and_entities(self):
        result = IntelligenceExtractionResult(
            events=[ExtractedEventRaw(
                title="Missile Test",
                codebook_type="military.weapons_test",
                severity="high",
                confidence=0.9,
            )],
            entities=[ExtractedEntityRaw(
                name="North Korea",
                type="organization",
                confidence=0.8,
            )],
            locations=[],
        )
        text = _format_extraction_result(result)
        assert "Missile Test" in text
        assert "military.weapons_test" in text
        assert "North Korea" in text

    def test_empty_result(self):
        result = IntelligenceExtractionResult()
        text = _format_extraction_result(result)
        assert "no events" in text.lower()

    def test_multiple_events_formatted(self):
        result = IntelligenceExtractionResult(
            events=[
                ExtractedEventRaw(title="Event A", codebook_type="military.airstrike", severity="high", confidence=0.8),
                ExtractedEventRaw(title="Event B", codebook_type="political.sanctions_imposed", severity="medium", confidence=0.7),
            ],
        )
        text = _format_extraction_result(result)
        assert "Event A" in text
        assert "Event B" in text


class TestClassifyEventTool:
    @pytest.mark.asyncio
    async def test_empty_text_returns_message(self):
        result = await classify_event.ainvoke({"text": "", "context": ""})
        assert "provide text" in result.lower() or "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_text_too_long_gets_truncated(self):
        """The tool should not crash on long text — extractor handles truncation."""
        long_text = "A " * 5000
        with patch("agents.tools.classify._get_extractor") as mock_get:
            mock_extractor = AsyncMock()
            mock_extractor.extract.return_value = IntelligenceExtractionResult()
            mock_get.return_value = mock_extractor

            result = await classify_event.ainvoke({"text": long_text, "context": ""})
            mock_extractor.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_extractor_failure_returns_error(self):
        with patch("agents.tools.classify._get_extractor") as mock_get:
            mock_extractor = AsyncMock()
            mock_extractor.extract.side_effect = Exception("LLM down")
            mock_get.return_value = mock_extractor

            result = await classify_event.ainvoke({"text": "some text", "context": ""})
            assert "failed" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/intelligence && uv run pytest tests/test_classify.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement classify.py**

Create `services/intelligence/agents/tools/classify.py`:

```python
"""classify_event tool — on-demand event classification via IntelligenceExtractor."""

from __future__ import annotations

import structlog
from langchain_core.tools import tool

from codebook.extractor import IntelligenceExtractor, IntelligenceExtractionResult
from config import settings

log = structlog.get_logger(__name__)

_extractor: IntelligenceExtractor | None = None


def _get_extractor() -> IntelligenceExtractor:
    """Lazy-init the IntelligenceExtractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = IntelligenceExtractor(
            vllm_url=settings.vllm_url,
            vllm_model=settings.vllm_model,
        )
    return _extractor


def _format_extraction_result(result: IntelligenceExtractionResult) -> str:
    """Format extraction result as readable text for the agent."""
    if not result.events and not result.entities:
        return "No events or entities detected in the provided text."

    lines = []
    if result.events:
        lines.append("[Classified Events]")
        for ev in result.events:
            lines.append(
                f"  - {ev.title} | type: {ev.codebook_type} | "
                f"severity: {ev.severity} | confidence: {ev.confidence:.1f}"
            )
            if ev.summary:
                lines.append(f"    {ev.summary}")

    if result.entities:
        lines.append("[Extracted Entities]")
        for ent in result.entities:
            lines.append(f"  - {ent.name} ({ent.type}, confidence: {ent.confidence:.1f})")

    if result.locations:
        lines.append("[Locations]")
        for loc in result.locations:
            lines.append(f"  - {loc.name}, {loc.country}")

    return "\n".join(lines)


@tool
async def classify_event(text: str, context: str = "") -> str:
    """Classify a piece of text using the intelligence event codebook.
    Returns event type, severity, confidence, and extracted entities.

    Args:
        text: The text to classify (headline, paragraph, or article).
        context: Optional context about the source or region.
    """
    if not text or not text.strip():
        return "Please provide text to classify."

    try:
        extractor = _get_extractor()
        result = await extractor.extract(text=text, source_url=context)
        return _format_extraction_result(result)
    except Exception as e:
        log.warning("classify_event_failed", error=str(e))
        return f"Classification failed: {e}"
```

- [ ] **Step 4: Run tests**

Run: `cd services/intelligence && uv run pytest tests/test_classify.py -v`
Expected: all 6 tests pass

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/agents/tools/classify.py services/intelligence/tests/test_classify.py
git commit -m "feat(intelligence): add classify_event tool wrapping IntelligenceExtractor"
```

---

## Task 6: Vision Tool

**Files:**
- Create: `services/intelligence/agents/tools/vision.py`
- Test: `services/intelligence/tests/test_vision.py`

- [ ] **Step 1: Write failing tests**

Create `services/intelligence/tests/test_vision.py`:

```python
"""Tests for vision tool — URL validation, SSRF protection, image analysis."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.tools.vision import (
    validate_image_url,
    _is_private_ip,
    analyze_image,
)


class TestUrlValidation:
    def test_https_allowed(self):
        assert validate_image_url("https://example.com/image.jpg") is True

    def test_http_rejected(self):
        assert validate_image_url("http://example.com/image.jpg") is False

    def test_whitelisted_local_path(self):
        assert validate_image_url("/tmp/odin/images/sat.png") is True

    def test_non_whitelisted_local_path(self):
        assert validate_image_url("/etc/passwd") is False

    def test_empty_url_rejected(self):
        assert validate_image_url("") is False

    def test_ftp_rejected(self):
        assert validate_image_url("ftp://files.com/image.png") is False

    def test_data_url_rejected(self):
        assert validate_image_url("data:image/png;base64,abc") is False


class TestPrivateIpDetection:
    def test_localhost_is_private(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_ten_range_is_private(self):
        assert _is_private_ip("10.0.0.5") is True

    def test_172_range_is_private(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_192_range_is_private(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_public_ip_not_private(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_invalid_ip_treated_as_not_private(self):
        assert _is_private_ip("not-an-ip") is False


class TestAnalyzeImageTool:
    @pytest.mark.asyncio
    async def test_rejects_http_url(self):
        result = await analyze_image.ainvoke({
            "image_url": "http://evil.com/img.jpg",
            "question": "what is this",
        })
        assert "rejected" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_private_path(self):
        result = await analyze_image.ainvoke({
            "image_url": "/etc/shadow",
            "question": "what is this",
        })
        assert "rejected" in result.lower() or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_download_error(self):
        with patch("agents.tools.vision._download_image") as mock_dl:
            mock_dl.side_effect = Exception("Connection refused")

            result = await analyze_image.ainvoke({
                "image_url": "https://example.com/img.jpg",
                "question": "describe this",
            })
            assert "failed" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/intelligence && uv run pytest tests/test_vision.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement vision.py**

Create `services/intelligence/agents/tools/vision.py`:

```python
"""analyze_image tool — Qwen3.5 multimodal vision via vLLM.

Security: URL validation, SSRF protection, size/dimension limits.
"""

from __future__ import annotations

import base64
import ipaddress
import socket
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
import structlog
from langchain_core.tools import tool
from PIL import Image

from config import settings

log = structlog.get_logger(__name__)


def validate_image_url(url: str) -> bool:
    """Check if URL is safe: https:// or whitelisted local path."""
    if not url:
        return False

    # Local file path
    if url.startswith("/"):
        return any(url.startswith(p) for p in settings.vision_allowed_local_paths)

    # Only HTTPS
    parsed = urlparse(url)
    return parsed.scheme == "https"


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_private or addr.is_loopback or addr.is_reserved
    except ValueError:
        return False


async def _download_image(url: str) -> bytes:
    """Download image with SSRF protection and size limits."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Resolve hostname and check for private IPs
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved_ips:
            ip = sockaddr[0]
            if _is_private_ip(ip):
                raise ValueError(f"URL resolves to private IP: {ip}")
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    max_size = settings.vision_max_file_size_mb * 1024 * 1024

    async with httpx.AsyncClient(
        timeout=settings.vision_download_timeout_s,
        follow_redirects=False,
    ) as client:
        # HEAD check for content type
        head_resp = await client.head(url)
        content_type = head_resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"Not an image: content-type={content_type}")

        content_length = int(head_resp.headers.get("content-length", 0))
        if content_length > max_size:
            raise ValueError(f"Image too large: {content_length} bytes (max {max_size})")

        # Download
        resp = await client.get(url)
        resp.raise_for_status()

        if len(resp.content) > max_size:
            raise ValueError(f"Image too large: {len(resp.content)} bytes")

        return resp.content


def _validate_dimensions(image_bytes: bytes) -> None:
    """Check image dimensions are within limits."""
    img = Image.open(BytesIO(image_bytes))
    w, h = img.size
    max_dim = settings.vision_max_dimension
    if w > max_dim or h > max_dim:
        raise ValueError(f"Image dimensions {w}x{h} exceed max {max_dim}x{max_dim}")


async def _load_image(url: str) -> str:
    """Load image from URL or local path and return base64 data URL."""
    if url.startswith("/"):
        # Local file
        path = Path(url)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {url}")
        image_bytes = path.read_bytes()
    else:
        image_bytes = await _download_image(url)

    max_size = settings.vision_max_file_size_mb * 1024 * 1024
    if len(image_bytes) > max_size:
        raise ValueError(f"Image too large: {len(image_bytes)} bytes")

    _validate_dimensions(image_bytes)

    b64 = base64.b64encode(image_bytes).decode()
    # Detect format from bytes
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        mime = "image/png"
    elif image_bytes[:2] == b'\xff\xd8':
        mime = "image/jpeg"
    else:
        mime = "image/png"  # default

    return f"data:{mime};base64,{b64}"


@tool
async def analyze_image(
    image_url: str,
    question: str = "Describe this image in detail. Identify objects, text, locations, and any intelligence-relevant features.",
) -> str:
    """Analyze an image using Qwen3.5 multimodal vision.
    Use for satellite imagery, document photos, maps, or any visual content.

    Args:
        image_url: HTTPS URL or whitelisted local path to the image.
        question: Specific question about the image content.
    """
    if not validate_image_url(image_url):
        return (
            f"Image URL rejected: '{image_url}'. "
            "Only HTTPS URLs or whitelisted local paths are allowed."
        )

    try:
        data_url = await _load_image(image_url)
    except Exception as e:
        log.warning("vision_image_load_failed", url=image_url[:200], error=str(e))
        return f"Failed to load image: {e}"

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key="not-needed",
        )

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": question},
                ],
            }],
            max_tokens=1000,
            temperature=0.2,
        )

        return response.choices[0].message.content or "No analysis returned."

    except Exception as e:
        log.warning("vision_analysis_failed", url=image_url[:200], error=str(e))
        return f"Image analysis failed: {e}"
```

- [ ] **Step 4: Run tests**

Run: `cd services/intelligence && uv run pytest tests/test_vision.py -v`
Expected: all 13 tests pass

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/agents/tools/vision.py services/intelligence/tests/test_vision.py
git commit -m "feat(intelligence): add analyze_image tool with SSRF protection and dimension validation"
```

---

## Task 7: ReAct Agent + Updated Workflow

**Files:**
- Create: `services/intelligence/agents/react_agent.py`
- Modify: `services/intelligence/graph/workflow.py`
- Modify: `services/intelligence/agents/tools/__init__.py`
- Delete: `services/intelligence/agents/tools/web_search.py`
- Test: `services/intelligence/tests/test_react_agent.py`

- [ ] **Step 1: Write failing tests**

Create `services/intelligence/tests/test_react_agent.py`:

```python
"""Tests for ReAct agent workflow — tool binding, guards, fallback."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.react_agent import (
    REACT_SYSTEM_PROMPT,
    create_react_agent,
    should_continue,
    guard_check,
)
from graph.state import AgentState


class TestSystemPrompt:
    def test_mentions_all_tools(self):
        prompt = REACT_SYSTEM_PROMPT
        assert "qdrant_search" in prompt
        assert "query_knowledge_graph" in prompt
        assert "classify_event" in prompt
        assert "analyze_image" in prompt
        assert "gdelt_query" in prompt
        assert "rss_fetch" in prompt

    def test_includes_tool_budget(self):
        assert "8" in REACT_SYSTEM_PROMPT or "max" in REACT_SYSTEM_PROMPT.lower()


class TestGuardCheck:
    def test_under_limit_continues(self):
        state: AgentState = {
            "query": "test",
            "image_url": None,
            "messages": [],
            "tool_calls_count": 3,
            "iteration": 2,
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "executive_summary": "",
            "key_findings": [],
            "threat_assessment": "",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": [],
            "tool_trace": [],
            "error": None,
        }
        assert guard_check(state) == "continue"

    def test_tool_calls_exceeded_stops(self):
        state: AgentState = {
            "query": "test",
            "image_url": None,
            "messages": [],
            "tool_calls_count": 9,
            "iteration": 2,
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "executive_summary": "",
            "key_findings": [],
            "threat_assessment": "",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": [],
            "tool_trace": [],
            "error": None,
        }
        assert guard_check(state) == "stop"

    def test_iterations_exceeded_stops(self):
        state: AgentState = {
            "query": "test",
            "image_url": None,
            "messages": [],
            "tool_calls_count": 2,
            "iteration": 6,
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "executive_summary": "",
            "key_findings": [],
            "threat_assessment": "",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": [],
            "tool_trace": [],
            "error": None,
        }
        assert guard_check(state) == "stop"


class TestShouldContinue:
    def test_no_tool_calls_goes_to_synthesis(self):
        """If the last message has no tool_calls, agent is done thinking."""
        mock_msg = MagicMock()
        mock_msg.tool_calls = []
        state: AgentState = {
            "query": "test",
            "image_url": None,
            "messages": [mock_msg],
            "tool_calls_count": 1,
            "iteration": 1,
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "executive_summary": "",
            "key_findings": [],
            "threat_assessment": "",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": [],
            "tool_trace": [],
            "error": None,
        }
        assert should_continue(state) == "synthesis"

    def test_has_tool_calls_continues(self):
        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "semantic_search", "args": {}}]
        state: AgentState = {
            "query": "test",
            "image_url": None,
            "messages": [mock_msg],
            "tool_calls_count": 1,
            "iteration": 1,
            "osint_results": [],
            "analysis": "",
            "synthesis": "",
            "executive_summary": "",
            "key_findings": [],
            "threat_assessment": "",
            "confidence": 0.0,
            "sources_used": [],
            "agent_chain": [],
            "tool_trace": [],
            "error": None,
        }
        assert should_continue(state) == "tools"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/intelligence && uv run pytest tests/test_react_agent.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Update tools/__init__.py**

Replace `services/intelligence/agents/tools/__init__.py`:

```python
from agents.tools.gdelt_query import gdelt_query
from agents.tools.qdrant_search import qdrant_search
from agents.tools.rss_fetch import rss_fetch
from agents.tools.graph_query import query_knowledge_graph
from agents.tools.classify import classify_event
from agents.tools.vision import analyze_image

ALL_TOOLS = [
    qdrant_search,
    query_knowledge_graph,
    classify_event,
    analyze_image,
    gdelt_query,
    rss_fetch,
]
```

- [ ] **Step 4: Delete web_search.py stub**

```bash
rm services/intelligence/agents/tools/web_search.py
```

- [ ] **Step 5: Implement react_agent.py**

Create `services/intelligence/agents/react_agent.py`:

```python
"""ReAct research agent — LLM with bind_tools for autonomous tool selection.

Uses Qwen3.5-27B-AWQ via vLLM with LangChain's tool calling interface.
Guard logic enforces max_tool_calls and max_iterations.
"""

from __future__ import annotations

import structlog
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from agents.tools import ALL_TOOLS
from config import settings
from graph.state import AgentState

log = structlog.get_logger(__name__)

REACT_SYSTEM_PROMPT = f"""\
You are a geopolitical intelligence analyst with access to specialized tools.

Your job is to answer intelligence queries by gathering information from
multiple sources, analyzing patterns, and identifying threats.

Available tools:
- qdrant_search: Search the intelligence knowledge base (Qdrant RAG with reranking + graph context)
- query_knowledge_graph: Query entity relationships and event timelines (Neo4j)
- classify_event: Classify text using the intelligence event codebook
- analyze_image: Analyze images (satellite, documents, maps) — only if image provided
- gdelt_query: Search recent global events via GDELT
- rss_fetch: Fetch articles from RSS feeds

Guidelines:
- Start with qdrant_search or query_knowledge_graph for existing intelligence
- Use gdelt_query for recent/breaking events not yet in the knowledge base
- Use classify_event when you need to categorize an event precisely
- Use analyze_image ONLY when an image URL is provided in the query
- Cross-reference findings from multiple sources when possible
- Stop when you have sufficient evidence — do not use tools unnecessarily
- Maximum {settings.react_max_tool_calls} tool calls allowed
"""


def create_react_agent() -> ChatOpenAI:
    """Create the ReAct agent LLM with tools bound."""
    llm = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key="not-needed",
        model=settings.llm_model,
        temperature=0.3,
        max_tokens=2000,
    )
    return llm.bind_tools(ALL_TOOLS)


def guard_check(state: AgentState) -> str:
    """Check if ReAct guards have been exceeded.

    Returns 'continue' or 'stop'.
    """
    if state.get("tool_calls_count", 0) >= settings.react_max_tool_calls:
        log.warning("react_guard_tool_limit", count=state["tool_calls_count"])
        return "stop"
    if state.get("iteration", 0) >= settings.react_max_iterations:
        log.warning("react_guard_iteration_limit", iteration=state["iteration"])
        return "stop"
    return "continue"


def should_continue(state: AgentState) -> str:
    """Decide whether to execute tools, go to synthesis, or stop.

    Returns 'tools', 'synthesis', or 'synthesis' (on guard breach).
    """
    # Guard check first
    if guard_check(state) == "stop":
        return "synthesis"

    # Check if the last message has tool calls
    messages = state.get("messages", [])
    if not messages:
        return "synthesis"

    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "synthesis"
```

- [ ] **Step 6: Run tests**

Run: `cd services/intelligence && uv run pytest tests/test_react_agent.py -v`
Expected: all 7 tests pass

- [ ] **Step 7: Update workflow.py**

Replace `services/intelligence/graph/workflow.py`:

```python
"""LangGraph workflow — ReAct agent + deterministic synthesis with legacy fallback."""

import asyncio
from datetime import datetime, timezone

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agents.react_agent import (
    REACT_SYSTEM_PROMPT,
    create_react_agent,
    should_continue,
)
from agents.tools import ALL_TOOLS
from agents.tools.graph_query import set_graph_client
from agents.synthesis_agent import create_synthesis_llm, get_system_message as synthesis_sys
from graph.client import GraphClient
from graph.nodes import analyst_node, osint_node, router_node, synthesis_node as legacy_synthesis_node
from graph.state import AgentState

logger = structlog.get_logger()


# ── ReAct Node Functions ──────────────────────────────────────────────────────

async def react_agent_node(state: AgentState) -> dict:
    """ReAct agent node — invokes LLM with tools bound."""
    logger.info("react_agent_node", iteration=state.get("iteration", 0))

    try:
        llm = create_react_agent()

        # Build initial messages if first iteration
        if state.get("iteration", 0) == 0:
            query = state["query"]
            image_note = ""
            if state.get("image_url"):
                image_note = f"\n\nAn image has been provided for analysis: {state['image_url']}"

            initial_messages = [
                SystemMessage(content=REACT_SYSTEM_PROMPT),
                HumanMessage(content=f"{query}{image_note}"),
            ]
            messages = list(state.get("messages", [])) + initial_messages
        else:
            messages = list(state.get("messages", []))

        response = await llm.ainvoke(messages)

        # Count tool calls in this response
        new_tool_calls = len(response.tool_calls) if hasattr(response, "tool_calls") else 0

        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
            "tool_calls_count": state.get("tool_calls_count", 0) + new_tool_calls,
            "agent_chain": state.get("agent_chain", []) + ["react_agent"],
        }

    except Exception as e:
        logger.error("react_agent_failed", error=str(e))
        return {
            "error": f"ReAct agent failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["react_agent"],
            "iteration": state.get("iteration", 0) + 1,
        }


async def react_synthesis_node(state: AgentState) -> dict:
    """Deterministic synthesis node — produces structured intelligence report."""
    logger.info("react_synthesis_node")

    try:
        llm = create_synthesis_llm()

        # Collect all tool results from messages
        tool_results = []
        for msg in state.get("messages", []):
            if hasattr(msg, "content") and msg.type == "tool":
                tool_results.append(msg.content if isinstance(msg.content, str) else str(msg.content))

        research_text = "\n\n---\n\n".join(tool_results) if tool_results else "No research results collected."

        messages = [
            synthesis_sys(),
            HumanMessage(
                content=(
                    f"Synthesize a final intelligence report.\n\n"
                    f"Query: {state['query']}\n\n"
                    f"Research Findings:\n{research_text}\n\n"
                    "Produce a concise, actionable intelligence report with:\n"
                    "1. Executive Summary (2-3 sentences)\n"
                    "2. Key Findings (bullet list)\n"
                    "3. Threat Assessment (CRITICAL/HIGH/ELEVATED/MODERATE)\n"
                    "4. Confidence Level (high/moderate/low)\n"
                    "5. Recommended Actions"
                ),
            ),
        ]
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Extract threat level
        threat = "MODERATE"
        for level in ["CRITICAL", "HIGH", "ELEVATED"]:
            if level in content.upper():
                threat = level
                break

        # Extract confidence
        confidence = 0.5
        if "high confidence" in content.lower():
            confidence = 0.8
        elif "moderate confidence" in content.lower():
            confidence = 0.6
        elif "low confidence" in content.lower():
            confidence = 0.3

        return {
            "synthesis": content,
            "threat_assessment": threat,
            "confidence": confidence,
            "agent_chain": state.get("agent_chain", []) + ["synthesis"],
            "messages": [response],
        }

    except Exception as e:
        logger.error("react_synthesis_failed", error=str(e))
        return {
            "synthesis": f"Synthesis failed: {e}",
            "threat_assessment": "MODERATE",
            "confidence": 0.0,
            "error": f"Synthesis failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["synthesis"],
        }


# ── Graph Builders ────────────────────────────────────────────────────────────

def build_react_graph() -> StateGraph:
    """Build the ReAct agent workflow."""
    graph = StateGraph(AgentState)

    graph.add_node("react_agent", react_agent_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("synthesis", react_synthesis_node)

    graph.set_entry_point("react_agent")
    graph.add_conditional_edges(
        "react_agent",
        should_continue,
        {
            "tools": "tools",
            "synthesis": "synthesis",
        },
    )
    graph.add_edge("tools", "react_agent")
    graph.add_edge("synthesis", END)

    return graph


def build_legacy_graph() -> StateGraph:
    """Build the legacy linear pipeline (fallback)."""
    graph = StateGraph(AgentState)

    graph.add_node("osint", osint_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("synthesis", legacy_synthesis_node)

    graph.set_entry_point("osint")
    graph.add_conditional_edges(
        "osint",
        router_node,
        {"more_research": "osint", "continue": "analyst"},
    )
    graph.add_edge("analyst", "synthesis")
    graph.add_edge("synthesis", END)

    return graph


# Compile both graphs
react_graph = build_react_graph().compile()
legacy_graph = build_legacy_graph().compile()

# ── Neo4j Lifecycle (lazy singleton) ──────────────────────────────────────────

_graph_client: GraphClient | None = None


def _ensure_graph_client() -> None:
    """Initialize the shared GraphClient singleton on first use."""
    global _graph_client
    if _graph_client is not None:
        return
    from config import settings
    try:
        _graph_client = GraphClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        set_graph_client(_graph_client)
        logger.info("graph_client_initialized")
    except Exception as e:
        logger.warning("graph_client_init_failed", error=str(e))


async def shutdown_graph_client() -> None:
    """Close the shared GraphClient. Call from FastAPI shutdown / atexit."""
    global _graph_client
    if _graph_client is not None:
        await _graph_client.close()
        _graph_client = None
        set_graph_client(None)
        logger.info("graph_client_closed")


async def run_intelligence_query(
    query: str,
    region: str | None = None,
    image_url: str | None = None,
    use_legacy: bool = False,
) -> dict:
    """Run intelligence analysis — ReAct by default, legacy as fallback.

    Args:
        query: The intelligence query.
        region: Optional region filter.
        image_url: Optional image URL for vision analysis.
        use_legacy: Force legacy pipeline.

    Returns:
        Dictionary with analysis results.
    """
    mode = "legacy" if use_legacy else "react"
    logger.info("intelligence_query_started", query=query, region=region, mode=mode)

    # Wire Neo4j client for graph_query tool (lazy singleton)
    _ensure_graph_client()

    initial_state: AgentState = {
        "query": query,
        "image_url": image_url,
        "messages": [],
        "tool_calls_count": 0,
        "iteration": 0,
        "osint_results": [],
        "analysis": "",
        "synthesis": "",
        "executive_summary": "",
        "key_findings": [],
        "threat_assessment": "",
        "confidence": 0.0,
        "sources_used": [],
        "agent_chain": [],
        "tool_trace": [],
        "error": None,
    }

    try:
        if use_legacy:
            result = await legacy_graph.ainvoke(initial_state)
        else:
            result = await asyncio.wait_for(
                react_graph.ainvoke(initial_state),
                timeout=60,
            )
    except (asyncio.TimeoutError, Exception) as e:
        if not use_legacy:
            logger.warning("react_fallback_to_legacy", error=str(e))
            try:
                result = await legacy_graph.ainvoke(initial_state)
                mode = "legacy_fallback"
            except Exception as legacy_err:
                logger.error("legacy_fallback_also_failed", error=str(legacy_err))
                return {
                    "query": query,
                    "analysis": f"Both ReAct and legacy pipelines failed: {e} / {legacy_err}",
                    "threat_assessment": "MODERATE",
                    "confidence": 0.0,
                    "sources_used": [],
                    "agent_chain": ["error"],
                    "tool_trace": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode": "error",
                }
        else:
            return {
                "query": query,
                "analysis": f"Legacy pipeline failed: {e}",
                "threat_assessment": "MODERATE",
                "confidence": 0.0,
                "sources_used": [],
                "agent_chain": ["error"],
                "tool_trace": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "error",
            }

    return {
        "query": query,
        "agent_chain": result.get("agent_chain", []),
        "sources_used": result.get("sources_used", []),
        "analysis": result.get("synthesis", result.get("analysis", "")),
        "confidence": result.get("confidence", 0.0),
        "threat_assessment": result.get("threat_assessment", "MODERATE"),
        "tool_trace": result.get("tool_trace", []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
    }


if __name__ == "__main__":
    async def main() -> None:
        result = await run_intelligence_query(
            "Current situation in the Taiwan Strait"
        )
        print(f"Query: {result['query']}")
        print(f"Mode: {result['mode']}")
        print(f"Agent Chain: {' → '.join(result['agent_chain'])}")
        print(f"Threat: {result['threat_assessment']}")
        print(f"Confidence: {result['confidence']}")
        print(f"\nAnalysis:\n{result['analysis']}")

    asyncio.run(main())
```

- [ ] **Step 8: Update main.py**

Replace `services/intelligence/main.py`:

```python
"""Intelligence service FastAPI app — exposes LangGraph pipeline over HTTP."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from pydantic import BaseModel, Field

from graph.workflow import run_intelligence_query, shutdown_graph_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await shutdown_graph_client()


app = FastAPI(title="WorldView Intelligence Service", version="0.2.0", lifespan=lifespan)


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    region: str | None = None
    image_url: str | None = None
    use_legacy: bool = False


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/query")
async def query_intelligence(req: QueryRequest) -> dict:
    """Run intelligence pipeline and return full analysis result."""
    return await run_intelligence_query(
        req.query,
        req.region,
        req.image_url,
        req.use_legacy,
    )
```

- [ ] **Step 9: Run all tests**

Run: `cd services/intelligence && uv run pytest tests/ -v`
Expected: all tests pass (existing 99 + new ~51 = ~150)

- [ ] **Step 10: Commit**

```bash
git add services/intelligence/agents/ services/intelligence/graph/workflow.py services/intelligence/main.py
git rm services/intelligence/agents/tools/web_search.py
git commit -m "feat(intelligence): implement ReAct agent workflow with tool binding, guards, and legacy fallback"
```

---

## Task 8: Backend Graph Router

**Files:**
- Create: `services/backend/app/models/graph.py`
- Create: `services/backend/app/routers/graph.py`
- Modify: `services/backend/app/main.py:14,67-73`
- Modify: `services/backend/app/models/intel.py:11-14,28-35`
- Modify: `services/backend/app/routers/intel.py:44-46`
- Test: `services/backend/tests/unit/test_graph_router.py`

- [ ] **Step 1: Write failing tests**

Create `services/backend/tests/unit/test_graph_router.py`:

```python
"""Tests for graph router — REST endpoints for Neo4j graph exploration."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app


class TestGraphEndpoints:
    """Test graph router endpoints with mocked Neo4j."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_entity_not_found(self, client):
        with patch("app.routers.graph._get_graph_client") as mock:
            mock_client = AsyncMock()
            mock_client.run_query.return_value = []
            mock.return_value = mock_client

            resp = client.get("/api/v1/graph/entity/NonExistent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["nodes"] == []

    def test_entity_found(self, client):
        with patch("app.routers.graph._get_graph_client") as mock:
            mock_client = AsyncMock()
            mock_client.run_query.return_value = [
                {"name": "NATO", "type": "organization", "id": "e-1", "aliases": [], "confidence": 0.9}
            ]
            mock.return_value = mock_client

            resp = client.get("/api/v1/graph/entity/NATO")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 1
            assert data["nodes"][0]["name"] == "NATO"

    def test_neighbors_returns_nodes_and_edges(self, client):
        with patch("app.routers.graph._get_graph_client") as mock:
            mock_client = AsyncMock()
            mock_client.run_query.return_value = [
                {"source": "NATO", "relationship": "INVOLVES", "target": "EU", "target_type": "Entity"},
            ]
            mock.return_value = mock_client

            resp = client.get("/api/v1/graph/neighbors/NATO")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["edges"]) >= 1

    def test_search_returns_matching_entities(self, client):
        with patch("app.routers.graph._get_graph_client") as mock:
            mock_client = AsyncMock()
            mock_client.run_query.return_value = [
                {"name": "NATO", "type": "organization"},
                {"name": "National Guard", "type": "military_unit"},
            ]
            mock.return_value = mock_client

            resp = client.get("/api/v1/graph/search?q=nat&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 2

    def test_limit_capped_at_200(self, client):
        with patch("app.routers.graph._get_graph_client") as mock:
            mock_client = AsyncMock()
            mock_client.run_query.return_value = []
            mock.return_value = mock_client

            resp = client.get("/api/v1/graph/entity/Test?limit=500")
            assert resp.status_code == 200
            # The router should cap at 200 internally
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/backend && uv run pytest tests/unit/test_graph_router.py -v`
Expected: FAIL — router not registered

- [ ] **Step 3: Create graph models**

Create `services/backend/app/models/graph.py`:

```python
"""Graph exploration response models."""

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    name: str
    type: str
    properties: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str
    properties: dict = Field(default_factory=dict)


class GraphResponse(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    total_count: int = 0
```

- [ ] **Step 4: Create graph router**

Create `services/backend/app/routers/graph.py`:

```python
"""Graph exploration REST endpoints — reads from Neo4j via GraphClient."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Query
from neo4j import AsyncGraphDatabase

from app.config import settings
from app.models.graph import GraphEdge, GraphNode, GraphResponse

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

_driver = None


async def _get_graph_client():
    """Lazy-init async Neo4j driver."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def _read_query(cypher: str, params: dict) -> list[dict]:
    """Execute a read-only Cypher query."""
    import neo4j
    driver = await _get_graph_client()
    async with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
        result = await session.run(cypher, params)
        return [dict(record) async for record in result]


def _cap_limit(limit: int) -> int:
    return min(max(limit, 1), 200)


@router.get("/entity/{name}", response_model=GraphResponse)
async def get_entity(name: str, limit: int = Query(default=50, le=200)) -> GraphResponse:
    """Get entity details by name."""
    limit = _cap_limit(limit)
    rows = await _read_query(
        "MATCH (e:Entity {name: $name}) "
        "RETURN e.id AS id, e.name AS name, e.type AS type, "
        "e.aliases AS aliases, e.confidence AS confidence "
        "LIMIT $limit",
        {"name": name, "limit": limit},
    )
    nodes = [
        GraphNode(
            id=r.get("id", r.get("name", "")),
            name=r.get("name", ""),
            type=r.get("type", "unknown"),
            properties={k: v for k, v in r.items() if k not in ("id", "name", "type") and v is not None},
        )
        for r in rows
    ]
    return GraphResponse(nodes=nodes, total_count=len(nodes))


@router.get("/neighbors/{name}", response_model=GraphResponse)
async def get_neighbors(
    name: str,
    limit: int = Query(default=50, le=200),
    entity_type: str | None = None,
) -> GraphResponse:
    """Get 1-hop neighbors of an entity."""
    limit = _cap_limit(limit)
    type_filter = "AND n.type = $entity_type" if entity_type else ""
    rows = await _read_query(
        f"MATCH (e:Entity {{name: $name}})-[r]-(n) "
        f"WHERE true {type_filter} "
        f"RETURN e.name AS source, type(r) AS relationship, "
        f"n.name AS target, labels(n)[0] AS target_type, "
        f"n.type AS target_subtype "
        f"LIMIT $limit",
        {"name": name, "limit": limit, "entity_type": entity_type},
    )
    nodes_map: dict[str, GraphNode] = {}
    edges = []

    # Add the source entity
    nodes_map[name] = GraphNode(id=name, name=name, type="Entity")

    for r in rows:
        target = r.get("target", "")
        if target and target not in nodes_map:
            nodes_map[target] = GraphNode(
                id=target, name=target,
                type=r.get("target_subtype") or r.get("target_type", "unknown"),
            )
        edges.append(GraphEdge(
            source=name, target=target,
            relationship=r.get("relationship", "RELATED"),
        ))

    return GraphResponse(
        nodes=list(nodes_map.values()),
        edges=edges,
        total_count=len(rows),
    )


@router.get("/network/{name}", response_model=GraphResponse)
async def get_network(
    name: str,
    limit: int = Query(default=50, le=200),
    entity_type: str | None = None,
) -> GraphResponse:
    """Get 2-hop network around an entity."""
    limit = _cap_limit(limit)
    type_filter = "AND t.type = $entity_type" if entity_type else ""
    rows = await _read_query(
        f"MATCH path = (e:Entity {{name: $name}})-[*1..2]-(n) "
        f"UNWIND relationships(path) AS r "
        f"WITH startNode(r) AS s, type(r) AS rel, endNode(r) AS t "
        f"WHERE true {type_filter} "
        f"RETURN DISTINCT s.name AS source, rel AS relationship, "
        f"t.name AS target, labels(t)[0] AS target_type, "
        f"t.type AS target_subtype "
        f"LIMIT $limit",
        {"name": name, "limit": limit, "entity_type": entity_type},
    )
    nodes_map: dict[str, GraphNode] = {}
    edges = []

    for r in rows:
        src = r.get("source", "")
        tgt = r.get("target", "")
        if src and src not in nodes_map:
            nodes_map[src] = GraphNode(id=src, name=src, type="Entity")
        if tgt and tgt not in nodes_map:
            nodes_map[tgt] = GraphNode(
                id=tgt, name=tgt,
                type=r.get("target_subtype") or r.get("target_type", "unknown"),
            )
        edges.append(GraphEdge(
            source=src, target=tgt,
            relationship=r.get("relationship", "RELATED"),
        ))

    return GraphResponse(
        nodes=list(nodes_map.values()),
        edges=edges,
        total_count=len(rows),
    )


@router.get("/events", response_model=GraphResponse)
async def get_events(
    entity: str | None = None,
    limit: int = Query(default=30, le=200),
) -> GraphResponse:
    """Get events, optionally filtered by entity."""
    limit = _cap_limit(limit)
    if entity:
        rows = await _read_query(
            "MATCH (e:Entity {name: $entity})<-[:INVOLVES]-(ev:Event) "
            "RETURN ev.id AS id, ev.title AS name, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp "
            "ORDER BY ev.timestamp DESC LIMIT $limit",
            {"entity": entity, "limit": limit},
        )
    else:
        rows = await _read_query(
            "MATCH (ev:Event) "
            "RETURN ev.id AS id, ev.title AS name, ev.codebook_type AS type, "
            "ev.severity AS severity, ev.timestamp AS timestamp "
            "ORDER BY ev.timestamp DESC LIMIT $limit",
            {"limit": limit},
        )

    nodes = [
        GraphNode(
            id=r.get("id", ""),
            name=r.get("name", ""),
            type=r.get("type", "event"),
            properties={k: v for k, v in r.items() if k not in ("id", "name", "type") and v is not None},
        )
        for r in rows
    ]
    return GraphResponse(nodes=nodes, total_count=len(nodes))


@router.get("/search", response_model=GraphResponse)
async def search_entities(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=200),
) -> GraphResponse:
    """Search entities by name (case-insensitive contains)."""
    limit = _cap_limit(limit)
    rows = await _read_query(
        "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($q) "
        "RETURN e.id AS id, e.name AS name, e.type AS type "
        "ORDER BY e.name LIMIT $limit",
        {"q": q, "limit": limit},
    )
    nodes = [
        GraphNode(id=r.get("id", r.get("name", "")), name=r.get("name", ""), type=r.get("type", "unknown"))
        for r in rows
    ]
    return GraphResponse(nodes=nodes, total_count=len(nodes))
```

- [ ] **Step 5: Register graph router in backend main.py**

In `services/backend/app/main.py`, add the import and router registration:

Add to imports (line 14):
```python
from app.routers import earthquakes, flights, graph, hotspots, intel, rag, satellites, vessels
```

Add after line 73 (`app.include_router(rag.router, prefix="/api/v1")`):
```python
app.include_router(graph.router, prefix="/api/v1")
```

- [ ] **Step 6: Update intel models for new fields**

In `services/backend/app/models/intel.py`, add `image_url` and `use_legacy` to `IntelQuery`, and new fields to `IntelAnalysis`:

```python
class IntelQuery(BaseModel):
    query: str = Field(..., max_length=2000)
    region: str | None = None
    hotspot_id: str | None = None
    image_url: str | None = None
    use_legacy: bool = False


class IntelAnalysis(BaseModel):
    query: str
    agent_chain: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    analysis: str
    confidence: float = 0.0
    threat_assessment: str | None = None
    tool_trace: list[dict] = Field(default_factory=list)
    mode: str = "react"
    timestamp: datetime = Field(default_factory=_utc_now)
```

- [ ] **Step 7: Update intel router to pass new fields**

In `services/backend/app/routers/intel.py`, update line 45 to pass through `image_url` and `use_legacy`:

```python
                resp = await client.post(
                    f"{settings.intelligence_url}/query",
                    json={
                        "query": query.query,
                        "region": query.region,
                        "image_url": query.image_url,
                        "use_legacy": query.use_legacy,
                    },
                )
```

And update the `IntelAnalysis` construction (line 50-60) to include the new fields:

```python
            analysis = IntelAnalysis(
                query=query.query,
                agent_chain=data.get("agent_chain", []),
                sources_used=data.get("sources_used", []),
                analysis=data.get("analysis", ""),
                confidence=data.get("confidence", 0.0),
                threat_assessment=data.get("threat_assessment", "MODERATE"),
                tool_trace=data.get("tool_trace", []),
                mode=data.get("mode", "react"),
                timestamp=datetime.fromisoformat(data["timestamp"])
                if "timestamp" in data
                else datetime.now(timezone.utc),
            )
```

- [ ] **Step 8: Run all backend tests**

Run: `cd services/backend && uv run pytest tests/ -v`
Expected: all tests pass (existing 12 + new ~5)

- [ ] **Step 9: Commit**

```bash
git add services/backend/app/models/graph.py services/backend/app/routers/graph.py \
    services/backend/app/main.py services/backend/app/models/intel.py \
    services/backend/app/routers/intel.py services/backend/tests/unit/test_graph_router.py
git commit -m "feat(backend): add graph REST endpoints and update intel models for ReAct pipeline"
```

---

## Task 9: Frontend EntityExplorer

**Files:**
- Create: `services/frontend/src/components/graph/types.ts`
- Create: `services/frontend/src/components/graph/GraphCanvas.tsx`
- Create: `services/frontend/src/components/graph/NodeTooltip.tsx`
- Create: `services/frontend/src/components/graph/EntitySearch.tsx`
- Create: `services/frontend/src/components/graph/EntityExplorer.tsx`
- Create: `services/frontend/src/components/graph/graph.module.css`
- Modify: `services/frontend/package.json`

- [ ] **Step 1: Install dependency**

```bash
cd services/frontend && npm install react-force-graph-2d@^1.25
```

- [ ] **Step 2: Install types (if available)**

```bash
cd services/frontend && npm install -D @types/react-force-graph-2d 2>/dev/null || true
```

- [ ] **Step 3: Create types.ts**

Create `services/frontend/src/components/graph/types.ts`:

```typescript
export interface GraphNode {
  id: string;
  name: string;
  type: string;
  properties?: Record<string, unknown>;
  // react-force-graph internal
  x?: number;
  y?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  properties?: Record<string, unknown>;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_count: number;
}

export const NODE_COLORS: Record<string, string> = {
  person: "#3b82f6",        // blue
  organization: "#22c55e",  // green
  location: "#ef4444",      // red
  Event: "#f97316",         // orange
  military_unit: "#8b5cf6", // purple
  weapon_system: "#ec4899", // pink
  satellite: "#06b6d4",     // cyan
  vessel: "#14b8a6",        // teal
  aircraft: "#eab308",      // yellow
  unknown: "#6b7280",       // gray
};
```

- [ ] **Step 4: Create GraphCanvas.tsx**

Create `services/frontend/src/components/graph/GraphCanvas.tsx`:

```tsx
import { useCallback, useRef } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { GraphNode, GraphEdge, NODE_COLORS } from "./types";

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick: (node: GraphNode) => void;
  onNodeDoubleClick: (node: GraphNode) => void;
  hoveredNode: GraphNode | null;
  onNodeHover: (node: GraphNode | null) => void;
}

export default function GraphCanvas({
  nodes,
  edges,
  onNodeClick,
  onNodeDoubleClick,
  hoveredNode,
  onNodeHover,
}: GraphCanvasProps) {
  const fgRef = useRef<ForceGraphMethods>(null);

  const graphData = {
    nodes: nodes.map((n) => ({ ...n })),
    links: edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: e.relationship,
    })),
  };

  const nodeColor = useCallback(
    (node: Record<string, unknown>) =>
      NODE_COLORS[(node as GraphNode).type] || NODE_COLORS.unknown,
    [],
  );

  const nodeSize = useCallback(
    (node: Record<string, unknown>) => {
      const degree = edges.filter(
        (e) => e.source === (node as GraphNode).id || e.target === (node as GraphNode).id,
      ).length;
      return Math.max(4, Math.min(12, 4 + degree));
    },
    [edges],
  );

  const nodeLabel = useCallback(
    (node: Record<string, unknown>) => {
      const n = node as GraphNode;
      return `${n.name} (${n.type})`;
    },
    [],
  );

  return (
    <ForceGraph2D
      ref={fgRef}
      graphData={graphData}
      nodeColor={nodeColor}
      nodeVal={nodeSize}
      nodeLabel={nodeLabel}
      linkLabel="label"
      linkDirectionalArrowLength={3}
      linkDirectionalArrowRelPos={1}
      onNodeClick={(node) => onNodeClick(node as unknown as GraphNode)}
      onNodeRightClick={(node) => onNodeDoubleClick(node as unknown as GraphNode)}
      onNodeHover={(node) => onNodeHover(node as unknown as GraphNode | null)}
      width={800}
      height={600}
      backgroundColor="#0f172a"
      linkColor={() => "#475569"}
      nodeCanvasObjectMode={() => "after"}
      nodeCanvasObject={(node, ctx, globalScale) => {
        const n = node as unknown as GraphNode & { x: number; y: number };
        const label = n.name;
        const fontSize = 10 / globalScale;
        ctx.font = `${fontSize}px Inter, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#e2e8f0";
        ctx.fillText(label, n.x, n.y + 8);
      }}
    />
  );
}
```

- [ ] **Step 5: Create NodeTooltip.tsx**

Create `services/frontend/src/components/graph/NodeTooltip.tsx`:

```tsx
import { GraphNode, NODE_COLORS } from "./types";

interface NodeTooltipProps {
  node: GraphNode | null;
}

export default function NodeTooltip({ node }: NodeTooltipProps) {
  if (!node) return null;

  const color = NODE_COLORS[node.type] || NODE_COLORS.unknown;

  return (
    <div className="absolute top-4 right-4 bg-slate-800 border border-slate-600 rounded-lg p-3 text-sm text-slate-200 max-w-xs shadow-lg">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-3 h-3 rounded-full inline-block" style={{ backgroundColor: color }} />
        <span className="font-semibold">{node.name}</span>
      </div>
      <div className="text-slate-400 text-xs">{node.type}</div>
      {node.properties && Object.keys(node.properties).length > 0 && (
        <div className="mt-2 text-xs text-slate-400">
          {Object.entries(node.properties).map(([k, v]) => (
            <div key={k}>
              <span className="text-slate-500">{k}:</span> {String(v)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Create EntitySearch.tsx**

Create `services/frontend/src/components/graph/EntitySearch.tsx`:

```tsx
import { useState, useCallback } from "react";
import { GraphNode, GraphResponse } from "./types";

interface EntitySearchProps {
  apiBaseUrl: string;
  onSelect: (entity: GraphNode) => void;
}

export default function EntitySearch({ apiBaseUrl, onSelect }: EntitySearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GraphNode[]>([]);
  const [loading, setLoading] = useState(false);

  const search = useCallback(
    async (q: string) => {
      if (q.length < 2) {
        setResults([]);
        return;
      }
      setLoading(true);
      try {
        const resp = await fetch(`${apiBaseUrl}/search?q=${encodeURIComponent(q)}&limit=10`);
        const data: GraphResponse = await resp.json();
        setResults(data.nodes);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl],
  );

  return (
    <div className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          search(e.target.value);
        }}
        placeholder="Search entities..."
        className="w-full px-3 py-2 bg-slate-800 border border-slate-600 rounded text-sm text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:outline-none"
      />
      {results.length > 0 && (
        <ul className="absolute z-10 w-full mt-1 bg-slate-800 border border-slate-600 rounded shadow-lg max-h-48 overflow-y-auto">
          {results.map((r) => (
            <li
              key={r.id}
              className="px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 cursor-pointer"
              onClick={() => {
                onSelect(r);
                setQuery(r.name);
                setResults([]);
              }}
            >
              <span className="font-medium">{r.name}</span>
              <span className="ml-2 text-xs text-slate-400">{r.type}</span>
            </li>
          ))}
        </ul>
      )}
      {loading && (
        <div className="absolute right-3 top-2.5 text-xs text-slate-400">...</div>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Create EntityExplorer.tsx**

Create `services/frontend/src/components/graph/EntityExplorer.tsx`:

```tsx
import { useState, useCallback, useEffect } from "react";
import GraphCanvas from "./GraphCanvas";
import EntitySearch from "./EntitySearch";
import NodeTooltip from "./NodeTooltip";
import { GraphNode, GraphEdge, GraphResponse, NODE_COLORS } from "./types";

interface EntityExplorerProps {
  initialEntity?: string;
  apiBaseUrl?: string;
}

const ENTITY_TYPES = ["all", "person", "organization", "location", "military_unit", "weapon_system", "satellite", "vessel", "aircraft"];

export default function EntityExplorer({
  initialEntity,
  apiBaseUrl = "/api/v1/graph",
}: EntityExplorerProps) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  const loadNetwork = useCallback(
    async (entityName: string) => {
      setLoading(true);
      try {
        const resp = await fetch(`${apiBaseUrl}/network/${encodeURIComponent(entityName)}?limit=50`);
        const data: GraphResponse = await resp.json();
        setNodes(data.nodes);
        setEdges(data.edges);
        setExpandedNodes(new Set([entityName]));
      } catch (err) {
        console.error("Failed to load network:", err);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl],
  );

  useEffect(() => {
    if (initialEntity) {
      loadNetwork(initialEntity);
    }
  }, [initialEntity, loadNetwork]);

  const handleNodeClick = useCallback(
    async (node: GraphNode) => {
      if (expandedNodes.has(node.name)) return;

      setLoading(true);
      try {
        const resp = await fetch(`${apiBaseUrl}/neighbors/${encodeURIComponent(node.name)}?limit=30`);
        const data: GraphResponse = await resp.json();

        setNodes((prev) => {
          const existing = new Set(prev.map((n) => n.id));
          const newNodes = data.nodes.filter((n) => !existing.has(n.id));
          return [...prev, ...newNodes];
        });
        setEdges((prev) => {
          const existingKeys = new Set(prev.map((e) => `${e.source}-${e.relationship}-${e.target}`));
          const newEdges = data.edges.filter((e) => !existingKeys.has(`${e.source}-${e.relationship}-${e.target}`));
          return [...prev, ...newEdges];
        });
        setExpandedNodes((prev) => new Set([...prev, node.name]));
      } catch (err) {
        console.error("Failed to expand node:", err);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl, expandedNodes],
  );

  const handleNodeDoubleClick = useCallback(
    (node: GraphNode) => {
      // Collapse: remove nodes only reachable through this node
      // Simple version: just reload from initial
      if (expandedNodes.has(node.name) && expandedNodes.size > 1) {
        setExpandedNodes((prev) => {
          const next = new Set(prev);
          next.delete(node.name);
          return next;
        });
      }
    },
    [expandedNodes],
  );

  const filteredNodes = typeFilter === "all" ? nodes : nodes.filter((n) => n.type === typeFilter);
  const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
  const filteredEdges = edges.filter((e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target));

  return (
    <div className="relative bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      {/* Controls */}
      <div className="flex gap-3 p-3 border-b border-slate-700">
        <div className="flex-1">
          <EntitySearch apiBaseUrl={apiBaseUrl} onSelect={(n) => loadNetwork(n.name)} />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2 bg-slate-800 border border-slate-600 rounded text-sm text-slate-200"
        >
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All types" : t}
            </option>
          ))}
        </select>
      </div>

      {/* Graph */}
      <div className="relative">
        {loading && (
          <div className="absolute inset-0 bg-slate-900/50 flex items-center justify-center z-10">
            <span className="text-slate-400 text-sm">Loading...</span>
          </div>
        )}
        <GraphCanvas
          nodes={filteredNodes}
          edges={filteredEdges}
          onNodeClick={handleNodeClick}
          onNodeDoubleClick={handleNodeDoubleClick}
          hoveredNode={hoveredNode}
          onNodeHover={setHoveredNode}
        />
        <NodeTooltip node={hoveredNode} />
      </div>

      {/* Status bar */}
      <div className="flex justify-between px-3 py-1 border-t border-slate-700 text-xs text-slate-500">
        <span>{filteredNodes.length} nodes, {filteredEdges.length} edges</span>
        <span>Click to expand, right-click to collapse</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Create graph.module.css (minimal)**

Create `services/frontend/src/components/graph/graph.module.css`:

```css
/* EntityExplorer styles — most styling via Tailwind, this is for overrides */
.graphContainer canvas {
  cursor: grab;
}
.graphContainer canvas:active {
  cursor: grabbing;
}
```

- [ ] **Step 9: Verify build**

Run: `cd services/frontend && npm run type-check && npm run build`
Expected: no TypeScript errors, build succeeds

- [ ] **Step 10: Commit**

```bash
git add services/frontend/src/components/graph/ services/frontend/package.json services/frontend/package-lock.json
git commit -m "feat(frontend): add EntityExplorer standalone component with react-force-graph-2d"
```

---

## Task 10: Integration Test + Full Test Run

**Files:**
- All test files across all services

- [ ] **Step 1: Run all intelligence tests**

```bash
cd services/intelligence && uv run pytest tests/ -v --tb=short
```
Expected: ~150+ tests pass (99 existing + ~51 new)

- [ ] **Step 2: Run all backend tests**

```bash
cd services/backend && uv run pytest tests/ -v --tb=short
```
Expected: ~17+ tests pass (12 existing + ~5 new)

- [ ] **Step 3: Run all data-ingestion tests (regression)**

```bash
cd services/data-ingestion && uv run pytest tests/ -v --tb=short
```
Expected: 43 tests pass (unchanged)

- [ ] **Step 4: Run frontend type-check**

```bash
cd services/frontend && npm run type-check
```
Expected: no errors

- [ ] **Step 5: Run frontend lint**

```bash
cd services/frontend && npm run lint
```
Expected: no errors (or only pre-existing warnings)

- [ ] **Step 6: Fix any failures**

If any tests fail, fix them before proceeding. Do not skip.

- [ ] **Step 7: Final commit (if any fixes)**

```bash
git add -u
git commit -m "fix: resolve test issues from TASK-105 integration"
```

- [ ] **Step 8: Update TASKS.md status**

In `TASKS.md`, update TASK-105 status to `DONE ✅` with test count. Update the test count for intelligence service.

```bash
git add TASKS.md
git commit -m "docs: mark TASK-105 as done"
```

---

## Dependency Graph

```
Task 1 (deps + config)
    ↓
Task 2 (state + schema whitelist)
    ↓
Task 3 (graph templates)  ──→  Task 4 (graph_query tool)
                                    ↓
Task 5 (classify tool)  ────────┐
                                ├──→  Task 7 (ReAct agent + workflow)
Task 6 (vision tool)  ─────────┘           ↓
                                    Task 8 (backend graph router)
                                           ↓
                                    Task 9 (frontend EntityExplorer)
                                           ↓
                                    Task 10 (integration + final test)
```

Tasks 3, 5, 6 can be parallelized after Task 2 is done.
Tasks 8 and 9 can be parallelized after Task 7 is done.
