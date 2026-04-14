# Spark Ingestion Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route extraction-LLM-Calls from `services/data-ingestion` permanently to the DGX Spark vLLM (Gemma-4 26B) so Ingestion + Interactive can run in parallel without GPU swap.

**Architecture:** New `ingestion_vllm_*` settings in `data-ingestion/config.py`. `process_item` raises one of three exclusive error classes (`ExtractionTransientError`, `ExtractionConfigError`, or returns `None`/dict for valid-empty). All collectors that call `process_item` get matching except-blocks that skip Qdrant on errors → retry happens via source re-fetch (Hash-Dedup doesn't trip). New compose service `data-ingestion-spark` and odin.sh mode `interactive-spark` enable parallel operation. Old compose service `data-ingestion` keeps working by also receiving `INGESTION_VLLM_URL=http://vllm:8000` so `up ingestion` continues to use the local 27B model.

**Sequencing note:** Tasks 3 (rewire `_call_vllm`) and 4-7 (collector wraps) leave the branch in an intermediate state between commits where typed exceptions can propagate from `_call_vllm` while not all collectors catch them yet. **This is intentional for this single feature branch — do not cherry-pick individual commits to other branches.** Run all of Tasks 3-7 in one merge unit. Task 14's full test sweep validates the end-state.

**Tech Stack:** Python 3.12, httpx, pytest + pytest-asyncio, pydantic-settings, structlog, Docker Compose, bash.

**Spec:** `docs/superpowers/specs/2026-04-14-spark-ingestion-wiring-design.md`

---

## File Map

**Modify:**
- `services/data-ingestion/config.py` — add 3 ingestion settings
- `services/data-ingestion/pipeline.py` — new exception classes + `_call_vllm` uses ingestion settings + error mapping
- `services/data-ingestion/scheduler.py` — `check_ingestion_llm()` helper + call after `scheduler.start()`
- `services/data-ingestion/nlm_ingest/extract.py` — URL convention: function expects base URL without `/v1`
- `services/data-ingestion/nlm_ingest/cli.py` — pass `ingestion_vllm_url` / `ingestion_vllm_model`
- `services/data-ingestion/feeds/rss_collector.py` — except blocks around `process_item`
- `services/data-ingestion/feeds/gdelt_collector.py` — same
- `services/data-ingestion/feeds/telegram_collector.py` — same (2 call sites)
- `services/data-ingestion/feeds/firms_collector.py` — same
- `services/data-ingestion/feeds/usgs_collector.py` — same
- `services/data-ingestion/feeds/ucdp_collector.py` — same
- `services/data-ingestion/feeds/eonet_collector.py` — same
- `services/data-ingestion/feeds/gdacs_collector.py` — same
- `services/data-ingestion/feeds/hapi_collector.py` — same
- `services/data-ingestion/feeds/noaa_nhc_collector.py` — same
- `services/data-ingestion/feeds/portwatch_collector.py` — same (2 call sites)
- `docker-compose.yml` — new service `data-ingestion-spark`
- `odin.sh` — new mode `interactive-spark` + stop-updates in existing modes
- `.env.example` — 3 new env vars

**Create:**
- `services/data-ingestion/tests/test_pipeline_errors.py` — new test file for error-class mapping
- `services/data-ingestion/tests/test_scheduler_healthcheck.py` — new test file for `check_ingestion_llm()`
- `services/data-ingestion/tests/test_nlm_extract_url.py` — URL-normalization test
- `services/data-ingestion/tests/integration/test_spark_smoke.py` — integration test (skip-if-unreachable)

**Modify (tests):**
- `services/data-ingestion/tests/test_config.py` — assert ingestion defaults (create if missing)
- `services/data-ingestion/tests/test_pipeline.py` — update for new URL/model vars
- One test per existing collector for transient/config error skip behavior

---

## Task 1: Setup branch and config foundation

**Files:**
- Modify: `services/data-ingestion/config.py`
- Modify: `.env.example`
- Create: `services/data-ingestion/tests/test_config.py` (if missing — check first)

- [ ] **Step 1: Create feature branch**

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git checkout -b feature/spark-ingestion-wiring
```

- [ ] **Step 2: Check whether `tests/test_config.py` exists**

Run: `ls services/data-ingestion/tests/test_config.py 2>/dev/null && echo EXISTS || echo MISSING`

If MISSING, create the file in Step 3 below; if EXISTS, append the test class.

- [ ] **Step 3: Write failing test for ingestion config defaults**

Add (or create) at `services/data-ingestion/tests/test_config.py`:

```python
"""Tests for Settings — covers Spark ingestion vars."""

import os
from unittest.mock import patch

from config import Settings


class TestIngestionVllmSettings:
    def test_defaults_point_to_spark(self):
        s = Settings(_env_file=None)
        assert s.ingestion_vllm_url == "http://192.168.178.39:8000"
        assert s.ingestion_vllm_model == "google/gemma-4-26B-A4B-it"
        assert s.ingestion_vllm_timeout == 120.0

    def test_env_override(self):
        with patch.dict(os.environ, {
            "INGESTION_VLLM_URL": "http://other:9000",
            "INGESTION_VLLM_MODEL": "test/model",
            "INGESTION_VLLM_TIMEOUT": "60.5",
        }):
            s = Settings(_env_file=None)
            assert s.ingestion_vllm_url == "http://other:9000"
            assert s.ingestion_vllm_model == "test/model"
            assert s.ingestion_vllm_timeout == 60.5

    def test_legacy_vllm_url_preserved(self):
        """vllm_url must remain for backwards-compat with Modus D."""
        s = Settings(_env_file=None)
        assert s.vllm_url == "http://localhost:8000"
        assert s.vllm_model == "qwen3.5"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'ingestion_vllm_url'`

- [ ] **Step 5: Add settings fields**

In `services/data-ingestion/config.py`, after the existing `vllm_model` line (currently line 30), insert:

```python
    # Ingestion LLM (Spark — Gemma-4 26B). URL WITHOUT /v1 — callers append full path.
    ingestion_vllm_url: str = "http://192.168.178.39:8000"
    ingestion_vllm_model: str = "google/gemma-4-26B-A4B-it"
    ingestion_vllm_timeout: float = 120.0
```

- [ ] **Step 6: Run test to verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: Update `.env.example`**

Append to `.env.example`:

```bash

# Ingestion LLM (Spark — eliminates GPU swap on RTX 5090)
INGESTION_VLLM_URL=http://192.168.178.39:8000
INGESTION_VLLM_MODEL=google/gemma-4-26B-A4B-it
INGESTION_VLLM_TIMEOUT=120.0
```

- [ ] **Step 8: Commit**

```bash
git add services/data-ingestion/config.py services/data-ingestion/tests/test_config.py .env.example
git commit -m "feat(ingestion): add Spark vLLM settings + tests"
```

---

## Task 2: Add error classes to pipeline.py

**Files:**
- Modify: `services/data-ingestion/pipeline.py`
- Create: `services/data-ingestion/tests/test_pipeline_errors.py`

- [ ] **Step 1: Write failing test for error class definitions**

Create `services/data-ingestion/tests/test_pipeline_errors.py`:

```python
"""Tests for pipeline error classes."""

import pytest


def test_extraction_transient_error_exists():
    from pipeline import ExtractionTransientError
    assert issubclass(ExtractionTransientError, Exception)


def test_extraction_config_error_exists():
    from pipeline import ExtractionConfigError
    assert issubclass(ExtractionConfigError, Exception)


def test_error_classes_are_distinct():
    from pipeline import ExtractionConfigError, ExtractionTransientError
    assert not issubclass(ExtractionTransientError, ExtractionConfigError)
    assert not issubclass(ExtractionConfigError, ExtractionTransientError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_errors.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExtractionTransientError'`

- [ ] **Step 3: Add error classes to pipeline.py**

In `services/data-ingestion/pipeline.py`, after the imports block (around line 21, after `log = structlog.get_logger(__name__)`), add:

```python


class ExtractionTransientError(Exception):
    """vLLM extraction failed transiently (timeout, connect-error, 5xx, JSON-parse).

    Caller MUST skip Qdrant upsert so the item is retried via source re-fetch.
    """


class ExtractionConfigError(Exception):
    """vLLM extraction failed due to misconfiguration (404 model, 401/403 auth).

    Caller MUST skip Qdrant upsert. Recovery requires fixing config — no auto-retry.
    """
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_errors.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/pipeline.py services/data-ingestion/tests/test_pipeline_errors.py
git commit -m "feat(ingestion): add ExtractionTransientError and ExtractionConfigError"
```

---

## Task 3: Switch `_call_vllm` to ingestion settings + error mapping

**Files:**
- Modify: `services/data-ingestion/pipeline.py`
- Modify: `services/data-ingestion/tests/test_pipeline_errors.py`
- Modify: `services/data-ingestion/tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests for URL, model, and error mapping**

Append to `services/data-ingestion/tests/test_pipeline_errors.py`:

```python
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from config import Settings
from pipeline import (
    ExtractionConfigError,
    ExtractionTransientError,
    process_item,
)


def _settings(**overrides) -> Settings:
    base = {
        "redis_url": "redis://localhost:6379/0",
        "qdrant_url": "http://localhost:6333",
        "tei_embed_url": "http://localhost:8001",
        "vllm_url": "http://localhost:8000",
        "vllm_model": "legacy",
        "ingestion_vllm_url": "http://192.168.178.39:8000",
        "ingestion_vllm_model": "google/gemma-4-26B-A4B-it",
        "ingestion_vllm_timeout": 120.0,
        "neo4j_url": "http://localhost:7474",
        "neo4j_user": "neo4j",
        "neo4j_password": "test",
        "redis_stream_events": "events:new",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _ok_resp():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({
            "events": [], "entities": [], "locations": []
        })}}]
    }
    return resp


