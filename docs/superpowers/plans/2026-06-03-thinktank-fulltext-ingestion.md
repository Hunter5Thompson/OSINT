# Think-Tank Full-Text Ingestion (Slice A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the RSS *teaser* (`summary[:1000]`) of the ~10 think-tank feeds with the article *full text* — fetched via the running crawl4ai (HTML) + docling (PDF) REST services — chunked, embedded, written as `source="rss_fulltext"` Qdrant points, with the teaser soft-superseded; and wire the read-path (PR #37) to read + tier-boost the new source.

**Architecture:** A decoupled scroll-enrichment collector (data-ingestion) selects think-tank teaser points, fetches full text, structure-aware-chunks (~650 tok), embeds (TEI), upserts `rss_fulltext` points (canonical `source_type="rss"` + `provider`=feed domain, **inherited** entities/meta, deterministic uint64 IDs), then soft-supersedes the teaser via `set_payload(points=[record.id])` with a 4-state status model + backoff. The read-path (#37 `corpus_policy`/`credibility`) gains `rss_fulltext` + `must_not superseded` + domain credibility overrides. No LLM graph extract (Slice B).

**Tech Stack:** Python 3.12, httpx, qdrant-client (sync `QdrantClient` via `asyncio.to_thread`), pydantic-settings, structlog, APScheduler, pytest + pytest-asyncio. Services: crawl4ai (:11235), docling-serve (:5001), TEI embed (:8001), Qdrant (:6333). Spec: `docs/superpowers/specs/2026-06-03-thinktank-fulltext-ingestion-design.md`. **Depends on PR #37** (branch is stacked on it; `rag/corpus_policy.py`, `rag/credibility.py`, `scripts/ensure_payload_indexes.py` exist from #37).

**Working dirs:** data-ingestion tasks → `services/data-ingestion/` (`uv run pytest`, `@pytest.mark.asyncio` on async tests). intelligence tasks → `services/intelligence/` (`asyncio_mode=auto`, no mark needed).

---

## File Structure

| File | Service | Responsibility | Action |
|---|---|---|---|
| `feeds/_fulltext_fetch.py` | data-ingestion | crawl4ai/docling HTTP clients, HTML/PDF routing, quality-gate | Create |
| `feeds/fulltext_chunker.py` | data-ingestion | structure-aware markdown chunking | Create |
| `feeds/fulltext_collector.py` | data-ingestion | `THINKTANK_FEEDS`, `build_fulltext_payload`, `FulltextCollector` (select→fetch→chunk→embed→write→supersede) | Create |
| `config.py` | data-ingestion | `fulltext_*` settings + `fulltext_enabled` opt-in | Modify |
| `scheduler.py` | data-ingestion | `run_fulltext_collector` + gated `add_job` | Modify |
| `tests/fixtures/fulltext/` | data-ingestion | pinned crawl4ai/docling response fixtures | Create (Task 1) |
| `rag/credibility.py` | intelligence | think-tank **domain** overrides | Modify |
| `rag/corpus_policy.py` | intelligence | `ANALYSIS_SOURCES += rss_fulltext`, `must_not superseded`, guard | Modify |
| `rag/qdrant_schema.py` + `scripts/ensure_payload_indexes.py` | intelligence | typed `PAYLOAD_INDEXES` dict (+ bool) | Modify |

Tasks ordered so each leaves its service's suite green. Data-ingestion (T1–T7) and intelligence (T8–T10) are independent until the live measurement (T11).

---

## Task 1: Pin crawl4ai + docling endpoint shapes (fixtures-first)

**Why first:** the spec's `fit`-markdown param and docling endpoint are assumptions. Pin them against the **running** services and save real response fixtures, so Task 3 builds against facts. (No red-green here — this is verification that produces fixtures.)

**Files:**
- Create: `tests/fixtures/fulltext/crawl4ai_md.json`, `tests/fixtures/fulltext/docling_convert.json`, `tests/fixtures/fulltext/SHAPES.md`

- [ ] **Step 1: Probe crawl4ai `/md` with the fit filter on a real think-tank article**

```bash
# from services/data-ingestion (host, where localhost reaches the services)
URL="https://warontherocks.com/cogs-of-war/how-this-precision-weapon-reengineered-modern-war/"
curl -s -m 60 -X POST http://localhost:11235/md -H 'Content-Type: application/json' \
  -d "{\"url\":\"$URL\",\"f\":\"fit\"}" > tests/fixtures/fulltext/crawl4ai_md.json
python3 -c "import json;d=json.load(open('tests/fixtures/fulltext/crawl4ai_md.json'));print('keys',list(d.keys()));m=d.get('markdown') or d.get('fit_markdown');print('type',type(m).__name__);print('len', len(m) if isinstance(m,str) else 'nested:'+str(list(m.keys()) if isinstance(m,dict) else m)[:120])"
```
Record in `SHAPES.md`: the exact request body that yields filtered markdown, the response key holding the **fit** markdown (`markdown` vs `fit_markdown` vs nested `markdown.fit_markdown`), and whether `success` is present.

- [ ] **Step 2: Discover + probe the docling-serve convert endpoint**

```bash
curl -s -m 6 http://localhost:5001/openapi.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('\n'.join(p for p in d['paths'] if 'convert' in p.lower()))"
# Then probe the convert-from-source endpoint with a PDF URL (use the path printed above):
curl -s -m 90 -X POST http://localhost:5001/v1alpha/convert/source -H 'Content-Type: application/json' \
  -d '{"http_sources":[{"url":"https://www.rand.org/content/dam/rand/pubs/research_reports/RRA2900/RRA2945-1/RAND_RRA2945-1.pdf"}],"options":{"to_formats":["md"]}}' \
  > tests/fixtures/fulltext/docling_convert.json
python3 -c "import json;d=json.load(open('tests/fixtures/fulltext/docling_convert.json'));print('top',list(d.keys())[:8])"
```
Record in `SHAPES.md`: exact convert path, request body shape, and the response JSON-path to the markdown text (e.g. `document.md_content`). If the exact path/shape differs on the running v-version, use what the live API returns — the fixtures are the source of truth.

- [ ] **Step 3: Commit the fixtures + SHAPES.md**

```bash
git add tests/fixtures/fulltext/
git commit -m "test(fulltext): pin crawl4ai/docling response fixtures (Task 1 endpoint discovery)"
```

> **Hand-off to Task 3:** Use the response keys recorded in `SHAPES.md` verbatim. If `f="fit"` is unsupported on this crawl4ai build, record the working alternative (e.g. raw `markdown` + Task-3 boilerplate strip) — the chunker + quality-gate (Tasks 2/3) handle residual boilerplate regardless.

---

## Task 2: Config — `fulltext_*` settings + opt-in switch

**Files:**
- Modify: `config.py` (data-ingestion `Settings`)
- Test: `tests/test_fulltext_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_config.py`:

```python
def test_fulltext_settings_defaults():
    from config import Settings
    s = Settings()
    assert s.fulltext_enabled is False                 # opt-in, OFF by default
    assert s.crawl4ai_url == "http://localhost:11235"
    assert s.docling_url == "http://localhost:5001"
    assert s.fulltext_min_body_chars == 1500
    assert s.fulltext_min_paragraphs == 3
    assert s.fulltext_chunk_tokens == 650
    assert s.fulltext_chunk_overlap == 100
    assert s.fulltext_max_attempts == 4
    assert s.fulltext_batch_size == 25
    assert s.fulltext_interval_minutes == 60
    assert s.fulltext_rate_limit_per_domain_s == 2.0


def test_fulltext_enabled_env_override(monkeypatch):
    monkeypatch.setenv("FULLTEXT_ENABLED", "true")
    from config import Settings
    assert Settings().fulltext_enabled is True
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_fulltext_config.py -q` → FAIL (`fulltext_enabled` undefined).

- [ ] **Step 3: Implement**

In `config.py`, inside `class Settings`, add a block (after the existing HTTP settings):

```python
    # Think-Tank Full-Text (Slice A) — opt-in (external crawls + Qdrant mutation)
    fulltext_enabled: bool = False
    crawl4ai_url: str = "http://localhost:11235"
    docling_url: str = "http://localhost:5001"
    fulltext_batch_size: int = 25
    fulltext_min_body_chars: int = 1500
    fulltext_min_paragraphs: int = 3
    fulltext_chunk_tokens: int = 650
    fulltext_chunk_overlap: int = 100
    fulltext_max_attempts: int = 4
    fulltext_rate_limit_per_domain_s: float = 2.0
    fulltext_interval_minutes: int = 60
```

- [ ] **Step 4: Run — expect PASS** (+ full suite unaffected)

Run: `uv run pytest tests/test_fulltext_config.py -q` → PASS. Then `uv run pytest -q` (baseline + 2). Then `uv run ruff check config.py tests/test_fulltext_config.py`.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_fulltext_config.py
git commit -m "feat(fulltext): config settings + fulltext_enabled opt-in switch"
```

---

## Task 3: `_fulltext_fetch.py` — fetch clients + routing + quality-gate

**Files:**
- Create: `feeds/_fulltext_fetch.py`
- Test: `tests/test_fulltext_fetch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_fetch.py` (adjust the crawl4ai/docling response keys to match Task-1 `SHAPES.md`):

```python
from unittest.mock import AsyncMock, patch

import pytest

from feeds._fulltext_fetch import clean_body, is_quality, route_kind, fetch_fulltext


class TestRoutingAndGate:
    def test_route_pdf_vs_html(self):
        assert route_kind("https://x.org/report.pdf") == "pdf"
        assert route_kind("https://x.org/commentary/abc") == "html"

    def test_clean_body_strips_nav_link_lines(self):
        md = "[Home](/) [About](/about)\n\nReal prose paragraph one.\n\nReal prose two.\n"
        cleaned, paras = clean_body(md)
        assert "Home" not in cleaned and "About" not in cleaned
        assert paras == 2

    def test_quality_gate_rejects_short_or_few_paragraphs(self):
        assert is_quality("x" * 5000, paragraphs=5, min_chars=1500, min_paras=3) is True
        assert is_quality("x" * 500, paragraphs=5, min_chars=1500, min_paras=3) is False
        assert is_quality("x" * 5000, paragraphs=1, min_chars=1500, min_paras=3) is False


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_html_uses_crawl4ai_fit(self):
        captured = {}

        async def fake_post(url, json=None):
            captured["url"] = url
            captured["json"] = json
            from httpx import Request, Response
            body = {"markdown": "## Title\n\n" + "Real analysis paragraph. " * 200 + "\n\nP2 " * 50, "success": True}
            return Response(200, json=body, request=Request("POST", url))

        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            md = await fetch_fulltext("https://csis.org/analysis/x",
                                      crawl4ai_url="http://c:11235", docling_url="http://d:5001",
                                      min_chars=100, min_paras=1)
        assert captured["url"].endswith("/md")
        assert captured["json"]["f"] == "fit"           # fit filter requested
        assert md and "Real analysis paragraph" in md

    @pytest.mark.asyncio
    async def test_fetch_returns_none_on_paywall_short(self):
        async def fake_post(url, json=None):
            from httpx import Request, Response
            return Response(200, json={"markdown": "[Subscribe](/join)\n\nJoin now.", "success": True},
                            request=Request("POST", url))
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            md = await fetch_fulltext("https://csis.org/x", crawl4ai_url="http://c", docling_url="http://d",
                                      min_chars=1500, min_paras=3)
        assert md is None
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`).

Run: `uv run pytest tests/test_fulltext_fetch.py -q`

- [ ] **Step 3: Implement**

Create `feeds/_fulltext_fetch.py` (set `_FIT_KEY`/request body from Task-1 `SHAPES.md`):

```python
"""Full-text fetch clients (crawl4ai HTML, docling PDF) + quality gate.

Pure helpers (route_kind/clean_body/is_quality) are I/O-free and unit-tested.
Network response shapes are pinned by tests/fixtures/fulltext (Task 1)."""
from __future__ import annotations

import re

import httpx
import structlog

log = structlog.get_logger(__name__)

# Response key holding the content-filtered markdown — VERIFY against Task-1 SHAPES.md.
_CRAWL4AI_FIT_KEYS = ("fit_markdown", "markdown")
# JSON path to docling markdown — VERIFY against Task-1 SHAPES.md.
_DOCLING_MD_PATH = ("document", "md_content")

_LINK_LINE = re.compile(r"^\s*(?:\[[^\]]*\]\([^)]*\)\s*)+$")  # line = only md links


def route_kind(url: str) -> str:
    return "pdf" if url.lower().split("?", 1)[0].endswith(".pdf") else "html"


def clean_body(markdown: str) -> tuple[str, int]:
    """Drop nav/link-only lines; return (cleaned_text, prose_paragraph_count)."""
    lines = [ln for ln in markdown.splitlines() if not _LINK_LINE.match(ln)]
    cleaned = "\n".join(lines).strip()
    paras = [p for p in re.split(r"\n\s*\n", cleaned) if len(p.strip()) >= 80]
    return cleaned, len(paras)


def is_quality(cleaned: str, *, paragraphs: int, min_chars: int, min_paras: int) -> bool:
    return len(cleaned) >= min_chars and paragraphs >= min_paras


def _dig(d: dict, path: tuple[str, ...]):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


async def _crawl4ai_md(url: str, base: str, client: httpx.AsyncClient) -> str | None:
    resp = await client.post(f"{base.rstrip('/')}/md", json={"url": url, "f": "fit"})
    resp.raise_for_status()
    data = resp.json()
    for k in _CRAWL4AI_FIT_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):  # nested {fit_markdown,...}
            for kk in _CRAWL4AI_FIT_KEYS:
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk]
    return None


