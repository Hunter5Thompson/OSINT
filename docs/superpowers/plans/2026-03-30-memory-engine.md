# ODIN Memory Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `services/memory` — a new FastAPI service (port 8004) that stores atomic IntelFacts in Neo4j, runs LLM-based resolution (UPDATES/EXTENDS/DERIVES), syncs to Qdrant via an outbox worker, and integrates with `services/intelligence` and `services/data-ingestion`.

**Architecture:** Facts arrive at `/ingest`, get SHA256-keyed, embedded via TEI, resolved against existing facts via semantic search + vLLM resolver, and written to Neo4j transactionally. An outbox worker syncs `is_latest` state to Qdrant asynchronously. `/recall` does vector search with entity filters and enriches results with Neo4j relation data.

**Tech Stack:** FastAPI 0.128+, `neo4j>=5.0` async driver, `qdrant-client>=1.13` async, `httpx`, `redis[hiredis]`, `pydantic-settings`, `structlog`, `pytest-asyncio`

---

## File Structure

```
services/memory/
├── pyproject.toml
├── Dockerfile
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── facts.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── ingest.py
│   │   └── recall.py
│   └── services/
│       ├── __init__.py
│       ├── hasher.py
│       ├── neo4j_client.py
│       ├── embed_client.py
│       ├── qdrant_service.py
│       ├── idempotency.py
│       ├── resolver.py
│       ├── orchestrator.py
│       └── outbox_worker.py
└── tests/
    ├── conftest.py
    └── unit/
        ├── __init__.py
        ├── test_hasher.py
        ├── test_idempotency.py
        └── test_resolver.py

Modified (other services):
services/intelligence/config.py           — add memory_url
services/intelligence/graph/nodes.py      — osint_node /recall, synthesis_node /ingest/sync
services/data-ingestion/config.py         — add memory_url
services/data-ingestion/feeds/rss_collector.py   — POST /ingest after Qdrant write
services/data-ingestion/feeds/gdelt_collector.py — POST /ingest after Qdrant write
docker-compose.yml                        — memory service + runtime: nvidia GPU fix
```

---

### Task 1: Project scaffold — pyproject.toml, Dockerfile, config.py, main.py skeleton

**Files:**
- Create: `services/memory/pyproject.toml`
- Create: `services/memory/Dockerfile`
- Create: `services/memory/app/__init__.py`
- Create: `services/memory/app/config.py`
- Create: `services/memory/app/main.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
# services/memory/pyproject.toml
[project]
name = "memory"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.128.0",
    "uvicorn[standard]>=0.34.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "httpx>=0.28.0",
    "neo4j>=5.0.0",
    "qdrant-client>=1.13.0",
    "redis[hiredis]>=5.0",
    "structlog>=25.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "ruff>=0.8",
    "mypy>=1.13",
    "respx>=0.22",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Write Dockerfile**

```dockerfile
# services/memory/Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY app/ app/
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
```

- [ ] **Step 3: Write app/__init__.py**

```python
```
(empty file)

- [ ] **Step 4: Write config.py**

```python
# services/memory/app/config.py
"""Memory service configuration — all values from env vars or .env."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Infrastructure
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # required — set NEO4J_PASSWORD in .env

    qdrant_url: str = "http://localhost:6333"
    qdrant_facts_collection: str = "odin_facts"

    redis_url: str = "redis://localhost:6379/0"

    # LLM / Embedding
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "models/qwen3.5-27b-awq"
    tei_embed_url: str = "http://localhost:8001"
    embed_dim: int = 1024

    # Resolution tuning
    resolution_score_threshold: float = 0.75
    resolver_confidence_threshold: float = 0.7
    corroboration_boost: float = 0.1
    default_confidence_raw: float = 0.8

    # Outbox worker
    outbox_batch_size: int = 50
    outbox_poll_interval: float = 5.0
    outbox_reconcile_interval: float = 60.0
    outbox_stale_lock_seconds: float = 120.0
    outbox_max_retries: int = 5

    # Idempotency
    idempotency_ttl: int = 86400  # 24h in seconds

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 5: Write main.py skeleton (lifespan stubs — filled in later tasks)**

```python
# services/memory/app/main.py
"""Memory Engine — FastAPI application."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: init connections. Shutdown: close them."""
    # Connections initialised in later tasks — stubs here
    logger.info("memory_service_started", port=8004)
    yield
    logger.info("memory_service_stopped")


