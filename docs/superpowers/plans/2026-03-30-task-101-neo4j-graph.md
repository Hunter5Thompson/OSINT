# TASK-101: Neo4j Two-Loop Graph Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc HTTP Neo4j calls in `entity_extractor.py` with a proper async Bolt client, Pydantic graph models, deterministic write templates, and a read-only query path with defense-in-depth security.

**Architecture:** Three-layer design. `graph/models.py` defines the data (Entity, Event, Source, Location). `graph/write_templates.py` holds deterministic Cypher templates — no LLM touches the write path. `graph/client.py` wraps the async Neo4j Bolt driver with `READ_ACCESS` enforcement for read queries. `graph/read_queries.py` (existing) provides application-level Cypher validation. `entity_extractor.py` is refactored to use the new client instead of raw HTTP.

**Tech Stack:** `neo4j>=5.23` (async Bolt driver), Pydantic v2, pytest, pytest-asyncio

**Working directory:** `services/intelligence/`

**Run tests with:** `cd services/intelligence && uv run python -m pytest tests/ -v --tb=short`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `graph/models.py` | CREATE | Pydantic models: Entity, Event, Source, Location, ExtractionResult |
| `graph/write_templates.py` | CREATE | Deterministic Cypher template strings |
| `graph/client.py` | CREATE | Async Neo4j Bolt wrapper with READ_ACCESS |
| `graph/read_queries.py` | EXISTS | `validate_cypher_readonly()` — no changes |
| `graph/__init__.py` | MODIFY | Re-export public API |
| `config.py` | MODIFY | Add Neo4j settings (url, user, password) |
| `extraction/entity_extractor.py` | MODIFY | Replace HTTP Neo4j calls with GraphClient |
| `tests/test_graph_models.py` | CREATE | Model validation tests |
| `tests/test_write_templates.py` | CREATE | Template string correctness tests |
| `tests/test_graph_client.py` | CREATE | Client logic tests (mocked driver) |
| `tests/test_entity_extractor_refactor.py` | CREATE | Verify extractor uses new client |
| `pyproject.toml` | MODIFY | Add `neo4j>=5.23` dependency |

---

## Task 1: Add neo4j dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add neo4j to dependencies**

In `pyproject.toml`, add `neo4j>=5.23` to the `dependencies` list:

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
]
```

- [ ] **Step 2: Install**

Run: `uv sync`
Expected: Resolves and installs neo4j driver

- [ ] **Step 3: Verify import**

Run: `uv run python -c "import neo4j; print(neo4j.__version__)"`
Expected: Prints version >= 5.23

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(intelligence): add neo4j>=5.23 async driver dependency"
```

---

## Task 2: Graph models (Pydantic)

**Files:**
- Create: `tests/test_graph_models.py`
- Create: `graph/models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_graph_models.py
"""Tests for Neo4j graph Pydantic models."""

import pytest
from datetime import datetime, timezone
from graph.models import Entity, Event, Source, Location


class TestEntity:
    def test_defaults(self):
        e = Entity(name="NATO", type="organization")
        assert e.name == "NATO"
        assert e.type == "organization"
        assert e.confidence == 0.5
        assert e.aliases == []
        assert len(e.id) == 12

    def test_aliases_not_shared(self):
        """Mutable default must not be shared between instances."""
        a = Entity(name="A", type="person")
        b = Entity(name="B", type="person")
        a.aliases.append("x")
        assert b.aliases == []

    def test_valid_types(self):
        for t in ["person", "organization", "location", "weapon_system",
                   "satellite", "vessel", "aircraft", "military_unit"]:
            e = Entity(name="test", type=t)
            assert e.type == t

    def test_invalid_type_rejected(self):
        with pytest.raises(ValueError):
            Entity(name="test", type="invalid_type")

    def test_confidence_bounds(self):
        Entity(name="t", type="person", confidence=0.0)
        Entity(name="t", type="person", confidence=1.0)
        with pytest.raises(ValueError):
            Entity(name="t", type="person", confidence=1.1)
        with pytest.raises(ValueError):
            Entity(name="t", type="person", confidence=-0.1)


class TestEvent:
    def test_defaults(self):
        ev = Event(
            title="Drone Strike",
            timestamp=datetime(2026, 3, 30, tzinfo=timezone.utc),
            codebook_type="military.drone_attack",
            severity="high",
        )
        assert ev.title == "Drone Strike"
        assert ev.severity == "high"
        assert ev.confidence == 0.5
        assert ev.summary == ""
        assert len(ev.id) == 12

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValueError):
            Event(
                title="t",
                timestamp=datetime.now(tz=timezone.utc),
                codebook_type="x",
                severity="extreme",
            )


class TestSource:
    def test_creation(self):
        s = Source(url="https://example.com", name="Example")
        assert s.credibility_score == 0.5


class TestLocation:
    def test_creation(self):
        loc = Location(name="Jiuquan", country="China", lat=40.96, lon=100.17)
        assert loc.name == "Jiuquan"

    def test_optional_coords(self):
        loc = Location(name="Unknown Place", country="Unknown")
        assert loc.lat is None
        assert loc.lon is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_graph_models.py -x --tb=short`