async def _docling_md(url: str, base: str, client: httpx.AsyncClient) -> str | None:
    resp = await client.post(
        f"{base.rstrip('/')}/v1alpha/convert/source",
        json={"http_sources": [{"url": url}], "options": {"to_formats": ["md"]}},
    )
    resp.raise_for_status()
    md = _dig(resp.json(), _DOCLING_MD_PATH)
    return md if isinstance(md, str) and md.strip() else None


async def fetch_fulltext(
    url: str, *, crawl4ai_url: str, docling_url: str,
    min_chars: int, min_paras: int, timeout: float = 60.0,
) -> str | None:
    """Fetch + clean + quality-gate. Returns cleaned markdown or None (skip)."""
    kind = route_kind(url)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            raw = (await _docling_md(url, docling_url, client)) if kind == "pdf" \
                else (await _crawl4ai_md(url, crawl4ai_url, client))
    except httpx.HTTPError as exc:
        log.warning("fulltext_fetch_failed", url=url, kind=kind, error=str(exc))
        raise  # transient — caller records status="retry"
    if not raw:
        return None
    cleaned, paras = clean_body(raw)
    if not is_quality(cleaned, paragraphs=paras, min_chars=min_chars, min_paras=min_paras):
        log.info("fulltext_quality_gate_skip", url=url, chars=len(cleaned), paras=paras)
        return None
    return cleaned