app = FastAPI(
    title="ODIN Memory Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 6: Verify the app imports cleanly**

```bash
cd services/memory
uv sync
uv run python -c "from app.main import app; print('ok')"
```

Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add services/memory/
git commit -m "feat(memory): scaffold service — pyproject.toml, Dockerfile, config, main skeleton"
```

---

### Task 2: Pydantic models — facts.py

**Files:**
- Create: `services/memory/app/models/__init__.py`
- Create: `services/memory/app/models/facts.py`

- [ ] **Step 1: Write models/__init__.py** (empty)

- [ ] **Step 2: Write facts.py**

```python
# services/memory/app/models/facts.py
"""Pydantic models for the Memory Engine API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Ingest ──────────────────────────────────────────────────────────────────

class IngestItem(BaseModel):
    content: str = Field(..., description="Atomic fact content")
    source_ref: str = Field(..., description="e.g. 'rss:bellingcat' or 'gdelt:conflict_military'")
    source_url: str | None = None
    domain: Literal["osint", "sigint", "humint", "geoint", "techint", "analysis"] = "osint"
    entity_id: str = Field(..., description="Slugified entity identifier, e.g. 'pla_rocket_force'")


class IngestRequest(BaseModel):
    items: list[IngestItem] = Field(..., min_length=1)


# ── Resolution result (embedded in responses) ────────────────────────────────

class ResolutionInfo(BaseModel):
    relation: Literal["UPDATES", "EXTENDS", "DERIVES", "NONE"]
    target_fact_id: str | None = None
    reason: str
    resolver_confidence: float
    model_version: str
    trace_id: str


# ── Sync ingest response ─────────────────────────────────────────────────────

class FactResult(BaseModel):
    fact_id: str
    canonical_fact_id: str
    content: str
    entity_id: str
    confidence_raw: float
    confidence_final: float
    corroboration_count: int
    resolution: ResolutionInfo | None = None
    skipped: bool = False  # True when fact_id already existed


class SyncIngestResponse(BaseModel):
    ingest_id: str
    facts: list[FactResult]


# ── Async ingest response ────────────────────────────────────────────────────

class AsyncIngestResponse(BaseModel):
    ingest_id: str
    status: Literal["pending"] = "pending"
    item_count: int


class IngestStatusResponse(BaseModel):
    ingest_id: str
    status: Literal["pending", "processing", "done", "failed"]
    facts_extracted: int = 0
    facts_stored: int = 0
    error_code: str | None = None
    error: str | None = None


# ── Recall ───────────────────────────────────────────────────────────────────

class RecallRequest(BaseModel):
    query: str
    entity_id: str | None = None
    domain: Literal["osint", "sigint", "humint", "geoint", "techint", "analysis"] | None = None
    min_confidence: float = 0.6
    top_k: int = Field(default=10, ge=1, le=50)


class RelationLinks(BaseModel):
    updates_out: list[str] = Field(default_factory=list)
    updated_by: list[str] = Field(default_factory=list)
    extends_out: list[str] = Field(default_factory=list)
    extends_in: list[str] = Field(default_factory=list)
    derives_out: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)


class RecalledFact(BaseModel):
    fact_id: str
    content: str
    entity_id: str
    score: float
    confidence_final: float
    corroboration_count: int
    source_ref: str
    timestamp: datetime
    is_latest: bool
    relations: RelationLinks


class RecallResponse(BaseModel):
    facts: list[RecalledFact]


# ── Entity stub ──────────────────────────────────────────────────────────────

class EntityStubResponse(BaseModel):
    entity_id: str
    fact_count: int


# ── Health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
```

- [ ] **Step 3: Verify models import**

```bash
cd services/memory
uv run python -c "from app.models.facts import IngestRequest, RecallRequest; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add services/memory/app/models/
git commit -m "feat(memory): add Pydantic models for IntelFact API"
```

---

### Task 3: Hasher service (with unit tests)

**Files:**
- Create: `services/memory/app/services/__init__.py`
- Create: `services/memory/app/services/hasher.py`
- Create: `services/memory/tests/conftest.py`
- Create: `services/memory/tests/__init__.py`
- Create: `services/memory/tests/unit/__init__.py`
- Create: `services/memory/tests/unit/test_hasher.py`

- [ ] **Step 1: Write services/__init__.py** (empty)

- [ ] **Step 2: Write hasher.py**

```python
# services/memory/app/services/hasher.py
"""Deterministic SHA-256 hashing for IntelFact deduplication."""
import hashlib
import re
import uuid


def normalize(content: str) -> str:
    """Lowercase, strip, collapse whitespace. No stemming (v1)."""
    return re.sub(r"\s+", " ", content.lower().strip())


def compute_fact_id(entity_id: str, content: str, source_ref: str) -> str:
    """SHA256(entity_id || normalize(content) || source_ref) — unique per source."""
    raw = f"{entity_id}||{normalize(content)}||{source_ref}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_canonical_fact_id(entity_id: str, content: str) -> str:
    """SHA256(entity_id || normalize(content)) — cross-source corroboration key."""
    raw = f"{entity_id}||{normalize(content)}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

- [ ] **Step 3: Write tests/conftest.py**

```python
# services/memory/tests/conftest.py
"""Shared pytest configuration."""
```

- [ ] **Step 4: Write tests/__init__.py and tests/unit/__init__.py** (both empty)

- [ ] **Step 5: Write test_hasher.py**

```python
# services/memory/tests/unit/test_hasher.py
"""Unit tests for the hasher module."""
from app.services.hasher import (
    compute_canonical_fact_id,
    compute_fact_id,
    normalize,
)


class TestNormalize:
    def test_lowercases(self) -> None:
        assert normalize("PLA Rocket Force") == "pla rocket force"

    def test_strips_whitespace(self) -> None:
        assert normalize("  hello  ") == "hello"

    def test_collapses_internal_spaces(self) -> None:
        assert normalize("hello   world") == "hello world"

    def test_combined(self) -> None:
        assert normalize("  PLA  Rocket  Force  ") == "pla rocket force"


class TestComputeFactId:
    def test_deterministic(self) -> None:
        fid1 = compute_fact_id("entity_a", "content x", "rss:source1")
        fid2 = compute_fact_id("entity_a", "content x", "rss:source1")
        assert fid1 == fid2

    def test_different_sources_produce_different_ids(self) -> None:
        fid1 = compute_fact_id("entity_a", "content x", "rss:source1")
        fid2 = compute_fact_id("entity_a", "content x", "rss:source2")
        assert fid1 != fid2

    def test_normalizes_content(self) -> None:
        fid1 = compute_fact_id("entity_a", "Content X", "src")
        fid2 = compute_fact_id("entity_a", "content x", "src")
        assert fid1 == fid2

    def test_returns_64_char_hex(self) -> None:
        fid = compute_fact_id("e", "c", "s")
        assert len(fid) == 64
        assert all(c in "0123456789abcdef" for c in fid)


class TestComputeCanonicalFactId:
    def test_same_content_different_source_produces_same_canonical(self) -> None:
        c1 = compute_canonical_fact_id("entity_a", "content x")
        c2 = compute_canonical_fact_id("entity_a", "content x")
        assert c1 == c2

    def test_different_from_fact_id(self) -> None:
        fid = compute_fact_id("e", "c", "s")
        cfid = compute_canonical_fact_id("e", "c")
        assert fid != cfid


```

- [ ] **Step 6: Run tests — expect all pass**

```bash
cd services/memory
uv run pytest tests/unit/test_hasher.py -v
```

Expected: `10 passed`

- [ ] **Step 7: Commit**

```bash
git add services/memory/app/services/ services/memory/tests/
git commit -m "feat(memory): add hasher service with SHA256 + normalize + 10 unit tests"
```

---

### Task 4: Neo4j client — connection, schema setup, write operations

**Files:**
- Create: `services/memory/app/services/neo4j_client.py`

- [ ] **Step 1: Write neo4j_client.py**

```python
# services/memory/app/services/neo4j_client.py
"""Async Neo4j driver wrapper with schema setup and IntelFact write operations."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import ConstraintError

from app.config import Settings

log = structlog.get_logger()

_SCHEMA_QUERIES = [
    "CREATE CONSTRAINT unique_fact_id IF NOT EXISTS FOR (f:IntelFact) REQUIRE f.fact_id IS UNIQUE",
    "CREATE CONSTRAINT unique_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
    "CREATE INDEX fact_entity_latest IF NOT EXISTS FOR (f:IntelFact) ON (f.entity_id, f.is_latest, f.timestamp)",
    "CREATE INDEX fact_canonical IF NOT EXISTS FOR (f:IntelFact) ON (f.canonical_fact_id)",
    "CREATE INDEX fact_sync_status IF NOT EXISTS FOR (f:IntelFact) ON (f.qdrant_sync_status)",
]


def build_driver(settings: Settings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.neo4j_url,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


async def setup_schema(driver: AsyncDriver) -> None:
    """Idempotent: create constraints + indices if they don't exist."""
    async with driver.session() as session:
        for q in _SCHEMA_QUERIES:
            await session.run(q)
    log.info("neo4j_schema_ready")


async def ensure_entity(
    driver: AsyncDriver,
    entity_id: str,
    entity_type: str = "unknown",
    display_name: str | None = None,
) -> None:
    """MERGE Entity node — creates if missing, updates updated_at if exists."""
    now = datetime.now(timezone.utc).isoformat()
    display = display_name or entity_id

    async def _tx(tx) -> None:  # type: ignore[no-untyped-def]
        await tx.run(
            """
            MERGE (e:Entity {entity_id: $entity_id})
            ON CREATE SET e.entity_type = $entity_type,
                          e.display_name = $display_name,
                          e.created_at = $now,
                          e.updated_at = $now
            ON MATCH SET  e.updated_at = $now
            """,
            entity_id=entity_id,
            entity_type=entity_type,
            display_name=display,
            now=now,
        )

    async with driver.session() as session:
        await session.execute_write(_tx)


async def fact_exists(driver: AsyncDriver, fact_id: str) -> bool:
    """Advisory idempotency check — not race-safe, reduces unnecessary work."""
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:IntelFact {fact_id: $fid}) RETURN count(f) AS n",
            fid=fact_id,
        )
        record = await result.single()
        return bool(record and record["n"] > 0)


async def write_fact(
    driver: AsyncDriver,
    fact_props: dict,
    entity_id: str,
    relation_type: str | None = None,
    target_fact_id: str | None = None,
    rel_props: dict | None = None,
) -> bool:
    """
    Write a new IntelFact node. Returns True if created, False if duplicate (skip).

    relation_type: one of "UPDATES", "EXTENDS", "DERIVES", or None.
    If "UPDATES", also sets target.is_latest = false and target.qdrant_sync_status = "pending".
    """

    async def _tx(tx) -> None:  # type: ignore[no-untyped-def]
        # 1. Create the new fact (raises ConstraintError if duplicate)
        await tx.run(
            """
            CREATE (f:IntelFact $props)
            """,
            props=fact_props,
        )
        # 2. ABOUT edge
        await tx.run(
            """
            MATCH (f:IntelFact {fact_id: $fid}), (e:Entity {entity_id: $eid})
            CREATE (f)-[:ABOUT]->(e)
            """,
            fid=fact_props["fact_id"],
            eid=entity_id,
        )
        # 3. Resolution edge (optional)
        if relation_type and target_fact_id and rel_props:
            if relation_type == "UPDATES":
                await tx.run(
                    """
                    MATCH (old:IntelFact {fact_id: $tid})
                    SET old.is_latest = false, old.qdrant_sync_status = "pending"
                    """,
                    tid=target_fact_id,
                )
            cypher_rel = (
                f"MATCH (new:IntelFact {{fact_id: $fid}}), (target:IntelFact {{fact_id: $tid}})\n"
                f"CREATE (new)-[:{relation_type} $rel_props]->(target)"
            )
            await tx.run(
                cypher_rel,
                fid=fact_props["fact_id"],
                tid=target_fact_id,
                rel_props=rel_props,
            )

    try:
        async with driver.session() as session:
            await session.execute_write(_tx)
        return True
    except ConstraintError:
        log.debug("neo4j_fact_duplicate_skipped", fact_id=fact_props.get("fact_id"))
        return False


async def update_corroboration(
    driver: AsyncDriver,
    fact_id: str,
    corroborating_source_ref: str,
    boost: float,
) -> None:
    """
    Add corroboration to an existing fact.
    Adds source_ref to corroboration_sources list, increments count, boosts confidence_final.
    """

    async def _tx(tx) -> None:  # type: ignore[no-untyped-def]
        await tx.run(
            """
            MATCH (f:IntelFact {fact_id: $fid})
            SET f.corroboration_count = coalesce(f.corroboration_count, 0) + 1,
                f.confidence_final = min(coalesce(f.confidence_final, 0.8) + $boost, 1.0),
                f.corroboration_sources = coalesce(f.corroboration_sources, []) + [$src],
                f.qdrant_sync_status = "pending"
            """,
            fid=fact_id,
            src=corroborating_source_ref,
            boost=boost,
        )

    async with driver.session() as session:
        await session.execute_write(_tx)


async def claim_outbox_batch(
    driver: AsyncDriver,
    worker_id: str,
    batch_size: int,
    now: datetime,
) -> list[dict]:
    """Claim up to batch_size pending facts for Qdrant sync. Returns list of fact dicts."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:IntelFact)
            WHERE f.qdrant_sync_status = "pending"
              AND f.qdrant_sync_retry_count < $max_retries
              AND (f.qdrant_sync_next_retry_at IS NULL OR f.qdrant_sync_next_retry_at <= $now)
            WITH f LIMIT $batch_size
            SET f.qdrant_sync_status = "in_progress",
                f.qdrant_sync_worker_id = $worker_id,
                f.qdrant_sync_in_progress_at = $now
            RETURN f
            """,
            max_retries=5,
            now=now,
            batch_size=batch_size,
            worker_id=worker_id,
        )
        records = await result.data()
        return [r["f"] for r in records]


