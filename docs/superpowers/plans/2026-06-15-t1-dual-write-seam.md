# T1 — Dual-Write Seam Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live-ingestion write path consistent and idempotent so a Neo4j failure can never orphan a Qdrant vector, emit a phantom Redis event, or duplicate Event nodes on retry (closes WP-01, WP-03, and KNOWN BH-EDGE-WRITE-01).

**Architecture:** "Key + Signal + Reconcile" (per spec `docs/superpowers/specs/2026-06-15-writepath-graph-integrity-fixes-design.md`, T1). (1) Surface Neo4j write failures as a typed `Neo4jWriteError` — including the HTTP-200-with-`errors[]` case the tx/commit endpoint returns. (2) In the two affected collectors, treat that error like the existing transient errors: skip the Qdrant upsert so the dedup point is never minted and the item retries cleanly. (3) Make the Event write idempotent via `MERGE` on a deterministic `event_key` so retries converge instead of forking. (4) A one-off Python repair backfills `event_key` + dedupes existing live-pipeline Events, then a unique constraint locks it. (5) A lossy reconcile CLI heals already-orphaned vectors.

**Tech Stack:** Python 3.12, `uv`, `pytest`/`pytest-asyncio`, httpx (Neo4j HTTP tx API), `qdrant-client`, structlog, Neo4j 5 **Community**.

---

## File Structure

- **Modify** `services/data-ingestion/pipeline.py` — new `Neo4jWriteError`; `content_hash`/`_normalize_event_title`/`_event_key` helpers; `_write_to_neo4j` raises on failure + writes Events via idempotent `MERGE`; `process_item` gains `content_hash` + `raise_on_write_error` params.
- **Modify** `services/data-ingestion/feeds/gdelt_collector.py` — import shared `content_hash`/`Neo4jWriteError`; guard the dedup `retrieve`; pass `content_hash` + `raise_on_write_error=True`; catch `Neo4jWriteError` → skip point.
- **Modify** `services/data-ingestion/feeds/rss_collector.py` — same as gdelt_collector.
- **Modify** `services/data-ingestion/tests/test_pipeline_codebook_guard.py` — the existing `"CREATE (ev:Event"` assertion must become `"MERGE (ev:Event"`.
- **Create** `services/data-ingestion/tests/test_pipeline_dual_write.py` — new unit tests for the helpers, the raise behavior, the MERGE, and the propagate/skip flag.
- **Create** `services/data-ingestion/tests/test_collector_dual_write.py` — collector skips Qdrant on `Neo4jWriteError`.
- **Create** `services/data-ingestion/migrations/backfill_event_key.py` — Python backfill + dedupe (parity with `_event_key`), `--dry-run` first.
- **Create** `services/data-ingestion/migrations/event_key_unique.cypher` — the unique constraint, applied after backfill.
- **Create** `services/data-ingestion/tests/test_backfill_event_key.py` — pure keying/grouping/survivor logic.
- **Create** `services/data-ingestion/graph_integrity/reconcile_orphans.py` — lossy orphan-vector reconcile CLI.
- **Create** `services/data-ingestion/tests/test_reconcile_orphans.py` — pure orphan-detection logic.

Run all commands from `services/data-ingestion/` unless noted.

---

## Task 1: `Neo4jWriteError` + `_write_to_neo4j` raises on failure

**Files:**
- Modify: `services/data-ingestion/pipeline.py` (exception block ~`87-99`; commit block `547-556`)
- Test: `services/data-ingestion/tests/test_pipeline_dual_write.py`

- [ ] **Step 1: Write the failing test**

Create `services/data-ingestion/tests/test_pipeline_dual_write.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import pipeline
from config import settings
from pipeline import Neo4jWriteError, _write_to_neo4j


def _resp(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value=json_body)
    return resp


def _patched_client(resp_or_exc):
    """Return a patch() context for pipeline.httpx.AsyncClient whose .post
    returns resp_or_exc (or raises it if it's an Exception)."""
    client = AsyncMock()
    if isinstance(resp_or_exc, Exception):
        client.post = AsyncMock(side_effect=resp_or_exc)
    else:
        client.post = AsyncMock(return_value=resp_or_exc)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch("pipeline.httpx.AsyncClient", return_value=cm)


@pytest.mark.asyncio
async def test_write_raises_on_tx_errors_array():
    """tx/commit returns HTTP 200 with a populated errors[] — must raise, not warn."""
    body = {"results": [], "errors": [{"code": "Neo.ClientError.Statement.SyntaxError"}]}
    with _patched_client(_resp(body)):
        with pytest.raises(Neo4jWriteError):
            await _write_to_neo4j(
                [{"title": "x", "codebook_type": "other.unclassified"}], [],
                "http://u", "t", "rss", settings,
            )


@pytest.mark.asyncio
async def test_write_raises_on_http_error():
    with _patched_client(httpx.ConnectError("refused")):
        with pytest.raises(Neo4jWriteError):
            await _write_to_neo4j(
                [{"title": "x", "codebook_type": "other.unclassified"}], [],
                "http://u", "t", "rss", settings,
            )


@pytest.mark.asyncio
async def test_write_ok_when_no_errors():
    with _patched_client(_resp({"results": [], "errors": []})):
        await _write_to_neo4j(
            [{"title": "x", "codebook_type": "other.unclassified"}], [],
            "http://u", "t", "rss", settings,
        )  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_dual_write.py -v`
Expected: FAIL — `ImportError: cannot import name 'Neo4jWriteError'`.

- [ ] **Step 3: Add the exception**

In `pipeline.py`, after the `ExtractionConfigError` class (after line ~99) add:

