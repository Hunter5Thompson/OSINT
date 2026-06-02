# RAG Corpus Read-Path Scoping + Tier-Rerank — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope Munin's semantic retrieval to a vetted prose-analysis corpus (rss + NotebookLM + vetted Telegram) and re-rank it by source reputation, so think-tank/NLM analysis surfaces to the top and GDELT-GKG / FIRMS / unvetted Telegram never reach the final briefing evidence set — without re-extracting or re-embedding existing points.

**Architecture:** One policy module (`rag/corpus_policy.py`) owns the corpus rules; it produces (a) a pre-retrieval Qdrant whitelist filter per lane, (b) a post-rerank tier-boost, and (c) a defensive output guard. The generic retriever stays neutral via an optional `post_rerank` callback. The `qdrant_search` tool runs two separate lanes (analysis + realtime Telegram, ≤1 Telegram in the final top-5) and merges them.

**Tech Stack:** Python >=3.12, FastAPI/LangChain tool, Qdrant (`odin_intel`, 1024-dim cosine), TEI bge-reranker-v2-m3, pytest + pytest-asyncio (`asyncio_mode=auto`), structlog. Spec: `docs/superpowers/specs/2026-06-02-rag-corpus-read-path-scoping-design.md`.

**Working dir for all commands:** `services/intelligence/` (run via `uv run pytest …`). Tests live in `services/intelligence/tests/`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `rag/credibility.py` | Reliability registry (source_type baseline + provider overrides) | Modify — add think-tank + wire overrides |
| `rag/reranker.py` | TEI rerank; text selection | Modify — `content or summary or title` |
| `rag/corpus_policy.py` | **New** — lane filters, tier-boost, output guard, merge, constants | Create |
| `rag/retriever.py` | Dense search + rerank + graph context | Modify — `query_filter`, `pool`, neutral `post_rerank` |
| `rag/evidence.py` | Evidence model + `[EVIDENCE]` codec | Modify — `source_class` passthrough |
| `agents/tools/qdrant_search.py` | The ReAct retrieval tool | Modify — two-lane + guard + merge |
| `rag/qdrant_schema.py` | Collection/index validators | Modify — `missing_payload_indexes` |
| `scripts/ensure_payload_indexes.py` | **New** — idempotent index migration (`wait=true`) | Create |
| `scripts/measure_corpus_scoping.py` | **New** — before/after measurement harness | Create |

Tasks are ordered so each leaves the suite green. Dependencies: Tasks 1, 2, 6, 7 are independent; Task 3 is independent; **Task 4 depends on 1 + 3**; **Task 5 depends on 3**; Task 8 integrates 1–7; **Task 10 depends on the `REQUIRED_PAYLOAD_INDEXES` contract introduced in Task 9** (which itself imports it from `qdrant_schema` — see Task 9/10).

---

## Task 1: Credibility provider overrides (think-tanks + wire)

**Files:**
- Modify: `rag/credibility.py:23-27` (`PROVIDER_OVERRIDES`)
- Test: `tests/test_credibility.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_credibility.py` (create the file if absent, with `from rag.credibility import credibility_score`):

```python
import pytest
from rag.credibility import credibility_score


class TestProviderOverrides:
    @pytest.mark.parametrize("feed_name,expected", [
        ("csis", 0.82),
        ("rand corporation", 0.82),
        ("rusi commentary", 0.82),
        ("rusi publications", 0.82),
        ("sipri", 0.82),
        ("atlantic council", 0.82),
        ("war on the rocks", 0.82),
        ("brookings", 0.82),
        ("crisis group", 0.82),
        ("arms control association", 0.82),
        ("swp publications (de)", 0.82),
        ("swp publications (en)", 0.82),
        ("bellingcat", 0.85),
        ("reuters (google)", 0.85),
        ("ap news (google)", 0.85),
        ("bbc world", 0.80),
        ("eu parliament security and defence", 0.80),
        ("euvsdisinfo", 0.80),
    ])
    def test_analysis_feed_override(self, feed_name, expected):
        # rss provider is the lowercased feed_name
        assert credibility_score("rss", feed_name) == expected

    def test_local_rss_keeps_baseline(self):
        assert credibility_score("rss", "some local paper") == 0.60

    def test_unknown_source_type_still_fail_fast(self):
        with pytest.raises(KeyError):
            credibility_score("not_a_type", "whatever")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_credibility.py::TestProviderOverrides -q`
Expected: FAIL (overrides return 0.60 baseline, not 0.82/0.85/0.80).

- [ ] **Step 3: Write minimal implementation**

In `rag/credibility.py`, replace the `PROVIDER_OVERRIDES` dict (keep the two existing domain keys, add the feed_name keys):

```python
PROVIDER_OVERRIDES: dict[str, float] = {
    # Domain keys (GDELT-discovery path surfaces bare domains)
    "reuters.com": 0.85,  # international wire, strong editorial standards
    "bbc.com": 0.80,      # public broadcaster (international domain)
    "bbc.co.uk": 0.80,    # public broadcaster (UK domain — the RSS feed's provider)
    # RSS feed_name keys (provider == normalize_provider(feed_name.lower())).
    # Registry models reliability, not document genre — wire services included.
    "reuters (google)": 0.85,
    "ap news (google)": 0.85,
    "bbc world": 0.80,
    "bellingcat": 0.85,                       # OSINT verification, methodical
    "rand corporation": 0.82,
    "csis": 0.82,
    "rusi commentary": 0.82,
    "rusi publications": 0.82,
    "sipri": 0.82,
    "swp publications (de)": 0.82,
    "swp publications (en)": 0.82,
    "atlantic council": 0.82,
    "brookings": 0.82,
    "crisis group": 0.82,
    "war on the rocks": 0.82,
    "arms control association": 0.82,
    "eu parliament security and defence": 0.80,
    "euvsdisinfo": 0.80,
}
```

Note: `normalize_provider` lowercases and strips `www.`/scheme but leaves spaces and parentheses intact, so the lowercased feed_name matches these keys verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_credibility.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/credibility.py tests/test_credibility.py
git commit -m "feat(intelligence): credibility overrides for think-tank + wire feeds"
```

---

## Task 2: Reranker uses RSS teaser (`content or summary or title`)

**Files:**
- Modify: `rag/reranker.py:23`
- Test: `tests/test_reranker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reranker.py`:

```python
from unittest.mock import AsyncMock, patch

import httpx


def _resp(scores):
    req = httpx.Request("POST", "http://x/rerank")
    return httpx.Response(200, json=scores, request=req)