async def mark_outbox_done(driver: AsyncDriver, fact_id: str) -> None:
    async with driver.session() as session:
        await session.run(
            'MATCH (f:IntelFact {fact_id: $fid}) SET f.qdrant_sync_status = "done"',
            fid=fact_id,
        )


async def mark_outbox_retry(
    driver: AsyncDriver,
    fact_id: str,
    retry_count: int,
    next_retry_at: datetime,
) -> None:
    async with driver.session() as session:
        await session.run(
            """
            MATCH (f:IntelFact {fact_id: $fid})
            SET f.qdrant_sync_status = "pending",
                f.qdrant_sync_retry_count = $retry_count,
                f.qdrant_sync_next_retry_at = $next_retry_at
            """,
            fid=fact_id,
            retry_count=retry_count,
            next_retry_at=next_retry_at,
        )


async def mark_outbox_permanent_fail(driver: AsyncDriver, fact_id: str) -> None:
    async with driver.session() as session:
        await session.run(
            'MATCH (f:IntelFact {fact_id: $fid}) SET f.qdrant_sync_status = "failed_permanent"',
            fid=fact_id,
        )


async def reconcile_stale_locks(
    driver: AsyncDriver,
    stale_before: datetime,
) -> int:
    """Reset in_progress facts whose lock is older than stale_before. Returns count reset."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:IntelFact {qdrant_sync_status: "in_progress"})
            WHERE f.qdrant_sync_in_progress_at < $stale_before
            SET f.qdrant_sync_status = "pending",
                f.qdrant_sync_worker_id = null,
                f.qdrant_sync_next_retry_at = null
            RETURN count(f) AS n
            """,
            stale_before=stale_before,
        )
        record = await result.single()
        return int(record["n"]) if record else 0


async def get_fact_relations(driver: AsyncDriver, fact_id: str) -> dict:
    """Return relation lists for a fact (for /recall enrichment)."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:IntelFact {fact_id: $fid})
            OPTIONAL MATCH (f)-[:UPDATES]->(u_out:IntelFact)
            OPTIONAL MATCH (f)<-[:UPDATES]-(u_in:IntelFact)
            OPTIONAL MATCH (f)-[:EXTENDS]->(e_out:IntelFact)
            OPTIONAL MATCH (f)<-[:EXTENDS]-(e_in:IntelFact)
            OPTIONAL MATCH (f)-[:DERIVES]->(d_out:IntelFact)
            OPTIONAL MATCH (f)<-[:DERIVES]-(d_in:IntelFact)
            RETURN
              collect(DISTINCT u_out.fact_id) AS updates_out,
              collect(DISTINCT u_in.fact_id)  AS updated_by,
              collect(DISTINCT e_out.fact_id) AS extends_out,
              collect(DISTINCT e_in.fact_id)  AS extends_in,
              collect(DISTINCT d_out.fact_id) AS derives_out,
              collect(DISTINCT d_in.fact_id)  AS derived_from
            """,
            fid=fact_id,
        )
        record = await result.single()
        if not record:
            return {}
        return {
            "updates_out": [x for x in record["updates_out"] if x],
            "updated_by": [x for x in record["updated_by"] if x],
            "extends_out": [x for x in record["extends_out"] if x],
            "extends_in": [x for x in record["extends_in"] if x],
            "derives_out": [x for x in record["derives_out"] if x],
            "derived_from": [x for x in record["derived_from"] if x],
        }


async def count_facts_for_entity(driver: AsyncDriver, entity_id: str) -> int:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:IntelFact {entity_id: $eid}) RETURN count(f) AS n",
            eid=entity_id,
        )
        record = await result.single()
        return int(record["n"]) if record else 0
```

- [ ] **Step 2: Verify import**

```bash
cd services/memory
uv run python -c "from app.services.neo4j_client import build_driver, setup_schema; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add services/memory/app/services/neo4j_client.py
git commit -m "feat(memory): add Neo4j async client with schema setup and outbox operations"
```

---

### Task 5: Embed client + Qdrant service

**Files:**
- Create: `services/memory/app/services/embed_client.py`
- Create: `services/memory/app/services/qdrant_service.py`

- [ ] **Step 1: Write embed_client.py**

```python
# services/memory/app/services/embed_client.py
"""TEI (Text Embeddings Inference) HTTP client for 1024-dim embeddings."""
import httpx
import structlog

log = structlog.get_logger()


async def embed(http_client: httpx.AsyncClient, tei_url: str, text: str) -> list[float]:
    """Return a 1024-dim embedding vector for text."""
    resp = await http_client.post(
        f"{tei_url}/embed",
        json={"inputs": text},
        timeout=30.0,
    )
    resp.raise_for_status()
    result = resp.json()
    # TEI returns [[...floats...]] for single input
    return result[0] if isinstance(result[0], list) else result
```

- [ ] **Step 2: Write qdrant_service.py**

```python
# services/memory/app/services/qdrant_service.py
"""Qdrant async operations: collection setup, semantic search, upsert."""
from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

log = structlog.get_logger()


async def setup_collection(qdrant: AsyncQdrantClient, collection: str, dim: int) -> None:
    """Create odin_facts collection if it does not exist."""
    existing = await qdrant.get_collections()
    names = [c.name for c in existing.collections]
    if collection not in names:
        await qdrant.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        log.info("qdrant_collection_created", collection=collection)


async def semantic_search(
    qdrant: AsyncQdrantClient,
    collection: str,
    vector: list[float],
    entity_id: str,
    is_latest: bool = True,
    top_k: int = 10,
) -> list[dict]:
    """Search by vector, filtered by entity_id and is_latest. Returns list of {fact_id, score, payload}."""
    filt = Filter(
        must=[
            FieldCondition(key="entity_id", match=MatchValue(value=entity_id)),
            FieldCondition(key="is_latest", match=MatchValue(value=is_latest)),
        ]
    )
    results = await qdrant.search(
        collection_name=collection,
        query_vector=vector,
        query_filter=filt,
        limit=top_k,
        with_payload=True,
    )
    return [
        {"fact_id": r.payload.get("fact_id", ""), "score": r.score, "payload": r.payload}
        for r in results
        if r.payload
    ]


async def corroboration_search(
    qdrant: AsyncQdrantClient,
    collection: str,
    canonical_fact_id: str,
    top_k: int = 3,
) -> list[dict]:
    """Find existing facts sharing the same canonical_fact_id (cross-source corroboration)."""
    filt = Filter(
        must=[
            FieldCondition(
                key="canonical_fact_id",
                match=MatchValue(value=canonical_fact_id),
            )
        ]
    )
    results = await qdrant.scroll(
        collection_name=collection,
        scroll_filter=filt,
        limit=top_k,
        with_payload=True,
    )
    points = results[0]
    return [
        {"fact_id": p.payload.get("fact_id", ""), "payload": p.payload}
        for p in points
        if p.payload
    ]


async def recall_search(
    qdrant: AsyncQdrantClient,
    collection: str,
    vector: list[float],
    entity_id: str | None,
    domain: str | None,
    min_confidence: float,
    top_k: int,
) -> list[dict]:
    """Semantic search for /recall endpoint with optional filters.

    Note: min_confidence filters payload.confidence_final, not vector similarity score.
    """
    must_conditions = [
        FieldCondition(key="is_latest", match=MatchValue(value=True)),
        FieldCondition(key="confidence_final", range=Range(gte=min_confidence)),
    ]
    if entity_id:
        must_conditions.append(
            FieldCondition(key="entity_id", match=MatchValue(value=entity_id))
        )
    if domain:
        must_conditions.append(
            FieldCondition(key="domain", match=MatchValue(value=domain))
        )
    filt = Filter(must=must_conditions)
    results = await qdrant.search(
        collection_name=collection,
        query_vector=vector,
        query_filter=filt,
        limit=top_k,
        with_payload=True,
    )
    return [
        {"fact_id": r.payload.get("fact_id", ""), "score": r.score, "payload": r.payload}
        for r in results
        if r.payload
    ]


async def upsert_fact(
    qdrant: AsyncQdrantClient,
    collection: str,
    fact_id: str,
    vector: list[float],
    payload: dict,
) -> None:
    """Upsert a single IntelFact into Qdrant using fact_id as bridge key. Idempotent."""
    await qdrant.upsert(
        collection_name=collection,
        points=[PointStruct(id=fact_id, vector=vector, payload=payload)],
    )
```

- [ ] **Step 3: Verify imports**

```bash
cd services/memory
uv run python -c "from app.services.embed_client import embed; from app.services.qdrant_service import setup_collection; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add services/memory/app/services/embed_client.py services/memory/app/services/qdrant_service.py
git commit -m "feat(memory): add embed client (TEI) and Qdrant async service"
```

---

### Task 6: Idempotency service (with unit tests)

**Files:**
- Create: `services/memory/app/services/idempotency.py`
- Create: `services/memory/tests/unit/test_idempotency.py`

- [ ] **Step 1: Write idempotency.py**

```python
# services/memory/app/services/idempotency.py
"""Redis-backed idempotency key management for /ingest endpoints."""
from __future__ import annotations

import hashlib
import json
from enum import Enum

import redis.asyncio as aioredis


class IdempotencyStatus(str, Enum):
    HIT = "hit"           # Key exists, body matches — return cached response
    CONFLICT = "conflict" # Key exists, body hash differs — return 409
    MISS = "miss"         # Key not seen before