```python
class Neo4jWriteError(Exception):
    """The Neo4j write failed — either an httpx transport error, or the tx/commit
    endpoint returned HTTP 200 with a non-empty errors[] (the Cypher/tx itself failed).

    process_item re-raises this to the caller only when raise_on_write_error=True, so a
    partial-success tick (graph failed, vector would still commit) can skip the Qdrant
    upsert and retry cleanly instead of orphaning a vector.
    """
```

- [ ] **Step 4: Make `_write_to_neo4j` raise**

Replace the commit block at `pipeline.py:547-556`:

```python
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{settings.neo4j_http_url}/db/neo4j/tx/commit",
            json={"statements": statements},
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        resp.raise_for_status()
        errors = resp.json().get("errors", [])
        if errors:
            log.warning("neo4j_write_errors", errors=errors)
```

with:

```python
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.neo4j_http_url}/db/neo4j/tx/commit",
                json={"statements": statements},
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            resp.raise_for_status()
            errors = resp.json().get("errors", [])
    except httpx.HTTPError as exc:
        # Connect/timeout/5xx — the graph write did not land.
        raise Neo4jWriteError(f"neo4j http error: {exc}") from exc
    if errors:
        # The tx/commit endpoint returns HTTP 200 with a populated errors[] when the
        # Cypher/transaction itself failed. Must NOT be swallowed — it is a real failure.
        log.warning("neo4j_write_errors", errors=errors)
        raise Neo4jWriteError(f"neo4j tx errors: {errors}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_dual_write.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add pipeline.py tests/test_pipeline_dual_write.py
git commit -m "fix(ingestion): raise Neo4jWriteError on tx errors[] and httpx failures (WP-01)"
```

---

## Task 2: Deterministic Event-key helpers

**Files:**
- Modify: `services/data-ingestion/pipeline.py` (imports `9-24`; helpers near the other module-level helpers)
- Test: `services/data-ingestion/tests/test_pipeline_dual_write.py`

- [ ] **Step 1: Write the failing test** (append to `test_pipeline_dual_write.py`)

```python
from pipeline import _event_key, _normalize_event_title, content_hash


def test_content_hash_matches_collector_formula():
    # Must equal the collectors' historical _content_hash(title, url).
    import hashlib
    raw = f"{'  Title '.strip().lower()}|{'HTTP://U '.strip().lower()}"
    assert content_hash("  Title ", "HTTP://U ") == hashlib.sha256(raw.encode()).hexdigest()


def test_normalize_event_title_collapses_and_caps():
    assert _normalize_event_title("  Foo   Bar ") == "foo bar"
    assert _normalize_event_title("FOO bar") == "foo bar"
    assert len(_normalize_event_title("x" * 500)) == 200


def test_event_key_stable_across_title_whitespace_and_case():
    h = content_hash("doc", "http://u")
    k1 = _event_key(h, "conflict.armed_clash", "  Strike  on  Kyiv ")
    k2 = _event_key(h, "conflict.armed_clash", "strike on kyiv")
    assert k1 == k2
    assert len(k1) == 24


def test_event_key_differs_by_codebook_type_and_title():
    h = content_hash("doc", "http://u")
    assert _event_key(h, "a.b", "t") != _event_key(h, "c.d", "t")
    assert _event_key(h, "a.b", "t1") != _event_key(h, "a.b", "t2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_dual_write.py -k "event_key or content_hash or normalize" -v`
Expected: FAIL — `ImportError: cannot import name 'content_hash'`.

- [ ] **Step 3: Add imports and helpers**

In `pipeline.py`, add to the stdlib imports (after line `11 import json`):

```python
import hashlib
import re
```

Then add these module-level helpers (place them near the top-level helper functions, e.g. just before `def process_item`):

```python
_EVENT_TITLE_MAXLEN = 200


def content_hash(title: str, url: str) -> str:
    """Canonical content hash shared by the Qdrant dedup point-id and the Event key,
    so the graph Event identity and the vector dedup identity share one root.
    MUST stay byte-identical to the value the collectors derive for their Qdrant point.
    """
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _normalize_event_title(title: str) -> str:
    """trim -> whitespace-collapse -> lowercase -> cap length, so minor LLM title
    variations do not fork a new Event under the MERGE key."""
    collapsed = re.sub(r"\s+", " ", title.strip()).lower()
    return collapsed[:_EVENT_TITLE_MAXLEN]


def _event_key(doc_content_hash: str, codebook_type: str, event_title: str) -> str:
    """Deterministic per-event identity for idempotent MERGE. One article can yield
    several events, so the doc hash alone is not unique — fold in codebook_type and
    the normalized event title."""
    raw = f"{doc_content_hash}|{codebook_type}|{_normalize_event_title(event_title)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_dual_write.py -k "event_key or content_hash or normalize" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline_dual_write.py
git commit -m "feat(ingestion): add deterministic content_hash/event_key helpers (WP-03)"
```

---

## Task 3: Idempotent Event `MERGE` (replace `CREATE`)

**Files:**
- Modify: `services/data-ingestion/pipeline.py` (`_write_to_neo4j` signature `426-439`; Event loop `511-539`)
- Modify: `services/data-ingestion/tests/test_pipeline_codebook_guard.py` (`134-135`)
- Test: `services/data-ingestion/tests/test_pipeline_dual_write.py`

- [ ] **Step 1: Write the failing test** (append to `test_pipeline_dual_write.py`)