class TestRerankTextSelection:
    async def test_prefers_content_then_summary_then_title(self):
        from rag.reranker import rerank

        docs = [
            {"content": "C", "summary": "S", "title": "T"},   # -> "C"
            {"summary": "S2", "title": "T2"},                 # -> "S2"
            {"title": "T3"},                                  # -> "T3"
        ]
        captured = {}

        async def fake_post(url, json=None):
            captured["texts"] = json["texts"]
            return _resp([{"index": i, "score": 1.0 - i * 0.1} for i in range(len(docs))])

        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=fake_post)):
            await rerank("q", docs, top_k=3)

        assert captured["texts"] == ["C", "S2", "T3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reranker.py -q`
Expected: FAIL — current code sends `["C", "T2", "T3"]` (ignores `summary`).

- [ ] **Step 3: Write minimal implementation**

In `rag/reranker.py`, change line 23:

```python
    texts = [d.get("content") or d.get("summary") or d.get("title", "") for d in documents]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reranker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/reranker.py tests/test_reranker.py
git commit -m "fix(intelligence): rerank RSS on summary, not title-only"
```

---

## Task 3: Corpus policy — lane filters + constants

**Files:**
- Modify: `config.py` (add env-overridable tunables)
- Create: `rag/corpus_policy.py`
- Test: `tests/test_corpus_policy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_corpus_policy.py`:

```python
from rag import corpus_policy as cp


class TestLaneFilters:
    def test_analysis_filter_shape(self):
        f = cp.analysis_filter()
        should = f["should"]
        # source ∈ ANALYSIS_SOURCES (match any, extensible to future "nlm")
        assert {"key": "source", "match": {"any": sorted(cp.ANALYSIS_SOURCES)}} in should
        # NLM via notebook_id presence (raw source is "unknown" in legacy points)
        assert {"must_not": [{"is_empty": {"key": "notebook_id"}}]} in should

    def test_realtime_filter_shape(self):
        f = cp.realtime_filter()
        must = f["must"]
        assert {"key": "source", "match": {"value": "telegram"}} in must
        chan = next(c for c in must if c["key"] == "telegram_channel")
        allowed = set(chan["match"]["any"])
        assert {"wartranslated", "OSINTdefender"} <= allowed
        assert "rybar" not in allowed

    def test_constants_present(self):
        assert cp.ANALYSIS_POOL == 40
        assert cp.REALTIME_POOL == 20
        assert cp.RT_SCORE_THRESHOLD == 0.45
        assert cp.FINAL_K == 5
        assert cp.TELEGRAM_MAX == 1
        assert cp.TIER_BOOST_LAMBDA == 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_policy.py::TestLaneFilters -q`
Expected: FAIL with `ModuleNotFoundError: rag.corpus_policy`.

- [ ] **Step 3: Write minimal implementation**

First add the env-overridable tunables to `config.py` (calibration must not require a code deploy). In `services/intelligence/config.py`, inside `class Settings`, right after the `# RAG feature flags` block (`enable_graph_context: bool = True`):

```python
    # Read-corpus scoping (P1+P4) — tunable via env
    # (RAG_TIER_BOOST_LAMBDA, RAG_ANALYSIS_POOL, RAG_REALTIME_POOL,
    #  RAG_REALTIME_SCORE_THRESHOLD, RAG_FINAL_K, RAG_TELEGRAM_MAX)
    rag_tier_boost_lambda: float = 0.2
    rag_analysis_pool: int = 40
    rag_realtime_pool: int = 20
    rag_realtime_score_threshold: float = 0.45
    rag_final_k: int = 5
    rag_telegram_max: int = 1
```

Then create `rag/corpus_policy.py`:

```python
"""Read-corpus policy — the single auditable place for *which sources are
readable* and *how reputation nudges relevance*. Consumed only by the
qdrant_search tool; the generic retriever stays neutral.

Two lanes:
  analysis  — rss OR NotebookLM (notebook_id present; legacy raw source="unknown")
  realtime  — vetted Telegram leads (NOT verified primary sources)
"""
from __future__ import annotations

import structlog

from config import settings

log = structlog.get_logger(__name__)

# Analysis lane: prose analysis.
ANALYSIS_SOURCES: frozenset[str] = frozenset({"rss"})

# Realtime lane: vetted Telegram leads. rybar (state-aligned) deliberately excluded.
TELEGRAM_ALLOWLIST: frozenset[str] = frozenset({
    "wartranslated", "OSINTdefender", "liveuamap", "AuroraIntel", "DeepStateEN",
})

# Tunable start values — sourced from settings (env-overridable). NOT permanent truth.
TIER_BOOST_LAMBDA: float = settings.rag_tier_boost_lambda
ANALYSIS_POOL: int = settings.rag_analysis_pool
REALTIME_POOL: int = settings.rag_realtime_pool
RT_SCORE_THRESHOLD: float = settings.rag_realtime_score_threshold
FINAL_K: int = settings.rag_final_k
TELEGRAM_MAX: int = settings.rag_telegram_max


def analysis_filter() -> dict:
    """Qdrant filter: source ∈ ANALYSIS_SOURCES OR notebook_id present (NLM).
    min_should=1 (Qdrant default)."""
    return {"should": [
        {"key": "source", "match": {"any": sorted(ANALYSIS_SOURCES)}},
        {"must_not": [{"is_empty": {"key": "notebook_id"}}]},
    ]}


def realtime_filter() -> dict:
    """Qdrant filter: vetted Telegram channels."""
    return {"must": [
        {"key": "source", "match": {"value": "telegram"}},
        {"key": "telegram_channel", "match": {"any": sorted(TELEGRAM_ALLOWLIST)}},
    ]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus_policy.py::TestLaneFilters -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/corpus_policy.py tests/test_corpus_policy.py
git commit -m "feat(intelligence): corpus policy lane filters + constants"
```

---

## Task 4: Corpus policy — `credibility_of` + `apply_tier_boost`

**Depends on:** Task 1 (override values it asserts) + Task 3 (module + constants).

**Files:**
- Modify: `rag/corpus_policy.py`
- Test: `tests/test_corpus_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_corpus_policy.py`:

```python
class TestTierBoost:
    def _rss(self, feed, content, score, rerank):
        return {"source": "rss", "feed_name": feed, "content": content,
                "title": content, "score": score, "rerank_score": rerank}

    def test_credibility_of_rss_and_nlm(self):
        assert cp.credibility_of(self._rss("CSIS", "x", 0.9, 5.0)) == 0.82
        assert cp.credibility_of(self._rss("Local Paper", "x", 0.9, 5.0)) == 0.60
        nlm = {"notebook_id": "nb1", "content": "claim", "title": "t", "score": 0.9}
        assert cp.credibility_of(nlm) == 0.60  # notebooklm baseline

    def test_near_tie_flips_to_higher_credibility(self):
        # local slightly more relevant, think-tank slightly less — tank should win
        local = self._rss("Local Paper", "a", 0.9, 1.01)
        tank = self._rss("CSIS", "b", 0.9, 1.00)
        out = cp.apply_tier_boost([local, tank])
        assert out[0]["feed_name"] == "CSIS"

    def test_large_relevance_gap_not_flipped(self):
        local = self._rss("Local Paper", "a", 0.9, 10.0)  # much more relevant
        tank = self._rss("CSIS", "b", 0.9, 0.0)
        out = cp.apply_tier_boost([local, tank])
        assert out[0]["feed_name"] == "Local Paper"

    def test_max_equals_min_sorts_by_credibility_no_zerodiv(self):
        local = self._rss("Local Paper", "a", 0.5, 3.0)
        tank = self._rss("CSIS", "b", 0.5, 3.0)  # identical rerank scores
        out = cp.apply_tier_boost([local, tank])
        assert out[0]["feed_name"] == "CSIS"

    def test_falls_back_to_dense_score_without_rerank_score(self):
        a = {"source": "rss", "feed_name": "CSIS", "content": "a", "title": "a", "score": 0.8}
        b = {"source": "rss", "feed_name": "Local Paper", "content": "b", "title": "b", "score": 0.2}
        out = cp.apply_tier_boost([a, b])  # no rerank_score key
        assert out[0]["feed_name"] == "CSIS"
        assert "tier_score" in out[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_policy.py::TestTierBoost -q`
Expected: FAIL — `AttributeError: module has no attribute 'credibility_of'`.

- [ ] **Step 3: Write minimal implementation**

Append to `rag/corpus_policy.py`:

```python
def credibility_of(payload: dict) -> float:
    """Reliability for a raw retriever-result payload. Reuses the read-side
    provenance derivation so NLM(notebook_id)->notebooklm(0.60), rss->feed_name
    override or 0.60, telegram->0.40, etc."""
    from rag.evidence import to_evidence_item  # local import avoids cycle
    return to_evidence_item(payload).source.credibility_score


def apply_tier_boost(results: list[dict], *, lam: float = TIER_BOOST_LAMBDA) -> list[dict]:
    """final = (1-lam)*rerank_norm + lam*credibility, stable-sorted desc.

    rerank_norm is the min-max normalized rerank_score (dense `score` if no
    rerank_score). When max==min (ties / pool size 1) rerank_norm=1.0 for all,
    so reputation decides. Suitable as enhanced_search's post_rerank callback.
    """
    if not results:
        return results
    raws = [float(r.get("rerank_score", r.get("score", 0.0))) for r in results]
    lo, hi = min(raws), max(raws)
    span = hi - lo
    out: list[dict] = []
    for r, raw in zip(results, raws):
        r_norm = 1.0 if span == 0 else (raw - lo) / span
        cred = credibility_of(r)
        final = (1.0 - lam) * r_norm + lam * cred
        out.append({**r, "tier_raw": raw, "tier_norm": r_norm,
                    "tier_cred": cred, "tier_score": final})
    out.sort(key=lambda x: x["tier_score"], reverse=True)
    log.info(
        "tier_boost_applied",
        lam=lam,
        ranked=[{"provider": x.get("feed_name") or x.get("source"),
                 "source": x.get("source"), "raw": round(x["tier_raw"], 4),
                 "norm": round(x["tier_norm"], 4), "cred": x["tier_cred"],
                 "final": round(x["tier_score"], 4)} for x in out],
    )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/corpus_policy.py tests/test_corpus_policy.py
git commit -m "feat(intelligence): tier-boost scoring + credibility_of"
```

---

## Task 5: Corpus policy — `validate_lane` (output guard) + `merge_lanes`

**Depends on:** Task 3 (module + `ANALYSIS_SOURCES`/`TELEGRAM_ALLOWLIST`/`TELEGRAM_MAX`).

**Files:**
- Modify: `rag/corpus_policy.py`
- Test: `tests/test_corpus_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_corpus_policy.py`:

```python
class TestGuardAndMerge:
    def test_validate_analysis_drops_cross_lane(self, caplog):
        rss = {"source": "rss", "feed_name": "CSIS"}
        nlm = {"source": "unknown", "notebook_id": "nb1"}
        junk = {"source": "gdelt_gkg", "doc_id": "gdelt:gkg:1"}
        firms = {"source": "firms"}
        kept = cp.validate_lane([rss, nlm, junk, firms], "analysis")
        assert kept == [rss, nlm]

    def test_validate_realtime_only_allowlisted(self):
        ok = {"source": "telegram", "telegram_channel": "wartranslated"}
        bad = {"source": "telegram", "telegram_channel": "rybar"}
        assert cp.validate_lane([ok, bad], "realtime") == [ok]

    def test_merge_caps_one_realtime_at_end(self):
        analysis = [{"id": i} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated"}]
        out = cp.merge_lanes(analysis, realtime)
        assert len(out) == 5
        assert out[:4] == analysis[:4]
        assert out[4]["source_class"] == "realtime"

    def test_merge_no_realtime_keeps_five_analysis(self):
        analysis = [{"id": i} for i in range(5)]
        out = cp.merge_lanes(analysis, [])
        assert out == analysis[:5]
        assert all("source_class" not in r for r in out)

    def test_validate_rejects_inconsistent_source_type(self):
        # raw source says rss but canonical source_type says gdelt -> reject
        bad = {"source": "rss", "feed_name": "x", "source_type": "gdelt"}
        good = {"source": "rss", "feed_name": "CSIS", "source_type": "rss"}
        assert cp.validate_lane([good, bad], "analysis") == [good]

    def test_validate_realtime_rejects_inconsistent_source_type(self):
        bad = {"source": "telegram", "telegram_channel": "wartranslated",
               "source_type": "rss"}
        assert cp.validate_lane([bad], "realtime") == []

    def test_merge_uses_telegram_max(self):
        analysis = [{"id": i} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated"},
                    {"source": "telegram", "telegram_channel": "OSINTdefender"}]
        out = cp.merge_lanes(analysis, realtime)
        assert sum(1 for r in out if r.get("source_class") == "realtime") == cp.TELEGRAM_MAX
        assert len(out) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_policy.py::TestGuardAndMerge -q`
Expected: FAIL — `validate_lane`/`merge_lanes` undefined.

- [ ] **Step 3: Write minimal implementation**

Append to `rag/corpus_policy.py`:

```python
# Canonical source_types consistent with each lane (when the contract field
# is present on a payload).
_ANALYSIS_TYPES: frozenset[str] = frozenset({"rss", "notebooklm"})


def validate_lane(results: list[dict], lane: str) -> list[dict]:
    """Second barrier (AC-2): keep only results that satisfy the lane invariant.
    Qdrant filter is the first barrier; index lag / a filter bug must not break
    AC-2. A payload whose canonical `source_type` contradicts the lane (e.g.
    source="rss" but source_type="gdelt") is rejected too. Dropped are logged."""
    kept, dropped = [], []
    for r in results:
        st = r.get("source_type")  # canonical contract field, if present
        if lane == "analysis":
            identity = r.get("source") in ANALYSIS_SOURCES or bool(r.get("notebook_id"))
            type_ok = st is None or st in _ANALYSIS_TYPES
            ok = identity and type_ok
        elif lane == "realtime":
            identity = (r.get("source") == "telegram"
                        and r.get("telegram_channel") in TELEGRAM_ALLOWLIST)
            type_ok = st is None or st == "telegram"
            ok = identity and type_ok
        else:
            ok = False
        (kept if ok else dropped).append(r)
    if dropped:
        log.warning("corpus_guard_dropped", lane=lane, count=len(dropped),
                    sources=[d.get("source") for d in dropped])
    return kept


def merge_lanes(analysis: list[dict], realtime: list[dict],
                *, final_k: int = FINAL_K, telegram_max: int = TELEGRAM_MAX) -> list[dict]:
    """Analysis dominates the top; at most `telegram_max` realtime leads, last,
    each marked source_class="realtime". Realtime displaces at most
    `telegram_max` analysis slots."""
    rt = [{**r, "source_class": "realtime"} for r in realtime[:telegram_max]]
    if rt:
        return list(analysis[:final_k - len(rt)]) + rt
    return list(analysis[:final_k])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/corpus_policy.py tests/test_corpus_policy.py
git commit -m "feat(intelligence): corpus output guard + two-lane merge"
```

---

## Task 6: Retriever — `query_filter`, `pool`, neutral `post_rerank`

**Files:**
- Modify: `rag/retriever.py` (`search` ~line 70-100; `enhanced_search` ~line 139-205)
- Test: `tests/test_hybrid_retriever.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hybrid_retriever.py`:

```python
class TestQueryFilterAndPostRerank:
    async def test_query_filter_passed_to_search(self):
        from rag.retriever import enhanced_search

        captured = {}

        async def fake_search(query, **kwargs):
            captured.update(kwargs)
            return [{"title": "r", "content": "c", "score": 0.9}]

        with patch("rag.retriever.search", AsyncMock(side_effect=fake_search)):
            await enhanced_search(
                "q", query_filter={"should": [{"key": "source", "match": {"value": "rss"}}]},
                pool=40, enable_rerank=False, enable_graph_context=False,
            )
        assert captured["query_filter"] == {"should": [{"key": "source", "match": {"value": "rss"}}]}
        assert captured["limit"] == 40  # pool drives overfetch

    async def test_post_rerank_none_is_neutral(self):
        from rag.retriever import enhanced_search

        results = [{"title": "a", "content": "a", "score": 0.1},
                   {"title": "b", "content": "b", "score": 0.9}]
        with patch("rag.retriever.search", AsyncMock(return_value=results)):
            out = await enhanced_search(
                "q", enable_rerank=False, enable_graph_context=False,
            )
        # untouched order, no tier_* keys injected
        assert [r["title"] for r in out] == ["a", "b"]
        assert all("tier_score" not in r for r in out)

    async def test_post_rerank_callback_applied(self):
        from rag.retriever import enhanced_search

        results = [{"title": "a", "content": "a", "score": 0.1},
                   {"title": "b", "content": "b", "score": 0.9}]

        def reverse(rs):
            return list(reversed(rs))

        with patch("rag.retriever.search", AsyncMock(return_value=results)):
            out = await enhanced_search(
                "q", post_rerank=reverse, enable_rerank=False, enable_graph_context=False,
            )
        assert [r["title"] for r in out] == ["b", "a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hybrid_retriever.py::TestQueryFilterAndPostRerank -q`
Expected: FAIL — `search()`/`enhanced_search()` don't accept `query_filter`/`pool`/`post_rerank`.

- [ ] **Step 3: Write minimal implementation**

In `rag/retriever.py`, change the `search` signature and filter assembly. Replace the signature line and the filter-building block:

```python
async def search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
    query_filter: dict | None = None,
) -> list[dict]:
```

Replace the `must_conditions` / `search_body["filter"]` block (currently ~lines 101-113) with:

```python
    # Build filter conditions
    must_conditions: list[dict] = []
    if region:
        must_conditions.append({"key": "region", "match": {"value": region}})
    if source:
        must_conditions.append({"key": "source", "match": {"value": source}})

    filt: dict = {}
    if must_conditions:
        filt["must"] = must_conditions
    if query_filter:
        for k, v in query_filter.items():
            if k == "must":
                filt["must"] = filt.get("must", []) + v
            else:
                filt[k] = v
    if filt:
        search_body["filter"] = filt
```

Then change `enhanced_search`. Update its signature to add the three params:

```python
async def enhanced_search(
    query: str,
    limit: int = 5,
    region: str | None = None,
    source: str | None = None,
    score_threshold: float = 0.3,
    query_filter: dict | None = None,
    pool: int | None = None,
    post_rerank=None,
    *,
    enable_hybrid: bool | None = None,
    enable_rerank: bool | None = None,
    enable_graph_context: bool | None = None,
    graph_client=None,
) -> list[dict]:
```

Replace the Stage 1/2/3 body (from `overfetch = ...` through `return results`) with:

```python
    # Stage 1: Dense search (baseline). pool overrides the rerank overfetch.
    overfetch = pool if pool is not None else (limit * 2 if enable_rerank else limit)
    results = await search(
        query, limit=overfetch, region=region,
        source=source, score_threshold=score_threshold, query_filter=query_filter,
    )

    if not results:
        return []

    # Stage 2: Rerank (optional). When a post_rerank hook is set we rerank the
    # whole pool so the hook can re-order across all candidates before the cut.
    if enable_rerank:
        rerank_top_k = overfetch if post_rerank is not None else limit
        results = await _rerank_fn(query, results, top_k=rerank_top_k)

    # Stage 2b: Optional post-rerank hook (e.g. tier-boost). Keeps the primitive
    # neutral when None — no corpus policy leaks into the generic retriever.
    if post_rerank is not None:
        results = post_rerank(results)

    results = results[:limit]

    # Stage 3: Graph Context Injection (optional) — only for the final items.
    if enable_graph_context:
        entity_names = set()
        for r in results:
            for e in r.get("entities", []):
                if isinstance(e, dict) and "name" in e:
                    entity_names.add(e["name"])
        if entity_names:
            gc = graph_client or _get_graph_client()
            graph_ctx = await _graph_context_fn(list(entity_names), graph_client=gc)
            if graph_ctx:
                for r in results:
                    r["graph_context"] = graph_ctx

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hybrid_retriever.py -q`
Expected: PASS (new tests + all pre-existing retriever tests stay green).

- [ ] **Step 5: Commit**

```bash
git add rag/retriever.py tests/test_hybrid_retriever.py
git commit -m "feat(intelligence): retriever query_filter + pool + neutral post_rerank hook"
```

---

## Task 7: Evidence — `source_class` passthrough

**Files:**
- Modify: `rag/evidence.py` (`EvidenceItem` ~line 31-36; `to_evidence_item` ~line 147-153; `_block` ~line 159-173)
- Test: `tests/test_evidence.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_evidence.py` (create with `from rag.evidence import to_evidence_item, format_evidence_pack` if absent):

```python
import json
from rag.evidence import to_evidence_item, format_evidence_pack


class TestSourceClass:
    def test_realtime_marker_in_evidence_line(self):
        item = to_evidence_item({
            "source": "telegram", "telegram_channel": "wartranslated",
            "title": "lead", "content": "raw lead", "score": 0.5,
            "source_class": "realtime",
        })
        assert item.source_class == "realtime"
        pack = format_evidence_pack([item], budget=2000)
        meta_line = next(l for l in pack.splitlines() if l.startswith("[EVIDENCE] "))
        meta = json.loads(meta_line[len("[EVIDENCE] "):])
        assert meta["source_class"] == "realtime"

    def test_analysis_item_has_no_source_class_key(self):
        item = to_evidence_item({
            "source": "rss", "feed_name": "CSIS", "title": "t",
            "summary": "s", "score": 0.5,
        })
        assert item.source_class is None
        pack = format_evidence_pack([item], budget=2000)
        meta_line = next(l for l in pack.splitlines() if l.startswith("[EVIDENCE] "))
        assert "source_class" not in json.loads(meta_line[len("[EVIDENCE] "):])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evidence.py::TestSourceClass -q`
Expected: FAIL — `EvidenceItem` has no `source_class`.

- [ ] **Step 3: Write minimal implementation**

In `rag/evidence.py`:

1. Add the field to `EvidenceItem` (after `content_hash`):

```python
class EvidenceItem(BaseModel):
    source: SourceRef
    title: str
    excerpt: str
    relevance_score: float
    content_hash: str | None = None     # for dedup only, not public provenance
    source_class: str | None = None     # "realtime" marks an unverified lead
```

2. In `to_evidence_item`, pass it through in the `EvidenceItem(...)` return:

```python
    return EvidenceItem(
        source=ref,
        title=title,
        excerpt=excerpt,
        relevance_score=float(result.get("score", 0.0)),
        content_hash=str(content_hash) if content_hash else None,
        source_class=result.get("source_class"),
    )
```

3. In `_block`, add the key only when present (keeps existing output stable for analysis items):

```python
def _block(item: EvidenceItem) -> str:
    s = item.source
    meta = {
        "credibility_score": s.credibility_score,
        "display_name": s.display_name,
        "provenance_inferred": s.provenance_inferred,
        "provider": s.provider,
        "published_at": s.published_at.isoformat() if s.published_at else None,
        "relevance_score": item.relevance_score,
        "source_ref_id": s.source_ref_id,
        "source_type": s.source_type,
        "url": s.url,
    }
    if item.source_class:
        meta["source_class"] = item.source_class
    header = _EVIDENCE_PREFIX + json.dumps(meta, sort_keys=True, separators=(",", ":"))
    return f"{header}\nTitle: {item.title}\nExcerpt: {item.excerpt}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_evidence.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/evidence.py tests/test_evidence.py
git commit -m "feat(intelligence): evidence source_class passthrough (realtime lead marker)"
```

---

## Task 8: `qdrant_search` — two-lane retrieval + guard + merge

**Depends on:** Tasks 1–7.

**Files:**
- Modify: `agents/tools/qdrant_search.py` (two-lane body ~59-96 + docstring ~27-34)
- Modify: `agents/react_agent.py:29-35` (tool description)
- Test: `tests/test_qdrant_search_tool.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_qdrant_search_tool.py`:

```python
class TestTwoLaneScoping:
    def _lane_mock(self, analysis, realtime):
        # enhanced_search is called analysis-lane first, realtime-lane second
        return AsyncMock(side_effect=[analysis, realtime])

    async def test_excludes_gkg_and_firms_keeps_analysis(self):
        from agents.tools import qdrant_search as qs

        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "Tank view",
             "summary": "deep analysis", "score": 0.8},
            {"source": "rss", "feed_name": "RUSI Commentary", "title": "RUSI",
             "summary": "more analysis", "score": 0.7},
        ]
        realtime = []  # nothing cleared the 0.45 bar
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await qs.qdrant_search.ainvoke({"query": "taiwan strait"})

        assert "CSIS" in out or "Tank view" in out
        assert "gdelt_gkg" not in out
        assert "firms" not in out

    async def test_at_most_one_realtime_marked(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": f"A{i}",
                     "summary": "x", "score": 0.8} for i in range(5)]
        realtime = [{"source": "telegram", "telegram_channel": "wartranslated",
                     "title": "RT lead", "content": "raw", "score": 0.6}]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await qs.qdrant_search.ainvoke({"query": "kharkiv"})

        assert out.count('"source_class":"realtime"') == 1

    async def test_guard_drops_leaked_unvetted_telegram(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": "A",
                     "summary": "x", "score": 0.8}]
        # a rybar item leaks past the (mocked) filter — guard must drop it
        realtime = [{"source": "telegram", "telegram_channel": "rybar",
                     "title": "propaganda", "content": "raw", "score": 0.9}]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, realtime)):
            out = await qs.qdrant_search.ainvoke({"query": "donbas"})

        assert "propaganda" not in out
        assert '"source_class":"realtime"' not in out

    async def test_guard_drops_injected_gkg_and_firms(self):
        from agents.tools import qdrant_search as qs

        # gkg + firms leak INTO the analysis lane past the (mocked) filter — the
        # output guard is the second barrier and must drop them (AC-2).
        analysis = [
            {"source": "rss", "feed_name": "CSIS", "title": "Real analysis",
             "summary": "x", "score": 0.8},
            {"source": "gdelt_gkg", "doc_id": "gdelt:gkg:9",
             "title": "gdelt:gkg:9", "score": 0.95},
            {"source": "firms", "title": "thermal anomaly", "score": 0.9},
        ]
        with patch("agents.tools.qdrant_search.enhanced_search",
                   self._lane_mock(analysis, [])):
            out = await qs.qdrant_search.ainvoke({"query": "taiwan strait"})

        assert "gdelt:gkg:9" not in out
        assert "thermal anomaly" not in out
        assert "Real analysis" in out or "CSIS" in out

    async def test_realtime_error_degrades_gracefully(self):
        from agents.tools import qdrant_search as qs

        analysis = [{"source": "rss", "feed_name": "CSIS", "title": "A",
                     "summary": "x", "score": 0.8}]
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[analysis, RuntimeError("realtime down")]),
        ):
            out = await qs.qdrant_search.ainvoke({"query": "kyiv"})

        assert "CSIS" in out or "A" in out          # analysis lane survives
        assert '"source_class":"realtime"' not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_qdrant_search_tool.py::TestTwoLaneScoping -q`
Expected: FAIL — current tool does a single unscoped `enhanced_search` call.

- [ ] **Step 3: Write minimal implementation**

In `agents/tools/qdrant_search.py`, add imports near the top:

```python
from rag.corpus_policy import (
    ANALYSIS_POOL,
    FINAL_K,
    REALTIME_POOL,
    RT_SCORE_THRESHOLD,
    analysis_filter,
    apply_tier_boost,
    merge_lanes,
    realtime_filter,
    validate_lane,
)
```

Replace the body inside `try:` (the `results = await enhanced_search(...)` block down to the line that sets `results`) with the two-lane retrieval, keeping the existing evidence-pack/graph-context formatting that follows:

```python
        analysis = await enhanced_search(
            query, limit=FINAL_K, pool=ANALYSIS_POOL,
            query_filter=analysis_filter(), region=region or None,
            post_rerank=apply_tier_boost,
        )
        try:
            realtime = await enhanced_search(
                query, limit=1, pool=REALTIME_POOL,
                query_filter=realtime_filter(), region=region or None,
                post_rerank=apply_tier_boost, score_threshold=RT_SCORE_THRESHOLD,
            )
        except Exception as e:  # realtime is best-effort; never fail the analysis lane
            logger.warning("realtime_lane_failed", query=query, error=str(e))
            realtime = []

        analysis = validate_lane(analysis, "analysis")
        realtime = validate_lane(realtime, "realtime")
        results = merge_lanes(analysis, realtime)

        logger.info(
            "qdrant_search_executed",
            query=query,
            analysis_count=len(analysis),
            realtime_count=len(realtime),
            result_count=len(results),
        )

        if not results:
            return f"No relevant documents found for: {query}"
```

Remove the now-stale single-call block and its old `logger.info("qdrant_search_executed", …)`/empty-check (replaced above). `region` **is still forwarded** to both lanes (`region=region or None`) so the API behavior does not silently disappear; the index simply has no region tags yet. Scoping is via `query_filter`. Everything from `items = [to_evidence_item(r) for r in results]` onward is unchanged.

- [ ] **Step 3b: Update the three pre-existing budgeting tests (they will break)**

These tests mock `enhanced_search` with a single `return_value` and use synthetic payloads that don't carry raw `source:"rss"`. The two-lane code calls `enhanced_search` twice, and `validate_lane` (keyed on raw `source`, by design identical to the Qdrant filter) drops them. Live RSS points carry `source:"rss"`, so the fix is to make the synthetic payloads realistic and feed an empty realtime lane. In `tests/test_qdrant_search_tool.py`:

1. `test_dedupes_graph_context_and_caps_output`: in the result dict change `"source": "test",` → `"source": "rss",`; change the patch to `AsyncMock(side_effect=[results, []])`.

2. `test_emits_parsable_evidence_blocks_with_provider`: do **not** disguise the dataset row as rss. Keep the Reuters row as a genuine RSS point (canonical `source_type="rss"`, `provider="reuters.com"`, plus raw `source="rss"`) and **replace** the `usgs.gov`/`dataset` row with a real RSS think-tank fixture. Update the patch and the provider assertion. Full replacement of that test body:

```python
        results = [
            {
                "score": 0.9, "source": "rss", "source_type": "rss",
                "provider": "reuters.com", "title": "Tanker seized",
                "content": "body " * 50, "url": "https://reuters.com/a",
                "content_hash": "h1",
            },
            {
                "score": 0.8, "source": "rss", "feed_name": "RUSI Commentary",
                "title": "RUSI analysis", "summary": "rusi " * 50,
                "content_hash": "h2",
            },
        ]
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[results, []]),
        ):
            out = await qdrant_search.ainvoke({"query": "baltic tanker"})
        refs = parse_evidence_refs(out)
        assert {r.provider for r in refs} == {"reuters.com", "rusi commentary"}
        assert refs[0].provider == "reuters.com"  # higher score first
```

3. `test_output_never_exceeds_cap_with_full_pack_no_graph`: add `"source": "rss",` to the comprehension dict; change the patch to `AsyncMock(side_effect=[results, []])`.

Example for test 1:

```python
        results = [
            {
                "score": 0.9 - i * 0.01,
                "title": f"Result {i}",
                "source": "rss",
                "region": "N/A",
                "content": "source text " * 200,
                "graph_context": graph_context,
            }
            for i in range(5)
        ]

        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(side_effect=[results, []]),
        ):
            output = await qdrant_search.ainvoke({"query": "bundeswehr strategy"})
```

- [ ] **Step 3c: Fix the tool description so Munin's mental model matches reality**

The `qdrant_search` docstring and the ReAct system prompt still claim Qdrant returns rybar, FIRMS, UCDP, GDACS, EONET. After scoping that is false. Update both (no test asserts this prose — it is a grounding/correctness fix verified by reading; commit it with this task).

In `agents/tools/qdrant_search.py`, replace the docstring's index-content block (the `Index content (≈20k documents…)` bullet list, ~lines 27-34) with:

```
    Index content — VETTED ANALYSIS PROSE only (1024-dim cosine):
    - 37 RSS feeds: think-tanks (CSIS, RUSI, RAND, SIPRI, SWP, Atlantic Council,
      War on the Rocks, Brookings, Crisis Group, Bellingcat), gov/mil (BMVg,
      Bundeswehr, Bundestag, NATO, UN, US Gov), wire (Reuters, AP, BBC), defense media
    - NotebookLM extractions from briefing audio and research reports
    Plus AT MOST ONE vetted Telegram realtime LEAD (wartranslated, OSINTdefender,
    liveuamap, AuroraIntel, DeepStateEN), marked source_class="realtime" — treat it
    as an unverified lead, not a primary source.

    NOT here: GDELT-GKG, FIRMS, UCDP, GDACS, EONET and other structured/sensor data
    — reach those via query_knowledge_graph (Neo4j), not this tool.
```

In `agents/react_agent.py`, replace the `- **qdrant_search** — …` bullet (~lines 29-35) with:

```
- **qdrant_search** — Vektor-Index über **geprüfte Analyse-Prosa**: 37 RSS-Feeds
  (Think-Tanks CSIS/RUSI/RAND/SIPRI/SWP/Atlantic Council/Bellingcat; BMVg,
  Bundeswehr, Bundestag, NATO/UN/US Gov; Reuters/AP/BBC; Defense-/OSINT-Medien)
  plus NotebookLM-Extraktionen — sowie **höchstens einen** vetted Telegram-
  Realtime-Lead (markiert, KEINE verifizierte Primärquelle). GDELT-GKG, FIRMS,
  UCDP, GDACS, EONET sind hier **NICHT** abrufbar — strukturierte Events/Sensorik
  laufen über `query_knowledge_graph`. Best für **thematische** Suche +
  semantische Ähnlichkeit. Args: query, region (optional).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_qdrant_search_tool.py -q`
Expected: PASS (5 new TwoLaneScoping tests + 3 updated budgeting tests).

- [ ] **Step 5: Commit**

```bash
git add agents/tools/qdrant_search.py agents/react_agent.py tests/test_qdrant_search_tool.py
git commit -m "feat(intelligence): two-lane corpus-scoped qdrant_search with output guard"
```

---

## Task 9: Idempotent payload-index migration script

**Files:**
- Modify: `rag/qdrant_schema.py` (define the central `REQUIRED_PAYLOAD_INDEXES` contract)
- Create: `scripts/ensure_payload_indexes.py`
- Test: `tests/test_ensure_payload_indexes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ensure_payload_indexes.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock


class TestEnsureIndexes:
    def _client(self, existing):
        c = SimpleNamespace()
        c.get_collection = AsyncMock(
            return_value=SimpleNamespace(payload_schema={k: object() for k in existing})
        )
        c.create_payload_index = AsyncMock()
        return c

    async def test_creates_only_missing_with_wait(self):
        from scripts.ensure_payload_indexes import ensure_indexes

        client = self._client(existing={"source"})
        created = await ensure_indexes(client=client, collection="odin_intel")

        assert set(created) == {"telegram_channel", "notebook_id"}
        for call in client.create_payload_index.await_args_list:
            assert call.kwargs["wait"] is True
            assert call.kwargs["field_schema"] == "keyword"

    async def test_idempotent_second_run_noop(self):
        from scripts.ensure_payload_indexes import ensure_indexes

        client = self._client(existing={"source", "telegram_channel", "notebook_id"})
        created = await ensure_indexes(client=client, collection="odin_intel")

        assert created == []
        client.create_payload_index.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ensure_payload_indexes.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

First add the central field contract to `rag/qdrant_schema.py` (single source of truth, imported by both the migration script and the Task 10 startup validator). Append it and add it to `__all__`:

```python
REQUIRED_PAYLOAD_INDEXES = ("source", "telegram_channel", "notebook_id")
```

Then create `scripts/__init__.py` (empty, if it does not exist) and `scripts/ensure_payload_indexes.py`:

```python
"""Idempotent migration: create keyword payload indexes required by the
read-corpus filter. Run once before relying on filtered search — Qdrant needs an
HNSW rebuild to fully use filter-aware links for indexes added after points
exist. Safe to re-run.

Usage:  uv run python -m scripts.ensure_payload_indexes
"""
from __future__ import annotations

import asyncio

import structlog

from config import settings
from rag.qdrant_schema import REQUIRED_PAYLOAD_INDEXES

log = structlog.get_logger(__name__)


async def ensure_indexes(*, client=None, collection: str | None = None) -> list[str]:
    own_client = client is None
    if own_client:
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(url=settings.qdrant_url)
    collection = collection or settings.qdrant_collection
    try:
        info = await client.get_collection(collection)
        existing = set((info.payload_schema or {}).keys())
        created: list[str] = []
        for field in REQUIRED_PAYLOAD_INDEXES:
            if field in existing:
                continue
            await client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema="keyword",
                wait=True,
            )
            created.append(field)
        log.info("payload_indexes_ensured", created=created,
                 already_present=sorted(existing & set(REQUIRED_PAYLOAD_INDEXES)))
        return created
    finally:
        if own_client:
            await client.close()