Expected: `ModuleNotFoundError: No module named 'graph.models'` (models.py doesn't export these yet)

- [ ] **Step 3: Implement models**

```python
# graph/models.py
"""Pydantic models for the Neo4j knowledge graph."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    type: Literal[
        "person", "organization", "location", "weapon_system",
        "satellite", "vessel", "aircraft", "military_unit",
    ]
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


class Location(BaseModel):
    name: str
    country: str
    lat: float | None = None
    lon: float | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_graph_models.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Run all tests**

Run: `uv run python -m pytest tests/ -v --tb=short`
Expected: All 38+ tests pass (existing + new)

- [ ] **Step 6: Commit**

```bash
git add graph/models.py tests/test_graph_models.py
git commit -m "feat(graph): add Entity, Event, Source, Location Pydantic models"
```

---

## Task 3: Write templates (deterministic Cypher)

**Files:**
- Create: `tests/test_write_templates.py`
- Create: `graph/write_templates.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_write_templates.py
"""Tests for deterministic Cypher write templates."""

from graph.write_templates import (
    UPSERT_ENTITY,
    CREATE_EVENT,
    LINK_ENTITY_EVENT,
    LINK_EVENT_SOURCE,
    LINK_EVENT_LOCATION,
)


class TestTemplateStrings:
    """Verify templates contain expected Cypher patterns."""

    def test_upsert_entity_merges_on_name_and_type(self):
        assert "MERGE (e:Entity {name: $name, type: $type})" in UPSERT_ENTITY

    def test_upsert_entity_sets_id_on_create(self):
        assert "ON CREATE SET" in UPSERT_ENTITY
        assert "e.id = $id" in UPSERT_ENTITY

    def test_upsert_entity_returns_id(self):
        assert "RETURN e.id" in UPSERT_ENTITY

    def test_create_event_uses_create_not_merge(self):
        assert "CREATE (ev:Event" in CREATE_EVENT
        assert "MERGE" not in CREATE_EVENT

    def test_create_event_returns_id(self):
        assert "RETURN ev.id" in CREATE_EVENT

    def test_link_entity_event_uses_involves(self):
        assert "[:INVOLVES]" in LINK_ENTITY_EVENT

    def test_link_event_source_uses_reported_by(self):
        assert "[:REPORTED_BY]" in LINK_EVENT_SOURCE

    def test_link_event_location_uses_occurred_at(self):
        assert "[:OCCURRED_AT]" in LINK_EVENT_LOCATION

    def test_all_templates_are_parameterized(self):
        """No string interpolation — all values via $params."""
        for tmpl in [UPSERT_ENTITY, CREATE_EVENT, LINK_ENTITY_EVENT,
                     LINK_EVENT_SOURCE, LINK_EVENT_LOCATION]:
            assert "$" in tmpl, f"Template has no parameters: {tmpl[:60]}"

    def test_no_template_contains_f_string_markers(self):
        """Templates must not use Python f-string formatting."""
        for tmpl in [UPSERT_ENTITY, CREATE_EVENT, LINK_ENTITY_EVENT,
                     LINK_EVENT_SOURCE, LINK_EVENT_LOCATION]:
            assert "{entity" not in tmpl
            assert "{event" not in tmpl
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_write_templates.py -x --tb=short`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement write templates**

```python
# graph/write_templates.py
"""
Deterministic Cypher templates for graph writes.

The LLM extracts DATA (JSON) → Pydantic validates → these templates write.
NO LLM-generated Cypher on the write path.
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_write_templates.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add graph/write_templates.py tests/test_write_templates.py
git commit -m "feat(graph): add deterministic Cypher write templates"
```

---

## Task 4: GraphClient (async Bolt driver)

**Files:**
- Create: `tests/test_graph_client.py`
- Create: `graph/client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_graph_client.py
"""Tests for the async Neo4j client wrapper.

Uses a mock Neo4j driver — no real DB connection needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from graph.client import GraphClient


@pytest.fixture
def mock_driver():
    driver = AsyncMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return driver, session


class TestGraphClientRunQuery:
    async def test_write_query_uses_default_session(self, mock_driver):
        driver, session = mock_driver
        record = MagicMock()
        record.__iter__ = MagicMock(return_value=iter([("id", "abc123")]))
        record.keys.return_value = ["id"]
        record.__getitem__ = lambda self, key: "abc123"
        result_mock = AsyncMock()
        result_mock.__aiter__ = MagicMock(return_value=iter([record]))
        session.run.return_value = result_mock

        with patch("graph.client.AsyncGraphDatabase") as mock_agd:
            mock_agd.driver.return_value = driver
            client = GraphClient("bolt://localhost:7687", "neo4j", "pass")
            await client.run_query("CREATE (n) RETURN n")
            session.run.assert_called_once()

    async def test_read_only_sets_access_mode(self, mock_driver):
        driver, session = mock_driver
        result_mock = AsyncMock()
        result_mock.__aiter__ = MagicMock(return_value=iter([]))
        session.run.return_value = result_mock

        with patch("graph.client.AsyncGraphDatabase") as mock_agd:
            mock_agd.driver.return_value = driver
            client = GraphClient("bolt://localhost:7687", "neo4j", "pass")
            await client.run_query("MATCH (n) RETURN n", read_only=True)

            # Verify session was opened with READ_ACCESS
            call_kwargs = driver.session.call_args
            assert call_kwargs is not None
            # The default_access_mode should be set
            kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
            assert "default_access_mode" in kwargs


class TestGraphClientClose:
    async def test_close_closes_driver(self):
        with patch("graph.client.AsyncGraphDatabase") as mock_agd:
            driver = AsyncMock()
            mock_agd.driver.return_value = driver
            client = GraphClient("bolt://localhost:7687", "neo4j", "pass")
            await client.close()
            driver.close.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_graph_client.py -x --tb=short`
Expected: `ModuleNotFoundError: No module named 'graph.client'`

- [ ] **Step 3: Implement GraphClient**

```python
# graph/client.py
"""Async Neo4j client wrapper with read-only enforcement."""

from __future__ import annotations

import neo4j
from neo4j import AsyncGraphDatabase
import structlog

log = structlog.get_logger(__name__)


class GraphClient:
    """Thin async wrapper around the Neo4j Bolt driver.

    Enforces READ_ACCESS at the Neo4j session level for read-only queries
    (defense-in-depth layer 2, complementing validate_cypher_readonly).
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        await self._driver.close()

    async def run_query(
        self,
        cypher: str,
        params: dict | None = None,
        read_only: bool = False,
    ) -> list[dict]:
        session_kwargs = {}
        if read_only:
            session_kwargs["default_access_mode"] = neo4j.READ_ACCESS

        async with self._driver.session(**session_kwargs) as session:
            result = await session.run(cypher, params or {})
            return [dict(record) async for record in result]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_graph_client.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add graph/client.py tests/test_graph_client.py
git commit -m "feat(graph): add async Neo4j client with READ_ACCESS enforcement"
```

---

## Task 5: Add Neo4j config to intelligence service

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add Neo4j settings**

Add three fields to the `Settings` class in `config.py`:

```python
class Settings(BaseSettings):
    inference_provider: str = "vllm"
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "models/qwen3.5-27b-awq"
    tei_embed_url: str = "http://localhost:8001"
    tei_rerank_url: str = "http://localhost:8002"
    embedding_dimensions: int = 1024
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "odin_intel"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "odin1234"

    @property
    def llm_base_url(self) -> str:
        return f"{self.vllm_url}/v1"

    @property
    def llm_model(self) -> str:
        return self.vllm_model

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(intelligence): add Neo4j config (uri, user, password)"
```

---

## Task 6: Update graph/__init__.py exports

**Files:**
- Modify: `graph/__init__.py`

- [ ] **Step 1: Add public API exports**

```python
# graph/__init__.py
"""Neo4j knowledge graph package."""

from graph.client import GraphClient
from graph.models import Entity, Event, Location, Source
from graph.read_queries import validate_cypher_readonly

__all__ = [
    "GraphClient",
    "Entity",
    "Event",
    "Location",
    "Source",
    "validate_cypher_readonly",
]
```

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from graph import GraphClient, Entity, Event, validate_cypher_readonly; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add graph/__init__.py
git commit -m "feat(graph): export public API from package"
```

---

## Task 7: Refactor entity_extractor.py to use GraphClient

**Files:**
- Create: `tests/test_entity_extractor_refactor.py`
- Modify: `extraction/entity_extractor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_entity_extractor_refactor.py
"""Tests that entity_extractor uses GraphClient instead of raw HTTP."""

from unittest.mock import AsyncMock, patch
import pytest

from extraction.entity_extractor import EntityExtractor, ExtractionResult, ExtractedEntity


class TestEntityExtractorUsesGraphClient:
    async def test_write_to_neo4j_calls_graph_client(self):
        """Verify write_to_neo4j delegates to a GraphClient, not raw HTTP."""
        mock_graph = AsyncMock()
        mock_graph.run_query.return_value = [{"d": "ok"}]

        extractor = EntityExtractor(
            vllm_url="http://localhost:8000",
            graph_client=mock_graph,
        )

        result = ExtractionResult(entities=[
            ExtractedEntity(
                name="NATO",
                type="Organization",
                mention="NATO forces",
                context="NATO deployed troops",
            ),
        ])

        count = await extractor.write_to_neo4j(result, "Test Doc", "http://test.com", "rss")

        assert count == 1
        assert mock_graph.run_query.call_count >= 2  # Document + Entity

    async def test_write_to_neo4j_no_entities(self):
        mock_graph = AsyncMock()
        extractor = EntityExtractor(
            vllm_url="http://localhost:8000",
            graph_client=mock_graph,
        )
        count = await extractor.write_to_neo4j(
            ExtractionResult(entities=[]), "Title", "http://x.com"
        )
        assert count == 0
        mock_graph.run_query.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_entity_extractor_refactor.py -x --tb=short`
Expected: `TypeError` — EntityExtractor doesn't accept `graph_client` parameter yet

- [ ] **Step 3: Refactor entity_extractor.py**

Replace the entire file:

```python
# extraction/entity_extractor.py
"""
Entity Extractor — LLM-based NER via Qwen3.5-27B (vLLM).

Extracts Person, Organization, Country, Location, Facility,
Commodity, Event entities from OSINT text and writes them to Neo4j
via GraphClient.
"""

from __future__ import annotations

import json
import httpx
import structlog
from pydantic import BaseModel, Field

from graph.client import GraphClient

log = structlog.get_logger(__name__)

# ── Pydantic schema for structured LLM output ────────────────────────────────

class ExtractedEntity(BaseModel):
    name: str = Field(description="Canonical name of the entity")
    type: str = Field(description="One of: Person, Organization, Country, Location, Facility, Commodity, Event")
    mention: str = Field(description="Exact quote from the text that mentions this entity")
    context: str = Field(description="One sentence explaining the entity's role in this document")

class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)

# ── JSON Schema for vLLM response_format ─────────────────────────────────────

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":    {"type": "string"},
                    "type":    {"type": "string", "enum": ["Person", "Organization", "Country", "Location", "Facility", "Commodity", "Event"]},
                    "mention": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["name", "type", "mention", "context"],
            },
        }
    },
    "required": ["entities"],
}

_SYSTEM_PROMPT = """\
You are an OSINT entity extraction specialist. Extract named entities from the provided text.

Rules:
- Extract only entities explicitly mentioned in the text
- Use canonical names (e.g. "Vladimir Putin" not "Putin", "Russian Federation" not "Russia")
- Types: Person, Organization, Country, Location, Facility, Commodity, Event
- Commodity: oil, gas, wheat, rare earths, weapons systems, etc.
- Event: battles, treaties, elections, attacks, sanctions, etc.
- Skip generic terms, pronouns, and vague references
- Maximum 20 entities per document
- Return valid JSON only"""


class EntityExtractor:
    """Extract entities from text using Qwen3.5-27B via vLLM."""

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        vllm_model: str = "models/qwen3.5-27b-awq",
        graph_client: GraphClient | None = None,
    ) -> None:
        self.vllm_url = vllm_url
        self.vllm_model = vllm_model
        self._graph = graph_client

    # ── LLM extraction ────────────────────────────────────────────────────────

    async def extract(self, text: str, source_url: str = "", max_chars: int = 3000) -> ExtractionResult:
        """Extract entities from text using Qwen3.5-27B structured output."""
        truncated = text[:max_chars]

        payload = {
            "model": self.vllm_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract entities from this OSINT document:\n\n{truncated}"},
            ],
            "temperature": 0,
            "max_tokens": 1500,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction_result",
                    "schema": _RESPONSE_SCHEMA,
                    "strict": True,
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.vllm_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                result = ExtractionResult(**data)
                log.info("extraction_complete", url=source_url, entity_count=len(result.entities))
                return result
        except Exception as e:
            log.warning("extraction_failed", url=source_url, error=str(e))
            return ExtractionResult(entities=[])

    # ── Neo4j write via GraphClient ───────────────────────────────────────────

    async def write_to_neo4j(
        self,
        result: ExtractionResult,
        doc_title: str,
        doc_url: str,
        doc_source: str = "rss",
    ) -> int:
        """Write extracted entities to Neo4j via GraphClient. Returns entity count."""
        if not result.entities or self._graph is None:
            return 0

        # Upsert Document node
        await self._graph.run_query(
            "MERGE (d:Document {url: $url}) "
            "SET d.title = $title, d.source = $source, d.updated_at = datetime() "
            "RETURN d",
            {"url": doc_url, "title": doc_title, "source": doc_source},
        )

        # Upsert each Entity + MENTIONS relationship
        for entity in result.entities:
            await self._graph.run_query(
                f"MERGE (e:Entity:{entity.type} {{name: $name}}) "
                "SET e.last_seen = datetime() "
                "WITH e "
                "MATCH (d:Document {url: $url}) "
                "MERGE (d)-[r:MENTIONS]->(e) "
                "SET r.mention = $mention, r.context = $context",
                {
                    "name": entity.name,
                    "url": doc_url,
                    "mention": entity.mention,
                    "context": entity.context,
                },
            )

        log.info("neo4j_write_complete", url=doc_url, entities=len(result.entities))
        return len(result.entities)

    # ── Combined pipeline ─────────────────────────────────────────────────────

    async def extract_and_store(
        self,
        text: str,
        doc_title: str,
        doc_url: str,
        doc_source: str = "rss",
    ) -> ExtractionResult:
        """Extract entities from text and write to Neo4j in one call."""
        result = await self.extract(text, source_url=doc_url)
        await self.write_to_neo4j(result, doc_title, doc_url, doc_source)
        return result
```

- [ ] **Step 4: Run refactor tests**

Run: `uv run python -m pytest tests/test_entity_extractor_refactor.py -v --tb=short`
Expected: All pass

- [ ] **Step 5: Run ALL tests**

Run: `uv run python -m pytest tests/ -v --tb=short`
Expected: All pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add extraction/entity_extractor.py tests/test_entity_extractor_refactor.py
git commit -m "refactor(extraction): replace ad-hoc HTTP Neo4j with GraphClient"
```

---

## Task 8: Final integration verification

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m pytest tests/ -v --tb=short`
Expected: All tests pass:
- `test_cypher_validation.py` — 36 tests (existing)
- `test_workflow.py` — 2 tests (existing)
- `test_graph_models.py` — ~10 tests (new)
- `test_write_templates.py` — ~10 tests (new)
- `test_graph_client.py` — ~3 tests (new)
- `test_entity_extractor_refactor.py` — ~2 tests (new)

- [ ] **Step 2: Verify imports are clean**

Run: `uv run python -c "from graph import GraphClient, Entity, Event, Source, Location, validate_cypher_readonly; from graph.write_templates import UPSERT_ENTITY, CREATE_EVENT; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Commit any remaining changes**

```bash
git add -A
git commit -m "feat(graph): complete TASK-101 — Neo4j Two-Loop Graph Architecture"
```