```python
async def _captured_statements(events):
    """Run _write_to_neo4j with a mock client and return the posted statements list."""
    captured = {}
    client = AsyncMock()

    async def _post(url, json, auth):  # noqa: A002
        captured["statements"] = json["statements"]
        return _resp({"results": [], "errors": []})

    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("pipeline.httpx.AsyncClient", return_value=cm):
        await _write_to_neo4j(events, [], "http://u", "doc title", "rss", settings)
    return captured["statements"]


@pytest.mark.asyncio
async def test_event_written_with_merge_not_create():
    stmts = await _captured_statements(
        [{"title": "Strike on Kyiv", "codebook_type": "conflict.armed_clash"}]
    )
    ev_stmts = [s for s in stmts if "Event" in s["statement"]]
    assert ev_stmts, "expected an Event statement"
    assert all("MERGE (ev:Event {event_key:" in s["statement"] for s in ev_stmts)
    assert all("CREATE (ev:Event" not in s["statement"] for s in ev_stmts)
    assert all("event_key" in s["parameters"] for s in ev_stmts)


@pytest.mark.asyncio
async def test_same_event_yields_same_event_key():
    e = {"title": "Strike on Kyiv", "codebook_type": "conflict.armed_clash"}
    s1 = await _captured_statements([e])
    s2 = await _captured_statements([dict(e, title="  strike on  KYIV ")])
    k1 = next(s["parameters"]["event_key"] for s in s1 if "Event" in s["statement"])
    k2 = next(s["parameters"]["event_key"] for s in s2 if "Event" in s["statement"])
    assert k1 == k2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_dual_write.py -k merge -v`
Expected: FAIL — current statement contains `CREATE (ev:Event`, no `event_key`.

- [ ] **Step 3: Add `doc_content_hash` param to `_write_to_neo4j`**

In `pipeline.py`, change the `_write_to_neo4j` signature (line `438`) to add a keyword param right after `locations`:

```python
    locations: list[dict] | None = None,
    doc_content_hash: str | None = None,
```

Then inside `_write_to_neo4j`, just before the Event loop (before line `511 for event in events:`), compute the shared doc hash once:

```python
    doc_hash = doc_content_hash or content_hash(doc_title, doc_url)
```

- [ ] **Step 4: Replace the Event statement with a MERGE**

Replace the `statements.append({...})` Event block at `pipeline.py:517-538` with:

```python
        ev_codebook_type = event.get("codebook_type", "other.unclassified")
        ev_key = _event_key(doc_hash, ev_codebook_type, event.get("title", ""))
        statements.append({
            "statement": (
                "MERGE (ev:Event {event_key: $event_key}) "
                "ON CREATE SET "
                "  ev.title = $title, ev.summary = $summary,"
                "  ev.codebook_type = $codebook_type,"
                "  ev.severity = $severity, ev.confidence = $confidence,"
                "  ev.timeline_at = datetime($timeline_at), ev.time_basis = $time_basis "
                "ON MATCH SET ev.updated_at = datetime() "
                "WITH ev "
                "MATCH (d:Document {url: $url}) "
                "MERGE (d)-[:DESCRIBES]->(ev)"
            ),
            "parameters": {
                "event_key": ev_key,
                "title": event.get("title", ""),
                "summary": event.get("summary", ""),
                "codebook_type": ev_codebook_type,
                "severity": event.get("severity", "low"),
                "confidence": event.get("confidence", 0.5),
                "timeline_at": timeline_at,
                "time_basis": time_basis,
                "url": doc_url,
            },
        })
```

(The geo fragment append at `540-545` is unchanged — `ev` is still bound after the `MERGE (d)-[:DESCRIBES]->(ev)`.)

- [ ] **Step 5: Fix the existing codebook-guard test**

In `tests/test_pipeline_codebook_guard.py` line `134-135`, change:

```python
        event_statements = [s for s in body["statements"] if "CREATE (ev:Event" in s["statement"]]
        assert event_statements, "Expected an Event CREATE statement"
```

to:

```python
        event_statements = [s for s in body["statements"] if "MERGE (ev:Event" in s["statement"]]
        assert event_statements, "Expected an Event MERGE statement"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline_dual_write.py tests/test_pipeline_codebook_guard.py tests/test_pipeline_timeline_at.py -v`
Expected: PASS (new merge tests + the existing guard/timeline suites still green — they read `body["statements"]`, which still carries the Event statement and params).

- [ ] **Step 7: Commit**

```bash
git add pipeline.py tests/test_pipeline_dual_write.py tests/test_pipeline_codebook_guard.py
git commit -m "fix(ingestion): MERGE Event on deterministic event_key (idempotent retries) (WP-03)"
```

---

## Task 4: `process_item` — propagate-or-swallow flag + thread `content_hash`

> **Compatibility decision (per spec).** `process_item` has 14 callers; only `gdelt_collector` and `rss_collector` are
> in T1 scope. `process_item`'s **default stays legacy fail-soft** (`raise_on_write_error=False` → log + swallow) so the
> other 12 collectors are unchanged this tranche. The **T1 collectors MUST pass `raise_on_write_error=True`** (Tasks 5/6),
> and **only those paths satisfy the dual-write guarantee**. A non-`Neo4jWriteError` exception stays logged-and-swallowed
> for every caller. Migrating the rest to propagate-by-default is explicit future work.

**Files:**
- Modify: `services/data-ingestion/pipeline.py` (`process_item` signature `274-285`; Neo4j write block `313-327`)
- Test: `services/data-ingestion/tests/test_pipeline_dual_write.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from pipeline import process_item


def _vllm_patch(events):
    return patch("pipeline._call_vllm", AsyncMock(return_value={
        "events": events, "entities": [], "locations": [],
    }))


def _failing_neo4j_patch():
    # tx/commit returns errors[] -> _write_to_neo4j raises Neo4jWriteError.
    return _patched_client(_resp({"results": [], "errors": [{"code": "X"}]}))


@pytest.mark.asyncio
async def test_process_item_swallows_by_default():
    ev = [{"title": "t", "codebook_type": "other.unclassified"}]
    with _vllm_patch(ev), _failing_neo4j_patch():
        # default raise_on_write_error=False -> no raise, returns enrichment
        result = await process_item("t", "body", "http://u", "rss", settings=settings)
    assert result is not None


@pytest.mark.asyncio
async def test_process_item_propagates_when_flag_set():
    ev = [{"title": "t", "codebook_type": "other.unclassified"}]
    with _vllm_patch(ev), _failing_neo4j_patch():
        with pytest.raises(Neo4jWriteError):
            await process_item(
                "t", "body", "http://u", "rss",
                settings=settings, raise_on_write_error=True,
            )


@pytest.mark.asyncio
async def test_process_item_no_redis_publish_on_write_failure():
    ev = [{"title": "t", "codebook_type": "other.unclassified"}]
    redis = AsyncMock()
    with _vllm_patch(ev), _failing_neo4j_patch():
        with pytest.raises(Neo4jWriteError):
            await process_item(
                "t", "body", "http://u", "rss",
                settings=settings, redis_client=redis, raise_on_write_error=True,
            )
    redis.xadd.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_dual_write.py -k "process_item" -v`