if __name__ == "__main__":
    print(asyncio.run(ensure_indexes()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ensure_payload_indexes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/qdrant_schema.py scripts/__init__.py scripts/ensure_payload_indexes.py tests/test_ensure_payload_indexes.py
git commit -m "feat(intelligence): idempotent payload-index migration + central REQUIRED_PAYLOAD_INDEXES"
```

---

## Task 10: Startup validates index presence (warn, no mutation)

**Depends on:** Task 9 (`REQUIRED_PAYLOAD_INDEXES` lives in `qdrant_schema`).

**Files:**
- Modify: `rag/qdrant_schema.py` (add `missing_payload_indexes`, reusing Task 9's `REQUIRED_PAYLOAD_INDEXES`)
- Modify: `rag/retriever.py` (`_ensure_schema_validated` ~line 44-67) — warn on missing, **never mutate**
- Test: `tests/test_qdrant_schema.py`, `tests/test_hybrid_retriever.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_qdrant_schema.py` (create with `from rag.qdrant_schema import ...` if absent):

```python
from types import SimpleNamespace
from rag.qdrant_schema import missing_payload_indexes


class TestMissingPayloadIndexes:
    def test_reports_missing(self):
        info = SimpleNamespace(payload_schema={"source": object()})
        assert set(missing_payload_indexes(info)) == {"telegram_channel", "notebook_id"}

    def test_none_missing(self):
        info = SimpleNamespace(
            payload_schema={"source": 1, "telegram_channel": 1, "notebook_id": 1}
        )
        assert missing_payload_indexes(info) == []

    def test_handles_absent_schema(self):
        info = SimpleNamespace(payload_schema=None)
        assert set(missing_payload_indexes(info)) == {"source", "telegram_channel", "notebook_id"}
```

Also append the **startup-is-read-only** preflight test to `tests/test_hybrid_retriever.py`:

```python
class TestStartupIndexPreflight:
    async def test_startup_warns_missing_indexes_and_never_mutates(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        import rag.retriever as retr

        client = SimpleNamespace(
            get_collections=AsyncMock(return_value=SimpleNamespace(
                collections=[SimpleNamespace(name=retr.settings.qdrant_collection)])),
            get_collection=AsyncMock(return_value=SimpleNamespace(
                payload_schema={"source": 1})),   # telegram_channel + notebook_id missing
            create_payload_index=AsyncMock(),
            close=AsyncMock(),
        )
        retr._schema_validated = False
        with patch("rag.retriever.AsyncQdrantClient", return_value=client), \
             patch("rag.retriever.validate_collection_schema"), \
             patch.object(retr.logger, "warning") as warn:
            await retr._ensure_schema_validated()

        client.create_payload_index.assert_not_called()   # startup is read-only
        assert any(c.args[:1] == ("payload_indexes_missing",) for c in warn.call_args_list)
        retr._schema_validated = False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_qdrant_schema.py::TestMissingPayloadIndexes tests/test_hybrid_retriever.py::TestStartupIndexPreflight -q`
Expected: FAIL — `missing_payload_indexes` undefined / no `payload_indexes_missing` warning yet.

- [ ] **Step 3: Write minimal implementation**

In `rag/qdrant_schema.py` — `REQUIRED_PAYLOAD_INDEXES` was already added in Task 9 — add `missing_payload_indexes` to `__all__` and define:

```python
def missing_payload_indexes(info) -> list[str]:
    """Return required payload-index fields absent from the collection.
    Read-only: callers warn; the migration script (scripts/ensure_payload_indexes)
    is the only writer."""
    existing = set((getattr(info, "payload_schema", None) or {}).keys())
    return [f for f in REQUIRED_PAYLOAD_INDEXES if f not in existing]
```

In `rag/retriever.py`, import it and warn inside `_ensure_schema_validated` after the `validate_collection_schema(...)` call:

```python
from rag.qdrant_schema import (
    QdrantSchemaMismatch,
    missing_payload_indexes,
    validate_collection_schema,
)
```

```python
            if settings.qdrant_collection in names:
                info = await client.get_collection(settings.qdrant_collection)
                validate_collection_schema(info, enable_hybrid=settings.enable_hybrid)
                missing = missing_payload_indexes(info)
                if missing:
                    logger.warning(
                        "payload_indexes_missing",
                        fields=missing,
                        hint="run: uv run python -m scripts.ensure_payload_indexes",
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_qdrant_schema.py tests/test_hybrid_retriever.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rag/qdrant_schema.py rag/retriever.py tests/test_qdrant_schema.py tests/test_hybrid_retriever.py
git commit -m "feat(intelligence): startup warns on missing payload indexes (no mutation)"
```

---

## Task 11: Before/after measurement harness (six fixed queries)

**Files:**
- Create: `scripts/measure_corpus_scoping.py`
- Test: `tests/test_measure_corpus_scoping.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_measure_corpus_scoping.py`:

```python
class TestFormatRow:
    def test_format_top5_row(self):
        from scripts.measure_corpus_scoping import format_hits

        hits = [
            {"source": "rss", "feed_name": "CSIS", "tier_score": 0.91},
            {"source": "gdelt_gkg", "title": "gdelt:gkg:1"},
        ]
        line = format_hits(hits)
        assert "rss:CSIS" in line
        assert "gdelt_gkg" in line

    def test_queries_constant(self):
        from scripts.measure_corpus_scoping import QUERIES
        assert len(QUERIES) == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_measure_corpus_scoping.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/measure_corpus_scoping.py`:

```python
"""Read-only before/after measurement for the corpus-scoping slice.

Runs six fixed queries against live Qdrant and prints the top-5 source mix
BEFORE (the prior product path: enhanced_search, no scoping) vs AFTER (two-lane
scoped + tier-boost), with source, provider and raw/norm/final scores. Paste the
table into the PR to evidence AC-1/AC-2. Not a CI gate (live-data dependent).

Usage:  uv run python -m scripts.measure_corpus_scoping
"""
from __future__ import annotations

import asyncio

QUERIES = [
    "Bundeswehr Beschaffung",
    "Russia shadow fleet",
    "Taiwan strait tensions",
    "NATO eastern flank posture",
    "Iran proxy escalation",
    "Sahel coup instability",
]


def _label(hit: dict) -> str:
    src = hit.get("source", "?")
    name = hit.get("feed_name") or hit.get("telegram_channel") or hit.get("source_name")
    return f"{src}:{name}" if name else src


def _scores(hit: dict) -> str:
    raw = hit.get("tier_raw", hit.get("rerank_score", hit.get("score")))
    norm = hit.get("tier_norm")
    final = hit.get("tier_score")
    parts = []
    if raw is not None:
        parts.append(f"raw={raw:.3f}")
    if norm is not None:
        parts.append(f"norm={norm:.3f}")
    if final is not None:
        parts.append(f"final={final:.3f}")
    return f"({','.join(parts)})" if parts else ""


def format_hits(hits: list[dict]) -> str:
    """One line: `source:provider(raw=…,norm=…,final=…)` per hit."""
    return " | ".join(f"{_label(h)}{_scores(h)}" for h in hits)


async def _run() -> None:
    from rag.corpus_policy import (
        ANALYSIS_POOL, FINAL_K, REALTIME_POOL, RT_SCORE_THRESHOLD,
        analysis_filter, apply_tier_boost, merge_lanes, realtime_filter, validate_lane,
    )
    from rag.retriever import enhanced_search

    for q in QUERIES:
        # BEFORE = the prior product path (dense + rerank, NO scoping/tier-boost).
        before = await enhanced_search(q, limit=FINAL_K, enable_graph_context=False)
        analysis = await enhanced_search(
            q, limit=FINAL_K, pool=ANALYSIS_POOL, query_filter=analysis_filter(),
            post_rerank=apply_tier_boost, enable_graph_context=False,
        )
        realtime = await enhanced_search(
            q, limit=1, pool=REALTIME_POOL, query_filter=realtime_filter(),
            post_rerank=apply_tier_boost, score_threshold=RT_SCORE_THRESHOLD,
            enable_graph_context=False,
        )
        after = merge_lanes(validate_lane(analysis, "analysis"),
                            validate_lane(realtime, "realtime"))
        print(f"\n### {q}")
        print(f"BEFORE: {format_hits(before)}")
        print(f"AFTER : {format_hits(after)}")


if __name__ == "__main__":
    asyncio.run(_run())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_measure_corpus_scoping.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/measure_corpus_scoping.py tests/test_measure_corpus_scoping.py
git commit -m "feat(intelligence): corpus-scoping measurement harness (6 fixed queries)"
```

---

## Final verification (after all tasks)

- [ ] **Full suite green:** `uv run pytest -q` → expect `0 failures` (235 baseline + new tests).
- [ ] **Lint:** `uv run ruff check rag/ agents/ scripts/ tests/` → 0 findings.
- [ ] **Run the index migration once (live Qdrant up):** `uv run python -m scripts.ensure_payload_indexes` → prints created fields (or `[]` on a re-run).
- [ ] **Run the measurement harness (live Qdrant up):** `uv run python -m scripts.measure_corpus_scoping` → capture the BEFORE/AFTER table for the PR.
- [ ] **AC check against the spec §11:** AC-1 (analysis surfaced), AC-2 (no gkg/firms/unvetted-telegram — two barriers), AC-3 (≤1 realtime, marked), AC-4 (tier-boost ordering tests green), AC-5 (suite green).

## Notes for the implementer
- `asyncio_mode=auto` — async test functions need no decorator.
- Patch `rag.retriever.search` (not `enhanced_search`) when testing the retriever; patch `agents.tools.qdrant_search.enhanced_search` (two lanes → `AsyncMock(side_effect=[analysis, realtime])`) when testing the tool.
- `credibility_score` is fail-fast on unknown `source_type` — keep new sources out of the analysis lane unless you also extend `evidence._legacy_provenance` (a documented follow-up, not this slice).
- Do NOT relabel existing points or touch the write path — this slice is read-only by contract.
