# TASK-104: Hybrid Search + Reranker + Graph-Context — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the RAG retrieval pipeline with three stages: (1) Rerank via TEI, (2) Graph Context Injection from Neo4j via GraphClient (Bolt). All stages are feature-flagged and independently toggleable. No breaking changes to the existing agent flow. Hybrid Search (dense + sparse) is deferred to Phase 2 (requires Collection schema change + ingestion update); the flag exists but defaults to False.

**Architecture:** `rag/reranker.py` calls TEI Rerank on Port 8002. `rag/graph_context.py` uses the existing `GraphClient` (Bolt driver, NOT HTTP) to query Neo4j for 1-2 hop entity neighborhoods. The existing `search()` function stays as-is (baseline). A new `enhanced_search()` orchestrates dense search → rerank → graph context based on config flags. The LangGraph agent tool `qdrant_search.py` is updated to call `enhanced_search()`. Phase 2 (hybrid dense+sparse) is deferred until `odin_v2` collection with sparse vectors exists.

**Tech Stack:** httpx (Qdrant REST + TEI Rerank + Neo4j HTTP), existing embedder.py, existing config.py

**Working directory:** `services/intelligence/`

**Run tests with:** `cd services/intelligence && uv run python -m pytest tests/ -v --tb=short`

**Definition of Done:**
1. No breaking changes in current agent flow
2. Configurable per flags: `enable_hybrid`, `enable_rerank`, `enable_graph_context`
3. Tests for each of the three building blocks + 1 E2E happy path
4. Fix: `indexer.py` VECTOR_SIZE 768 → use `settings.embedding_dimensions`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | MODIFY | Add feature flags + TEI rerank URL already exists |
| `rag/indexer.py` | MODIFY | Fix VECTOR_SIZE 768 → settings.embedding_dimensions |
| `rag/reranker.py` | CREATE | TEI Rerank via HTTP (Port 8002) |
| `rag/graph_context.py` | CREATE | Neo4j 1-2 hop neighborhood → compact context block |
| `rag/retriever.py` | MODIFY | Add hybrid_search() + enhanced_search() orchestrator |
| `agents/tools/qdrant_search.py` | MODIFY | Use enhanced_search() |
| `tests/test_reranker.py` | CREATE | Reranker tests |
| `tests/test_graph_context.py` | CREATE | Graph context tests |
| `tests/test_hybrid_retriever.py` | CREATE | Hybrid search + E2E tests |

---

## Task 1: Config flags + indexer fix

**Files:**
- Modify: `config.py`
- Modify: `rag/indexer.py`

- [ ] **Step 1: Add feature flags to config.py**

Add after `neo4j_password`:
```python
    # RAG feature flags
    enable_hybrid: bool = True
    enable_rerank: bool = True
    enable_graph_context: bool = True
```

- [ ] **Step 2: Fix indexer.py VECTOR_SIZE**

Replace `VECTOR_SIZE = 768` with `from config import settings` usage:
```python
# Remove: VECTOR_SIZE = 768
# In ensure_collection():
"vectors": {"size": settings.embedding_dimensions, "distance": "Cosine"},
```

- [ ] **Step 3: Verify existing tests pass**

---

## Task 2: Reranker via TEI (TDD)

**Files:**
- Create: `tests/test_reranker.py`
- Create: `rag/reranker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reranker.py
"""Tests for TEI-based reranker."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from rag.reranker import rerank


class TestReranker:
    async def test_reranks_results_by_score(self):
        """TEI reranker should reorder results by relevance score."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        # TEI rerank returns list of {"index": N, "score": float}
        mock_resp.json.return_value = [
            {"index": 0, "score": 0.3},
            {"index": 1, "score": 0.9},
            {"index": 2, "score": 0.6},
        ]

        documents = [
            {"title": "Low relevance", "content": "text A", "score": 0.5},
            {"title": "High relevance", "content": "text B", "score": 0.4},
            {"title": "Mid relevance", "content": "text C", "score": 0.45},
        ]

        with patch("rag.reranker.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await rerank("military drone", documents, top_k=2)

        assert len(result) == 2
        assert result[0]["title"] == "High relevance"  # score 0.9
        assert result[1]["title"] == "Mid relevance"    # score 0.6

    async def test_returns_originals_on_failure(self):
        """If TEI is down, return original results unranked (graceful degradation)."""
        documents = [
            {"title": "A", "content": "text", "score": 0.5},
            {"title": "B", "content": "text", "score": 0.4},
        ]

        with patch("rag.reranker.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("TEI down")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await rerank("query", documents, top_k=2)

        assert len(result) == 2
        assert result[0]["title"] == "A"  # original order preserved

    async def test_respects_top_k(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"index": 0, "score": 0.9},
            {"index": 1, "score": 0.8},
            {"index": 2, "score": 0.7},
        ]

        documents = [
            {"title": "A", "content": "t", "score": 0.5},
            {"title": "B", "content": "t", "score": 0.4},
            {"title": "C", "content": "t", "score": 0.3},
        ]

        with patch("rag.reranker.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await rerank("query", documents, top_k=1)

        assert len(result) == 1
```