@pytest.mark.asyncio
async def test_call_vllm_uses_spark_url_and_model():
    """_call_vllm posts to ingestion_vllm_url + /v1/chat/completions, never /v1/v1."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["url"] = url
        captured["model"] = json["model"]
        return _ok_resp()

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await process_item(
            title="t", text="x", url="http://e/1", source="rss",
            settings=_settings(),
        )

    assert captured["url"] == "http://192.168.178.39:8000/v1/chat/completions"
    assert not re.search(r"/v1/v1", captured["url"])
    assert captured["model"] == "google/gemma-4-26B-A4B-it"


@pytest.mark.asyncio
async def test_connect_error_raises_transient():
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_timeout_raises_transient():
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("slow")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_http_5xx_raises_transient():
    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=MagicMock(status_code=503)
    )
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_http_4xx_raises_config(status):
    bad = MagicMock()
    bad.status_code = status
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=MagicMock(status_code=status)
    )
    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionConfigError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )


@pytest.mark.asyncio
async def test_json_parse_error_raises_transient():
    """JSON parse failure after 200 OK → transient (not silent unclassified)."""
    bad = MagicMock()
    bad.status_code = 200
    bad.raise_for_status = MagicMock()
    bad.json.return_value = {"choices": [{"message": {"content": "not-json {{"}}]}

    with patch("pipeline.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ExtractionTransientError):
            await process_item(
                title="t", text="x", url="http://e/1", source="rss",
                settings=_settings(),
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_errors.py -v`
Expected: All new tests FAIL (current `_call_vllm` uses `vllm_url`, doesn't raise the new classes).

- [ ] **Step 3: Update `_call_vllm` and `process_item` in pipeline.py**

Replace the current `_call_vllm` function (currently at `pipeline.py:176-205`) with:

```python
async def _call_vllm(title: str, text: str, url: str, settings: Settings) -> dict:
    """Call vLLM for intelligence extraction.

    Returns parsed dict on success.
    Raises ExtractionTransientError for timeout/connect/5xx/JSON-parse failure.
    Raises ExtractionConfigError for 404/401/403 (model/auth misconfiguration).
    """
    payload = {
        "model": settings.ingestion_vllm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Source: {url}\n\nText: {text[:4000]}"},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "intelligence_extraction",
                "schema": _RESPONSE_SCHEMA,
                "strict": True,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        async with httpx.AsyncClient(timeout=settings.ingestion_vllm_timeout) as client:
            resp = await client.post(
                f"{settings.ingestion_vllm_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ExtractionTransientError(f"timeout: {exc}") from exc
    except httpx.ConnectError as exc:
        raise ExtractionTransientError(f"connect: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403, 404):
            raise ExtractionConfigError(f"http {status}: {exc}") from exc
        if 500 <= status < 600:
            raise ExtractionTransientError(f"http {status}: {exc}") from exc
        raise ExtractionTransientError(f"http {status}: {exc}") from exc

    try:
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ExtractionTransientError(f"parse: {exc}") from exc
```

Replace the existing `process_item` Step 1 try/except (currently `pipeline.py:128-133`) with:

```python
    # Step 1: Call vLLM for extraction
    # ExtractionTransientError / ExtractionConfigError propagate to caller (collector).
    extraction = await _call_vllm(title, text, url, settings)

    if extraction is None:
        return None
```

(I.e. the bare `try/except Exception → log + return None` is removed; the typed errors propagate.)

- [ ] **Step 4: Run new error tests to verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_errors.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Update existing test_pipeline.py for new settings**

In `services/data-ingestion/tests/test_pipeline.py:11-24`, replace `_make_settings` with:

```python
def _make_settings(**overrides) -> Settings:
    defaults = {
        "redis_url": "redis://localhost:6379/0",
        "qdrant_url": "http://localhost:6333",
        "tei_embed_url": "http://localhost:8001",
        "vllm_url": "http://localhost:8000",
        "vllm_model": "models/qwen3.5-27b-awq",
        "ingestion_vllm_url": "http://192.168.178.39:8000",
        "ingestion_vllm_model": "google/gemma-4-26B-A4B-it",
        "ingestion_vllm_timeout": 120.0,
        "neo4j_url": "http://localhost:7474",
        "neo4j_user": "neo4j",
        "neo4j_password": "test",
        "redis_stream_events": "events:new",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)
```

The existing graceful-degradation test `test_returns_none_on_vllm_failure` (around `tests/test_pipeline.py:158`) needs adjustment: previously, vLLM failure returned `None`; now it raises `ExtractionTransientError`. Replace the test body with:

```python
    async def test_raises_transient_on_vllm_failure(self):
        """If vLLM call fails transiently, process_item raises ExtractionTransientError."""
        from pipeline import ExtractionTransientError

        with patch("pipeline.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("down")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ExtractionTransientError):
                await process_item(
                    title="t", text="x", url="http://e/1", source="rss",
                    settings=_make_settings(),
                )
```

Add `import httpx` at the top of `tests/test_pipeline.py` if missing.

- [ ] **Step 6: Run full pipeline test suite**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline.py tests/test_pipeline_errors.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add services/data-ingestion/pipeline.py services/data-ingestion/tests/test_pipeline.py services/data-ingestion/tests/test_pipeline_errors.py
git commit -m "feat(ingestion): route _call_vllm to Spark + map errors to typed classes"
```

---

## Task 4: rss_collector — handle both error classes

**Files:**
- Modify: `services/data-ingestion/feeds/rss_collector.py`
- Modify: `services/data-ingestion/tests/test_rss_collector.py` (or create if missing)

- [ ] **Step 1: Check whether `tests/test_rss_collector.py` exists**

Run: `ls services/data-ingestion/tests/test_rss_collector.py 2>/dev/null && echo EXISTS || echo MISSING`

- [ ] **Step 2: Write failing test for transient + config skip behavior**

If MISSING, create the file. If EXISTS, append a new `TestExtractionErrorHandling` class. Either way, the test class is:

```python
"""Tests for rss_collector error-handling behavior."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from feeds.rss_collector import RSSCollector
from pipeline import ExtractionConfigError, ExtractionTransientError