async def check(
    redis_client: aioredis.Redis,
    key: str,
    body_bytes: bytes,
) -> tuple[IdempotencyStatus, bytes | None]:
    """
    Check idempotency key against Redis.
    Returns (HIT, cached_response_bytes) | (CONFLICT, None) | (MISS, None).
    """
    stored = await redis_client.hgetall(f"idempotency:{key}")
    if not stored:
        return IdempotencyStatus.MISS, None

    stored_body_hash = stored.get(b"body_hash", b"").decode()
    request_body_hash = hashlib.sha256(body_bytes).hexdigest()

    if stored_body_hash == request_body_hash:
        cached = stored.get(b"response", b"")
        return IdempotencyStatus.HIT, cached

    return IdempotencyStatus.CONFLICT, None


async def store(
    redis_client: aioredis.Redis,
    key: str,
    body_bytes: bytes,
    response_bytes: bytes,
    ttl: int,
) -> None:
    """Store idempotency key with body hash + response. Expires after ttl seconds."""
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    pipe = redis_client.pipeline()
    pipe.hset(
        f"idempotency:{key}",
        mapping={"body_hash": body_hash, "response": response_bytes},
    )
    pipe.expire(f"idempotency:{key}", ttl)
    await pipe.execute()
```

- [ ] **Step 2: Write test_idempotency.py**

```python
# services/memory/tests/unit/test_idempotency.py
"""Unit tests for the idempotency service."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.idempotency import IdempotencyStatus, check, store


class TestCheck:
    async def test_miss_when_key_not_in_redis(self) -> None:
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={})
        status, cached = await check(redis, "key1", b'{"items":[]}')
        assert status == IdempotencyStatus.MISS
        assert cached is None

    async def test_hit_when_key_and_body_match(self) -> None:
        import hashlib

        body = b'{"items":[]}'
        body_hash = hashlib.sha256(body).hexdigest()
        cached_response = b'{"ingest_id":"abc"}'

        redis = AsyncMock()
        redis.hgetall = AsyncMock(
            return_value={b"body_hash": body_hash.encode(), b"response": cached_response}
        )
        status, cached = await check(redis, "key1", body)
        assert status == IdempotencyStatus.HIT
        assert cached == cached_response

    async def test_conflict_when_body_differs(self) -> None:
        import hashlib

        body_stored = b'{"items":[]}'
        body_stored_hash = hashlib.sha256(body_stored).hexdigest()

        redis = AsyncMock()
        redis.hgetall = AsyncMock(
            return_value={b"body_hash": body_stored_hash.encode(), b"response": b"{}"}
        )
        # Different body
        status, cached = await check(redis, "key1", b'{"items":[{"x":1}]}')
        assert status == IdempotencyStatus.CONFLICT
        assert cached is None


class TestStore:
    async def test_stores_body_hash_and_response(self) -> None:
        redis = AsyncMock()
        pipe = AsyncMock()
        pipe.hset = AsyncMock()
        pipe.expire = AsyncMock()
        pipe.execute = AsyncMock(return_value=[1, 1])
        redis.pipeline = MagicMock(return_value=pipe)

        await store(redis, "key1", b'{"items":[]}', b'{"ingest_id":"x"}', 86400)

        pipe.hset.assert_called_once()
        pipe.expire.assert_called_once_with("idempotency:key1", 86400)
```

- [ ] **Step 3: Run tests**

```bash
cd services/memory
uv run pytest tests/unit/test_idempotency.py -v
```

Expected: `4 passed`

- [ ] **Step 4: Commit**

```bash
git add services/memory/app/services/idempotency.py services/memory/tests/unit/test_idempotency.py
git commit -m "feat(memory): add Redis idempotency service with 4 unit tests"
```

---

### Task 7: vLLM Resolver (with unit tests)

**Files:**
- Create: `services/memory/app/services/resolver.py`
- Create: `services/memory/tests/unit/test_resolver.py`

- [ ] **Step 1: Write resolver.py**

```python
# services/memory/app/services/resolver.py
"""vLLM-based resolution: determines UPDATES / EXTENDS / DERIVES / NONE between facts."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal

import httpx
import structlog

log = structlog.get_logger()

RESOLVER_SYSTEM_PROMPT = """You are a fact resolution engine for an intelligence database.
Given a new intelligence fact and a list of candidate existing facts, determine the relationship.

Output ONLY valid JSON (no markdown, no explanation):
{
  "relation": "UPDATES" | "EXTENDS" | "DERIVES" | "NONE",
  "target_fact_id": "<sha256 hex of the best matching candidate, or null if NONE>",
  "reason": "<one sentence>",
  "resolver_confidence": 0.0
}

Rules:
- UPDATES: new fact directly contradicts or supersedes the candidate (e.g. newer count replaces old count, event status changed)
- EXTENDS: new fact adds non-contradictory information to the candidate (e.g. additional detail about the same event)
- DERIVES: new fact is a logical inference derived from the candidate (e.g. capability assessment from deployment data)
- NONE: no meaningful relationship with any candidate
- Only output UPDATES/EXTENDS/DERIVES if resolver_confidence >= 0.7, otherwise output NONE"""


@dataclass
class ResolutionResult:
    relation: Literal["UPDATES", "EXTENDS", "DERIVES", "NONE"]
    target_fact_id: str | None
    reason: str
    resolver_confidence: float
    model_version: str
    trace_id: str


async def resolve(
    http_client: httpx.AsyncClient,
    vllm_url: str,
    vllm_model: str,
    new_fact_content: str,
    new_fact_entity_id: str,
    new_fact_domain: str,
    new_fact_source_ref: str,
    candidates: list[dict],
    confidence_threshold: float = 0.7,
) -> ResolutionResult:
    """
    Call vLLM to determine relation between new_fact and top candidates.
    Returns NONE if no candidates or vLLM confidence is below threshold.
    """
    trace_id = str(uuid.uuid4())
    model_version = f"{vllm_model}/v1"

    if not candidates:
        return ResolutionResult(
            relation="NONE",
            target_fact_id=None,
            reason="No candidates found",
            resolver_confidence=0.0,
            model_version=model_version,
            trace_id=trace_id,
        )

    user_content = json.dumps(
        {
            "new_fact": {
                "content": new_fact_content,
                "entity_id": new_fact_entity_id,
                "domain": new_fact_domain,
                "source_ref": new_fact_source_ref,
            },
            "candidates": [
                {
                    "fact_id": c.get("fact_id"),
                    "content": c.get("payload", {}).get("content", ""),
                    "confidence_final": c.get("payload", {}).get("confidence_final", 0.0),
                    "source_ref": c.get("payload", {}).get("source_ref", ""),
                    "score": c.get("score", 0.0),
                }
                for c in candidates[:5]  # top-5 only
            ],
        }
    )

    try:
        resp = await http_client.post(
            f"{vllm_url}/v1/chat/completions",
            json={
                "model": vllm_model,
                "messages": [
                    {"role": "system", "content": RESOLVER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.0,
                "max_tokens": 256,
                "response_format": {"type": "json_object"},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        log.warning("resolver_failed", error=str(exc), trace_id=trace_id)
        return ResolutionResult(
            relation="NONE",
            target_fact_id=None,
            reason=f"Resolver error: {exc}",
            resolver_confidence=0.0,
            model_version=model_version,
            trace_id=trace_id,
        )

    relation = parsed.get("relation", "NONE")
    rc = float(parsed.get("resolver_confidence", 0.0))

    # Enforce confidence threshold
    if relation != "NONE" and rc < confidence_threshold:
        relation = "NONE"
        parsed["target_fact_id"] = None

    return ResolutionResult(
        relation=relation,
        target_fact_id=parsed.get("target_fact_id"),
        reason=parsed.get("reason", ""),
        resolver_confidence=rc,
        model_version=model_version,
        trace_id=trace_id,
    )
```

- [ ] **Step 2: Write test_resolver.py**

```python
# services/memory/tests/unit/test_resolver.py
"""Unit tests for the resolver module."""
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from app.services.resolver import RESOLVER_SYSTEM_PROMPT, ResolutionResult, resolve


VLLM_URL = "http://localhost:8000"
MODEL = "models/test"


def _mock_vllm_response(relation: str, target_id: str | None, confidence: float) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "relation": relation,
                            "target_fact_id": target_id,
                            "reason": "test reason",
                            "resolver_confidence": confidence,
                        }
                    )
                }
            }
        ]
    }


class TestResolveNoCandidates:
    async def test_returns_none_when_no_candidates(self) -> None:
        async with httpx.AsyncClient() as client:
            result = await resolve(
                client, VLLM_URL, MODEL,
                "Some fact", "entity_a", "osint", "rss:src",
                candidates=[],
            )
        assert result.relation == "NONE"
        assert result.target_fact_id is None