- [ ] **Step 2: Run tests, verify failure (ModuleNotFoundError)**

- [ ] **Step 3: Implement rag/reranker.py**

```python
# rag/reranker.py
"""Reranker via TEI (Text Embeddings Inference) on Port 8002."""

import httpx
import structlog

from config import settings

log = structlog.get_logger(__name__)


async def rerank(
    query: str,
    documents: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """Rerank documents using TEI rerank endpoint.

    Falls back to returning original documents (truncated to top_k) on failure.
    """
    if not documents:
        return []

    texts = [d.get("content", d.get("title", "")) for d in documents]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.tei_rerank_url}/rerank",
                json={"query": query, "texts": texts},
            )
            resp.raise_for_status()
            scores = resp.json()  # [{"index": N, "score": float}, ...]

        # Sort by score descending
        ranked = sorted(scores, key=lambda x: x["score"], reverse=True)
        result = []
        for item in ranked[:top_k]:
            doc = documents[item["index"]].copy()
            doc["rerank_score"] = item["score"]
            result.append(doc)
        return result

    except Exception as e:
        log.warning("rerank_failed_using_original_order", error=str(e))
        return documents[:top_k]
```

- [ ] **Step 4: Run tests, verify pass**

---

## Task 3: Graph Context Injection (TDD)

**Files:**
- Create: `tests/test_graph_context.py`
- Create: `rag/graph_context.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_graph_context.py
"""Tests for Neo4j graph context injection."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from rag.graph_context import get_graph_context


class TestGraphContext:
    async def test_returns_context_for_entities(self):
        """Given entity names, return their Neo4j neighborhood as text."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [{
                "columns": ["e_name", "e_type", "rel", "connected_name", "connected_type"],
                "data": [
                    {"row": ["NATO", "organization", "INVOLVES", "Ukraine Conflict", "Event"]},
                    {"row": ["NATO", "organization", "ASSOCIATED_WITH", "EU", "organization"]},
                ],
            }],
            "errors": [],
        }

        with patch("rag.graph_context.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            context = await get_graph_context(["NATO"])

        assert "NATO" in context
        assert "Ukraine Conflict" in context or "EU" in context

    async def test_empty_entities_returns_empty(self):
        context = await get_graph_context([])
        assert context == ""

    async def test_neo4j_failure_returns_empty(self):
        """If Neo4j is down, return empty string (graceful degradation)."""
        with patch("rag.graph_context.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Neo4j down")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            context = await get_graph_context(["NATO"])

        assert context == ""
```

- [ ] **Step 2: Run tests, verify failure**

- [ ] **Step 3: Implement rag/graph_context.py**