@pytest.fixture
def mock_qdrant():
    return MagicMock()


def _entry(title="T", link="http://e/1"):
    return {
        "title": title, "link": link, "summary": "s",
        "published": "2026-01-01", "published_parsed": None,
    }


@pytest.mark.asyncio
async def test_transient_error_skips_qdrant_upsert(mock_qdrant, monkeypatch):
    """When process_item raises ExtractionTransientError, item is NOT upserted."""
    parsed = MagicMock()
    parsed.entries = [_entry()]
    parsed.bozo = False

    mock_qdrant.retrieve.return_value = []  # not a duplicate

    collector = RSSCollector.__new__(RSSCollector)
    collector.qdrant = mock_qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.rss_collector.feedparser.parse", return_value=parsed), \
         patch("feeds.rss_collector.process_item",
               new=AsyncMock(side_effect=ExtractionTransientError("down"))), \
         patch("feeds.rss_collector.httpx.AsyncClient") as mock_http:
        # Mock the feed-fetch HTTP response (any 200 with text body).
        feed_resp = MagicMock()
        feed_resp.status_code = 200
        feed_resp.text = "<rss/>"
        feed_resp.raise_for_status = MagicMock()
        mc = AsyncMock()
        mc.get.return_value = feed_resp
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector._process_feed({"name": "test", "url": "http://feed/x"})

    mock_qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_config_error_skips_qdrant_upsert(mock_qdrant):
    """When process_item raises ExtractionConfigError, item is NOT upserted."""
    parsed = MagicMock()
    parsed.entries = [_entry()]
    parsed.bozo = False

    mock_qdrant.retrieve.return_value = []

    collector = RSSCollector.__new__(RSSCollector)
    collector.qdrant = mock_qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    with patch("feeds.rss_collector.feedparser.parse", return_value=parsed), \
         patch("feeds.rss_collector.process_item",
               new=AsyncMock(side_effect=ExtractionConfigError("404 model"))), \
         patch("feeds.rss_collector.httpx.AsyncClient") as mock_http, \
         patch("feeds.rss_collector.log.error") as mock_err:
        feed_resp = MagicMock()
        feed_resp.status_code = 200
        feed_resp.text = "<rss/>"
        feed_resp.raise_for_status = MagicMock()
        mc = AsyncMock()
        mc.get.return_value = feed_resp
        mock_http.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector._process_feed({"name": "test", "url": "http://feed/x"})

    mock_qdrant.upsert.assert_not_called()
    # Error log was emitted with the canonical key.
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)
```

(Method `_process_feed` is defined at `rss_collector.py:119` and contains the loop with the `process_item` call at `:176`. Pass `feed_meta={"name": "test", "url": "http://feed/x"}`.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd services/data-ingestion && uv run pytest tests/test_rss_collector.py::test_transient_error_skips_qdrant_upsert tests/test_rss_collector.py::test_config_error_skips_qdrant_upsert -v`
Expected: FAIL — current code lets the exception propagate uncaught (test will see exception, not a clean skip).

- [ ] **Step 4: Wrap `process_item` call in try/except**

In `services/data-ingestion/feeds/rss_collector.py` around line 17, add to the imports:

```python
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item
```

(The existing `from pipeline import process_item` line is replaced.)

Around `rss_collector.py:175-183`, replace:

```python
            # Intelligence extraction (graceful — failure doesn't block ingest)
            enrichment = await process_item(
                title=title,
                text=embed_text,
                url=link,
                source="rss",
                settings=settings,
                redis_client=self._redis,
            )
```

with:

```python
            # Intelligence extraction. Transient/config errors skip Qdrant upsert
            # so the item is retried on the next source re-fetch (Hash-Dedup doesn't trip).
            try:
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=link,
                    source="rss",
                    settings=settings,
                    redis_client=self._redis,
                )
            except ExtractionTransientError as exc:
                log.warning("extraction_skipped_transient", url=link, error=str(exc))
                continue
            except ExtractionConfigError as exc:
                log.error("extraction_skipped_config", url=link, error=str(exc))
                continue
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_rss_collector.py -v`
Expected: PASS (both new tests + any pre-existing tests)

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/feeds/rss_collector.py services/data-ingestion/tests/test_rss_collector.py
git commit -m "feat(ingestion): rss_collector skips Qdrant on extraction errors"
```

---

## Task 5: gdelt_collector — same except-block

**Files:**
- Modify: `services/data-ingestion/feeds/gdelt_collector.py`
- Modify: `services/data-ingestion/tests/test_gdelt_collector.py` (or new)

- [ ] **Step 1: Locate the call site**

Run: `grep -n "process_item\|def " services/data-ingestion/feeds/gdelt_collector.py | head -40`

The call site is at `gdelt_collector.py:151`.

- [ ] **Step 2: Write failing test**

Pattern: same as Task 4, but using GDELT's enclosing method (find with grep above). If a `tests/test_gdelt_collector.py` exists, append:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from feeds.gdelt_collector import GDELTCollector
from pipeline import ExtractionConfigError, ExtractionTransientError


@pytest.mark.asyncio
async def test_gdelt_transient_skips_upsert():
    qdrant = MagicMock()
    qdrant.retrieve.return_value = []
    collector = GDELTCollector.__new__(GDELTCollector)
    collector.qdrant = qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    # Mock the GDELT API response with one article.
    gdelt_resp = MagicMock()
    gdelt_resp.status_code = 200
    gdelt_resp.json.return_value = {"articles": [{
        "title": "x", "url": "http://e/1", "seendate": "20260101T000000Z",
        "domain": "ex.com", "language": "English",
    }]}
    gdelt_resp.raise_for_status = MagicMock()

    with patch("feeds.gdelt_collector.httpx.AsyncClient") as mock_cls, \
         patch("feeds.gdelt_collector.process_item",
               new=AsyncMock(side_effect=ExtractionTransientError("down"))):
        mc = AsyncMock()
        mc.get.return_value = gdelt_resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Call whichever public method runs the loop — verify with `grep "def " ...`
        await collector.collect()

    qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_gdelt_config_skips_upsert():
    qdrant = MagicMock()
    qdrant.retrieve.return_value = []
    collector = GDELTCollector.__new__(GDELTCollector)
    collector.qdrant = qdrant
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    gdelt_resp = MagicMock()
    gdelt_resp.status_code = 200
    gdelt_resp.json.return_value = {"articles": [{
        "title": "x", "url": "http://e/1", "seendate": "20260101T000000Z",
        "domain": "ex.com", "language": "English",
    }]}
    gdelt_resp.raise_for_status = MagicMock()

    with patch("feeds.gdelt_collector.httpx.AsyncClient") as mock_cls, \
         patch("feeds.gdelt_collector.process_item",
               new=AsyncMock(side_effect=ExtractionConfigError("404"))), \
         patch("feeds.gdelt_collector.log.error") as mock_err:
        mc = AsyncMock()
        mc.get.return_value = gdelt_resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await collector.collect()

    qdrant.upsert.assert_not_called()
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)
```