Expected: FAIL — `process_item()` has no `raise_on_write_error` kwarg (TypeError).

- [ ] **Step 3: Add the params**

In `pipeline.py`, extend the `process_item` signature (after line `284 published_at: str | None = None,`):

```python
    content_hash: str | None = None,
    raise_on_write_error: bool = False,
```

- [ ] **Step 4: Thread the hash + narrow the except + conditional re-raise**

Replace the Neo4j write block at `pipeline.py:313-327`:

```python
    # Step 2: Write to Neo4j
    if events or entities:
        ingested_at = datetime.now(UTC).isoformat()
        try:
            await _write_to_neo4j(
                events, entities, url, title, source, settings,
                occurred_at=occurred_at, observed_at=observed_at,
                published_at=published_at, ingested_at=ingested_at,
                locations=locations,
            )
        except Exception as e:
            log.error("pipeline_neo4j_failed", url=url, error=str(e))
```

with:

```python
    # Step 2: Write to Neo4j
    if events or entities:
        ingested_at = datetime.now(UTC).isoformat()
        try:
            await _write_to_neo4j(
                events, entities, url, title, source, settings,
                occurred_at=occurred_at, observed_at=observed_at,
                published_at=published_at, ingested_at=ingested_at,
                locations=locations, doc_content_hash=content_hash,
            )
        except Neo4jWriteError as e:
            log.error("pipeline_neo4j_failed", url=url, error=str(e))
            # T1 collectors pass raise_on_write_error=True so they can skip the Qdrant
            # upsert (no orphan vector, no phantom Redis event). Other callers keep the
            # historical swallow-and-continue behavior.
            if raise_on_write_error:
                raise
        except Exception as e:  # noqa: BLE001 — preserve resilience for non-T1 callers
            log.error("pipeline_neo4j_failed", url=url, error=str(e))
```

(Step 3 / Redis publish at `329-344` is unchanged: when `raise_on_write_error=True` and the write failed, the `raise` exits `process_item` before the Redis block runs.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline_dual_write.py -v`
Expected: PASS (all dual-write tests).

- [ ] **Step 6: Commit**

```bash
git add pipeline.py tests/test_pipeline_dual_write.py
git commit -m "fix(ingestion): process_item propagates Neo4jWriteError on flag, threads content_hash (WP-01)"
```

---

## Task 5: `gdelt_collector` skips Qdrant on Neo4j failure

**Files:**
- Modify: `services/data-ingestion/feeds/gdelt_collector.py` (import `16`; `_content_hash` def `58-60`; dedup `149-158`; process_item call + excepts `170-189`)
- Test: `services/data-ingestion/tests/test_collector_dual_write.py`

- [ ] **Step 1: Write the failing test**

Create `services/data-ingestion/tests/test_collector_dual_write.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline import Neo4jWriteError


@pytest.mark.asyncio
async def test_gdelt_skips_point_on_neo4j_write_error():
    """When process_item raises Neo4jWriteError, the article's point is NOT appended
    to the Qdrant batch (so the dedup key is not minted and the item retries)."""
    from feeds import gdelt_collector

    col = gdelt_collector.GDELTCollector.__new__(gdelt_collector.GDELTCollector)
    col.qdrant = MagicMock()
    col.qdrant.retrieve = MagicMock(return_value=[])   # not a duplicate
    col.qdrant.upsert = MagicMock()
    col._redis = None
    col._embed = AsyncMock(return_value=[0.0] * 1024)

    articles = [{"title": "t", "url": "http://u", "seendate": "", "domain": "",
                 "language": "", "sourcecountry": ""}]

    with patch.object(gdelt_collector, "process_item",
                      AsyncMock(side_effect=Neo4jWriteError("down"))):
        n = await col._ingest_articles(articles, "q")

    assert n == 0
    col.qdrant.upsert.assert_not_called()
    col._embed.assert_not_called()
```

(Method confirmed: `GDELTCollector._ingest_articles(self, articles, query_name) -> int`; attributes used are `self.qdrant`, `self._redis`, `self._embed`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_collector_dual_write.py -k gdelt -v`
Expected: FAIL — currently `Neo4jWriteError` is not caught in the loop, so it propagates out of `_ingest_articles` (or is caught by the per-query `except Exception` and the assertion on `n == 0` / `upsert not called` does not hold as specified).

- [ ] **Step 3: Update the import**

In `gdelt_collector.py:16`, change:

```python
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item
```

to:

```python
from pipeline import (
    ExtractionConfigError,
    ExtractionTransientError,
    Neo4jWriteError,
    content_hash,
    process_item,
)
```

- [ ] **Step 4: Drop the local `_content_hash`, use the shared one**

Delete the local definition at `gdelt_collector.py:58-60`:

```python
def _content_hash(title: str, url: str) -> str:
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

and replace its single call site `chash = _content_hash(title, url)` (line `149`) with:

```python
            chash = content_hash(title, url)
```

(Leave `_point_id_from_hash` as-is; the hash value is identical.) If `hashlib` is now unused in this file, remove its import at line `5`.

- [ ] **Step 5: Guard the dedup retrieve**

Replace the dedup block at `gdelt_collector.py:152-158`:

```python
            # Deduplicate
            existing = self.qdrant.retrieve(
                collection_name=settings.qdrant_collection,
                ids=[point_id],
            )
            if existing:
                continue
```

with:

```python
            # Deduplicate — a transient Qdrant fault must not abandon the accumulated batch.
            try:
                existing = self.qdrant.retrieve(
                    collection_name=settings.qdrant_collection,
                    ids=[point_id],
                )
            except Exception as exc:  # noqa: BLE001 — skip this item, keep the batch
                log.warning("gdelt_dedup_retrieve_failed", url=url, error=str(exc))
                continue
            if existing:
                continue
```

- [ ] **Step 6: Pass the flag + content_hash, catch `Neo4jWriteError`**

In the `process_item` call (`gdelt_collector.py:170-177`) add the two kwargs:

```python
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=url,
                    source="gdelt",
                    settings=settings,
                    redis_client=self._redis,
                    content_hash=chash,
                    raise_on_write_error=True,
                )