```python
# rag/graph_context.py
"""Graph context injection — fetch entity neighborhoods from Neo4j."""

import httpx
import structlog

from config import settings

log = structlog.get_logger(__name__)

_NEIGHBORHOOD_QUERY = """
MATCH (e:Entity {name: $name})-[r]-(connected)
RETURN e.name AS e_name, e.type AS e_type,
       type(r) AS rel,
       connected.name AS connected_name,
       labels(connected)[0] AS connected_type
LIMIT 20
"""


async def get_graph_context(
    entity_names: list[str],
    max_entities: int = 5,
) -> str:
    """Fetch 1-hop neighborhoods for entities from Neo4j.

    Returns a compact text block for prompt injection, or "" on failure.
    """
    if not entity_names:
        return ""

    statements = []
    for name in entity_names[:max_entities]:
        statements.append({
            "statement": _NEIGHBORHOOD_QUERY,
            "parameters": {"name": name},
        })

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.neo4j_url}/db/neo4j/tx/commit",
                json={"statements": statements},
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("graph_context_failed", error=str(e))
        return ""

    if data.get("errors"):
        log.warning("graph_context_errors", errors=data["errors"])
        return ""

    # Build compact context block
    lines = []
    for result in data.get("results", []):
        for row_data in result.get("data", []):
            row = row_data.get("row", [])
            if len(row) >= 5:
                e_name, e_type, rel, c_name, c_type = row[:5]
                lines.append(f"  {e_name} ({e_type}) —[{rel}]→ {c_name} ({c_type})")

    if not lines:
        return ""

    return "[Knowledge Graph Context]\n" + "\n".join(lines)
```

- [ ] **Step 4: Run tests, verify pass**

---

## Task 4: Enhanced retriever + hybrid search (TDD)

**Files:**
- Create: `tests/test_hybrid_retriever.py`
- Modify: `rag/retriever.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hybrid_retriever.py
"""Tests for hybrid search and enhanced retriever pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from rag.retriever import enhanced_search


class TestEnhancedSearch:
    async def test_dense_only_when_flags_disabled(self):
        """With all flags off, enhanced_search behaves like basic search."""
        mock_embed = AsyncMock(return_value=[0.1] * 1024)
        mock_qdrant_resp = MagicMock()
        mock_qdrant_resp.status_code = 200
        mock_qdrant_resp.raise_for_status = MagicMock()
        mock_qdrant_resp.json.return_value = {
            "result": [
                {"score": 0.9, "payload": {"title": "Result 1", "content": "text 1"}},
                {"score": 0.7, "payload": {"title": "Result 2", "content": "text 2"}},
            ]
        }

        with patch("rag.retriever.embed_text", mock_embed), \
             patch("rag.retriever.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_qdrant_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await enhanced_search(
                "test query",
                enable_hybrid=False,
                enable_rerank=False,
                enable_graph_context=False,
            )

        assert len(results) == 2
        assert results[0]["title"] == "Result 1"

    async def test_rerank_reorders_results(self):
        """With rerank enabled, results should be reordered."""
        mock_embed = AsyncMock(return_value=[0.1] * 1024)
        mock_qdrant_resp = MagicMock()
        mock_qdrant_resp.status_code = 200
        mock_qdrant_resp.raise_for_status = MagicMock()
        mock_qdrant_resp.json.return_value = {
            "result": [
                {"score": 0.9, "payload": {"title": "Dense top", "content": "text A"}},
                {"score": 0.7, "payload": {"title": "Dense second", "content": "text B"}},
            ]
        }

        mock_rerank = AsyncMock(return_value=[
            {"title": "Dense second", "content": "text B", "score": 0.7, "rerank_score": 0.95},
            {"title": "Dense top", "content": "text A", "score": 0.9, "rerank_score": 0.4},
        ])

        with patch("rag.retriever.embed_text", mock_embed), \
             patch("rag.retriever.httpx.AsyncClient") as mock_cls, \
             patch("rag.retriever.rerank_fn", mock_rerank):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_qdrant_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await enhanced_search(
                "test query",
                enable_hybrid=False,
                enable_rerank=True,
                enable_graph_context=False,
            )

        assert results[0]["title"] == "Dense second"  # reranked to top

    async def test_graph_context_appended(self):
        """With graph context enabled, results include graph_context field."""
        mock_embed = AsyncMock(return_value=[0.1] * 1024)
        mock_qdrant_resp = MagicMock()
        mock_qdrant_resp.status_code = 200
        mock_qdrant_resp.raise_for_status = MagicMock()
        mock_qdrant_resp.json.return_value = {
            "result": [
                {"score": 0.9, "payload": {"title": "NATO expansion", "content": "NATO text",
                                            "entities": [{"name": "NATO", "type": "organization"}]}},
            ]
        }

        mock_graph = AsyncMock(return_value="[Knowledge Graph Context]\n  NATO (organization) —[INVOLVES]→ Ukraine (Event)")

        with patch("rag.retriever.embed_text", mock_embed), \
             patch("rag.retriever.httpx.AsyncClient") as mock_cls, \
             patch("rag.retriever.get_graph_context_fn", mock_graph):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_qdrant_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await enhanced_search(
                "NATO",
                enable_hybrid=False,
                enable_rerank=False,
                enable_graph_context=True,
            )

        assert "graph_context" in results[0]
        assert "NATO" in results[0]["graph_context"]

    async def test_full_pipeline_e2e(self):
        """E2E: dense search → rerank → graph context injection."""
        mock_embed = AsyncMock(return_value=[0.1] * 1024)
        mock_qdrant_resp = MagicMock()
        mock_qdrant_resp.status_code = 200
        mock_qdrant_resp.raise_for_status = MagicMock()
        mock_qdrant_resp.json.return_value = {
            "result": [
                {"score": 0.8, "payload": {"title": "Drone strike", "content": "text",
                                            "entities": [{"name": "Russia", "type": "organization"}]}},
                {"score": 0.6, "payload": {"title": "Peace talks", "content": "text",
                                            "entities": []}},
            ]
        }

        mock_rerank = AsyncMock(side_effect=lambda q, docs, top_k: docs[:top_k])
        mock_graph = AsyncMock(return_value="[Knowledge Graph Context]\n  Russia —[INVOLVES]→ Ukraine")

        with patch("rag.retriever.embed_text", mock_embed), \
             patch("rag.retriever.httpx.AsyncClient") as mock_cls, \
             patch("rag.retriever.rerank_fn", mock_rerank), \
             patch("rag.retriever.get_graph_context_fn", mock_graph):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_qdrant_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await enhanced_search(
                "drone attack Ukraine",
                enable_hybrid=False,
                enable_rerank=True,
                enable_graph_context=True,
            )

        assert len(results) >= 1
        assert "graph_context" in results[0]
```