(Engineer: verify the actual public collect method name and GDELT response shape against the source. Adjust accordingly.)

- [ ] **Step 3: Run tests — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_collector.py -v -k "transient or config"`

- [ ] **Step 4: Update gdelt_collector.py imports and call site**

Replace `from pipeline import process_item` (`gdelt_collector.py:16`) with:

```python
from pipeline import ExtractionConfigError, ExtractionTransientError, process_item
```

Wrap the call at `gdelt_collector.py:151` in the same try/except as Task 4 Step 4 (use `gdelt` as `source` in log key suffix where helpful, but log keys stay the same: `extraction_skipped_transient` / `extraction_skipped_config`).

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_collector.py -v`

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/feeds/gdelt_collector.py services/data-ingestion/tests/test_gdelt_collector.py
git commit -m "feat(ingestion): gdelt_collector skips Qdrant on extraction errors"
```

---

## Task 6: telegram_collector — two call sites

**Files:**
- Modify: `services/data-ingestion/feeds/telegram_collector.py`
- Modify: `services/data-ingestion/tests/test_telegram_collector.py`

Telegram has two call sites: `telegram_collector.py:351` (single message path) and `telegram_collector.py:432` (album path). Both need wrapping.

- [ ] **Step 1: Inspect both call sites**

Run: `sed -n '300,360p;380,440p' services/data-ingestion/feeds/telegram_collector.py`

Note: each site does its own `from pipeline import process_item` lazy import inside the function. Replace each with `from pipeline import ExtractionConfigError, ExtractionTransientError, process_item`.

- [ ] **Step 2: Write failing test for single-message transient skip**

First inspect existing setup in `tests/test_telegram_collector.py:740-744` to understand how the suite mocks Telethon clients and qdrant. The four new tests follow the same pattern but vary `process_item`'s `side_effect`. Append:

```python
from pipeline import ExtractionConfigError, ExtractionTransientError


@pytest.mark.asyncio
async def test_telegram_single_message_transient_skips_upsert(
    tmp_path, monkeypatch
):
    """Single-message path: ExtractionTransientError → no Qdrant upsert."""
    from feeds.telegram_collector import TelegramCollector

    collector = TelegramCollector.__new__(TelegramCollector)
    collector.qdrant = MagicMock()
    collector.qdrant.retrieve.return_value = []
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    msg = MagicMock()
    msg.id = 1
    msg.message = "hello"
    msg.date = MagicMock()
    msg.date.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    msg.media = None
    msg.grouped_id = None

    chan_cfg = MagicMock(handle="@x", display_name="x")

    with patch("pipeline.process_item",
               new_callable=AsyncMock,
               side_effect=ExtractionTransientError("down")):
        await collector._process_single_message(msg, chan_cfg)

    collector.qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_single_message_config_skips_upsert():
    """Single-message path: ExtractionConfigError → no Qdrant upsert + error log."""
    from feeds.telegram_collector import TelegramCollector
    from feeds import telegram_collector as tcm

    collector = TelegramCollector.__new__(TelegramCollector)
    collector.qdrant = MagicMock()
    collector.qdrant.retrieve.return_value = []
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    msg = MagicMock()
    msg.id = 1
    msg.message = "hello"
    msg.date = MagicMock()
    msg.date.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    msg.media = None
    msg.grouped_id = None

    chan_cfg = MagicMock(handle="@x", display_name="x")

    with patch("pipeline.process_item",
               new_callable=AsyncMock,
               side_effect=ExtractionConfigError("404")), \
         patch.object(tcm.log, "error") as mock_err:
        await collector._process_single_message(msg, chan_cfg)

    collector.qdrant.upsert.assert_not_called()
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)


@pytest.mark.asyncio
async def test_telegram_album_transient_skips_upsert():
    """Album path (telegram_collector.py:432): same skip semantics."""
    from feeds.telegram_collector import TelegramCollector

    collector = TelegramCollector.__new__(TelegramCollector)
    collector.qdrant = MagicMock()
    collector.qdrant.retrieve.return_value = []
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    album_msg = MagicMock()
    album_msg.id = 10
    album_msg.message = "caption"
    album_msg.date = MagicMock()
    album_msg.date.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    album_msg.grouped_id = 99
    chan_cfg = MagicMock(handle="@x", display_name="x")

    with patch("pipeline.process_item",
               new_callable=AsyncMock,
               side_effect=ExtractionTransientError("down")):
        await collector._process_album([album_msg], chan_cfg)

    collector.qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_album_config_skips_upsert():
    from feeds.telegram_collector import TelegramCollector
    from feeds import telegram_collector as tcm

    collector = TelegramCollector.__new__(TelegramCollector)
    collector.qdrant = MagicMock()
    collector.qdrant.retrieve.return_value = []
    collector._redis = None
    collector._embed = AsyncMock(return_value=[0.0] * 1024)

    album_msg = MagicMock()
    album_msg.id = 10
    album_msg.message = "caption"
    album_msg.date = MagicMock()
    album_msg.date.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    album_msg.grouped_id = 99
    chan_cfg = MagicMock(handle="@x", display_name="x")

    with patch("pipeline.process_item",
               new_callable=AsyncMock,
               side_effect=ExtractionConfigError("404")), \
         patch.object(tcm.log, "error") as mock_err:
        await collector._process_album([album_msg], chan_cfg)

    collector.qdrant.upsert.assert_not_called()
    assert any(c.args[0] == "extraction_skipped_config" for c in mock_err.call_args_list)
```

(Method names `_process_single_message` and `_process_album` are derived from the surrounding code; verify with `grep -n "async def _process" services/data-ingestion/feeds/telegram_collector.py` and adjust if naming differs. Field names on `chan_cfg` follow `feeds/telegram_models.py`'s `ChannelConfig` schema — read it before adapting.)

- [ ] **Step 3: Run tests — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py -v -k "transient or config"`

- [ ] **Step 4: Wrap both call sites**

For `telegram_collector.py:308` (lazy import at single-message path) — replace with:

```python
        from pipeline import ExtractionConfigError, ExtractionTransientError, process_item
```

For the call at `telegram_collector.py:351`, wrap in:

```python
        try:
            enrichment = await process_item(
                title=title,
                text=text,
                url=url,
                source="telegram",
                settings=settings,
                redis_client=self._redis,
            )
        except ExtractionTransientError as exc:
            log.warning("extraction_skipped_transient", url=url, error=str(exc))
            continue
        except ExtractionConfigError as exc:
            log.error("extraction_skipped_config", url=url, error=str(exc))
            continue
```

(If the enclosing block is not a loop, replace `continue` with `return None` or whatever makes the function skip the upsert for this item — verify by reading the surrounding 30 lines.)

Repeat for the album call site at `telegram_collector.py:387` (lazy import) and `:432` (call).

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_telegram_collector.py -v`

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/feeds/telegram_collector.py services/data-ingestion/tests/test_telegram_collector.py
git commit -m "feat(ingestion): telegram_collector skips Qdrant on extraction errors (both paths)"
```