class TestResolveWithCandidates:
    @respx.mock
    async def test_updates_relation_returned(self) -> None:
        target = "a" * 64
        respx.post(f"{VLLM_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=_mock_vllm_response("UPDATES", target, 0.9)
            )
        )
        async with httpx.AsyncClient() as client:
            result = await resolve(
                client, VLLM_URL, MODEL,
                "New fact", "entity_a", "osint", "rss:src2",
                candidates=[{"fact_id": target, "score": 0.9, "payload": {"content": "Old fact", "confidence_final": 0.8, "source_ref": "rss:src1"}}],
            )
        assert result.relation == "UPDATES"
        assert result.target_fact_id == target
        assert result.resolver_confidence == 0.9

    @respx.mock
    async def test_low_confidence_forces_none(self) -> None:
        target = "b" * 64
        respx.post(f"{VLLM_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=_mock_vllm_response("UPDATES", target, 0.5)
            )
        )
        async with httpx.AsyncClient() as client:
            result = await resolve(
                client, VLLM_URL, MODEL,
                "New fact", "entity_a", "osint", "rss:src",
                candidates=[{"fact_id": target, "score": 0.85, "payload": {"content": "old", "confidence_final": 0.7, "source_ref": "rss:x"}}],
            )
        assert result.relation == "NONE"

    @respx.mock
    async def test_http_error_returns_none(self) -> None:
        respx.post(f"{VLLM_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        async with httpx.AsyncClient() as client:
            result = await resolve(
                client, VLLM_URL, MODEL,
                "New fact", "entity_a", "osint", "rss:src",
                candidates=[{"fact_id": "c" * 64, "score": 0.9, "payload": {}}],
            )
        assert result.relation == "NONE"
```

- [ ] **Step 3: Run tests**

```bash
cd services/memory
uv run pytest tests/unit/test_resolver.py -v
```

Expected: `4 passed`

- [ ] **Step 4: Commit**

```bash
git add services/memory/app/services/resolver.py services/memory/tests/unit/test_resolver.py
git commit -m "feat(memory): add vLLM resolver with UPDATES/EXTENDS/DERIVES/NONE + 4 unit tests"
```

---

### Task 8: Resolution orchestrator

**Files:**
- Create: `services/memory/app/services/orchestrator.py`

- [ ] **Step 1: Write orchestrator.py**

```python
# services/memory/app/services/orchestrator.py
"""
End-to-end resolution flow for a single IngestItem:
  hash → advisory check → embed → qdrant search → corroboration → resolver → neo4j write
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.models.facts import FactResult, IngestItem, ResolutionInfo
from app.services import embed_client, neo4j_client, qdrant_service, resolver
from app.services.hasher import compute_canonical_fact_id, compute_fact_id

log = structlog.get_logger()


async def orchestrate_fact(
    item: IngestItem,
    settings: Settings,
    driver: AsyncDriver,
    qdrant: AsyncQdrantClient,
    http: httpx.AsyncClient,
) -> FactResult:
    """
    Process one IngestItem through the full resolution pipeline.
    Returns FactResult (with skipped=True if fact_id already exists).
    """
    # 1. Compute hashes
    fact_id = compute_fact_id(item.entity_id, item.content, item.source_ref)
    canonical_fact_id = compute_canonical_fact_id(item.entity_id, item.content)

    # 2. Advisory idempotency check (not race-safe — see write_fact for primary guard)
    if await neo4j_client.fact_exists(driver, fact_id):
        log.debug("fact_advisory_skip", fact_id=fact_id)
        return FactResult(
            fact_id=fact_id,
            canonical_fact_id=canonical_fact_id,
            content=item.content,
            entity_id=item.entity_id,
            confidence_raw=settings.default_confidence_raw,
            confidence_final=settings.default_confidence_raw,
            corroboration_count=0,
            resolution=None,
            skipped=True,
        )

    # 3. Ensure entity exists
    await neo4j_client.ensure_entity(driver, item.entity_id)

    # 4. Embed
    vector = await embed_client.embed(http, settings.tei_embed_url, item.content)

    # 5. Semantic search — top-10, entity + is_latest
    candidates = await qdrant_service.semantic_search(
        qdrant,
        settings.qdrant_facts_collection,
        vector,
        item.entity_id,
        is_latest=True,
        top_k=10,
    )

    # 6. Corroboration search — same canonical_fact_id, different sources
    corroboration_hits = await qdrant_service.corroboration_search(
        qdrant,
        settings.qdrant_facts_collection,
        canonical_fact_id,
        top_k=3,
    )

    # 7. Apply corroboration boost
    confidence_raw = settings.default_confidence_raw
    confidence_final = confidence_raw
    corroboration_count = 0
    corroboration_sources: list[str] = []

    for hit in corroboration_hits:
        payload = hit.get("payload", {})
        existing_src = payload.get("source_ref", "")
        existing_corroboration_sources: list[str] = payload.get("corroboration_sources", [])

        # Only boost if different source AND not already corroborated by us
        if (
            existing_src != item.source_ref
            and item.source_ref not in existing_corroboration_sources
        ):
            confidence_final = min(confidence_final + settings.corroboration_boost, 1.0)
            corroboration_count += 1
            corroboration_sources.append(existing_src)
            # Update existing fact's corroboration in Neo4j
            existing_fact_id = hit.get("fact_id", "")
            if existing_fact_id:
                await neo4j_client.update_corroboration(
                    driver,
                    existing_fact_id,
                    item.source_ref,
                    settings.corroboration_boost,
                )

    # 8. Call resolver if any candidate exceeds score threshold
    max_score = max((c.get("score", 0.0) for c in candidates), default=0.0)
    resolution_result = None

    if max_score > settings.resolution_score_threshold:
        resolution_result = await resolver.resolve(
            http,
            settings.vllm_url,
            settings.vllm_model,
            new_fact_content=item.content,
            new_fact_entity_id=item.entity_id,
            new_fact_domain=item.domain,
            new_fact_source_ref=item.source_ref,
            candidates=candidates,
            confidence_threshold=settings.resolver_confidence_threshold,
        )

    # 9. Build fact_props for Neo4j
    now = datetime.now(timezone.utc).isoformat()
    fact_props = {
        "fact_id": fact_id,
        "canonical_fact_id": canonical_fact_id,
        "content": item.content,
        "entity_id": item.entity_id,
        "fact_type": "fact",
        "domain": item.domain,
        "source_ref": item.source_ref,
        "source_url": item.source_url,
        "confidence_raw": confidence_raw,
        "confidence_final": confidence_final,
        "corroboration_count": corroboration_count,
        "corroboration_sources": corroboration_sources,
        "is_latest": True,
        "timestamp": now,
        "valid_until": None,
        "model_version": "memory-engine/v1",
        "normalizer_version": "v1",
        "qdrant_sync_status": "pending",
        "qdrant_sync_worker_id": None,
        "qdrant_sync_in_progress_at": None,
        "qdrant_sync_retry_count": 0,
        "qdrant_sync_next_retry_at": None,
    }

    # 10. Write to Neo4j (transactional)
    relation_type = None
    target_fact_id = None
    rel_props = None
    resolution_info = None

    if resolution_result and resolution_result.relation != "NONE":
        relation_type = resolution_result.relation
        target_fact_id = resolution_result.target_fact_id
        rel_props = {
            "reason": resolution_result.reason,
            "resolver_confidence": resolution_result.resolver_confidence,
            "model_version": resolution_result.model_version,
            "trace_id": resolution_result.trace_id,
            "created_at": now,
        }
        resolution_info = ResolutionInfo(
            relation=resolution_result.relation,
            target_fact_id=target_fact_id,
            reason=resolution_result.reason,
            resolver_confidence=resolution_result.resolver_confidence,
            model_version=resolution_result.model_version,
            trace_id=resolution_result.trace_id,
        )

    created = await neo4j_client.write_fact(
        driver,
        fact_props=fact_props,
        entity_id=item.entity_id,
        relation_type=relation_type,
        target_fact_id=target_fact_id,
        rel_props=rel_props,
    )

    return FactResult(
        fact_id=fact_id,
        canonical_fact_id=canonical_fact_id,
        content=item.content,
        entity_id=item.entity_id,
        confidence_raw=confidence_raw,
        confidence_final=confidence_final,
        corroboration_count=corroboration_count,
        resolution=resolution_info,
        skipped=not created,
    )
```

- [ ] **Step 2: Verify import**

```bash
cd services/memory
uv run python -c "from app.services.orchestrator import orchestrate_fact; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add services/memory/app/services/orchestrator.py
git commit -m "feat(memory): add resolution orchestrator (hash→embed→search→resolve→neo4j write)"
```

---

### Task 9: Outbox worker

**Files:**
- Create: `services/memory/app/services/outbox_worker.py`

- [ ] **Step 1: Write outbox_worker.py**

```python
# services/memory/app/services/outbox_worker.py
"""
Background asyncio task: claims pending IntelFacts and syncs them to Qdrant.
Implements exponential backoff, permanent failure handling, and stale-lock reconciliation.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from fastapi import FastAPI
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.services import embed_client, neo4j_client
from app.services.qdrant_service import upsert_fact

log = structlog.get_logger()

PERMANENT_ERROR_CODES = {400, 422}  # Qdrant schema errors — no point retrying


def _backoff_seconds(retry_count: int) -> float:
    """Exponential backoff: 2^n * 5s + jitter(0–2s), max 300s."""
    base = min((2**retry_count) * 5, 300)
    return base + random.uniform(0, 2)


async def _sync_one_fact(
    fact: dict,
    driver: AsyncDriver,
    qdrant: AsyncQdrantClient,
    http: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Sync a single claimed fact to Qdrant, then mark done or schedule retry."""
    fact_id: str = fact.get("fact_id", "")
    retry_count: int = int(fact.get("qdrant_sync_retry_count", 0))

    try:
        # Re-embed if vector not cached (we always re-embed — vectors are not stored in Neo4j)
        vector = await embed_client.embed(http, settings.tei_embed_url, fact["content"])
        payload = {
            "fact_id": fact_id,
            "canonical_fact_id": fact.get("canonical_fact_id", ""),
            "entity_id": fact.get("entity_id", ""),
            "is_latest": fact.get("is_latest", True),
            "domain": fact.get("domain", "osint"),
            "confidence_final": fact.get("confidence_final", 0.8),
            "corroboration_count": fact.get("corroboration_count", 0),
            "fact_type": fact.get("fact_type", "fact"),
            "source_ref": fact.get("source_ref", ""),
            "timestamp": fact.get("timestamp", ""),
            "valid_until": fact.get("valid_until"),
            "content": fact.get("content", ""),
        }
        await upsert_fact(qdrant, settings.qdrant_facts_collection, fact_id, vector, payload)
        await neo4j_client.mark_outbox_done(driver, fact_id)
        log.debug("outbox_fact_synced", fact_id=fact_id)

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in PERMANENT_ERROR_CODES:
            log.error("outbox_permanent_fail", fact_id=fact_id, status=exc.response.status_code)
            await neo4j_client.mark_outbox_permanent_fail(driver, fact_id)
        else:
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=_backoff_seconds(retry_count))
            await neo4j_client.mark_outbox_retry(driver, fact_id, retry_count + 1, next_retry)

    except Exception as exc:  # noqa: BLE001
        log.warning("outbox_transient_error", fact_id=fact_id, error=str(exc))
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=_backoff_seconds(retry_count))
        await neo4j_client.mark_outbox_retry(driver, fact_id, retry_count + 1, next_retry)


async def run_outbox_worker(app: FastAPI) -> None:
    """
    Main outbox loop. Runs until task is cancelled.
    - Claims batch of pending facts every poll_interval seconds
    - Reconciles stale locks every reconcile_interval seconds
    """
    settings: Settings = app.state.settings
    driver: AsyncDriver = app.state.neo4j
    qdrant: AsyncQdrantClient = app.state.qdrant
    http: httpx.AsyncClient = app.state.http

    worker_id = str(uuid.uuid4())
    log.info("outbox_worker_started", worker_id=worker_id)

    reconcile_counter = 0.0

    try:
        while True:
            now = datetime.now(timezone.utc)

            # Reconcile stale locks periodically
            reconcile_counter += settings.outbox_poll_interval
            if reconcile_counter >= settings.outbox_reconcile_interval:
                stale_before = now - timedelta(seconds=settings.outbox_stale_lock_seconds)
                n = await neo4j_client.reconcile_stale_locks(driver, stale_before)
                if n > 0:
                    log.info("outbox_stale_locks_reset", count=n)
                reconcile_counter = 0.0

            # Claim batch
            batch = await neo4j_client.claim_outbox_batch(
                driver, worker_id, settings.outbox_batch_size, now
            )

            if batch:
                log.debug("outbox_batch_claimed", count=len(batch))
                for fact in batch:
                    await _sync_one_fact(fact, driver, qdrant, http, settings)

            await asyncio.sleep(settings.outbox_poll_interval)

    except asyncio.CancelledError:
        log.info("outbox_worker_stopped", worker_id=worker_id)
```

- [ ] **Step 2: Verify import**

```bash
cd services/memory
uv run python -c "from app.services.outbox_worker import run_outbox_worker; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add services/memory/app/services/outbox_worker.py
git commit -m "feat(memory): add Qdrant outbox worker with backoff + stale-lock reconciliation"
```

---

### Task 10: /ingest/sync router

**Files:**
- Create: `services/memory/app/routers/__init__.py`
- Create: `services/memory/app/routers/ingest.py`

- [ ] **Step 1: Write routers/__init__.py** (empty)

- [ ] **Step 2: Write ingest.py (sync endpoint only)**

```python
# services/memory/app/routers/ingest.py
"""Ingest router: POST /ingest/sync, POST /ingest, GET /ingest/{ingest_id}."""
from __future__ import annotations

import json
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.models.facts import (
    AsyncIngestResponse,
    IngestRequest,
    IngestStatusResponse,
    SyncIngestResponse,
)
from app.services.idempotency import IdempotencyStatus, check, store
from app.services.orchestrator import orchestrate_fact

router = APIRouter(tags=["ingest"])


@router.post("/ingest/sync", response_model=SyncIngestResponse)
async def ingest_sync(
    request: Request,
    body: IngestRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SyncIngestResponse | JSONResponse:
    """Synchronous ingest — max 2000 chars per item content."""
    settings: Settings = request.app.state.settings
    redis_client: aioredis.Redis = request.app.state.redis

    # Validate content length
    for item in body.items:
        if len(item.content) > 2000:
            raise HTTPException(status_code=400, detail=f"content exceeds 2000 chars for entity_id={item.entity_id}")

    # Idempotency check
    raw_body = await request.body()
    if idempotency_key:
        status, cached = await check(redis_client, idempotency_key, raw_body)
        if status == IdempotencyStatus.HIT:
            return JSONResponse(content=json.loads(cached))
        if status == IdempotencyStatus.CONFLICT:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_key_body_mismatch"},
            )

    driver: AsyncDriver = request.app.state.neo4j
    qdrant: AsyncQdrantClient = request.app.state.qdrant

    ingest_id = str(uuid.uuid4())
    fact_results = []

    for item in body.items:
        result = await orchestrate_fact(
            item,
            settings,
            driver,
            qdrant,
            request.app.state.http,
        )
        fact_results.append(result)

    response = SyncIngestResponse(ingest_id=ingest_id, facts=fact_results)

    # Store idempotency result
    if idempotency_key:
        response_bytes = response.model_dump_json().encode()
        await store(redis_client, idempotency_key, raw_body, response_bytes, settings.idempotency_ttl)

    return response


@router.post("/ingest", response_model=AsyncIngestResponse, status_code=202)
async def ingest_async(
    request: Request,
    body: IngestRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AsyncIngestResponse | JSONResponse:
    """Async bulk ingest — max 500 items, no per-item content limit."""
    if len(body.items) > 500:
        raise HTTPException(status_code=413, detail="max 500 items per request")

    settings: Settings = request.app.state.settings
    redis_client: aioredis.Redis = request.app.state.redis

    raw_body = await request.body()
    if idempotency_key:
        status, cached = await check(redis_client, idempotency_key, raw_body)
        if status == IdempotencyStatus.HIT:
            return JSONResponse(status_code=202, content=json.loads(cached))
        if status == IdempotencyStatus.CONFLICT:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_key_body_mismatch"},
            )

    ingest_id = str(uuid.uuid4())

    # Store job status in Redis
    await redis_client.hset(
        f"ingest_job:{ingest_id}",
        mapping={
            "status": "pending",
            "facts_extracted": 0,
            "facts_stored": 0,
            "item_count": len(body.items),
        },
    )
    await redis_client.expire(f"ingest_job:{ingest_id}", 86400)

    # Process in background
    background_tasks.add_task(
        _process_async_ingest,
        ingest_id,
        body,
        request.app.state,
    )

    response = AsyncIngestResponse(
        ingest_id=ingest_id,
        status="pending",
        item_count=len(body.items),
    )

    if idempotency_key:
        response_bytes = response.model_dump_json().encode()
        await store(redis_client, idempotency_key, raw_body, response_bytes, settings.idempotency_ttl)

    return response


async def _process_async_ingest(ingest_id: str, body: IngestRequest, state) -> None:  # type: ignore[no-untyped-def]
    """Background task: process all items and update job status in Redis."""
    import structlog

    log = structlog.get_logger()
    redis_client: aioredis.Redis = state.redis
    settings: Settings = state.settings

    await redis_client.hset(f"ingest_job:{ingest_id}", "status", "processing")

    stored = 0
    try:
        for item in body.items:
            result = await orchestrate_fact(
                item, settings, state.neo4j, state.qdrant, state.http
            )
            if not result.skipped:
                stored += 1

        await redis_client.hset(
            f"ingest_job:{ingest_id}",
            mapping={
                "status": "done",
                "facts_extracted": len(body.items),
                "facts_stored": stored,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.error("async_ingest_failed", ingest_id=ingest_id, error=str(exc))
        await redis_client.hset(
            f"ingest_job:{ingest_id}",
            mapping={"status": "failed", "error": str(exc)},
        )


@router.get("/ingest/{ingest_id}", response_model=IngestStatusResponse)
async def get_ingest_status(
    ingest_id: str,
    request: Request,
) -> IngestStatusResponse:
    """Poll async ingest job status."""
    redis_client: aioredis.Redis = request.app.state.redis
    data = await redis_client.hgetall(f"ingest_job:{ingest_id}")
    if not data:
        raise HTTPException(status_code=404, detail="ingest_id not found")
    return IngestStatusResponse(
        ingest_id=ingest_id,
        status=data.get(b"status", b"pending").decode(),
        facts_extracted=int(data.get(b"facts_extracted", b"0")),
        facts_stored=int(data.get(b"facts_stored", b"0")),
        error=data.get(b"error", b"").decode() or None,
    )
```

- [ ] **Step 3: Commit**

```bash
git add services/memory/app/routers/
git commit -m "feat(memory): add ingest router (POST /ingest/sync, POST /ingest, GET /ingest/{id})"
```

---

### Task 11: /recall + /entity/{id} stub + /health + wire main.py

**Files:**
- Create: `services/memory/app/routers/recall.py`
- Modify: `services/memory/app/main.py`

- [ ] **Step 1: Write recall.py**

```python
# services/memory/app/routers/recall.py
"""Recall router: POST /recall, GET /entity/{entity_id}, GET /health."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.models.facts import (
    EntityStubResponse,
    HealthResponse,
    RecalledFact,
    RecallRequest,
    RecallResponse,
    RelationLinks,
)
from app.services import embed_client, neo4j_client
from app.services.qdrant_service import recall_search

router = APIRouter(tags=["recall"])


@router.post("/recall", response_model=RecallResponse)
async def recall(request: Request, body: RecallRequest) -> RecallResponse:
    """Semantic recall: embed query → Qdrant search → Neo4j relation enrichment."""
    settings: Settings = request.app.state.settings
    qdrant: AsyncQdrantClient = request.app.state.qdrant
    driver: AsyncDriver = request.app.state.neo4j

    vector = await embed_client.embed(
        request.app.state.http, settings.tei_embed_url, body.query
    )

    hits = await recall_search(
        qdrant,
        settings.qdrant_facts_collection,
        vector,
        entity_id=body.entity_id,
        domain=body.domain,
        min_confidence=body.min_confidence,
        top_k=body.top_k,
    )

    facts = []
    for hit in hits:
        payload = hit.get("payload", {})
        fact_id = hit.get("fact_id", "")

        relations_raw = await neo4j_client.get_fact_relations(driver, fact_id)
        relations = RelationLinks(**relations_raw) if relations_raw else RelationLinks()

        ts_raw = payload.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.min
        except ValueError:
            ts = datetime.min

        facts.append(
            RecalledFact(
                fact_id=fact_id,
                content=payload.get("content", ""),
                entity_id=payload.get("entity_id", ""),
                score=hit.get("score", 0.0),
                confidence_final=payload.get("confidence_final", 0.0),
                corroboration_count=payload.get("corroboration_count", 0),
                source_ref=payload.get("source_ref", ""),
                timestamp=ts,
                is_latest=payload.get("is_latest", True),
                relations=relations,
            )
        )

    return RecallResponse(facts=facts)


@router.get("/entity/{entity_id}", response_model=EntityStubResponse)
async def get_entity(entity_id: str, request: Request) -> EntityStubResponse:
    """v1 stub: returns entity_id + fact count."""
    driver: AsyncDriver = request.app.state.neo4j
    count = await neo4j_client.count_facts_for_entity(driver, entity_id)
    if count == 0:
        # Check entity exists at all
        raise HTTPException(status_code=404, detail="entity not found")
    return EntityStubResponse(entity_id=entity_id, fact_count=count)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()
```

- [ ] **Step 2: Replace main.py with fully wired version**

```python
# services/memory/app/main.py
"""Memory Engine — FastAPI application."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient

from app.config import settings
from app.routers import ingest as ingest_router
from app.routers import recall as recall_router
from app.services.neo4j_client import build_driver, setup_schema
from app.services.outbox_worker import run_outbox_worker
from app.services.qdrant_service import setup_collection

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: init all connections + outbox worker. Shutdown: clean up."""
    # Store settings on app state for router access
    app.state.settings = settings

    # Neo4j
    driver = build_driver(settings)
    await setup_schema(driver)
    app.state.neo4j = driver

    # Qdrant
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    await setup_collection(qdrant, settings.qdrant_facts_collection, settings.embed_dim)
    app.state.qdrant = qdrant

    # Redis
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis_client

    # HTTP client (TEI + vLLM)
    http_client = httpx.AsyncClient(timeout=60.0)
    app.state.http = http_client

    # Outbox worker
    outbox_task = asyncio.create_task(run_outbox_worker(app))

    logger.info(
        "memory_service_started",
        port=8004,
        neo4j=settings.neo4j_url,
        qdrant=settings.qdrant_url,
        vllm=settings.vllm_url,
    )
    yield

    # Shutdown
    outbox_task.cancel()
    try:
        await outbox_task
    except asyncio.CancelledError:
        pass
    await driver.close()
    await qdrant.close()
    await redis_client.aclose()
    await http_client.aclose()
    logger.info("memory_service_stopped")


app = FastAPI(
    title="ODIN Memory Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router.router, prefix="/api/v1")
app.include_router(recall_router.router, prefix="/api/v1")
```

- [ ] **Step 3: Verify the full app imports without errors**

```bash
cd services/memory
uv run python -c "from app.main import app; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Run all tests**

```bash
cd services/memory
uv run pytest -v
```

Expected: `18 passed` (10 hasher + 4 idempotency + 4 resolver)

- [ ] **Step 5: Commit**

```bash
git add services/memory/app/routers/ services/memory/app/main.py
git commit -m "feat(memory): add /recall, /entity stub, /health + wire full main.py with lifespan"
```

---

### Task 12: docker-compose — memory service + GPU runtime fix

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Read current docker-compose.yml to find exact insertion point**

Run: `cat -n docker-compose.yml` and confirm line numbers for each GPU service.

- [ ] **Step 2: Add `runtime: nvidia` to vllm service**

Add `runtime: nvidia` after the `image:` line in the `vllm:` service block. Also add `NVIDIA_VISIBLE_DEVICES: all` to its environment:

```yaml
  vllm:
    image: vllm/vllm-openai:latest
    runtime: nvidia                    # ← ADD THIS LINE
    ports:
      - "8000:8000"
    environment:
      - VLLM_FLASH_ATTN_VERSION=2
      - NVIDIA_VISIBLE_DEVICES=all     # ← ADD THIS LINE
```

- [ ] **Step 3: Add `runtime: nvidia` to tei-embed and tei-rerank**

```yaml
  tei-embed:
    image: ghcr.io/huggingface/text-embeddings-inference:120-1.9.3
    runtime: nvidia                    # ← ADD THIS LINE
    ...
    environment:
      - HF_TOKEN=${HF_TOKEN:-}
      - NVIDIA_VISIBLE_DEVICES=all     # ← ADD THIS LINE
```

```yaml
  tei-rerank:
    build:
      context: ./infra/docker/reranker
      dockerfile: Dockerfile
    runtime: nvidia                    # ← ADD THIS LINE
    ...
    environment:
      - MODEL_ID=BAAI/bge-reranker-v2-m3
      - HF_TOKEN=${HF_TOKEN:-}
      - HF_HUB_CACHE=/data
      - PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
      - NVIDIA_VISIBLE_DEVICES=all     # ← ADD THIS LINE
```

- [ ] **Step 4: Add memory service after the intelligence service block**

```yaml
  # ═══ MEMORY ENGINE (IntelFact Resolution) ═══
  memory:
    build:
      context: ./services/memory
      dockerfile: Dockerfile
    ports:
      - "8004:8004"
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - VLLM_URL=http://vllm:8000
      - TEI_EMBED_URL=http://tei-embed:80
      - NEO4J_URL=bolt://neo4j:7687
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8004/api/v1/health"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 30s
    depends_on:
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      tei-embed:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 5: Update intelligence service to depend on memory and add MEMORY_URL**

Find the `intelligence:` service and update `depends_on` and `environment`:

```yaml
  intelligence:
    ...
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - VLLM_URL=http://vllm:8000
      - TEI_EMBED_URL=http://tei-embed:80
      - TEI_RERANK_URL=http://tei-rerank:80
      - NEO4J_URL=bolt://neo4j:7687
      - MEMORY_URL=http://memory:8004      # ← ADD THIS LINE
    depends_on:
      tei-embed:
        condition: service_healthy
      tei-rerank:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      memory:                              # ← ADD THIS BLOCK
        condition: service_healthy
```

- [ ] **Step 6: Update data-ingestion to add MEMORY_URL**

```yaml
  data-ingestion:
    ...
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - TEI_EMBED_URL=http://tei-embed:80
      - MEMORY_URL=http://memory:8004      # ← ADD THIS LINE
    depends_on:
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      tei-embed:
        condition: service_started
      memory:                              # ← ADD THIS BLOCK
        condition: service_started
```

- [ ] **Step 7: Verify docker-compose parses correctly**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
docker compose config --quiet && echo "config ok"
```

Expected: `config ok`

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(infra): add memory service to compose + fix GPU runtime: nvidia for vLLM/TEI"
```

---

### Task 13: Intelligence service integration

**Files:**
- Modify: `services/intelligence/config.py`
- Modify: `services/intelligence/graph/nodes.py`

- [ ] **Step 1: Add memory_url to intelligence config**

Read `services/intelligence/config.py`, then add:

```python
    memory_url: str = "http://localhost:8004"
```

Add it after the existing `qdrant_collection` field, before `model_config`.

- [ ] **Step 2: Update osint_node to query memory /recall before LLM call**

Read `services/intelligence/graph/nodes.py`. The `osint_node` function is at line 14.

Replace the `osint_node` function body with this version that calls memory /recall first:

```python
async def osint_node(state: AgentState) -> dict:
    """OSINT agent: queries memory /recall first, then LLM for additional context."""
    logger.info("osint_node_started", query=state["query"])

    memory_facts: list[dict] = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.memory_url}/api/v1/recall",
                json={
                    "query": state["query"],
                    "min_confidence": 0.6,
                    "top_k": 10,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                memory_facts = data.get("facts", [])
                logger.info("osint_memory_recall", fact_count=len(memory_facts))
    except Exception as exc:
        logger.warning("osint_memory_recall_failed", error=str(exc))

    memory_context = ""
    if memory_facts:
        lines = [
            f"- [{f.get('source_ref','')}] {f.get('content','')} "
            f"(confidence: {f.get('confidence_final', 0):.2f})"
            for f in memory_facts
        ]
        memory_context = "Known facts from memory:\n" + "\n".join(lines) + "\n\n"

    try:
        llm = create_osint_llm()
        messages = [
            osint_sys(),
            HumanMessage(
                content=f"{memory_context}Gather OSINT information about: {state['query']}\n\n"
                "Use the known facts above as grounding. Add additional context and analysis."
            ),
        ]
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

        sources = ["llm_knowledge"]
        if memory_facts:
            sources.append("memory_recall")

        return {
            "osint_results": [
                {"source": "memory_recall", "content": f["content"]}
                for f in memory_facts
            ] + [{"source": "llm_analysis", "content": content}],
            "sources_used": sources,
            "agent_chain": state.get("agent_chain", []) + ["osint_agent"],
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
        }
    except Exception as e:
        logger.error("osint_node_failed", error=str(e))
        return {
            "error": f"OSINT agent failed: {e}",
            "agent_chain": state.get("agent_chain", []) + ["osint_agent"],
            "osint_results": [],
            "iteration": state.get("iteration", 0) + 1,
        }
```

- [ ] **Step 3: Add memory /ingest/sync call to synthesis_node**

In `synthesis_node`, after `content` is extracted from the LLM response (line ~110), add a memory write block before the `return` statement:

```python
        # Write synthesis result to memory as an "assessment" fact
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{settings.memory_url}/api/v1/ingest/sync",
                    json={
                        "items": [{
                            "content": content[:2000],  # respect 2000-char limit
                            "source_ref": "synthesis_agent/v1",
                            "domain": "analysis",
                            "entity_id": state.get("entity_id", "synthesis_output"),
                        }]
                    },
                )
        except Exception as exc:
            logger.warning("synthesis_memory_write_failed", error=str(exc))
```

Add this block before the `return { "synthesis": content, ... }` statement in synthesis_node.

- [ ] **Step 4: Add `from app.config import settings` import if not already present**

At the top of `nodes.py`, after existing imports, add:
```python
from config import settings
```

- [ ] **Step 5: Verify import**

```bash
cd services/intelligence
uv run python -c "from graph.nodes import osint_node, synthesis_node; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add services/intelligence/config.py services/intelligence/graph/nodes.py
git commit -m "feat(intelligence): integrate memory /recall in osint_node + /ingest/sync in synthesis_node"
```

---

### Task 14: Data-ingestion integration

**Files:**
- Modify: `services/data-ingestion/config.py`
- Modify: `services/data-ingestion/feeds/rss_collector.py`
- Modify: `services/data-ingestion/feeds/gdelt_collector.py`

- [ ] **Step 1: Add memory_url to data-ingestion config**

Read `services/data-ingestion/config.py`, then add `memory_url` field:

```python
    memory_url: str = "http://localhost:8004"
```

Add after `http_max_retries` and before `tle_cache_ttl`.

- [ ] **Step 2: Read rss_collector.py fully** (to understand the ingest loop)

```bash
cat -n services/data-ingestion/feeds/rss_collector.py
```

- [ ] **Step 3: Add _send_to_memory helper to RSSCollector**

After the `_embed` method in `RSSCollector`, add:

```python
    async def _send_to_memory(
        self, items: list[dict[str, str]], source_ref: str
    ) -> None:
        """POST ingested items to memory service. Fire-and-forget (errors are logged, not raised)."""
        if not items:
            return
        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
                resp = await client.post(
                    f"{settings.memory_url}/api/v1/ingest",
                    json={"items": items},
                )
                resp.raise_for_status()
                log.debug("memory_ingest_queued", source=source_ref, count=len(items))
        except httpx.HTTPError as exc:
            log.warning("memory_ingest_failed", source=source_ref, error=str(exc))
```

- [ ] **Step 4: Call _send_to_memory at the end of _process_feed in RSSCollector**

Find the section in `_process_feed` where `self.qdrant.upsert(...)` is called after building `points`. After the Qdrant upsert, add:

```python
        # Send to memory engine for fact resolution
        memory_items = [
            {
                "content": f"{p.payload.get('title', '')} — {p.payload.get('summary', '')}".strip(" —"),
                "source_ref": f"rss:{name.lower().replace(' ', '_')}",
                "source_url": p.payload.get("url", ""),
                "domain": "osint",
                "entity_id": f"rss_feed_{name.lower().replace(' ', '_')}",
            }
            for p in points
            if p.payload
        ]
        await self._send_to_memory(memory_items, source_ref=f"rss:{name}")
```

- [ ] **Step 5: Read gdelt_collector.py to understand its structure**

```bash
cat -n services/data-ingestion/feeds/gdelt_collector.py
```

- [ ] **Step 6: Add _send_to_memory helper and call to GDELTCollector**

Using the same pattern as steps 3–4, add to `GDELTCollector`:

```python
    async def _send_to_memory(
        self, items: list[dict[str, str]], source_ref: str
    ) -> None:
        """POST ingested items to memory service."""
        if not items:
            return
        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
                resp = await client.post(
                    f"{settings.memory_url}/api/v1/ingest",
                    json={"items": items},
                )
                resp.raise_for_status()
                log.debug("memory_ingest_queued", source=source_ref, count=len(items))
        except httpx.HTTPError as exc:
            log.warning("memory_ingest_failed", source=source_ref, error=str(exc))
```

After the Qdrant upsert in the GDELT processing loop, add:

```python
        # Send to memory engine
        memory_items = [
            {
                "content": f"{p.payload.get('title', '')} — {p.payload.get('url', '')}".strip(" —"),
                "source_ref": f"gdelt:{topic_key}",
                "source_url": p.payload.get("url", ""),
                "domain": "osint",
                "entity_id": f"gdelt_{topic_key}",
            }
            for p in points
            if p.payload
        ]
        await self._send_to_memory(memory_items, source_ref=f"gdelt:{topic_key}")
```

- [ ] **Step 7: Verify data-ingestion imports**

```bash
cd services/data-ingestion
uv run python -c "from feeds.rss_collector import RSSCollector; print('ok')"
```

Expected: `ok`

- [ ] **Step 8: Run data-ingestion tests**

```bash
cd services/data-ingestion
uv run pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 9: Commit**

```bash
git add services/data-ingestion/config.py services/data-ingestion/feeds/rss_collector.py services/data-ingestion/feeds/gdelt_collector.py
git commit -m "feat(data-ingestion): send RSS + GDELT items to memory /ingest after Qdrant write"
```

---

## Self-Review

**Spec coverage check:**

| Spec Requirement | Covered In |
|---|---|
| IntelFact node with all fields | Task 4 (neo4j_client), Task 8 (orchestrator) |
| Entity node + ABOUT edge | Task 4 (write_fact, ensure_entity) |
| UPDATES / EXTENDS / DERIVES / NONE | Task 7 (resolver), Task 8 (orchestrator), Task 4 (write_fact) |
| SHA256 fact_id + canonical_fact_id | Task 3 (hasher) |
| Neo4j constraints + indices | Task 4 (setup_schema) |
| Qdrant odin_facts collection | Task 5 (qdrant_service setup_collection) |
| Idempotency-Key header (HIT / CONFLICT / MISS) | Task 6 (idempotency), Task 10 (ingest.py) |
| POST /ingest/sync (sync, 2000-char limit) | Task 10 |
| POST /ingest (async, 500-item limit, 202) | Task 10 |
| GET /ingest/{id} status polling | Task 10 |
| POST /recall (semantic search + relation enrichment) | Task 11 |
| GET /entity/{id} stub | Task 11 |
| GET /health | Task 11 |
| Outbox worker with backoff + reconcile | Task 9 |
| Corroboration boost (source dedup) | Task 8 (orchestrator) |
| Resolver threshold (score > 0.75) | Task 8 (orchestrator), Task 7 (resolver) |
| docker-compose memory service | Task 12 |
| GPU runtime fix | Task 12 |
| Intelligence /recall integration | Task 13 |
| Intelligence /ingest/sync (synthesis) | Task 13 |
| Data-ingestion /ingest integration | Task 14 |

**No placeholders found.** All code blocks contain complete, runnable Python.

**Type consistency check:** All methods use the same signatures throughout:
- `orchestrate_fact` returns `FactResult`
- `resolver.resolve` returns `ResolutionResult`
- `neo4j_client.write_fact` takes `fact_props: dict`, returns `bool`
- `qdrant_service.upsert_fact` takes `fact_id: str, vector: list[float], payload: dict`