- [ ] **Step 2: Run tests, verify failure**

- [ ] **Step 3: Extend rag/retriever.py**

Keep existing `search()` function unchanged. Add:

```python
from rag.reranker import rerank as rerank_fn
from rag.graph_context import get_graph_context as get_graph_context_fn


async def enhanced_search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
    *,
    enable_hybrid: bool | None = None,
    enable_rerank: bool | None = None,
    enable_graph_context: bool | None = None,
) -> list[dict]:
    """Enhanced retrieval: dense search → optional rerank → optional graph context.

    Feature flags default to config.py settings if not explicitly passed.
    """
    # Use config defaults if not explicitly set
    if enable_hybrid is None:
        enable_hybrid = settings.enable_hybrid
    if enable_rerank is None:
        enable_rerank = settings.enable_rerank
    if enable_graph_context is None:
        enable_graph_context = settings.enable_graph_context

    # Stage 1: Dense search (baseline — always runs)
    results = await search(query, limit=limit * 2 if enable_rerank else limit,
                           region=region, source=source,
                           score_threshold=score_threshold)

    if not results:
        return []

    # Stage 2: Rerank (optional)
    if enable_rerank:
        results = await rerank_fn(query, results, top_k=limit)

    # Stage 3: Graph Context Injection (optional)
    if enable_graph_context:
        # Extract entity names from result payloads
        entity_names = set()
        for r in results:
            for e in r.get("entities", []):
                if isinstance(e, dict) and "name" in e:
                    entity_names.add(e["name"])
        if entity_names:
            graph_ctx = await get_graph_context_fn(list(entity_names))
            if graph_ctx:
                for r in results:
                    r["graph_context"] = graph_ctx

    return results
```

- [ ] **Step 4: Run tests, verify pass**

---

## Task 5: Update agent tool + final verification

**Files:**
- Modify: `agents/tools/qdrant_search.py`

- [ ] **Step 1: Update qdrant_search tool to use enhanced_search**

Replace the inline search logic with a call to `enhanced_search()`:

```python
from rag.retriever import enhanced_search

@tool
async def qdrant_search(query: str, region: str = "") -> str:
    """Search the intelligence knowledge base for relevant documents."""
    results = await enhanced_search(
        query,
        limit=5,
        region=region or None,
    )
    # ... format results as before ...
```

- [ ] **Step 2: Run full test suite**
- [ ] **Step 3: Commit**