```

- [ ] **Step 4: Run — expect PASS** + `uv run pytest -q` + `uv run ruff check feeds/_fulltext_fetch.py tests/test_fulltext_fetch.py`.

- [ ] **Step 5: Commit**

```bash
git add feeds/_fulltext_fetch.py tests/test_fulltext_fetch.py
git commit -m "feat(fulltext): crawl4ai/docling fetch clients + routing + quality gate"
```

---

## Task 4: `fulltext_chunker.py` — structure-aware chunking

**Files:**
- Create: `feeds/fulltext_chunker.py`
- Test: `tests/test_fulltext_chunker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_chunker.py`:

```python
from feeds.fulltext_chunker import chunk_markdown


def test_splits_into_multiple_chunks_with_target_size():
    para = ("This is a substantial analytic paragraph about strategy. " * 12).strip()
    md = "\n\n".join(f"## Section {i}\n\n{para}" for i in range(8))
    chunks = chunk_markdown(md, target_tokens=120, overlap_tokens=20)
    assert len(chunks) >= 3
    # ~target: no chunk wildly over (char-approx 4 chars/token)
    assert all(len(c) <= 120 * 4 * 2 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_no_mid_word_split_and_overlap():
    md = "## H\n\n" + "alpha beta gamma delta epsilon zeta eta theta iota kappa. " * 60
    chunks = chunk_markdown(md, target_tokens=80, overlap_tokens=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert not c.startswith(" ")
        # boundary words are whole (no split like 'gam')
        assert c.split()[0].isalpha()


def test_short_input_single_chunk():
    chunks = chunk_markdown("## H\n\nshort body paragraph here.", target_tokens=650, overlap_tokens=100)
    assert len(chunks) == 1
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Implement**

Create `feeds/fulltext_chunker.py`:

```python
"""Structure-aware markdown chunking. Splits at heading→paragraph→sentence
boundaries, accumulates to ~target_tokens (char-approx), with token overlap.
No blind fixed-window (keeps nav/footnote noise from cross-cutting chunks)."""
from __future__ import annotations

import re

_CHARS_PER_TOKEN = 4
_SENT = re.compile(r"(?<=[.!?])\s+")


def _segments(md: str) -> list[str]:
    """Heading-leading paragraphs, then sentences for over-long paragraphs."""
    segs: list[str] = []
    for para in re.split(r"\n\s*\n", md.strip()):
        p = para.strip()
        if not p:
            continue
        segs.extend(s.strip() for s in _SENT.split(p) if s.strip())
    return segs


def chunk_markdown(md: str, *, target_tokens: int = 650, overlap_tokens: int = 100) -> list[str]:
    target = target_tokens * _CHARS_PER_TOKEN
    overlap = overlap_tokens * _CHARS_PER_TOKEN
    segs = _segments(md)
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for seg in segs:
        if cur and cur_len + len(seg) + 1 > target:
            chunks.append(" ".join(cur).strip())
            # overlap: carry trailing segments up to ~overlap chars into next chunk
            carry: list[str] = []
            carry_len = 0
            for s in reversed(cur):
                if carry_len + len(s) > overlap:
                    break
                carry.insert(0, s)
                carry_len += len(s) + 1
            cur = carry
            cur_len = carry_len
        cur.append(seg)
        cur_len += len(seg) + 1
    if cur:
        chunks.append(" ".join(cur).strip())
    return [c for c in chunks if c]
```

- [ ] **Step 4: Run — expect PASS** + `uv run pytest -q` + ruff.

- [ ] **Step 5: Commit**

```bash
git add feeds/fulltext_chunker.py tests/test_fulltext_chunker.py
git commit -m "feat(fulltext): structure-aware markdown chunker"
```

---

## Task 5: `build_fulltext_payload` + deterministic uint64 ID (pure)

**Files:**
- Create: `feeds/fulltext_collector.py` (the pure helpers first; the class comes in Task 6)
- Test: `tests/test_fulltext_payload.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_payload.py`:

```python
from feeds.fulltext_collector import (
    THINKTANK_FEEDS, build_fulltext_payload, fulltext_point_id, article_id, normalize_url,
)


def test_thinktank_feeds_map():
    assert THINKTANK_FEEDS["CSIS"] == "csis.org"
    assert THINKTANK_FEEDS["War on the Rocks"] == "warontherocks.com"
    assert "rybar" not in THINKTANK_FEEDS  # only think-tanks


def test_point_id_is_deterministic_uint64():
    a = fulltext_point_id("https://csis.org/x", 0)
    b = fulltext_point_id("https://csis.org/x", 0)
    c = fulltext_point_id("https://csis.org/x", 1)
    assert a == b and a != c
    assert isinstance(a, int) and 0 <= a < 2**64


def test_payload_canonical_provenance_and_inherited_meta():
    teaser = {
        "feed_name": "CSIS", "url": "https://csis.org/a", "title": "T",
        "published_at": "2026-01-01T00:00:00+00:00", "published": "2026-01-01T00:00:00+00:00",
        "entities": [{"name": "China", "type": "ORG"}],
    }
    p = build_fulltext_payload(teaser, provider="csis.org", chunk_text="body text",
                               chunk_index=2, chunk_count=5)
    assert p["source"] == "rss_fulltext"
    assert p["source_type"] == "rss"            # canonical → credibility/guard
    assert p["provider"] == "csis.org"          # domain → credibility override
    assert p["feed_name"] == "CSIS"
    assert p["entities"] == teaser["entities"]  # inherited, no LLM
    assert p["content"] == "body text"
    assert p["chunk_index"] == 2 and p["chunk_count"] == 5
    assert p["fulltext_article_id"] == article_id("https://csis.org/a")
    assert "chunk_uid" in p
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Implement** (top of new `feeds/fulltext_collector.py`)

```python
"""Decoupled think-tank full-text enrichment collector.

Scrolls think-tank RSS teasers, fetches full text (crawl4ai/docling), chunks,
embeds, upserts rss_fulltext points (canonical provenance + inherited entities),
then soft-supersedes the teaser by record.id with a 4-state status model."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

# feed_name -> canonical provider domain (verified against rss_collector.py feed config)
THINKTANK_FEEDS: dict[str, str] = {
    "CSIS": "csis.org",
    "RUSI Commentary": "rusi.org",
    "RUSI Publications": "rusi.org",
    "RAND Corporation": "rand.org",
    "SIPRI": "sipri.org",
    "SWP Publications (DE)": "swp-berlin.org",
    "SWP Publications (EN)": "swp-berlin.org",
    "Atlantic Council": "atlanticcouncil.org",
    "Brookings": "brookings.edu",
    "Crisis Group": "crisisgroup.org",
    "War on the Rocks": "warontherocks.com",
    "Bellingcat": "bellingcat.com",
}


def normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def article_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def _chunk_uid(url: str, chunk_index: int) -> str:
    return hashlib.sha256(f"rss_fulltext|{normalize_url(url)}|{chunk_index}".encode()).hexdigest()


def fulltext_point_id(url: str, chunk_index: int) -> int:
    """Deterministic uint64 (Qdrant accepts uint64/UUID, not raw hex) → re-run upserts."""
    return int(_chunk_uid(url, chunk_index)[:16], 16)


def build_fulltext_payload(
    teaser: dict, *, provider: str, chunk_text: str, chunk_index: int, chunk_count: int,
) -> dict:
    """Pure rss_fulltext payload (no I/O). Canonical provenance + inherited teaser meta."""
    url = teaser["url"]
    return {
        "source": "rss_fulltext",
        "source_type": "rss",                 # canonical → credibility/tiering/guard
        "provider": provider,                 # feed domain → domain credibility override
        "feed_name": teaser.get("feed_name"),
        "url": normalize_url(url),
        "title": teaser.get("title"),
        "published_at": teaser.get("published_at"),
        "published": teaser.get("published"),  # legacy compat
        "entities": teaser.get("entities", []),  # INHERITED → graph-context reuse, no LLM
        "content": chunk_text,
        "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest()[:16],
        "chunk_uid": _chunk_uid(url, chunk_index),
        "fulltext_article_id": article_id(url),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "ingested_at": datetime.now(UTC).isoformat(),
    }
```

- [ ] **Step 4: Run — expect PASS** + `uv run pytest -q` + ruff.

- [ ] **Step 5: Commit**

```bash
git add feeds/fulltext_collector.py tests/test_fulltext_payload.py
git commit -m "feat(fulltext): THINKTANK_FEEDS + canonical rss_fulltext payload + uint64 ids"
```

---

## Task 6: `FulltextCollector` — select → fetch → chunk → embed → write → supersede

**Files:**
- Modify: `feeds/fulltext_collector.py` (append the class)
- Test: `tests/test_fulltext_collector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_collector.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.fulltext_collector import FulltextCollector

TERMINAL = {"done", "failed_permanent", "skipped_paywall"}


def _teaser(rid, url="https://csis.org/a", feed="CSIS"):
    return SimpleNamespace(id=rid, payload={
        "source": "rss", "feed_name": feed, "url": url, "title": "T",
        "published_at": "2026-01-01", "published": "2026-01-01",
        "entities": [{"name": "X"}],
    })


def _collector(scroll_points):
    qc = MagicMock()
    qc.scroll.return_value = (scroll_points, None)
    qc.upsert = MagicMock()
    qc.set_payload = MagicMock()
    c = FulltextCollector(qdrant=qc)
    c._embed = AsyncMock(return_value=[0.0] * 1024)        # type: ignore[method-assign]
    c._ensure_collection_ready = MagicMock()               # bypass schema preflight
    return c, qc


class TestCollect:
    @pytest.mark.asyncio
    async def test_success_writes_chunks_then_supersedes_by_record_id(self):
        c, qc = _collector([_teaser(rid=111)])
        with patch("feeds.fulltext_collector.fetch_fulltext",
                   AsyncMock(return_value="## H\n\n" + "Real analysis. " * 300)):
            await c.collect()
        # (1) chunks upserted, (2) THEN supersede on the scrolled record.id
        assert qc.upsert.called
        sp = qc.set_payload.call_args
        assert sp.kwargs["points"] == [111]                # record.id, NOT url
        assert sp.kwargs["payload"]["superseded_by_fulltext"] is True
        assert sp.kwargs["payload"]["fulltext_status"] == "done"

    @pytest.mark.asyncio
    async def test_quality_skip_marks_skipped_paywall_no_chunks(self):
        c, qc = _collector([_teaser(rid=222)])
        with patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value=None)):
            await c.collect()
        qc.upsert.assert_not_called()
        sp = qc.set_payload.call_args
        assert sp.kwargs["points"] == [222]
        assert sp.kwargs["payload"]["fulltext_status"] == "skipped_paywall"
        assert "superseded_by_fulltext" not in sp.kwargs["payload"]

    @pytest.mark.asyncio
    async def test_transient_error_marks_retry_with_backoff(self):
        c, qc = _collector([_teaser(rid=333)])
        import httpx
        with patch("feeds.fulltext_collector.fetch_fulltext",
                   AsyncMock(side_effect=httpx.ConnectError("down"))):
            await c.collect()
        qc.upsert.assert_not_called()
        pl = qc.set_payload.call_args.kwargs["payload"]
        assert pl["fulltext_status"] == "retry"
        assert pl["fulltext_attempts"] == 1
        assert pl["fulltext_retry_epoch"] > 0

    @pytest.mark.asyncio
    async def test_throttles_same_domain(self):
        c, qc = _collector([_teaser(rid=1, url="https://csis.org/a"),
                            _teaser(rid=2, url="https://csis.org/b")])
        sleeps: list[float] = []
        with patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value=None)), \
             patch("feeds.fulltext_collector.asyncio.sleep",
                   AsyncMock(side_effect=lambda s: sleeps.append(s))):
            await c.collect()
        assert any(s > 0 for s in sleeps)            # 2nd csis.org URL was throttled


class TestPreflight:
    @pytest.mark.asyncio
    async def test_invalid_schema_prevents_upsert(self):
        from qdrant_doctor.schema import QdrantSchemaMismatch
        qc = MagicMock()
        qc.scroll.return_value = ([_teaser(rid=9)], None)
        qc.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name="odin_intel")])
        c = FulltextCollector(qdrant=qc)
        c._embed = AsyncMock(return_value=[0.0] * 1024)   # type: ignore[method-assign]
        with patch("feeds.fulltext_collector.validate_collection_schema",
                   side_effect=QdrantSchemaMismatch("bad")), \
             patch("feeds.fulltext_collector.fetch_fulltext", AsyncMock(return_value="x" * 9000)):
            with pytest.raises(QdrantSchemaMismatch):
                await c.collect()
        qc.upsert.assert_not_called()                 # preflight aborts before any write
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Implement** (append to `feeds/fulltext_collector.py`)

```python
import asyncio
import time
from urllib.parse import urlparse

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from config import settings
from feeds._fulltext_fetch import fetch_fulltext
from feeds.fulltext_chunker import chunk_markdown
from qdrant_doctor.schema import validate_collection_schema

log = structlog.get_logger(__name__)

_TERMINAL = ("done", "failed_permanent", "skipped_paywall")


class FulltextCollector:
    def __init__(self, qdrant: QdrantClient | None = None) -> None:
        self.qdrant = qdrant or QdrantClient(url=settings.qdrant_url)
        self._last_fetch: dict[str, float] = {}

    def _ensure_collection_ready(self) -> None:
        """Schema preflight before any write (matches the other collectors)."""
        names = [c.name for c in self.qdrant.get_collections().collections]
        if settings.qdrant_collection not in names:
            raise RuntimeError(f"collection {settings.qdrant_collection!r} missing")
        info = self.qdrant.get_collection(settings.qdrant_collection)
        validate_collection_schema(info, enable_hybrid=settings.enable_hybrid)

    async def _throttle(self, domain: str) -> None:
        wait = settings.fulltext_rate_limit_per_domain_s - (time.time() - self._last_fetch.get(domain, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_fetch[domain] = time.time()

    async def _embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.post(f"{settings.tei_embed_url}/embed", json={"inputs": text})
            resp.raise_for_status()
            r = resp.json()
            return r[0] if isinstance(r[0], list) else r

    def _select(self) -> list:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
        flt = Filter(
            must=[
                FieldCondition(key="source", match=MatchValue(value="rss")),
                FieldCondition(key="feed_name", match=MatchAny(any=list(THINKTANK_FEEDS))),
            ],
            must_not=[
                FieldCondition(key="superseded_by_fulltext", match=MatchValue(value=True)),
                FieldCondition(key="fulltext_status", match=MatchAny(any=list(_TERMINAL))),
            ],
        )
        points, _ = self.qdrant.scroll(
            collection_name=settings.qdrant_collection, scroll_filter=flt,
            limit=settings.fulltext_batch_size, with_payload=True,
        )
        now = time.time()
        return [p for p in points if (p.payload or {}).get("fulltext_retry_epoch", 0) <= now]

    async def collect(self) -> None:
        await asyncio.to_thread(self._ensure_collection_ready)   # schema preflight before writes
        records = await asyncio.to_thread(self._select)
        log.info("fulltext_batch", count=len(records))
        for rec in records:
            await self._process(rec)

    async def _process(self, rec) -> None:
        pl = rec.payload or {}
        url, feed = pl.get("url"), pl.get("feed_name")
        provider = THINKTANK_FEEDS.get(feed, "")
        await self._throttle(urlparse(url).hostname or provider)
        try:
            md = await fetch_fulltext(
                url, crawl4ai_url=settings.crawl4ai_url, docling_url=settings.docling_url,
                min_chars=settings.fulltext_min_body_chars, min_paras=settings.fulltext_min_paragraphs,
            )
        except httpx.HTTPError as exc:
            return await self._mark_retry(rec, str(exc))
        if md is None:
            return await self._mark(rec, {"fulltext_status": "skipped_paywall",
                                          "fulltext_attempted_at": _now()})
        chunks = chunk_markdown(md, target_tokens=settings.fulltext_chunk_tokens,
                                overlap_tokens=settings.fulltext_chunk_overlap)
        points = []
        for i, ch in enumerate(chunks):
            vec = await self._embed(ch)
            points.append(PointStruct(
                id=fulltext_point_id(url, i), vector=vec,
                payload=build_fulltext_payload(pl, provider=provider, chunk_text=ch,
                                               chunk_index=i, chunk_count=len(chunks)),
            ))
        await asyncio.to_thread(self.qdrant.upsert,
                                collection_name=settings.qdrant_collection, points=points)
        await self._mark(rec, {
            "superseded_by_fulltext": True, "fulltext_status": "done",
            "fulltext_article_id": article_id(url), "fulltext_chunk_count": len(chunks),
            "fulltext_ingested_at": _now(),
        })

    async def _mark(self, rec, payload: dict) -> None:
        await asyncio.to_thread(
            self.qdrant.set_payload, collection_name=settings.qdrant_collection,
            payload=payload, points=[rec.id], wait=True,
        )

    async def _mark_retry(self, rec, error: str) -> None:
        attempts = int((rec.payload or {}).get("fulltext_attempts", 0)) + 1
        status = "failed_permanent" if attempts >= settings.fulltext_max_attempts else "retry"
        backoff = min(3600, 60 * (2 ** attempts))
        await self._mark(rec, {
            "fulltext_status": status, "fulltext_attempts": attempts,
            "fulltext_attempted_at": _now(), "fulltext_error": error[:300],
            "fulltext_retry_epoch": time.time() + backoff,
        })

    async def close(self) -> None:
        await asyncio.to_thread(self.qdrant.close)


def _now() -> str:
    return datetime.now(UTC).isoformat()
```

- [ ] **Step 4: Run — expect PASS** + `uv run pytest -q` + `uv run ruff check feeds/fulltext_collector.py tests/test_fulltext_collector.py`.

- [ ] **Step 5: Commit**

```bash
git add feeds/fulltext_collector.py tests/test_fulltext_collector.py
git commit -m "feat(fulltext): FulltextCollector select/fetch/chunk/embed/write/supersede"
```

---

## Task 7: Scheduler — gated `run_fulltext_collector` + `add_job`

**Files:**
- Modify: `scheduler.py`
- Test: `tests/test_fulltext_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_scheduler.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest


class TestFulltextJob:
    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setattr("config.settings.fulltext_enabled", False, raising=False)
        from scheduler import run_fulltext_collector
        with patch("scheduler.FulltextCollector") as Coll:
            await run_fulltext_collector()
        Coll.assert_not_called()              # opt-in OFF → never constructs/crawls

    @pytest.mark.asyncio
    async def test_enabled_runs_collect_off_loop(self, monkeypatch):
        monkeypatch.setattr("config.settings.fulltext_enabled", True, raising=False)
        from scheduler import run_fulltext_collector
        inst = AsyncMock()
        with patch("scheduler._construct_off_loop", AsyncMock(return_value=inst)) as col, \
             patch("scheduler.FulltextCollector") as FC:
            await run_fulltext_collector()
        col.assert_awaited_once_with(FC)         # constructed OFF-LOOP (matches other collectors)
        inst.collect.assert_awaited_once()
        inst.close.assert_awaited_once()
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Implement**

In `scheduler.py`: add import `from feeds.fulltext_collector import FulltextCollector` and the wrapper (near the other `run_*` wrappers):

```python
async def run_fulltext_collector() -> None:
    """Think-tank full-text enrichment — opt-in (FULLTEXT_ENABLED)."""
    if not settings.fulltext_enabled:
        log.info("fulltext_job_disabled")
        return
    collector = await _construct_off_loop(FulltextCollector)   # Qdrant owner → off-loop
    try:
        await collector.collect()
    except Exception:
        log.exception("fulltext_job_failed")
    finally:
        await collector.close()
```

In `create_scheduler()`, register it only when enabled (next to the other `add_job` calls):

```python
    if settings.fulltext_enabled:
        scheduler.add_job(
            run_fulltext_collector,
            trigger=IntervalTrigger(minutes=settings.fulltext_interval_minutes),
            id="fulltext_collector", name="Think-Tank Full-Text Enrichment",
            replace_existing=True,
        )
```
(`settings`, `IntervalTrigger`, and `_construct_off_loop` are already in scheduler.py. Also **extend the existing scheduler lifecycle test** that asserts collectors are constructed off-loop to include `run_fulltext_collector`.)

- [ ] **Step 4: Run — expect PASS** + `uv run pytest -q` + ruff.

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_fulltext_scheduler.py
git commit -m "feat(fulltext): gated scheduler job (opt-in via FULLTEXT_ENABLED)"
```

---

## Task 8: Intelligence — credibility **domain** overrides

**Working dir:** `services/intelligence/` (`asyncio_mode=auto`).

**Files:**
- Modify: `rag/credibility.py` (`PROVIDER_OVERRIDES`)
- Test: `tests/test_credibility.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_credibility.py`:

```python
class TestThinkTankDomainOverrides:
    @pytest.mark.parametrize("domain,expected", [
        ("csis.org", 0.82), ("rusi.org", 0.82), ("rand.org", 0.82), ("sipri.org", 0.82),
        ("swp-berlin.org", 0.82), ("atlanticcouncil.org", 0.82), ("brookings.edu", 0.82),
        ("crisisgroup.org", 0.82), ("warontherocks.com", 0.82), ("bellingcat.com", 0.85),
    ])
    def test_canonical_domain_override(self, domain, expected):
        # rss_fulltext writes provider=domain (canonical); the boost must fire
        assert credibility_score("rss", domain) == expected
```

- [ ] **Step 2: Run — expect FAIL** (domains return 0.60 baseline).

Run: `uv run pytest tests/test_credibility.py::TestThinkTankDomainOverrides -q`

- [ ] **Step 3: Implement** — add to `PROVIDER_OVERRIDES` in `rag/credibility.py`:

```python
    # Think-tank canonical DOMAIN overrides (rss_fulltext writes provider=domain).
    # Distinct from the feed_name LABEL keys above (legacy teasers lack canonical provider).
    "csis.org": 0.82,
    "rusi.org": 0.82,
    "rand.org": 0.82,
    "sipri.org": 0.82,
    "swp-berlin.org": 0.82,
    "atlanticcouncil.org": 0.82,
    "brookings.edu": 0.82,
    "crisisgroup.org": 0.82,
    "warontherocks.com": 0.82,
    "bellingcat.com": 0.85,
```

- [ ] **Step 4: Run — expect PASS** + `uv run pytest -q` + `uv run ruff check rag/credibility.py tests/test_credibility.py`.

- [ ] **Step 5: Commit**

```bash
git add rag/credibility.py tests/test_credibility.py
git commit -m "feat(intelligence): think-tank canonical domain credibility overrides"
```

---

## Task 9: Intelligence — read-path scopes `rss_fulltext` + excludes superseded

**Files:**
- Modify: `rag/corpus_policy.py` (`ANALYSIS_SOURCES`, `analysis_filter`, `validate_lane`)
- Test: `tests/test_corpus_policy.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_corpus_policy.py`:

```python
class TestFulltextReadPath:
    def test_analysis_sources_includes_fulltext(self):
        assert cp.ANALYSIS_SOURCES == frozenset({"rss", "rss_fulltext"})

    def test_analysis_filter_allows_fulltext_and_excludes_superseded(self):
        f = cp.analysis_filter()
        assert {"key": "source", "match": {"any": sorted(cp.ANALYSIS_SOURCES)}} in f["should"]
        assert {"key": "superseded_by_fulltext", "match": {"value": True}} in f["must_not"]

    def test_validate_lane_keeps_fulltext_chunk(self):
        chunk = {"source": "rss_fulltext", "source_type": "rss", "feed_name": "CSIS"}
        assert cp.validate_lane([chunk], "analysis") == [chunk]

    def test_validate_lane_drops_superseded_teaser(self):
        teaser = {"source": "rss", "feed_name": "CSIS", "superseded_by_fulltext": True}
        assert cp.validate_lane([teaser], "analysis") == []
```

- [ ] **Step 2: Run — expect FAIL**.

- [ ] **Step 3: Implement** in `rag/corpus_policy.py`:

(a) `ANALYSIS_SOURCES`:
```python
ANALYSIS_SOURCES: frozenset[str] = frozenset({"rss", "rss_fulltext"})
```
(b) `analysis_filter` — add the top-level `must_not`:
```python
def analysis_filter() -> dict:
    """source ∈ ANALYSIS_SOURCES OR notebook_id present (NLM); never a superseded teaser."""
    return {
        "should": [
            {"key": "source", "match": {"any": sorted(ANALYSIS_SOURCES)}},
            {"must_not": [{"is_empty": {"key": "notebook_id"}}]},
        ],
        "must_not": [{"key": "superseded_by_fulltext", "match": {"value": True}}],
    }
```
(c) `validate_lane` — in the analysis branch, drop superseded (belt-and-suspenders). Add at the start of the per-result loop body:
```python
        if r.get("superseded_by_fulltext") is True:
            dropped.append(r)
            continue
```
(`rss_fulltext` already passes: `source in ANALYSIS_SOURCES` identity, `source_type="rss" in _ANALYSIS_TYPES` type_ok.)

- [ ] **Step 4: Run — expect PASS** (incl. the existing TwoLaneScoping/Guard tests — the `must_not` doesn't affect non-superseded points). `uv run pytest -q` + ruff.

- [ ] **Step 5: Commit**

```bash
git add rag/corpus_policy.py tests/test_corpus_policy.py
git commit -m "feat(intelligence): read-path scopes rss_fulltext + excludes superseded teasers"
```

---

## Task 10: Intelligence — typed payload-index migration

**Files:**
- Modify: `rag/qdrant_schema.py` (`REQUIRED_PAYLOAD_INDEXES` → typed `PAYLOAD_INDEXES` dict; `missing_payload_indexes`)
- Modify: `scripts/ensure_payload_indexes.py` (iterate field+schema)
- Test: `tests/test_ensure_payload_indexes.py`, `tests/test_qdrant_schema.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_ensure_payload_indexes.py`:

```python
class TestTypedIndexes:
    def _client(self, existing):
        from types import SimpleNamespace
        c = SimpleNamespace()
        c.get_collection = AsyncMock(
            return_value=SimpleNamespace(payload_schema={k: object() for k in existing}))
        c.create_payload_index = AsyncMock()
        return c

    async def test_creates_with_correct_schema_types(self):
        from scripts.ensure_payload_indexes import ensure_indexes
        from rag.qdrant_schema import PAYLOAD_INDEXES
        client = self._client(existing=set())
        await ensure_indexes(client=client, collection="odin_intel")
        by_field = {c.kwargs["field_name"]: c.kwargs["field_schema"]
                    for c in client.create_payload_index.await_args_list}
        assert by_field["superseded_by_fulltext"] == "bool"      # NOT keyword
        assert by_field["source"] == "keyword"
        assert by_field["feed_name"] == "keyword"
        assert set(by_field) == set(PAYLOAD_INDEXES)
```

And in `tests/test_qdrant_schema.py` append:
```python
def test_payload_indexes_is_typed_dict():
    from rag.qdrant_schema import PAYLOAD_INDEXES
    assert PAYLOAD_INDEXES["superseded_by_fulltext"] == "bool"
    assert PAYLOAD_INDEXES["source"] == "keyword"
```

- [ ] **Step 2: Run — expect FAIL** (`PAYLOAD_INDEXES` undefined; `field_schema` hardcoded keyword).

- [ ] **Step 3: Implement**

In `rag/qdrant_schema.py` — replace the `REQUIRED_PAYLOAD_INDEXES` tuple with a typed dict, keep a name-tuple alias for `missing_payload_indexes`, add `PAYLOAD_INDEXES` to `__all__`:
```python
PAYLOAD_INDEXES: dict[str, str] = {
    "source": "keyword", "telegram_channel": "keyword", "notebook_id": "keyword",
    "feed_name": "keyword", "url": "keyword",
    "fulltext_article_id": "keyword", "fulltext_status": "keyword",
    "superseded_by_fulltext": "bool",
}
REQUIRED_PAYLOAD_INDEXES = tuple(PAYLOAD_INDEXES)   # field names (back-compat)
```
`missing_payload_indexes` is unchanged (iterates `REQUIRED_PAYLOAD_INDEXES`).

In `scripts/ensure_payload_indexes.py` — import `PAYLOAD_INDEXES` and iterate field+schema:
```python
from rag.qdrant_schema import PAYLOAD_INDEXES
...
        for field, schema in PAYLOAD_INDEXES.items():
            if field in existing:
                continue
            await client.create_payload_index(
                collection_name=collection, field_name=field,
                field_schema=schema, wait=True,
            )
            created.append(field)
        log.info("payload_indexes_ensured", created=created,
                 already_present=sorted(existing & set(PAYLOAD_INDEXES)))
```

- [ ] **Step 3b: Update the pre-existing #37 index tests (they assert the OLD 3-field set → will break)**

Growing the index set from 3→8 breaks tests that hardcoded the 3 #37 fields. Update them to the new set:

In `tests/test_qdrant_schema.py::TestMissingPayloadIndexes`:
- `test_reports_missing`: `info = SimpleNamespace(payload_schema={"source": object()})` → change the expected set to **all `PAYLOAD_INDEXES` keys minus `source`**: `assert set(missing_payload_indexes(info)) == set(PAYLOAD_INDEXES) - {"source"}` (import `PAYLOAD_INDEXES`).
- `test_none_missing`: change the present schema to **all** keys: `payload_schema={k: 1 for k in PAYLOAD_INDEXES}` → `assert missing_payload_indexes(info) == []`.
- `test_handles_absent_schema`: `assert set(missing_payload_indexes(info)) == set(PAYLOAD_INDEXES)`.

In `tests/test_ensure_payload_indexes.py::TestEnsureIndexes`:
- `test_creates_only_missing_with_wait`: `existing={"source"}` → `assert set(created) == set(PAYLOAD_INDEXES) - {"source"}` (import `PAYLOAD_INDEXES`); keep the per-call `wait is True` assertion (drop the `field_schema == "keyword"` blanket assertion — schema now varies by field; the new `TestTypedIndexes` covers per-field schema).
- `test_idempotent_second_run_noop`: set `existing={*PAYLOAD_INDEXES}` (all keys) → `assert created == []` and `create_payload_index.assert_not_awaited()`.
- `test_none_payload_schema_creates_all`: already asserts `set(created) == set(REQUIRED_PAYLOAD_INDEXES)` → self-adjusts (REQUIRED_PAYLOAD_INDEXES = tuple(PAYLOAD_INDEXES)). No change.

The startup preflight test (`test_startup_warns_missing_indexes…`) only asserts the warning fired (not the exact fields) → unchanged.

- [ ] **Step 4: Run — expect PASS** (`tests/test_ensure_payload_indexes.py tests/test_qdrant_schema.py`) + `uv run pytest -q` + ruff. If any OTHER pre-existing test breaks, STOP and report.

- [ ] **Step 5: Commit**

```bash
git add rag/qdrant_schema.py scripts/ensure_payload_indexes.py tests/test_ensure_payload_indexes.py tests/test_qdrant_schema.py
git commit -m "feat(intelligence): typed payload-index migration (bool superseded + fulltext fields)"
```

---

## Task 11: Live backfill + measurement (Acceptance evidence)

**Manual / operator task — not a unit test. Requires crawl4ai/docling/TEI/Qdrant reachable + `FULLTEXT_ENABLED=true`.**

- [ ] **Step 1: Run the index migration** (typed) from `services/intelligence`:

```bash
uv run python -m scripts.ensure_payload_indexes   # creates feed_name/url/superseded(bool)/...
```
(Operator: snapshot first — `curl -X POST http://localhost:6333/collections/odin_intel/snapshots` — HNSW rebuild.)

- [ ] **Step 2: Run a bounded backfill** from `services/data-ingestion` (host, so `localhost` reaches crawl4ai/docling):

```bash
FULLTEXT_ENABLED=true uv run python -c "import asyncio; from feeds.fulltext_collector import FulltextCollector; asyncio.run(FulltextCollector().collect())"
```
Repeat until the think-tank teasers are superseded (each run does `fulltext_batch_size`). Watch logs for `fulltext_quality_gate_skip` / `fulltext_job` counts.

- [ ] **Step 3: Re-run the measurement harness** from `services/intelligence`:

```bash
uv run python -m scripts.measure_corpus_scoping > /tmp/fulltext_after.txt
grep -E '^### |^AFTER ' /tmp/fulltext_after.txt
```

- [ ] **Step 4: Record AC evidence in the PR**

- **AC-1:** `rss_fulltext:`-chunks from ≥ CSIS/RUSI/RAND/SWP/Bellingcat appear in the AFTER top-5 of the 6 queries (vs the old teasers).
- **AC-2:** no superseded teaser AND its `rss_fulltext` chunks both present (one article, not double).
- **AC-3:** `rss_fulltext` chunks carry the domain credibility (tier-boost ordering reflects it).
- Paste the before/after table into the PR.

---

## Final verification (after all tasks)

- [ ] data-ingestion: `cd services/data-ingestion && uv run pytest -q` → green; `uv run ruff check feeds/ scheduler.py config.py tests/`.
- [ ] intelligence: `cd services/intelligence && uv run pytest -q` → green; `uv run ruff check rag/ scripts/ tests/`.
- [ ] Both `fulltext_enabled` default **False** confirmed (no crawl unless opted in).
- [ ] Final holistic review (subagent-driven flow) before finishing the branch.

## Notes for the implementer
- data-ingestion async tests use **`@pytest.mark.asyncio`** (pytest-asyncio); intelligence uses **`asyncio_mode=auto`** (no mark).
- Qdrant in data-ingestion is the **sync** `QdrantClient` via `asyncio.to_thread` (mock with `MagicMock`); intelligence uses `AsyncQdrantClient` (mock with `AsyncMock`).
- Task 1 is **mandatory first** — Task 3's `_CRAWL4AI_FIT_KEYS`/`_DOCLING_MD_PATH` + request bodies must match the pinned `SHAPES.md`. If the live API differs, the fixtures win.
- Do NOT add an LLM extract (Slice B). `entities` are inherited from the teaser only.
- Two-phase, not atomic: chunks upsert THEN supersede; a crash between is self-healed next run (deterministic IDs + re-select). Don't try to make it transactional.