---

## Task 7: Remaining collectors — apply the same pattern

For each of the following collectors, apply the same pattern as Task 4 (one TDD cycle each, one commit per collector):

- `firms_collector.py:183`
- `usgs_collector.py:273`
- `ucdp_collector.py:190`
- `eonet_collector.py:100` (lazy import inside function)
- `gdacs_collector.py:94` (lazy import)
- `hapi_collector.py:88` (lazy import)
- `noaa_nhc_collector.py:89` (lazy import)
- `portwatch_collector.py:124` and `:170` (lazy import, two sites)

For each:

- [ ] **Step 1: Find the enclosing loop/function** with `grep -n "def \|process_item" services/data-ingestion/feeds/<name>.py`

- [ ] **Step 2: Write a transient-skip + config-skip test** in `tests/test_<name>.py`. Use the Task 4 RSS test as template; adapt to the collector's mock pattern (look at any existing test in that file for the right HTTP-response mocks).

- [ ] **Step 3: Run test — expect FAIL**

- [ ] **Step 4: Update the collector**:
  - Top-level import: `from pipeline import ExtractionConfigError, ExtractionTransientError, process_item` (or the lazy-import version inside the function).
  - Wrap the `await process_item(...)` call in the standard try/except (Task 4 Step 4).

- [ ] **Step 5: Run test — expect PASS**

- [ ] **Step 6: Commit**: `git commit -m "feat(ingestion): <name> skips Qdrant on extraction errors"`

**End of Task 7:** Run the full collector test suite to catch regressions:

```bash
cd services/data-ingestion && uv run pytest tests/ -v -k "collector"
```
Expected: All PASS.

---

## Task 8: NLM extract — switch URL convention

**Files:**
- Modify: `services/data-ingestion/nlm_ingest/extract.py`
- Create: `services/data-ingestion/tests/test_nlm_extract_url.py`

- [ ] **Step 1: Write failing test for new URL convention**

Create `services/data-ingestion/tests/test_nlm_extract_url.py`:

```python
"""Verify extract_with_qwen treats vllm_url as base URL without /v1."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nlm_ingest.extract import extract_with_qwen
from nlm_ingest.schemas import Transcript


def _transcript():
    # Transcript requires notebook_id, duration_seconds, language, segments, full_text
    # (see nlm_ingest/schemas.py:33-38).
    return Transcript(
        notebook_id="nb1",
        duration_seconds=10.0,
        language="en",
        segments=[],
        full_text="hello world",
    )


def _ok_resp():
    # extract_with_qwen parses entities/relations/claims (see extract.py:79-81).
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps({
        "entities": [], "relations": [], "claims": [],
    })}}]}
    return resp


@pytest.mark.asyncio
async def test_extract_appends_v1_chat_completions_to_base_url():
    """vllm_url is base URL (no /v1). Function appends /v1/chat/completions."""
    captured = {}

    async def fake_post(url, json=None, **kw):
        captured["url"] = url
        captured["model"] = json["model"]
        return _ok_resp()

    client = AsyncMock()
    client.post.side_effect = fake_post

    await extract_with_qwen(
        transcript=_transcript(),
        metadata={},
        client=client,
        vllm_url="http://192.168.178.39:8000",
        vllm_model="google/gemma-4-26B-A4B-it",
    )

    assert captured["url"] == "http://192.168.178.39:8000/v1/chat/completions"
    assert not re.search(r"/v1/v1", captured["url"])
    assert captured["model"] == "google/gemma-4-26B-A4B-it"
```

