# TASK-103: Ingestion Pipeline — Extract → Graph Write — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert an intelligence extraction step between feed-fetch and Qdrant-embed in the RSS and GDELT collectors. Each new item gets classified (codebook event type) and entity-extracted via IntelligenceExtractor, then written to Neo4j via GraphClient, then embedded in Qdrant as before, then published to a Redis Stream for frontend live-updates.

**Architecture:** New `pipeline.py` module in data-ingestion with a `process_item()` function. RSS and GDELT collectors call it after fetch, before Qdrant upsert. The pipeline imports `IntelligenceExtractor` and `GraphClient` from the intelligence service. Config gets Neo4j + vLLM settings. Redis Stream `events:new` publishes each event for the frontend.

**Tech Stack:** httpx, redis (streams), qdrant-client, pydantic. No new dependencies — intelligence service packages accessed via relative imports or config-driven HTTP calls.

**Working directory:** `services/data-ingestion/`

**Run tests with:** `cd services/data-ingestion && uv run python -m pytest tests/ -v --tb=short`

**Key constraint:** The IntelligenceExtractor lives in the intelligence service. Data-ingestion cannot import it directly (separate venv). Instead, pipeline.py calls vLLM directly (same pattern as IntelligenceExtractor) or calls intelligence service via HTTP. **Simplest approach:** duplicate the lightweight extraction logic with httpx calls to vLLM and Neo4j endpoints, same as the existing embed pattern. The data-ingestion service already calls TEI directly.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | MODIFY | Add vLLM + Neo4j settings |
| `pipeline.py` | CREATE | process_item(): extract → graph write → embed → publish |
| `feeds/rss_collector.py` | MODIFY | Hook process_item after fetch, before upsert |
| `feeds/gdelt_collector.py` | MODIFY | Hook process_item after fetch, before upsert |
| `tests/test_pipeline.py` | CREATE | Pipeline tests with mocked vLLM/Neo4j/Qdrant/Redis |

---

## Task 1: Add vLLM + Neo4j config to data-ingestion

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add settings**

Add to the Settings class:
```python
    # vLLM (for intelligence extraction)
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "models/qwen3.5-27b-awq"

    # Neo4j (for graph writes)
    neo4j_url: str = "http://localhost:7474"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Redis Streams
    redis_stream_events: str = "events:new"
```

- [ ] **Step 2: Verify existing tests pass**

---

## Task 2: Pipeline module (TDD)

**Files:**
- Create: `tests/test_pipeline.py`
- Create: `pipeline.py`

- [ ] **Step 1: Write failing tests**

Test `process_item()` with fully mocked dependencies:
- `test_process_item_extracts_and_writes_to_neo4j` — mock vLLM response, verify Neo4j HTTP calls
- `test_process_item_embeds_in_qdrant` — verify Qdrant upsert still happens
- `test_process_item_publishes_redis_stream` — verify XADD to events:new
- `test_process_item_deduplication` — verify duplicate items (same hash) skip extraction
- `test_process_item_extraction_failure_continues` — vLLM fails, Qdrant upsert still happens (graceful degradation)

- [ ] **Step 2: Run tests, verify failures**

- [ ] **Step 3: Implement pipeline.py**

```python
# pipeline.py
"""Post-fetch intelligence extraction pipeline.

Inserted between feed-fetch and Qdrant-embed:
1. LLM extraction (events + entities + locations) via vLLM
2. Neo4j graph write (deterministic templates)
3. Qdrant embed (existing flow, enriched payload)
4. Redis Stream publish (frontend live-update)
"""
```

Key function:
```python
async def process_item(
    title: str,
    text: str,
    url: str,
    source: str,
    *,
    settings: Settings,
) -> dict | None:
    """
    Extract intelligence, write to Neo4j, return enriched metadata.
    Returns None if extraction fails (caller continues with plain embed).
    """
```

The function:
1. Calls vLLM `/v1/chat/completions` with the codebook system prompt (embedded in pipeline, loaded from YAML)
2. Parses response into events/entities/locations
3. Writes to Neo4j via HTTP transactional API (same pattern entity_extractor used before refactor — data-ingestion uses HTTP, not Bolt)
4. Publishes each event to Redis Stream `events:new`
5. Returns enriched metadata (codebook_type, entities) for Qdrant payload

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Run full suite, no regressions**

---

## Task 3: Hook pipeline into RSS collector

**Files:**
- Modify: `feeds/rss_collector.py`
- Add to: `tests/test_pipeline.py`

- [ ] **Step 1: Write test for RSS integration**

Test that RSS collector's `_process_feed` calls `process_item` for each new entry.

- [ ] **Step 2: Modify rss_collector.py**

In `_process_feed`, after dedup check and before Qdrant upsert, call:
```python
enrichment = await process_item(
    title=entry.title,
    text=embed_text,
    url=entry.link,
    source="rss",
    settings=self.settings,
)
if enrichment:
    payload["codebook_type"] = enrichment.get("codebook_type", "other.unclassified")
    payload["entities"] = enrichment.get("entities", [])
```

- [ ] **Step 3: Run tests, verify pass**

---

## Task 4: Hook pipeline into GDELT collector

**Files:**
- Modify: `feeds/gdelt_collector.py`
- Add to: `tests/test_pipeline.py`

Same pattern as Task 3 but for GDELT articles.

---

## Task 5: Final verification + commit

- [ ] **Step 1: Run full test suite**
- [ ] **Step 2: Commit**