```

Then add a new `except` next to the existing transient handlers (after `gdelt_collector.py:183`, the `ExtractionConfigError` handler):

```python
            except Neo4jWriteError as exc:
                # Graph write failed — skip the Qdrant upsert so the dedup point is not
                # minted; the still-fresh article is retried on the next fetch.
                log.warning("gdelt_neo4j_write_skipped", url=url, error=str(exc))
                continue
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_collector_dual_write.py -k gdelt -v`
Expected: PASS.

- [ ] **Step 8: Run the gdelt collector suite + lint**

Run: `uv run pytest tests/ -k gdelt_collector -v && uv run ruff check feeds/gdelt_collector.py`
Expected: PASS, no lint errors.

- [ ] **Step 9: Commit**

```bash
git add feeds/gdelt_collector.py tests/test_collector_dual_write.py
git commit -m "fix(ingestion): gdelt collector skips Qdrant on Neo4jWriteError, guards dedup (WP-01)"
```

---

## Task 6: `rss_collector` skips Qdrant on Neo4j failure

**Files:**
- Modify: `services/data-ingestion/feeds/rss_collector.py` (import; `_content_hash` `156-160`; dedup `271-277`; process_item call + excepts `296-310`)
- Test: `services/data-ingestion/tests/test_collector_dual_write.py`

- [ ] **Step 1: Write the failing test** (append to `test_collector_dual_write.py`)

```python
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_rss_skips_point_on_neo4j_write_error():
    """RSSCollector._process_feed fetches via httpx + feedparser; mock both, then make
    process_item raise -> the entry's point must not reach Qdrant."""
    from feeds import rss_collector

    col = rss_collector.RSSCollector.__new__(rss_collector.RSSCollector)
    col.qdrant = MagicMock()
    col.qdrant.retrieve = MagicMock(return_value=[])
    col.qdrant.upsert = MagicMock()
    col._redis = None
    col._embed = AsyncMock(return_value=[0.0] * 1024)

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = "<rss/>"
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    feed = SimpleNamespace(
        bozo=False,
        entries=[{"title": "t", "link": "http://u", "summary": "s"}],
    )

    with patch("feeds.rss_collector.httpx.AsyncClient", return_value=cm), \
         patch("feeds.rss_collector.feedparser.parse", return_value=feed), \
         patch.object(rss_collector, "process_item",
                      AsyncMock(side_effect=Neo4jWriteError("down"))):
        n = await col._process_feed({"name": "f", "url": "http://feed"})

    assert n == 0
    col.qdrant.upsert.assert_not_called()
    col._embed.assert_not_called()
```

(Method confirmed: `RSSCollector._process_feed(self, feed_meta: dict[str, str]) -> int`; it fetches via `httpx.AsyncClient` then `feedparser.parse(resp.text)` — both mocked above.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_collector_dual_write.py -k rss -v`
Expected: FAIL — `Neo4jWriteError` not caught; point logic unchanged.

- [ ] **Step 3: Update the import**

In `rss_collector.py`, add `Neo4jWriteError` and `content_hash` to the existing `from pipeline import (...)` (it imports `ExtractionConfigError, ExtractionTransientError, process_item`). Result:

```python
from pipeline import (
    ExtractionConfigError,
    ExtractionTransientError,
    Neo4jWriteError,
    content_hash,
    process_item,
)
```

- [ ] **Step 4: Drop local `_content_hash`, use shared**

Delete `def _content_hash(...)` at `rss_collector.py:156-160` and replace its call site `chash = _content_hash(title, link)` (line `267`) with:

```python
            chash = content_hash(title, link)
```

Remove the now-unused `hashlib` import if present.

- [ ] **Step 5: Guard the dedup retrieve**

Replace the dedup block at `rss_collector.py:270-277`:

```python
            # Deduplicate — skip if already stored
            existing = await asyncio.to_thread(
                self.qdrant.retrieve,
                collection_name=settings.qdrant_collection,
                ids=[point_id],
            )
            if existing:
                continue
```

with:

```python
            # Deduplicate — a transient Qdrant fault must not abandon the accumulated batch.
            try:
                existing = await asyncio.to_thread(
                    self.qdrant.retrieve,
                    collection_name=settings.qdrant_collection,
                    ids=[point_id],
                )
            except Exception as exc:  # noqa: BLE001 — skip this item, keep the batch
                log.warning("rss_dedup_retrieve_failed", url=link, error=str(exc))
                continue
            if existing:
                continue
```

- [ ] **Step 6: Pass the flag + content_hash, catch `Neo4jWriteError`**

In the `process_item` call (`rss_collector.py:296-304`) add the kwargs:

```python
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=link,
                    source="rss",
                    settings=settings,
                    redis_client=self._redis,
                    published_at=published_dt,
                    content_hash=chash,
                    raise_on_write_error=True,
                )
```

Add a new handler after the `ExtractionConfigError` block (`rss_collector.py:308-310`):

```python
            except Neo4jWriteError as exc:
                log.warning("rss_neo4j_write_skipped", url=link, error=str(exc))
                continue
```

- [ ] **Step 7: Run test + suite + lint**

Run: `uv run pytest tests/test_collector_dual_write.py -k rss -v && uv run pytest tests/ -k rss_collector -v && uv run ruff check feeds/rss_collector.py`
Expected: PASS, no lint errors.

- [ ] **Step 8: Commit**

```bash
git add feeds/rss_collector.py tests/test_collector_dual_write.py
git commit -m "fix(ingestion): rss collector skips Qdrant on Neo4jWriteError, guards dedup (WP-01)"
```

---

## Task 7: Repair migration — backfill `event_key` + dedupe + constraint

**Files:**
- Create: `services/data-ingestion/migrations/backfill_event_key.py`
- Create: `services/data-ingestion/migrations/event_key_unique.cypher`
- Test: `services/data-ingestion/tests/test_backfill_event_key.py`

This is the prod-data repair. **Scope:** live-pipeline `:Event` nodes that are **NOT** also `:GDELTEvent` (those keep their own `event_id`). The backfill recomputes `event_key` in **Python** (reusing `_event_key`) so it is byte-identical to what the forward path now writes. Then duplicates that collapse onto one key are merged, and the unique constraint is applied.

- [ ] **Step 1: Write the failing test (pure planning logic)**

Create `services/data-ingestion/tests/test_backfill_event_key.py`:

```python
from migrations.backfill_event_key import EventRow, plan_backfill


def test_plan_groups_duplicates_and_picks_lowest_id_survivor():
    rows = [
        EventRow(node_id=5, title="Strike on Kyiv", codebook_type="c.armed",
                 doc_url="http://u", doc_title="d"),
        EventRow(node_id=2, title="  strike on  KYIV ", codebook_type="c.armed",
                 doc_url="http://u", doc_title="d"),  # dup of above (normalized)
        EventRow(node_id=9, title="Sanctions on Iran", codebook_type="c.sanction",
                 doc_url="http://u", doc_title="d"),  # singleton
    ]
    plan = plan_backfill(rows)
    # one key for the dup pair, one for the singleton
    assert len(plan.assignments) == 3            # every node gets a key
    assert len(plan.merges) == 1                 # one merge group
    merge = plan.merges[0]
    assert merge.survivor_id == 2                # lowest node_id wins
    assert merge.loser_ids == [5]
    # survivor + loser share the same event_key
    assert plan.key_for(2) == plan.key_for(5)
    assert plan.key_for(9) != plan.key_for(2)


def test_plan_counts_for_dry_run():
    rows = [
        EventRow(2, "a", "t", "http://u", "d"),
        EventRow(3, "a", "t", "http://u", "d"),
    ]
    plan = plan_backfill(rows)
    assert plan.total == 2
    assert plan.duplicate_count == 1   # one node to be merged away
    assert plan.group_count == 1


def test_plan_idempotent_on_already_deduped_rows():
    """Re-run after a successful apply: rows are already unique -> no merges, and the
    recomputed keys equal a fresh EventRow.event_key() (deterministic)."""
    rows = [
        EventRow(2, "Strike on Kyiv", "c.armed", "http://u", "d"),
        EventRow(9, "Sanctions on Iran", "c.sanction", "http://u", "d"),
    ]
    plan = plan_backfill(rows)
    assert plan.merges == []
    assert plan.duplicate_count == 0
    assert plan.key_for(2) == rows[0].event_key()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_backfill_event_key.py -v`
Expected: FAIL — `ModuleNotFoundError: migrations.backfill_event_key`.

- [ ] **Step 3: Implement the pure planner + driver glue**

Create `services/data-ingestion/migrations/backfill_event_key.py`:

```python
"""Backfill event_key on live-pipeline :Event nodes (NOT :GDELTEvent) and merge
duplicates that collapse onto the same key, with parity to pipeline._event_key.

IDEMPOTENT BY RECOMPUTE: every run fetches ALL live :Event (not just event_key IS NULL),
recomputes the expected key in Python, (re)sets it, and merges any duplicate groups by the
computed key. So a crash after a partial apply self-heals on re-run — an `IS NULL` filter
would go blind to already-keyed survivors and leave duplicate groups unmerged.

Run with --dry-run first; it prints counts and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field

import structlog

from pipeline import _event_key, content_hash

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EventRow:
    node_id: int
    title: str
    codebook_type: str
    doc_url: str
    doc_title: str

    def event_key(self) -> str:
        return _event_key(content_hash(self.doc_title, self.doc_url),
                          self.codebook_type, self.title)


@dataclass
class MergeGroup:
    key: str
    survivor_id: int
    loser_ids: list[int]


@dataclass
class BackfillPlan:
    assignments: dict[int, str]            # node_id -> event_key
    merges: list[MergeGroup] = field(default_factory=list)

    def key_for(self, node_id: int) -> str:
        return self.assignments[node_id]

    @property
    def total(self) -> int:
        return len(self.assignments)

    @property
    def group_count(self) -> int:
        return len(self.merges)

    @property
    def duplicate_count(self) -> int:
        return sum(len(m.loser_ids) for m in self.merges)


def plan_backfill(rows: list[EventRow]) -> BackfillPlan:
    by_key: dict[str, list[int]] = {}
    assignments: dict[int, str] = {}
    for r in rows:
        k = r.event_key()
        assignments[r.node_id] = k
        by_key.setdefault(k, []).append(r.node_id)
    merges = []
    for k, ids in by_key.items():
        if len(ids) > 1:
            ordered = sorted(ids)            # lowest node_id = survivor (deterministic)
            merges.append(MergeGroup(key=k, survivor_id=ordered[0], loser_ids=ordered[1:]))
    return BackfillPlan(assignments=assignments, merges=merges)


# Fetch ALL live :Event (NOT :GDELTEvent) WITH document context — regardless of whether
# event_key is already set — so a re-run after a partial/crashed apply still sees every
# node and every duplicate group.
_FETCH = (
    "MATCH (d:Document)-[:DESCRIBES]->(ev:Event) "
    "WHERE NOT ev:GDELTEvent "
    "RETURN id(ev) AS node_id, ev.title AS title, "
    "       coalesce(ev.codebook_type,'other.unclassified') AS codebook_type, "
    "       d.url AS doc_url, coalesce(d.title,'') AS doc_title"
)
_SET_KEY = "MATCH (ev) WHERE id(ev) = $node_id SET ev.event_key = $key"
# Preflight before applying event_key_unique.cypher — MUST return zero rows.
_PREFLIGHT_DUP_KEYS = (
    "MATCH (ev:Event) WHERE NOT ev:GDELTEvent "
    "WITH ev.event_key AS k, count(*) AS c "
    "WHERE k IS NOT NULL AND c > 1 "
    "RETURN k AS event_key, c AS count ORDER BY c DESC"
)
_MERGE = (
    "MATCH (s) WHERE id(s) = $survivor_id "
    "MATCH (l) WHERE id(l) = $loser_id "
    "CALL apoc.refactor.mergeNodes([s, l], {properties:'discard', mergeRels:true}) "
    "YIELD node RETURN id(node)"
)


async def _fetch_rows(driver) -> list[EventRow]:
    async with driver.session() as s:
        res = await s.run(_FETCH)
        return [EventRow(r["node_id"], r["title"] or "", r["codebook_type"],
                         r["doc_url"], r["doc_title"]) async for r in res]


async def run(driver, *, dry_run: bool) -> BackfillPlan:
    rows = await _fetch_rows(driver)
    plan = plan_backfill(rows)
    log.info("backfill_event_key_plan", total=plan.total,
             groups=plan.group_count, duplicates=plan.duplicate_count, dry_run=dry_run)
    if dry_run:
        return plan
    merged_losers = {l for m in plan.merges for l in m.loser_ids}
    async with driver.session() as s:
        for m in plan.merges:                # collapse duplicate groups first
            for loser in m.loser_ids:
                await s.run(_MERGE, survivor_id=m.survivor_id, loser_id=loser)
        for node_id, key in plan.assignments.items():
            if node_id in merged_losers:
                continue                     # gone — merged into its survivor
            await s.run(_SET_KEY, node_id=node_id, key=key)   # (re)set; no-op if already correct
    return plan


async def verify_no_duplicate_keys(driver) -> list[tuple[str, int]]:
    """Preflight before applying event_key_unique.cypher — MUST return []."""
    async with driver.session() as s:
        res = await s.run(_PREFLIGHT_DUP_KEYS)
        return [(r["event_key"], r["count"]) async for r in res]


def _build_driver():
    import neo4j
    from config import settings
    return neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password))


async def _main(dry_run: bool) -> None:
    driver = _build_driver()
    try:
        await run(driver, dry_run=dry_run)
        if not dry_run:
            dups = await verify_no_duplicate_keys(driver)
            if dups:
                log.error("backfill_event_key_dups_remain", groups=len(dups), sample=dups[:5])
            else:
                log.info("backfill_event_key_verified", duplicate_keys=0)
    finally:
        await driver.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()
    asyncio.run(_main(dry_run=not args.apply))
```

Create `services/data-ingestion/migrations/event_key_unique.cypher`:

```cypher
// Apply ONLY after backfill_event_key.py --apply has run and reports 0 duplicate keys.
// Unique constraints allow NULLs, so :GDELTEvent nodes (which keep event_id, no event_key)
// are unaffected.
CREATE CONSTRAINT event_key_unique IF NOT EXISTS
FOR (ev:Event) REQUIRE ev.event_key IS UNIQUE;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_backfill_event_key.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff check migrations/backfill_event_key.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add migrations/backfill_event_key.py migrations/event_key_unique.cypher tests/test_backfill_event_key.py
git commit -m "feat(migration): backfill event_key + dedupe live Events, add unique constraint (WP-03)"
```

> **Operational note (do NOT run blind in prod):** the live run is
> `uv run python -m migrations.backfill_event_key` (dry-run, prints counts) → review counts →
> `uv run python -m migrations.backfill_event_key --apply` (re-runnable; it self-verifies via
> `_PREFLIGHT_DUP_KEYS` and logs `backfill_event_key_dups_remain` if any group survived) → **only when the
> preflight reports 0 duplicate keys**, apply `event_key_unique.cypher` via the existing `cypher-shell`/`apply.py`
> path. Requires the APOC plugin for `apoc.refactor.mergeNodes` (enabled in `docker-compose.yml`, consistent with the
> existing APOC migrations).

---

## Task 8: Lossy orphan-vector reconcile CLI

**Files:**
- Create: `services/data-ingestion/graph_integrity/reconcile_orphans.py`
- Test: `services/data-ingestion/tests/test_reconcile_orphans.py`

Heals vectors already orphaned in prod (Qdrant point exists, no Neo4j `Document`). **Lossy:** Qdrant carries only the title, so re-extraction is weaker than the original ingest. The forward fix (Tasks 1–6) is the real guarantee; this only cleans legacy damage.

- [ ] **Step 1: Write the failing test (pure detection)**

Create `services/data-ingestion/tests/test_reconcile_orphans.py`:

```python
from graph_integrity.reconcile_orphans import OrphanCandidate, find_orphans


def test_find_orphans_returns_points_whose_url_has_no_document():
    points = [
        OrphanCandidate(point_id=1, title="a", url="http://have"),
        OrphanCandidate(point_id=2, title="b", url="http://missing"),
    ]
    existing_doc_urls = {"http://have"}
    orphans = find_orphans(points, existing_doc_urls)
    assert [o.point_id for o in orphans] == [2]


def test_find_orphans_empty_when_all_present():
    points = [OrphanCandidate(1, "a", "http://have")]
    assert find_orphans(points, {"http://have"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reconcile_orphans.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `services/data-ingestion/graph_integrity/reconcile_orphans.py`:

```python
"""Lossy reconcile: find Qdrant points whose source URL has no Neo4j :Document and
re-run extraction from the stored title so the graph node is (re)created idempotently.

LOSSY — Qdrant stores only the title, not the original full text. The T1 forward fix is
the real guarantee; this heals legacy orphans only. Run with --dry-run first.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import structlog

from config import settings
from pipeline import content_hash, process_item

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OrphanCandidate:
    point_id: int
    title: str
    url: str


def find_orphans(points: list[OrphanCandidate], existing_doc_urls: set[str]) -> list[OrphanCandidate]:
    """Pure: points whose url is absent from the set of Document urls in Neo4j."""
    return [p for p in points if p.url and p.url not in existing_doc_urls]


async def _scroll_points(qdrant) -> list[OrphanCandidate]:
    out: list[OrphanCandidate] = []
    offset = None
    while True:
        batch, offset = qdrant.scroll(
            collection_name=settings.qdrant_collection,
            with_payload=True, limit=512, offset=offset,
        )
        for p in batch:
            pl = p.payload or {}
            if pl.get("url") and pl.get("title"):
                out.append(OrphanCandidate(p.id, pl["title"], pl["url"]))
        if offset is None:
            break
    return out


async def _existing_doc_urls(driver, urls: list[str]) -> set[str]:
    async with driver.session() as s:
        res = await s.run(
            "MATCH (d:Document) WHERE d.url IN $urls RETURN d.url AS url", urls=urls)
        return {r["url"] async for r in res}


async def run(qdrant, driver, *, dry_run: bool) -> list[OrphanCandidate]:
    points = await _scroll_points(qdrant)
    existing = await _existing_doc_urls(driver, [p.url for p in points])
    orphans = find_orphans(points, existing)
    log.info("reconcile_orphans_plan", total=len(points), orphans=len(orphans), dry_run=dry_run)
    if dry_run:
        return orphans
    for o in orphans:
        try:
            await process_item(
                title=o.title, text=o.title, url=o.url, source="reconcile",
                settings=settings, content_hash=content_hash(o.title, o.url),
                raise_on_write_error=True,
            )
        except Exception as exc:  # noqa: BLE001 — keep healing the rest
            log.warning("reconcile_item_failed", url=o.url, error=str(exc))
    return orphans


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="re-ingest orphans (default: dry-run)")
    args = ap.parse_args()

    import neo4j
    from qdrant_client import QdrantClient

    qc = QdrantClient(url=settings.qdrant_url)
    drv = neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_url, auth=(settings.neo4j_user, settings.neo4j_password))

    async def _go():
        try:
            await run(qc, drv, dry_run=not args.apply)
        finally:
            await drv.close()

    asyncio.run(_go())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reconcile_orphans.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff check graph_integrity/reconcile_orphans.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add graph_integrity/reconcile_orphans.py tests/test_reconcile_orphans.py
git commit -m "feat(graph-integrity): lossy orphan-vector reconcile CLI (WP-01 legacy repair)"
```

---

## Final verification

- [ ] **Run the full ingestion suite + lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green. If any pre-existing test asserted `CREATE (ev:Event`, update it to `MERGE (ev:Event` (grep: `grep -rn "CREATE (ev:Event" tests/`).

- [ ] **Run the write-path auditor**

Dispatch the `graph-rag-auditor` agent over `pipeline.py`, `feeds/gdelt_collector.py`, `feeds/rss_collector.py`, `migrations/backfill_event_key.py` to confirm: no LLM-generated Cypher on the write path, all writes parameter-bound, read/write separation intact.

- [ ] **Two-stage review** (spec-compliance + quality) before opening the PR, per project policy.

---

## Self-Review (author)

**Spec coverage (T1 section of the design spec):**
- WP-01 permanent loss → Tasks 1, 4, 5, 6 (raise + propagate + skip Qdrant so the dedup key is not minted). ✔
- WP-03 batch-amplified duplication → Tasks 2, 3 (deterministic `event_key` + `MERGE`) + dedup-retrieve guard in Tasks 5/6. ✔
- KNOWN BH-EDGE-WRITE-01 → Task 3 (`MERGE` not `CREATE`). ✔
- Redis only after success → Task 4 (raise exits before the Redis block). ✔
- Event-key normalization (trim/collapse/lowercase/cap 200) → Task 2. ✔
- Repair: backfill scope = live `:Event` not `:GDELTEvent`; dry-run counts; constraint after dedupe → Task 7. ✔
- Reconcile marked lossy → Task 8. ✔

**Placeholder scan:** none. The collector ingest methods are pinned to the real signatures (`GDELTCollector._ingest_articles(self, articles, query_name)`, `RSSCollector._process_feed(self, feed_meta)`); every code block is complete and runnable.

**Type/name consistency:** `Neo4jWriteError`, `content_hash`, `_event_key`, `_normalize_event_title`, `doc_content_hash`, `raise_on_write_error`, `event_key` used identically across Tasks 1–8. `content_hash` is imported into both collectors and reused by both the backfill and the reconcile script (single source — no duplicated formula).