(Engineer: adjust `Transcript` and response-content shape if `nlm_ingest/schemas.py` defines them differently. Read that file first.)

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_nlm_extract_url.py -v`
Expected: FAIL — currently the function appends `/chat/completions` (no `/v1`).

- [ ] **Step 3: Update extract.py URL line**

In `services/data-ingestion/nlm_ingest/extract.py:66`, change:

```python
    response = await client.post(
        f"{vllm_url}/chat/completions",
```

to:

```python
    response = await client.post(
        f"{vllm_url}/v1/chat/completions",
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_nlm_extract_url.py -v`
Expected: PASS

- [ ] **Step 5: Run existing nlm_extract tests for regressions**

Run: `cd services/data-ingestion && uv run pytest tests/test_nlm_extract.py -v`
Expected: PASS (some tests may need updating — if any fail, update the mock URL/payload in those tests to match the new convention).

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/nlm_ingest/extract.py services/data-ingestion/tests/test_nlm_extract_url.py
git commit -m "fix(nlm): extract_with_qwen treats vllm_url as base (appends /v1/chat/completions)"
```

---

## Task 9: NLM CLI — pass ingestion settings

**Files:**
- Modify: `services/data-ingestion/nlm_ingest/cli.py`

- [ ] **Step 1: Write a focused test for the CLI URL/model wiring**

Create `services/data-ingestion/tests/test_nlm_cli_wiring.py`:

```python
"""Verify nlm_ingest.cli passes ingestion_vllm_* to extract_with_qwen."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_cli_extract_uses_ingestion_vllm_settings(tmp_path, monkeypatch):
    """The 'extract' CLI step must use ingestion_vllm_url (no '+ /v1') and
    ingestion_vllm_model when calling extract_with_qwen."""

    # Smoke-level: import the module and inspect the relevant call line.
    # Easiest: patch extract_with_qwen, drive the CLI extract entry, capture kwargs.
    from nlm_ingest import cli

    captured = {}

    async def fake_extract(**kwargs):
        captured.update(kwargs)
        from nlm_ingest.schemas import Extraction
        return Extraction(
            notebook_id=kwargs["transcript"].notebook_id,
            entities=[],
            relations=[],
            claims=[],
            extraction_model=kwargs["vllm_model"],
            prompt_version="v0-test",
        )

    # Use whatever entry is the smallest unit that drives the call.
    # If cli has a function `_run_extract_for_one(...)`, prefer that.
    # Otherwise drive Click runner over a single-notebook fixture.
    ...

    assert captured["vllm_url"] == "http://192.168.178.39:8000"
    assert "/v1" not in captured["vllm_url"]
    assert captured["vllm_model"] == "google/gemma-4-26B-A4B-it"
```

(Engineer: read `nlm_ingest/cli.py` to find the smallest test surface — likely the `extract` subcommand. Use Click's `CliRunner` if needed. The key assertion is the two captured kwargs.)

- [ ] **Step 2: Run test — expect FAIL**

Currently the CLI passes `settings.vllm_url + "/v1"` and `settings.vllm_model`.

- [ ] **Step 3: Update CLI**

In `services/data-ingestion/nlm_ingest/cli.py:217-223`, change:

```python
                    extraction = await extract_with_qwen(
                        transcript=transcript,
                        metadata=metadata,
                        client=client,
                        vllm_url=settings.vllm_url + "/v1",
                        vllm_model=settings.vllm_model,
                    )
```

to:

```python
                    extraction = await extract_with_qwen(
                        transcript=transcript,
                        metadata=metadata,
                        client=client,
                        vllm_url=settings.ingestion_vllm_url,
                        vllm_model=settings.ingestion_vllm_model,
                    )
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/nlm_ingest/cli.py services/data-ingestion/tests/test_nlm_cli_wiring.py
git commit -m "fix(nlm-cli): pass ingestion_vllm_url/model (drop legacy '+ /v1')"
```

---

## Task 10: Scheduler healthcheck

**Files:**
- Modify: `services/data-ingestion/scheduler.py`
- Create: `services/data-ingestion/tests/test_scheduler_healthcheck.py`

- [ ] **Step 1: Write failing tests for three healthcheck outcomes**

Create `services/data-ingestion/tests/test_scheduler_healthcheck.py`:

```python
"""Tests for check_ingestion_llm() — three exclusive outcomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_ready_when_model_in_response(caplog):
    """200 + model in data[].id → log 'ingestion_llm_ready'."""
    from scheduler import check_ingestion_llm

    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [
        {"id": "google/gemma-4-26B-A4B-it"},
        {"id": "other/model"},
    ]}

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with caplog.at_level("INFO"):
            await check_ingestion_llm()

    assert any("ingestion_llm_ready" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_model_mismatch_logs_error(caplog):
    """200 + model NOT in data[].id → log 'ingestion_llm_model_mismatch'."""
    from scheduler import check_ingestion_llm

    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [{"id": "wrong/model"}]}

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = resp
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with caplog.at_level("ERROR"):
            await check_ingestion_llm()

    assert any("ingestion_llm_model_mismatch" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_4xx_logs_config_error(status, caplog):
    """401/403/404 on /v1/models → log 'ingestion_llm_config_error'."""
    from scheduler import check_ingestion_llm

    bad = MagicMock()
    bad.status_code = status
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status), request=MagicMock(), response=MagicMock(status_code=status)
    )

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.return_value = bad
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with caplog.at_level("ERROR"):
            await check_ingestion_llm()

    assert any("ingestion_llm_config_error" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_connect_error_logs_unreachable(caplog):
    """ConnectError → log 'ingestion_llm_unreachable'."""
    from scheduler import check_ingestion_llm

    with patch("scheduler.httpx.AsyncClient") as mock_cls:
        mc = AsyncMock()
        mc.get.side_effect = httpx.ConnectError("refused")
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mc)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with caplog.at_level("WARNING"):
            await check_ingestion_llm()

    assert any("ingestion_llm_unreachable" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_check_never_raises():
    """check_ingestion_llm() never raises — scheduler must always start."""
    from scheduler import check_ingestion_llm

    with patch("scheduler.httpx.AsyncClient", side_effect=Exception("anything")):
        # Must not raise.
        await check_ingestion_llm()
```

(Note: structlog routes through stdlib logging; `caplog` captures by message-key substring above. If structlog isn't piping to stdlib in tests, switch the assertion to capturing structlog's own list-handler — see `structlog.testing.capture_logs`.)

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_scheduler_healthcheck.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_ingestion_llm'`

- [ ] **Step 3: Add helper to scheduler.py**

In `services/data-ingestion/scheduler.py`, after the imports block (around line 33), add:

```python
import httpx


async def check_ingestion_llm() -> None:
    """Probe the ingestion vLLM at startup. Never raises — only logs.

    Three exclusive outcomes:
      - ready: 200 + ingestion_vllm_model in data[].id
      - config error: 200 without model OR 401/403/404
      - unreachable: connect/timeout/5xx
    """
    url = f"{settings.ingestion_vllm_url}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ids = [m.get("id") for m in resp.json().get("data", [])]
            if settings.ingestion_vllm_model in ids:
                log.info(
                    "ingestion_llm_ready",
                    url=settings.ingestion_vllm_url,
                    model=settings.ingestion_vllm_model,
                )
            else:
                log.error(
                    "ingestion_llm_model_mismatch",
                    url=settings.ingestion_vllm_url,
                    expected=settings.ingestion_vllm_model,
                    available=ids,
                )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403, 404):
            log.error(
                "ingestion_llm_config_error",
                url=url,
                status=status,
                error=str(exc),
            )
        else:
            log.warning(
                "ingestion_llm_unreachable",
                url=url,
                error=f"http {status}",
            )
    except Exception as exc:  # ConnectError, TimeoutException, anything else
        log.warning("ingestion_llm_unreachable", url=url, error=str(exc))
```

Also ensure `log = structlog.get_logger(__name__)` exists in `scheduler.py` (verify with `grep "get_logger" services/data-ingestion/scheduler.py`). If absent, add after the structlog config block.

- [ ] **Step 4: Wire helper into `main()`**

In `services/data-ingestion/scheduler.py`, find the line right after `scheduler.start()` and before `log.info("scheduler_running", ...)` (around `scheduler.py:421-425`). Insert:

```python
    await check_ingestion_llm()
```

(After `scheduler.start()` and before `initial_collection_starting`.)

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_scheduler_healthcheck.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/scheduler.py services/data-ingestion/tests/test_scheduler_healthcheck.py
git commit -m "feat(scheduler): add startup healthcheck for Spark ingestion LLM"
```

---

## Task 11: docker-compose — preserve `up ingestion` fallback + add `data-ingestion-spark`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Locate existing `data-ingestion` service**

Run: `grep -n "data-ingestion:" docker-compose.yml`
Note the line range (currently lines 263-293).

- [ ] **Step 2: Add INGESTION_VLLM_URL to existing `data-ingestion` service (Fallback fix)**

Since the new `_call_vllm` reads `INGESTION_VLLM_URL` instead of the legacy `VLLM_URL`, the existing `data-ingestion` service (used by `up ingestion`) MUST also export the ingestion vars — otherwise `up ingestion` would silently route to Spark instead of the local 27B vLLM, breaking the Fallback contract from spec §Nicht-Ziele.

In the `data-ingestion` service `environment:` block (currently lines ~269-279), add three new lines next to the existing `VLLM_URL=http://vllm:8000`:

```yaml
      - INGESTION_VLLM_URL=http://vllm:8000
      - INGESTION_VLLM_MODEL=qwen3.5
      - INGESTION_VLLM_TIMEOUT=120.0
```

(Keep the existing `VLLM_URL` / `VLLM_MODEL` lines for backwards-compat; they are no longer read by the pipeline but are documented as the legacy vars.)

- [ ] **Step 3: Add new service immediately after `data-ingestion`**

Insert (after the `restart: unless-stopped` line of `data-ingestion`):

```yaml

  # ═══ DATA INGESTION (interactive-spark mode) ═══
  # Identical to data-ingestion but uses Spark vLLM as ingestion backend
  # → no GPU swap on RTX 5090.
  data-ingestion-spark:
    profiles: ["interactive-spark"]
    container_name: odin-data-ingestion-spark
    build:
      context: ./services/data-ingestion
      dockerfile: Dockerfile
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - QDRANT_URL=http://qdrant:6333
      - TEI_EMBED_URL=http://tei-embed:80
      - INGESTION_VLLM_URL=http://192.168.178.39:8000
      - INGESTION_VLLM_MODEL=google/gemma-4-26B-A4B-it
      - INGESTION_VLLM_TIMEOUT=120.0
      - NEO4J_URL=http://neo4j:7474
      - NEO4J_USER=${NEO4J_USER:-neo4j}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD:-odin1234}
      - TELEGRAM_API_ID=${TELEGRAM_API_ID:-0}
      - TELEGRAM_API_HASH=${TELEGRAM_API_HASH:-}
    volumes:
      - ${ODIN_DATA_DIR:-${HOME}/ODIN/odin-data}/telegram:/data/telegram
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

- [ ] **Step 4: Validate compose syntax**

Run: `docker compose --profile interactive-spark config --quiet`
Expected: exit 0, no output.

- [ ] **Step 5: Verify `data-ingestion-spark` has no `vllm-27b` dep (robust check via Python YAML)**

Run:
```bash
docker compose --profile interactive-spark config | uv run --with pyyaml python -c '
import sys, yaml
cfg = yaml.safe_load(sys.stdin)
deps = cfg["services"]["data-ingestion-spark"].get("depends_on", {})
deps_list = list(deps.keys()) if isinstance(deps, dict) else list(deps)
assert "vllm-27b" not in deps_list, f"unexpected dep on vllm-27b: {deps_list}"
print("OK: no vllm-27b dep, depends_on =", deps_list)
'
```
Expected: `OK: no vllm-27b dep, depends_on = ['redis', 'qdrant', 'neo4j', 'tei-embed']`

- [ ] **Step 6: Verify `up ingestion` still routes to local vllm (Fallback check)**

Run:
```bash
docker compose --profile ingestion config | uv run --with pyyaml python -c '
import sys, yaml
cfg = yaml.safe_load(sys.stdin)
env = cfg["services"]["data-ingestion"].get("environment", [])
env_dict = dict(s.split("=", 1) for s in env) if isinstance(env, list) else env
assert env_dict.get("INGESTION_VLLM_URL") == "http://vllm:8000", env_dict.get("INGESTION_VLLM_URL")
print("OK: up ingestion routes to local vllm")
'
```

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): add data-ingestion-spark service for interactive-spark profile"
```

---

## Task 12: odin.sh — new mode + stop-updates

**Files:**
- Modify: `odin.sh`

- [ ] **Step 1: Update usage block**

In `odin.sh:17-30`, add this line to the help text after the `up interactive` line:

```
  ./odin.sh up interactive-spark  # Interactive on 5090 + Ingestion via Spark (no GPU swap)
```

- [ ] **Step 2: Add new case to `start_mode()`**

In `odin.sh`, the `start_mode()` function's `case "$mode"` block (around lines 40-64), add a new case before the `*)` default:

```bash
    interactive-spark)
      "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-27b data-ingestion 2>/dev/null || true
      echo "Pre-flight: checking Spark vLLM..."
      curl -sf http://192.168.178.39:8000/v1/models > /dev/null \
        && echo "  Spark reachable" \
        || echo "  WARN: Spark unreachable — scheduler will retry"
      echo "Starting INTERACTIVE+SPARK mode: 9B local + Ingestion via Spark"
      "${COMPOSE[@]}" --profile interactive --profile interactive-spark up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}" data-ingestion-spark
      ;;
```

- [ ] **Step 3: Update `ingestion)` case to also stop `data-ingestion-spark`**

Change the existing `ingestion)` branch (`odin.sh:43-50`) from:

```bash
    ingestion)
      "${COMPOSE[@]}" --profile ingestion --profile interactive stop \
        vllm-9b tei-rerank intelligence backend frontend 2>/dev/null || true
```

to:

```bash
    ingestion)
      "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-9b tei-rerank intelligence backend frontend data-ingestion-spark 2>/dev/null || true
```

- [ ] **Step 4: Update `interactive)` case the same way**

Change `odin.sh:51-57` from:

```bash
    interactive)
      "${COMPOSE[@]}" --profile ingestion --profile interactive stop \
        vllm-27b data-ingestion 2>/dev/null || true
```

to:

```bash
    interactive)
      "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-27b data-ingestion data-ingestion-spark 2>/dev/null || true
```

- [ ] **Step 5: Update `down` command (if present)**

Run: `grep -n "^down\|down)" odin.sh`

If a `down)` case or `down` function exists, ensure it includes `--profile interactive-spark` so `data-ingestion-spark` stops too. Example:

```bash
"${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark down
```

- [ ] **Step 6: Extend `doctor()` with Spark reachability check**

In `odin.sh`, find the `doctor()` function (`odin.sh:67`). Append before its closing `}`:

```bash
  echo "Spark vLLM reachability..."
  if curl -sf --max-time 5 http://192.168.178.39:8000/v1/models > /dev/null; then
    echo "  OK (Spark reachable)"
  else
    echo "  WARN: Spark unreachable — interactive-spark mode will retry but extraction blocks"
  fi
```

- [ ] **Step 7: Extend `smoke()` with Spark check**

In `odin.sh`, the `smoke()` function (`odin.sh:112`) uses `_check` and `_check_if_running` helpers. Add a new conditional line in the appropriate position (next to other `_check` calls; verify by reading lines 112-200 first):

```bash
  # Spark vLLM (used by interactive-spark mode). Always probed; SKIP if unreachable.
  if curl -sf --max-time 3 http://192.168.178.39:8000/v1/models > /dev/null 2>&1; then
    _check "spark-vllm" "http://192.168.178.39:8000/v1/models" 200
  else
    printf "  %-28s %s\n" "spark-vllm" "SKIP (unreachable)"
    _inc_skip
  fi
```

- [ ] **Step 8: Bash syntax check**

Run: `bash -n odin.sh`
Expected: exit 0.

- [ ] **Step 9: Run doctor + smoke**

```bash
./odin.sh doctor
./odin.sh smoke
```
Expected: doctor prints Spark line; smoke includes a `spark-vllm` row (OK or SKIP).

- [ ] **Step 10: Manual mode-switch test (skip if Docker daemon unavailable)**

```bash
./odin.sh up interactive-spark
sleep 5
docker compose ps --status running --format '{{.Service}}' | grep data-ingestion | sort
# Expected: only "data-ingestion-spark"

./odin.sh up ingestion
sleep 5
docker compose ps --status running --format '{{.Service}}' | grep data-ingestion | sort
# Expected: only "data-ingestion"

./odin.sh down
```

If both schedulers show up at any switch, the stop-update is wrong — fix and retest. Note: the existing `data-ingestion` service has no `container_name` (uses the auto-generated `odin-data-ingestion-1`), while the new `data-ingestion-spark` pins `container_name: odin-data-ingestion-spark`. Use `docker compose ps --format` (which shows compose service names, not container names) for portability.

- [ ] **Step 11: Commit**

```bash
git add odin.sh
git commit -m "feat(orchestration): add 'interactive-spark' mode + cross-mode stop-cleanup"
```

---

## Task 13: Integration smoke test

**Files:**
- Create: `services/data-ingestion/tests/integration/__init__.py` (empty, if missing)
- Create: `services/data-ingestion/tests/integration/test_spark_smoke.py`

- [ ] **Step 1: Check folder existence**

Run: `ls services/data-ingestion/tests/integration 2>/dev/null || mkdir -p services/data-ingestion/tests/integration && touch services/data-ingestion/tests/integration/__init__.py`

- [ ] **Step 2: Create the smoke test**

Create `services/data-ingestion/tests/integration/test_spark_smoke.py`:

```python
"""Integration smoke test against real Spark vLLM.

Skipped automatically if Spark is unreachable.
Run explicitly: pytest tests/integration -v
"""

import socket

import httpx
import pytest

from config import Settings


def _spark_reachable() -> bool:
    s = Settings(_env_file=None)
    host = s.ingestion_vllm_url.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(s.ingestion_vllm_url.rsplit(":", 1)[-1])
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _spark_reachable(),
    reason="Spark vLLM unreachable — skipping integration smoke",
)


@pytest.mark.asyncio
async def test_spark_models_endpoint_lists_expected_model():
    s = Settings(_env_file=None)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{s.ingestion_vllm_url}/v1/models")
    resp.raise_for_status()
    ids = [m["id"] for m in resp.json()["data"]]
    assert s.ingestion_vllm_model in ids, f"expected {s.ingestion_vllm_model} in {ids}"


@pytest.mark.asyncio
async def test_real_extraction_call():
    """Drive a real _call_vllm against Spark; assert it returns valid JSON shape."""
    from pipeline import _call_vllm

    s = Settings(_env_file=None)
    result = await _call_vllm(
        title="Test event",
        text="A drone was launched at the port of Odessa today.",
        url="http://example.com/test",
        settings=s,
    )
    assert isinstance(result, dict)
    assert "events" in result
    assert "entities" in result
    assert "locations" in result
```

- [ ] **Step 3: Run integration test**

Run: `cd services/data-ingestion && uv run pytest tests/integration -v`
Expected (with Spark reachable): both PASS. (Otherwise: SKIP.)

- [ ] **Step 4: Commit**

```bash
git add services/data-ingestion/tests/integration/
git commit -m "test(ingestion): integration smoke against Spark (skipped if unreachable)"
```

---

## Task 14: Lint, full test sweep, end-to-end manual verification

- [ ] **Step 1: Run lint**

Run: `cd services/data-ingestion && uv run ruff check .`
Expected: PASS (or fix issues, then re-run).

- [ ] **Step 2: Full test suite**

Run: `cd services/data-ingestion && uv run pytest -v`
Expected: ALL PASS (integration may SKIP).

- [ ] **Step 3: Start interactive-spark mode**

```bash
./odin.sh up interactive-spark
# data-ingestion-spark pins container_name: odin-data-ingestion-spark
docker logs -f odin-data-ingestion-spark 2>&1 | head -60
```

Expected log lines:
- `ingestion_llm_ready url=... model=google/gemma-4-26B-A4B-it`
- Then collector startup logs.

- [ ] **Step 4: Verify Spark sees requests**

```bash
ssh spark "docker logs vllm-gemma4 --tail 40 2>&1 | grep POST"
```

Expected: at least one `POST /v1/chat/completions` line within ~5 minutes (after first collector run).

- [ ] **Step 5: Verify Spark-down → no Qdrant pollution**

Stop Spark vLLM (on Spark host: `docker stop vllm-gemma4`). Wait one collector tick (~5 min for RSS). Then:

```bash
docker logs odin-data-ingestion-spark --tail 30 | grep extraction_skipped_transient
```

Expected: warning lines for skipped items.

Restart Spark: `docker start vllm-gemma4`. Wait next tick. Items should now be extracted (visible in `docker logs vllm-gemma4`).

- [ ] **Step 6: Update memory**

Edit `/home/deadpool-ultra/.claude/projects/-home-deadpool-ultra-ODIN-OSINT/memory/project_spark_ingestion_offload.md`:
- Update body to "DONE — wired in feature/spark-ingestion-wiring, merged YYYY-MM-DD"
- Or remove and update `MEMORY.md` index accordingly.

Add a new feedback memory file `feedback_extraction_retry_pattern.md`:

```markdown
---
name: Extraction retry pattern
description: Collectors must catch ExtractionTransientError + ExtractionConfigError and skip Qdrant upsert (no persistent pending state)
type: feedback
---
Collectors that call pipeline.process_item must wrap it in try/except for both
ExtractionTransientError and ExtractionConfigError, then `continue` (or return)
WITHOUT upserting to Qdrant.

**Why:** Hash-based dedup in Qdrant means once an item is upserted, it never gets
re-extracted. Skipping upsert on extraction errors is the only retry mechanism —
the next source re-fetch (RSS poll, GDELT query) will find the item again
because no Qdrant entry exists yet.

**How to apply:** Whenever adding a new collector that calls process_item or
when reviewing existing collector code, verify both except branches are
present. There is a per-collector behavior test for this in tests/test_<name>.py.
```

Add line to `MEMORY.md`:

```
- [Extraction retry pattern](feedback_extraction_retry_pattern.md) — collectors must skip Qdrant upsert on ExtractionTransientError + ExtractionConfigError
```

- [ ] **Step 7: Push branch + open PR**

The memory files at `/home/deadpool-ultra/.claude/projects/-home-deadpool-ultra-ODIN-OSINT/memory/` are NOT part of this git repo — Step 6 wrote them directly to the auto-memory store (no commit needed for them).

```bash
git push -u origin feature/spark-ingestion-wiring
gh pr create --title "feat(ingestion): wire ingestion LLM to DGX Spark" --body "$(cat <<'EOF'
## Summary
- Routes data-ingestion extraction calls to Spark vLLM (Gemma-4 26B), eliminating GPU-swap on RTX 5090.
- New compose service `data-ingestion-spark` and odin.sh mode `interactive-spark`.
- `process_item` now raises typed errors (`ExtractionTransientError` / `ExtractionConfigError`); collectors skip Qdrant upsert on errors so source re-fetch acts as retry.
- Startup healthcheck logs three exclusive outcomes (ready / model_mismatch / config_error / unreachable).

## Test plan
- [ ] `uv run pytest` (data-ingestion) green
- [ ] `./odin.sh up interactive-spark` shows `ingestion_llm_ready`
- [ ] Stop Spark vLLM → collectors log `extraction_skipped_transient`, no Qdrant upsert
- [ ] Restart Spark → next tick processes items, visible in vllm-gemma4 logs
- [ ] Mode-switch sanity: `up interactive-spark` → `up ingestion` → only one `data-ingestion*` container at a time

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes

- All spec sections (§1–§9) map to tasks 1–13. Healthcheck wording matches the three log keys (`ingestion_llm_ready`, `ingestion_llm_model_mismatch`, `ingestion_llm_config_error`, `ingestion_llm_unreachable`) defined in §6.
- Function/class names are consistent: `ExtractionTransientError`, `ExtractionConfigError`, `check_ingestion_llm()`, `_call_vllm`, `process_item` are used identically across tasks.
- URL normalization rule from spec §2 is enforced via Regex assertions (no `/v1/v1`) in tasks 3 and 8.
- Per-collector behavioral tests (spec §4) are scaffolded in tasks 4-7 — Telegram and the lazy-import collectors get their own task because they need bespoke mock setup.
- Compose + odin.sh changes (spec §8 + §9) covered in tasks 11 + 12, including the cross-mode stop cleanup that prevents two parallel schedulers.
- Memory + Rollout from spec §rollout covered in task 14.

### Rev-2 changes (after Codex review)

- **Fallback fix (Kritisch):** Task 11 Step 2 adds `INGESTION_VLLM_*` env vars to the existing `data-ingestion` service so `up ingestion` keeps using local 27B vLLM after the rewire.
- **doctor + smoke (Hoch):** Task 12 Steps 6-7 add Spark reachability checks to `doctor()` and `smoke()`.
- **Test scaffolds fully written (Hoch):** Telegram (Task 6) and GDELT-Config (Task 5) tests no longer use `...` placeholders.
- **rss method name (Mittel):** `_process_feed` (was `_fetch_and_store`); test passes `feed_meta` dict and mocks the RSS feed-fetch HTTP call.
- **Transcript schema (Mittel):** Task 8 test includes `duration_seconds` + `language`; mock response uses `entities/relations/claims` (not `events/citations`).
- **Compose dep check (Mittel):** Task 11 Step 5 parses YAML via Python instead of fragile `grep -A2`.
- **Sequencing risk (Mittel):** Documented as feature-branch-only constraint in plan header.
- **Memory + container name (Niedrig):** Task 14 Step 7 dropped invalid `git add` of `~/.claude/...`; Step 3 uses pinned `container_name: odin-data-ingestion-spark`.
