# Minimal Viable Evidence (Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ODIN's synthesis step real source criticism — canonical provenance facts on every new Qdrant point, a read-side normalization adapter + central credibility policy, and an evidence pack that carries provider/credibility/date into synthesis — while the `/query` API boundary stays `sources_used: list[str]` (now deduplicated provider IDs instead of tool names).

**Architecture:** Facts/policy split. Write side (data-ingestion) stamps `source_type`/`provider`/`published_at` into Qdrant payloads via a shared local helper. Read side (intelligence) normalizes heterogeneous payloads to `EvidenceItem`/`SourceRef`, derives `credibility_score` from a central provider registry, serializes a lossless `[EVIDENCE] <json>` pack consumed by `qdrant_search`/`gdelt_query`/`rss_fetch`, and the workflow parses those blocks into deduplicated provider IDs. No backfill, no corroboration, no API/frontend type changes.

**Tech Stack:** Python 3.12, Pydantic v2, LangChain tools, qdrant-client, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-05-31-minimal-viable-evidence-design.md` (commit `0066b5e`).

**Branch:** `feature/TASK-014c-evidence-contract`.

**HARD guardrails (do not violate):**
1. Slice 1 ends at `/query` with `sources_used: list[str]` = deduplicated provider IDs in evidence order. No `list[SourceRef]` crosses the API.
2. Backend and frontend stay UNCHANGED. The `[:6]` cap in `services/backend/app/routers/intel.py:106` is preserved (it keeps working because `sources_used` stays `list[str]`).
3. Strict TDD: red → green → refactor. No skipped tests. No LLM-generated Cypher. No writes on the read path.

---

## File Structure

**New files:**
- `contracts/qdrant-provenance-v1.json` — language-neutral write contract (single reference).
- `services/data-ingestion/feeds/provenance.py` — shared write-side helper (facts only).
- `services/intelligence/rag/evidence.py` — `SourceRef`/`EvidenceItem` models, read-side adapter, `[EVIDENCE]` serializer + parser.
- `services/intelligence/rag/credibility.py` — read-side credibility policy registry.

**Modified (write side, data-ingestion):** `feeds/base.py`, `feeds/firms_collector.py`, `feeds/usgs_collector.py`, `feeds/ucdp_collector.py`, `feeds/ofac_collector.py`, `feeds/hapi_collector.py`, `feeds/noaa_nhc_collector.py`, `feeds/portwatch_collector.py`, `feeds/eonet_collector.py`, `feeds/gdacs_collector.py`, `feeds/rss_collector.py`, `feeds/telegram_collector.py`, `gdelt_raw/writers/qdrant_writer.py`, `nlm_ingest/ingest_qdrant.py`.

**Modified (read side, intelligence):** `agents/tools/qdrant_search.py`, `agents/tools/gdelt_query.py`, `agents/tools/rss_fetch.py`, `graph/workflow.py`, `graph/nodes.py`, `agents/synthesis_agent.py`.

**Build order:** Phase 1 (contract + policy + models) → Phase 2 (adapter + serializer + parser) → Phase 3 (tool wiring) → Phase 4 (workflow + synthesis) → Phase 5 (write side). Read side is testable with synthetic payload dicts, so it does not depend on Phase 5.

**Canonical provider IDs (single source of truth, used across the plan):**
| source key | source_type | provider |
|---|---|---|
| firms | dataset | firms.modaps.eosdis.nasa.gov |
| usgs | dataset | usgs.gov |
| ucdp | dataset | ucdp.uu.se |
| ofac | dataset | ofac.treasury.gov |
| hapi | dataset | hapi.humdata.org |
| noaa_nhc | dataset | nhc.noaa.gov |
| portwatch | dataset | portwatch.imf.org |
| eonet | dataset | eonet.gsfc.nasa.gov |
| gdacs | dataset | gdacs.org |
| gdelt_gkg | gdelt | (origin domain, else `gdelt`) |
| rss | rss | (per-feed canonical domain) |
| telegram | telegram | `telegram:<handle>` |
| nlm | notebooklm | `notebooklm:<notebook_id>` |

---

## Phase 1 — Contract, Policy, Models

### Task 1: Language-neutral write contract + contract tests in both services

**Files:**
- Create: `contracts/qdrant-provenance-v1.json`
- Test: `services/intelligence/tests/test_provenance_contract.py`
- Test: `services/data-ingestion/tests/test_provenance_contract.py`

- [ ] **Step 1: Write the failing contract test (intelligence)**

`services/intelligence/tests/test_provenance_contract.py`:
```python
"""The intelligence read-side must agree with the shared provenance contract."""
from __future__ import annotations

import json
from pathlib import Path

_CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts" / "qdrant-provenance-v1.json"
)


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_contract_file_exists_and_is_versioned():
    data = _load()
    assert data["contract_version"] == 1


def test_required_and_optional_fields():
    data = _load()
    assert data["required"] == ["source_type", "provider", "ingested_at"]
    assert data["optional"] == ["published_at"]


def test_write_source_types_do_not_include_unknown():
    data = _load()
    assert "unknown" not in data["source_types"]
    assert set(data["source_types"]) == {
        "rss", "telegram", "gdelt", "notebooklm", "dataset",
    }
```

- [ ] **Step 2: Run it — verify it FAILS**

Run: `cd services/intelligence && uv run pytest tests/test_provenance_contract.py -v`
Expected: FAIL with `FileNotFoundError` (contract file does not exist yet). If the path `parents[3]` does not resolve to the repo root, fix it so it points at repo-root `contracts/`.

- [ ] **Step 3: Create the contract file (green)**

`contracts/qdrant-provenance-v1.json`:
```json
{
  "contract_version": 1,
  "required": ["source_type", "provider", "ingested_at"],
  "optional": ["published_at"],
  "source_types": ["rss", "telegram", "gdelt", "notebooklm", "dataset"]
}
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_provenance_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Mirror the test in data-ingestion + run**

`services/data-ingestion/tests/test_provenance_contract.py`: identical content to Step 1 (the path resolves the same: `Path(__file__).resolve().parents[3] / "contracts" / ...`). Copy verbatim.
Run: `cd services/data-ingestion && uv run pytest tests/test_provenance_contract.py -v`
Expected: PASS (the contract file now exists).

- [ ] **Step 6: Commit**
```bash
git add contracts/qdrant-provenance-v1.json \
  services/intelligence/tests/test_provenance_contract.py \
  services/data-ingestion/tests/test_provenance_contract.py
git commit -m "feat(contract): language-neutral qdrant provenance contract v1 + dual-service tests"
```

---

### Task 2: Credibility registry (intelligence read-side policy)

**Files:**
- Create: `services/intelligence/rag/credibility.py`
- Test: `services/intelligence/tests/test_credibility.py`

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_credibility.py`:
```python
"""Read-side credibility policy: source_type baseline + provider override."""
from __future__ import annotations

import pytest

from rag.credibility import credibility_score, normalize_provider


def test_baseline_per_source_type():
    assert credibility_score("rss", "some-unknown-blog.example") == 0.60
    assert credibility_score("telegram", "telegram:randomchannel") == 0.40
    assert credibility_score("gdelt", "aggregator.example") == 0.50
    assert credibility_score("dataset", "usgs.gov") == 0.80
    assert credibility_score("notebooklm", "notebooklm:nb-1") == 0.60
    assert credibility_score("unknown", "whatever") == 0.30


def test_provider_override_beats_baseline():
    assert credibility_score("rss", "reuters.com") == 0.85
    assert credibility_score("rss", "bbc.com") == 0.80


def test_normalize_provider_is_case_and_scheme_insensitive():
    assert normalize_provider("Reuters.com") == "reuters.com"
    assert normalize_provider("https://reuters.com/world") == "reuters.com"
    assert normalize_provider("  bbc.com/news  ") == "bbc.com"
    assert normalize_provider("telegram:Rybar") == "telegram:rybar"


def test_unknown_source_type_raises():
    with pytest.raises(KeyError):
        credibility_score("not-a-type", "x")
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_credibility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.credibility'`.

- [ ] **Step 3: Implement**

`services/intelligence/rag/credibility.py`:
```python
"""Read-side credibility policy.

Quellenverlässlichkeit (NICHT Aussagewahrheit). Zentrale, prüfbare Stelle.
source_type-Baseline + kurze, begründete Provider-Overrides.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Baseline reliability per source_type. notebooklm/gdelt are NOT primary sources.
TYPE_BASELINES: dict[str, float] = {
    "rss": 0.60,
    "telegram": 0.40,
    "gdelt": 0.50,        # aggregator/discovery path, not a publisher
    "dataset": 0.80,
    "notebooklm": 0.60,   # transformation path, conservative
    "unknown": 0.30,      # read-only legacy fallback
}

# Keep short. Every entry needs a one-line justification and a test.
PROVIDER_OVERRIDES: dict[str, float] = {
    "reuters.com": 0.85,  # international wire, strong editorial standards
    "bbc.com": 0.80,      # public broadcaster, strong editorial standards
}


def normalize_provider(provider: str) -> str:
    """Canonicalize a provider id for registry lookup.

    Lowercase; strip scheme/path; keep `telegram:<handle>` / `notebooklm:<id>`
    namespaced ids intact (only lowercased).
    """
    p = (provider or "").strip().lower()
    if ":" in p and not p.startswith(("http://", "https://")):
        # namespaced id like telegram:rybar — keep as-is
        return p
    if p.startswith(("http://", "https://")):
        p = urlparse(p).netloc or p
    # drop any path that slipped through (e.g. "bbc.com/news")
    return p.split("/", 1)[0]


def credibility_score(source_type: str, provider: str) -> float:
    """Provider override if present, else the source_type baseline.

    Raises KeyError if source_type is not a known baseline (fail-fast).
    """
    key = normalize_provider(provider)
    if key in PROVIDER_OVERRIDES:
        return PROVIDER_OVERRIDES[key]
    return TYPE_BASELINES[source_type]
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_credibility.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/rag/credibility.py services/intelligence/tests/test_credibility.py
git commit -m "feat(intelligence): central read-side credibility registry"
```

---

### Task 3: `SourceRef` and `EvidenceItem` models

**Files:**
- Create: `services/intelligence/rag/evidence.py`
- Test: `services/intelligence/tests/test_evidence_models.py`

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_evidence_models.py`:
```python
"""SourceRef / EvidenceItem model contract."""
from __future__ import annotations

from datetime import UTC, datetime

from rag.evidence import EvidenceItem, SourceRef


def test_sourceref_defaults():
    ref = SourceRef(
        source_ref_id="abc123",
        source_type="rss",
        provider="reuters.com",
    )
    assert ref.display_name is None
    assert ref.url is None
    assert ref.published_at is None
    assert ref.credibility_score == 0.5  # filled later by the adapter
    assert ref.provenance_inferred is False


def test_sourceref_accepts_unknown_read_only_type():
    ref = SourceRef(source_ref_id="x", source_type="unknown", provider="?")
    assert ref.source_type == "unknown"


def test_evidence_item_holds_source_and_text():
    ref = SourceRef(source_ref_id="x", source_type="rss", provider="bbc.com")
    item = EvidenceItem(
        source=ref,
        title="Headline",
        excerpt="body text",
        relevance_score=0.82,
        content_hash="deadbeef",
    )
    assert item.source.provider == "bbc.com"
    assert item.content_hash == "deadbeef"
    # published_at round-trips as datetime
    ref2 = SourceRef(
        source_ref_id="y", source_type="rss", provider="bbc.com",
        published_at=datetime(2026, 5, 31, 8, 0, tzinfo=UTC),
    )
    assert ref2.published_at.year == 2026
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.evidence'`.

- [ ] **Step 3: Implement (models only — adapter/serializer added in later tasks)**

`services/intelligence/rag/evidence.py`:
```python
"""Read-side evidence layer: models, normalization adapter, [EVIDENCE] codec.

This module is internal to the intelligence service. SourceRef objects are NEVER
serialized across the /query API boundary (Slice 1 keeps sources_used: list[str]).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["rss", "telegram", "gdelt", "notebooklm", "dataset", "unknown"]


class SourceRef(BaseModel):
    source_ref_id: str
    source_type: SourceType
    provider: str                       # canonical id
    display_name: str | None = None     # not scoring-relevant
    url: str | None = None
    published_at: datetime | None = None
    credibility_score: float = 0.5      # filled read-side from the registry
    provenance_inferred: bool = False


class EvidenceItem(BaseModel):
    source: SourceRef
    title: str
    excerpt: str
    relevance_score: float
    content_hash: str | None = None     # for dedup only, not public provenance
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/rag/evidence.py services/intelligence/tests/test_evidence_models.py
git commit -m "feat(intelligence): SourceRef and EvidenceItem models"
```

---

## Phase 2 — Adapter, source_ref_id, Serializer, Parser

### Task 4: `source_ref_id` deterministic identity

**Files:**
- Modify: `services/intelligence/rag/evidence.py`
- Test: `services/intelligence/tests/test_source_ref_id.py`

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_source_ref_id.py`:
```python
from __future__ import annotations

from rag.evidence import compute_source_ref_id


def test_external_key_wins_and_is_stable():
    a = compute_source_ref_id(
        source_type="gdelt", provider="reuters.com",
        external_key="doc-123", url="https://x", content_hash="h", title="t", excerpt="e",
    )
    b = compute_source_ref_id(
        source_type="gdelt", provider="reuters.com",
        external_key="doc-123", url="https://other", content_hash="h2", title="t2", excerpt="e2",
    )
    assert a == b  # identity is the external key; other fields don't change it
    assert len(a) == 20


def test_falls_back_to_url_then_hash_then_title_excerpt():
    by_url = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url="https://bbc.com/a", content_hash=None, title="t", excerpt="e",
    )
    by_hash = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url=None, content_hash="abc", title="t", excerpt="e",
    )
    by_text = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url=None, content_hash=None, title="t", excerpt="e",
    )
    assert len({by_url, by_hash, by_text}) == 3
    assert all(len(x) == 20 for x in (by_url, by_hash, by_text))


def test_provider_is_normalized_into_identity():
    upper = compute_source_ref_id(
        source_type="rss", provider="BBC.com",
        external_key=None, url="https://bbc.com/a", content_hash=None, title="t", excerpt="e",
    )
    lower = compute_source_ref_id(
        source_type="rss", provider="bbc.com",
        external_key=None, url="https://bbc.com/a", content_hash=None, title="t", excerpt="e",
    )
    assert upper == lower
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_source_ref_id.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_source_ref_id'`.

- [ ] **Step 3: Implement — add to `rag/evidence.py`**

Add these imports at the top of `rag/evidence.py`:
```python
import hashlib
```
Add this import from the registry:
```python
from rag.credibility import normalize_provider
```
Add the function:
```python
def compute_source_ref_id(
    *,
    source_type: str,
    provider: str,
    external_key: str | None,
    url: str | None,
    content_hash: str | None,
    title: str,
    excerpt: str,
) -> str:
    """Deterministic 20-char id. Identity = first non-empty of:
    external_key -> url -> content_hash -> normalized(title + excerpt)."""
    if external_key:
        kind, value = "ext", external_key
    elif url:
        kind, value = "url", url.strip()
    elif content_hash:
        kind, value = "hash", content_hash
    else:
        kind = "text"
        value = " ".join((title or "").split()) + "\x1f" + " ".join((excerpt or "").split())
    raw = "\x00".join(
        ["source-ref-v1", source_type, normalize_provider(provider), kind, value]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_source_ref_id.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/rag/evidence.py services/intelligence/tests/test_source_ref_id.py
git commit -m "feat(intelligence): deterministic source_ref_id"
```

---

### Task 5: Normalization adapter (canonical → legacy → unknown)

**Files:**
- Modify: `services/intelligence/rag/evidence.py`
- Test: `services/intelligence/tests/test_evidence_adapter.py`

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_evidence_adapter.py`:
```python
"""Adapter: retriever dict -> EvidenceItem. Canonical first, then legacy, then unknown."""
from __future__ import annotations

from rag.evidence import to_evidence_item


def test_canonical_payload_is_read_directly():
    item = to_evidence_item({
        "score": 0.9,
        "source_type": "rss",
        "provider": "reuters.com",
        "title": "Tanker seized",
        "content": "full body",
        "url": "https://reuters.com/a",
        "published_at": "2026-05-31T08:00:00+00:00",
        "content_hash": "h1",
    })
    assert item.source.source_type == "rss"
    assert item.source.provider == "reuters.com"
    assert item.source.provenance_inferred is False
    assert item.source.credibility_score == 0.85  # override
    assert item.excerpt == "full body"
    assert item.source.published_at is not None


def test_legacy_nlm_shape_is_inferred():
    item = to_evidence_item({
        "score": 0.7,
        "source": "unknown",
        "notebook_id": "nb-7",
        "source_kind": "report",
        "source_id": "rpt-3",
        "title": "Notebook claim",
        "content": "claim text",
    })
    assert item.source.source_type == "notebooklm"
    assert item.source.provenance_inferred is True
    assert item.source.provider.startswith("notebooklm:")


def test_legacy_rss_shape_is_inferred():
    item = to_evidence_item({
        "score": 0.6, "source": "rss", "feed_name": "BBC World",
        "title": "x", "summary": "sum", "url": "https://bbc.com/x",
        "published": "2026-05-30T00:00:00+00:00",
    })
    assert item.source.source_type == "rss"
    assert item.source.provenance_inferred is True


def test_unmatched_shape_is_unknown_not_guessed():
    item = to_evidence_item({"score": 0.4, "title": "mystery", "content": "?"})
    assert item.source.source_type == "unknown"
    assert item.source.provenance_inferred is True
    assert item.source.credibility_score == 0.30


def test_excerpt_priority_and_700_cap():
    item = to_evidence_item({
        "score": 0.5, "source_type": "dataset", "provider": "usgs.gov",
        "summary": "s" * 1000, "title": "t",
    })
    assert item.excerpt == "s" * 700  # content missing -> summary, capped at 700


def test_event_time_is_not_published_at():
    item = to_evidence_item({
        "score": 0.5, "source_type": "dataset", "provider": "usgs.gov",
        "title": "quake", "content": "m6", "event_time": "2026-05-31T00:00:00+00:00",
    })
    assert item.source.published_at is None  # event_time != published_at
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_adapter.py -v`
Expected: FAIL with `ImportError: cannot import name 'to_evidence_item'`.

- [ ] **Step 3: Implement — add to `rag/evidence.py`**

Add import:
```python
from rag.credibility import credibility_score
```
(Keep the existing `from rag.credibility import normalize_provider`; you may combine: `from rag.credibility import credibility_score, normalize_provider`.)

Add the constants and adapter:
```python
EXCERPT_MAX_CHARS = 700

# Event/observation timestamps that must NEVER be reinterpreted as published_at.
_EVENT_TIME_KEYS = (
    "event_time", "event_date", "date_start", "from_date", "acq_date",
    "seendate", "gdelt_date",
)


def _excerpt(payload: dict) -> str:
    for key in ("content", "summary", "description", "title"):
        val = payload.get(key)
        if val:
            return str(val)[:EXCERPT_MAX_CHARS]
    return ""


def _parse_dt(value):
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _canonical_provenance(payload: dict) -> tuple[str, str, str | None, bool] | None:
    """Return (source_type, provider, published_at_raw, inferred=False) if the
    payload already carries canonical contract fields, else None."""
    st = payload.get("source_type")
    pv = payload.get("provider")
    if st and pv:
        return str(st), str(pv), payload.get("published_at"), False
    return None


def _legacy_provenance(payload: dict) -> tuple[str, str, str | None]:
    """Small explicit legacy matchers. Returns (source_type, provider, published_raw).
    Anything unmatched -> ('unknown', '?', None). Never guesses."""
    src = str(payload.get("source", "")).lower()
    if "notebook_id" in payload:
        nb = payload.get("notebook_id", "")
        return "notebooklm", f"notebooklm:{nb}", None
    if "telegram_channel" in payload or src == "telegram":
        handle = str(payload.get("telegram_channel", "")).lstrip("@").lower()
        return "telegram", f"telegram:{handle}" if handle else "telegram", payload.get("published")
    if src == "rss":
        # legacy rss: published carries publication time
        prov = str(payload.get("feed_name") or payload.get("provider") or "rss").lower()
        return "rss", prov, payload.get("published")
    if src in ("gdelt", "gdelt_gkg"):
        return "gdelt", str(payload.get("source_name") or "gdelt").lower(), None
    return "unknown", "?", None


def to_evidence_item(result: dict) -> EvidenceItem:
    """Normalize one retriever result dict into an EvidenceItem.

    Order: canonical contract fields -> small explicit legacy matchers -> unknown.
    """
    canonical = _canonical_provenance(result)
    if canonical is not None:
        source_type, provider, published_raw, inferred = canonical
    else:
        source_type, provider, published_raw = _legacy_provenance(result)
        inferred = True

    # published_at is only ever the publication time. Never an event/observation time.
    published_at = _parse_dt(published_raw) if published_raw else None

    external_key = (
        result.get("doc_id")
        or (f"{result.get('telegram_channel')}:{result.get('telegram_message_id')}"
            if result.get("telegram_message_id") is not None else None)
        or (f"{result.get('notebook_id')}:{result.get('source_kind')}:{result.get('source_id')}"
            if result.get("notebook_id") else None)
        or result.get("ucdp_id")
    )
    title = str(result.get("title", "Untitled"))
    excerpt = _excerpt(result)
    content_hash = result.get("content_hash")
    url = result.get("url")

    source_ref_id = compute_source_ref_id(
        source_type=source_type, provider=provider,
        external_key=str(external_key) if external_key else None,
        url=url, content_hash=content_hash, title=title, excerpt=excerpt,
    )

    ref = SourceRef(
        source_ref_id=source_ref_id,
        source_type=source_type,
        provider=normalize_provider(provider),
        display_name=result.get("source_name") or result.get("feed_name"),
        url=url,
        published_at=published_at,
        credibility_score=credibility_score(source_type, provider),
        provenance_inferred=inferred,
    )
    return EvidenceItem(
        source=ref,
        title=title,
        excerpt=excerpt,
        relevance_score=float(result.get("score", 0.0)),
        content_hash=str(content_hash) if content_hash else None,
    )
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_adapter.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/rag/evidence.py services/intelligence/tests/test_evidence_adapter.py
git commit -m "feat(intelligence): evidence normalization adapter (canonical/legacy/unknown)"
```

---

### Task 6: Lossless `[EVIDENCE] <json>` serializer + budgeting + parser

**Files:**
- Modify: `services/intelligence/rag/evidence.py`
- Test: `services/intelligence/tests/test_evidence_codec.py`

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_evidence_codec.py`:
```python
"""Serializer (budgeted, no broken blocks) + lossless parser round-trip."""
from __future__ import annotations

from datetime import UTC, datetime

from rag.evidence import (
    EvidenceItem,
    SourceRef,
    format_evidence_pack,
    parse_evidence_refs,
)


def _item(i: int, prov: str, score: float) -> EvidenceItem:
    return EvidenceItem(
        source=SourceRef(
            source_ref_id=f"id{i}", source_type="rss", provider=prov,
            display_name="D", url=f"https://{prov}/{i}",
            published_at=datetime(2026, 5, 31, 8, tzinfo=UTC),
            credibility_score=0.85, provenance_inferred=False,
        ),
        title=f"Title {i}", excerpt=f"Body {i}", relevance_score=score,
        content_hash=f"h{i}",
    )


def test_pack_sorted_by_relevance_and_parsable():
    pack = format_evidence_pack(
        [_item(1, "bbc.com", 0.5), _item(2, "reuters.com", 0.9)],
        budget=10_000,
    )
    # higher relevance first
    assert pack.index("reuters.com") < pack.index("bbc.com")
    refs = parse_evidence_refs(pack)
    assert [r.provider for r in refs] == ["reuters.com", "bbc.com"]
    assert refs[0].source_ref_id == "id2"
    assert refs[0].credibility_score == 0.85
    assert refs[0].published_at is not None


def test_budget_never_emits_a_partial_block():
    items = [_item(i, "bbc.com", 1.0 - i * 0.01) for i in range(20)]
    pack = format_evidence_pack(items, budget=400)
    # whatever fit, every [EVIDENCE] line must have a complete json object
    refs = parse_evidence_refs(pack)
    assert len(refs) >= 1
    assert "[EVIDENCE]" in pack
    # strict no-partial-block check: every [EVIDENCE] header line parses to a ref,
    # so the count of header lines equals the count of reconstructed refs.
    headers = [ln for ln in pack.splitlines() if ln.startswith("[EVIDENCE] ")]
    assert len(headers) == len(refs)


def test_dedup_by_content_hash_then_ref_id():
    a = _item(1, "bbc.com", 0.9)
    b = _item(1, "bbc.com", 0.8)  # same content_hash h1 -> dropped
    pack = format_evidence_pack([a, b], budget=10_000)
    assert pack.count("[EVIDENCE]") == 1


def test_parser_ignores_non_evidence_lines():
    refs = parse_evidence_refs("noise\n[Graph Context]\nblah\n")
    assert refs == []
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_codec.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_evidence_pack'`.

- [ ] **Step 3: Implement — add to `rag/evidence.py`**

Add import:
```python
import json
```
Add the codec:
```python
_EVIDENCE_PREFIX = "[EVIDENCE] "


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
    header = _EVIDENCE_PREFIX + json.dumps(meta, sort_keys=True, separators=(",", ":"))
    return f"{header}\nTitle: {item.title}\nExcerpt: {item.excerpt}"


def format_evidence_pack(items: list[EvidenceItem], *, budget: int) -> str:
    """Deterministic, budgeted pack. Sorted by relevance desc, deduped, and a
    block is only appended if it fits whole — never a partial/truncated block."""
    ordered = sorted(items, key=lambda it: it.relevance_score, reverse=True)
    seen: set[str] = set()
    blocks: list[str] = []
    used = 0
    for it in ordered:
        key = it.content_hash or it.source.source_ref_id
        if key in seen:
            continue
        block = _block(it)
        add = len(block) + (2 if blocks else 0)  # "\n\n" separator
        if used + add > budget:
            continue  # try the next (smaller) block; never truncate
        seen.add(key)
        blocks.append(block)
        used += add
    return "\n\n".join(blocks)


def parse_evidence_refs(text: str) -> list[SourceRef]:
    """Reconstruct SourceRef from every complete [EVIDENCE] <json> line.
    Lines that don't parse are ignored. Order preserved."""
    refs: list[SourceRef] = []
    for line in text.splitlines():
        if not line.startswith(_EVIDENCE_PREFIX):
            continue
        try:
            meta = json.loads(line[len(_EVIDENCE_PREFIX):])
        except (ValueError, json.JSONDecodeError):
            continue
        try:
            refs.append(SourceRef(
                source_ref_id=meta["source_ref_id"],
                source_type=meta["source_type"],
                provider=meta["provider"],
                display_name=meta.get("display_name"),
                url=meta.get("url"),
                published_at=_parse_dt(meta.get("published_at")),
                credibility_score=meta.get("credibility_score", 0.5),
                provenance_inferred=meta.get("provenance_inferred", False),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return refs
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_codec.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor check + full read-side suite**

Run: `cd services/intelligence && uv run pytest tests/test_evidence_models.py tests/test_evidence_adapter.py tests/test_evidence_codec.py tests/test_source_ref_id.py tests/test_credibility.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**
```bash
git add services/intelligence/rag/evidence.py services/intelligence/tests/test_evidence_codec.py
git commit -m "feat(intelligence): lossless [EVIDENCE] serializer with whole-block budgeting + parser"
```

---

## Phase 3 — Tool Wiring (Live + Qdrant)

### Task 7: `qdrant_search` emits evidence pack; budget 3500→6500; excerpt 700

**Files:**
- Modify: `services/intelligence/agents/tools/qdrant_search.py`
- Test: `services/intelligence/tests/test_qdrant_search_tool.py` (extend existing)

- [ ] **Step 1: Write the failing test (append to existing test class)**

Add to `services/intelligence/tests/test_qdrant_search_tool.py`:
```python
    @pytest.mark.asyncio
    async def test_emits_parsable_evidence_blocks_with_provider(self):
        from rag.evidence import parse_evidence_refs
        results = [
            {
                "score": 0.9, "source_type": "rss", "provider": "reuters.com",
                "title": "Tanker seized", "content": "body " * 50,
                "url": "https://reuters.com/a", "content_hash": "h1",
            },
            {
                "score": 0.8, "source_type": "dataset", "provider": "usgs.gov",
                "title": "Quake", "content": "m6 " * 50, "content_hash": "h2",
            },
        ]
        from unittest.mock import AsyncMock, patch
        with patch(
            "agents.tools.qdrant_search.enhanced_search",
            AsyncMock(return_value=results),
        ):
            out = await qdrant_search.ainvoke({"query": "baltic tanker"})
        refs = parse_evidence_refs(out)
        assert {r.provider for r in refs} == {"reuters.com", "usgs.gov"}
        assert refs[0].provider == "reuters.com"  # higher score first
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_qdrant_search_tool.py::TestQdrantSearchTool::test_emits_parsable_evidence_blocks_with_provider -v`
Expected: FAIL (current tool emits `[Score: ...]` text, not `[EVIDENCE]` blocks).

- [ ] **Step 3: Rewrite the tool body**

Replace the constants and the result-formatting section in `services/intelligence/agents/tools/qdrant_search.py`. Change constant:
```python
TOOL_OUTPUT_MAX_CHARS = 6500
GRAPH_CONTEXT_MAX_CHARS = 1200
```
(Delete `RESULT_CONTENT_MAX_CHARS = 300` — excerpt length now lives in `rag.evidence.EXCERPT_MAX_CHARS = 700`.)

Add import near the top:
```python
from rag.evidence import format_evidence_pack, to_evidence_item
```
Replace the block from `if not results:` through `return _clip_text(output, TOOL_OUTPUT_MAX_CHARS)` with:
```python
        if not results:
            return f"No relevant documents found for: {query}"

        items = [to_evidence_item(r) for r in results]

        # Graph context is deduped and appended AFTER evidence within remaining budget.
        graph_blocks: list[str] = []
        seen_graph: set[str] = set()
        for r in results:
            gctx = r.get("graph_context", "")
            if gctx and gctx not in seen_graph:
                seen_graph.add(gctx)
                graph_blocks.append(_clip_text(str(gctx), GRAPH_CONTEXT_MAX_CHARS))

        graph_text = ""
        if graph_blocks:
            graph_text = "\n---\n[Graph Context]\n" + "\n\n".join(graph_blocks)

        header = f"[Knowledge Base Evidence for: {query}]\n"
        evidence_budget = TOOL_OUTPUT_MAX_CHARS - len(graph_text) - len(header)
        pack = format_evidence_pack(items, budget=max(evidence_budget, 0))
        output = header + pack
        if graph_text and len(output) + len(graph_text) <= TOOL_OUTPUT_MAX_CHARS:
            output += graph_text
        return output
```

- [ ] **Step 4: Run the full file — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_qdrant_search_tool.py -v`
Expected: ALL PASS. The existing `test_dedupes_graph_context_and_caps_output` should still pass (graph context appears once, output bounded). If it asserted the old `[Knowledge Graph Context]` literal count, update it to assert `output.count("[Graph Context]") == 1` and `len(output) <= TOOL_OUTPUT_MAX_CHARS`.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/agents/tools/qdrant_search.py services/intelligence/tests/test_qdrant_search_tool.py
git commit -m "feat(intelligence): qdrant_search emits budgeted [EVIDENCE] pack (budget 6500, excerpt 700)"
```

---

### Task 8: `gdelt_query` emits evidence blocks (live)

**Files:**
- Modify: `services/intelligence/agents/tools/gdelt_query.py`
- Test: `services/intelligence/tests/test_gdelt_query.py` (extend existing)

- [ ] **Step 1: Write the failing test (append)**

Add to `services/intelligence/tests/test_gdelt_query.py`, in `TestGdeltQueryTool`:
```python
    @pytest.mark.asyncio
    async def test_emits_evidence_blocks_seendate_not_published(self):
        from rag.evidence import parse_evidence_refs
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"articles": [{
            "title": "Shipping disruption",
            "url": "https://reuters.com/a",
            "domain": "reuters.com",
            "seendate": "20260423T120000Z",
            "language": "English",
        }]}
        response.headers = {"content-type": "application/json"}
        response.text = ""
        with patch(
            "agents.tools.gdelt_query.httpx.AsyncClient",
            return_value=_DummyAsyncClient(response),
        ):
            out = await gdelt_query.ainvoke({"query": "hormuz", "max_records": 5})
        refs = parse_evidence_refs(out)
        assert len(refs) == 1
        assert refs[0].source_type == "gdelt"
        assert refs[0].provider == "reuters.com"
        assert refs[0].published_at is None  # seendate is an observation, not publication
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_gdelt_query.py::TestGdeltQueryTool::test_emits_evidence_blocks_seendate_not_published -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite the result-formatting block**

In `services/intelligence/agents/tools/gdelt_query.py`, add import:
```python
from rag.evidence import format_evidence_pack, to_evidence_item
```
Replace the `results: list[str] = []` loop and its `return` with:
```python
        items = [
            to_evidence_item({
                "score": 1.0 - idx * 0.001,  # preserve newest-first ordering
                "source_type": "gdelt",
                "provider": article.get("domain", "gdelt"),
                "title": article.get("title", "No title"),
                "content": article.get("title", ""),
                "url": article.get("url", ""),
                # seendate is GDELT observation metadata — deliberately NOT published_at
            })
            for idx, article in enumerate(articles[:max_records])
        ]
        pack = format_evidence_pack(items, budget=6500)
        return f"[GDELT Evidence for: {query}]\n{pack}"
```

- [ ] **Step 4: Run the full file — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_gdelt_query.py -v`
Expected: ALL PASS. The existing `test_formats_article_list_when_json_is_valid` asserts `"[GDELT Results for: ...]"` and the article title — update its assertions to `"[GDELT Evidence for: strait of hormuz]"` and that `parse_evidence_refs(result)` yields the article's domain as provider.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/agents/tools/gdelt_query.py services/intelligence/tests/test_gdelt_query.py
git commit -m "feat(intelligence): gdelt_query emits [EVIDENCE] blocks (seendate != published_at)"
```

---

### Task 9: `rss_fetch` emits evidence blocks (live)

**Files:**
- Modify: `services/intelligence/agents/tools/rss_fetch.py`
- Test: `services/intelligence/tests/test_rss_fetch.py` (create)

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_rss_fetch.py`:
```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.tools.rss_fetch import rss_fetch
from rag.evidence import parse_evidence_refs

_FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Strike reported</title><link>https://bbc.com/news/1</link>
<pubDate>Sat, 30 May 2026 10:00:00 GMT</pubDate>
<description>Body text here</description></item>
</channel></rss>"""


class _DummyAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._response


@pytest.mark.asyncio
async def test_rss_fetch_emits_evidence_with_domain_provider():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.text = _FEED
    with patch(
        "agents.tools.rss_fetch.httpx.AsyncClient",
        return_value=_DummyAsyncClient(resp),
    ):
        out = await rss_fetch.ainvoke({"feed_url": "https://bbc.com/rss.xml"})
    refs = parse_evidence_refs(out)
    assert len(refs) == 1
    assert refs[0].source_type == "rss"
    assert refs[0].provider == "bbc.com"        # article link domain
    assert refs[0].published_at is not None       # pubDate IS publication time
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_rss_fetch.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite the tool**

In `services/intelligence/agents/tools/rss_fetch.py`, add imports:
```python
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from rag.evidence import format_evidence_pack, to_evidence_item
```
Replace the `results: list[str] = []` loop and the `return` with:
```python
        items = []
        for idx, item in enumerate(root.findall(".//item")[:10]):
            title = item.findtext("title", "No title")
            link = item.findtext("link", "") or ""
            pub_date = item.findtext("pubDate", "") or ""
            description = (item.findtext("description", "") or "")[:700]
            try:
                published_iso = parsedate_to_datetime(pub_date).isoformat() if pub_date else None
            except (TypeError, ValueError):
                published_iso = None
            domain = urlparse(link).netloc or urlparse(feed_url).netloc or "rss"
            items.append(to_evidence_item({
                "score": 1.0 - idx * 0.001,
                "source_type": "rss",
                "provider": domain,
                "title": title,
                "content": description,
                "url": link,
                "published_at": published_iso,
            }))

        if not items:
            return f"No articles found in feed: {feed_url}"

        pack = format_evidence_pack(items, budget=6500)
        return f"[RSS Evidence: {feed_url}]\n{pack}"
```
(Delete the original `items = root.findall(".//item")[:10]` line above the old loop — the new loop calls `root.findall(...)` directly and `items` is now the evidence list.)

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_rss_fetch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/agents/tools/rss_fetch.py services/intelligence/tests/test_rss_fetch.py
git commit -m "feat(intelligence): rss_fetch emits [EVIDENCE] blocks (pubDate is published_at)"
```

---

## Phase 4 — Workflow + Synthesis

### Task 10: Workflow derives `sources_used` from parsed evidence (provider IDs)

**Files:**
- Modify: `services/intelligence/graph/workflow.py`
- Test: `services/intelligence/tests/test_workflow_sources.py` (create)

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_workflow_sources.py`:
```python
"""sources_used must be deduplicated provider IDs in evidence order, not tool names."""
from __future__ import annotations

from graph.workflow import derive_sources_used


def test_derives_dedup_provider_ids_in_order():
    tool_outputs = [
        '[Knowledge Base Evidence for: x]\n'
        '[EVIDENCE] {"provider":"reuters.com","source_ref_id":"a","source_type":"rss",'
        '"credibility_score":0.85,"provenance_inferred":false,"published_at":null,'
        '"relevance_score":0.9,"url":null,"display_name":null}\nTitle: t\nExcerpt: e',
        '[GDELT Evidence for: x]\n'
        '[EVIDENCE] {"provider":"usgs.gov","source_ref_id":"b","source_type":"dataset",'
        '"credibility_score":0.8,"provenance_inferred":false,"published_at":null,'
        '"relevance_score":0.7,"url":null,"display_name":null}\nTitle: t2\nExcerpt: e2',
        '[EVIDENCE] {"provider":"reuters.com","source_ref_id":"c","source_type":"rss",'
        '"credibility_score":0.85,"provenance_inferred":false,"published_at":null,'
        '"relevance_score":0.6,"url":null,"display_name":null}\nTitle: t3\nExcerpt: e3',
    ]
    assert derive_sources_used(tool_outputs) == ["reuters.com", "usgs.gov"]


def test_no_evidence_yields_empty_no_tool_names():
    assert derive_sources_used(["No relevant documents found for: x"]) == []
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_workflow_sources.py -v`
Expected: FAIL with `ImportError: cannot import name 'derive_sources_used'`.

- [ ] **Step 3: Implement in `graph/workflow.py`**

Add import near the top:
```python
from rag.evidence import parse_evidence_refs
```
Add the helper (module-level):
```python
def derive_sources_used(tool_outputs: list[str]) -> list[str]:
    """Deduplicated provider IDs in first-seen (evidence) order.

    Parses [EVIDENCE] <json> blocks. Never falls back to tool names or
    "llm_knowledge". Empty list if there is no real evidence lineage.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for out in tool_outputs:
        for ref in parse_evidence_refs(out):
            if ref.provider not in seen:
                seen.add(ref.provider)
                ordered.append(ref.provider)
    return ordered
```
In `react_synthesis_node`, replace the line:
```python
        derived_sources = sorted({entry.get("tool", "?") for entry in state.get("tool_trace", [])})
```
with:
```python
        derived_sources = derive_sources_used(tool_results)
```
(`tool_results` is the existing list of tool-message strings collected a few lines above. Leave the `logger.info("react_synthesis_grounding", ...)` call — update its `unique_tools=derived_sources` key name to `providers=derived_sources` for clarity, optional.)

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_workflow_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Run the workflow regression suite**

Run: `cd services/intelligence && uv run pytest tests/test_workflow.py -v`
Expected: ALL PASS (graph compiles, clip/compaction unaffected).

- [ ] **Step 6: Commit**
```bash
git add services/intelligence/graph/workflow.py services/intelligence/tests/test_workflow_sources.py
git commit -m "feat(intelligence): sources_used = dedup provider IDs parsed from evidence, not tool names"
```

---

### Task 11: Legacy `osint_node` stops emitting `llm_knowledge`

**Files:**
- Modify: `services/intelligence/graph/nodes.py`
- Test: `services/intelligence/tests/test_nodes_sources.py` (create)

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_nodes_sources.py`:
```python
"""Legacy pipeline must not advertise llm_knowledge as a source."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from graph.nodes import osint_node


@pytest.mark.asyncio
async def test_osint_node_sources_used_is_empty():
    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(return_value=type("R", (), {"content": "analysis"})())
    with patch("graph.nodes.create_osint_llm", return_value=fake_llm):
        out = await osint_node({
            "query": "q", "agent_chain": [], "iteration": 0,
        })
    assert out["sources_used"] == []
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_nodes_sources.py -v`
Expected: FAIL (`sources_used == ["llm_knowledge"]`).

- [ ] **Step 3: Implement**

In `services/intelligence/graph/nodes.py`, in `osint_node`'s success return, change:
```python
            "sources_used": ["llm_knowledge"],  # <-- ATTRIBUTION
```
to:
```python
            "sources_used": [],  # legacy path has no real evidence lineage (Slice 1)
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_nodes_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/graph/nodes.py services/intelligence/tests/test_nodes_sources.py
git commit -m "fix(intelligence): legacy osint_node no longer reports llm_knowledge as a source"
```

---

### Task 12: Synthesis prompt teaches credibility/provenance/recency semantics

**Files:**
- Modify: `services/intelligence/agents/synthesis_agent.py`
- Test: `services/intelligence/tests/test_synthesis_prompt.py` (create)

- [ ] **Step 1: Write the failing test**

`services/intelligence/tests/test_synthesis_prompt.py`:
```python
from agents.synthesis_agent import SYSTEM_PROMPT


def test_prompt_explains_evidence_semantics():
    p = SYSTEM_PROMPT.lower()
    assert "credibility_score" in p
    assert "verlässlichkeit" in p          # reliability, not truth
    assert "provenance_inferred" in p
    assert "published_at" in p
    assert "ingested_at" in p
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_synthesis_prompt.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement — append a section to `SYSTEM_PROMPT`**

In `services/intelligence/agents/synthesis_agent.py`, append this block to the end of the `SYSTEM_PROMPT` string (before the closing `"""`):
```text

## Evidenz-Metadaten (aus [EVIDENCE]-Blöcken)

Jeder Research-Block trägt eine `[EVIDENCE]`-Metadatenzeile. Beachte:

- `credibility_score` ist **Quellenverlässlichkeit**, NICHT Aussagewahrheit.
  Eine verlässliche Quelle kann sich irren; eine unverlässliche kann recht haben.
  Gewichte widersprüchliche Angaben, aber behandle den Score nicht als Beweis.
- `provenance_inferred=true` bedeutet `(Herkunft aus Legacy-Payload abgeleitet)` —
  kennzeichne solche Aussagen entsprechend zurückhaltend.
- `published_at=null` oder fehlend: **Aktualität ist nicht aus der Quelle
  ableitbar** — behaupte keine Aktualität.
- `ingested_at` ist KEIN Publikationszeitpunkt und darf nicht als solcher gelten.
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/intelligence && uv run pytest tests/test_synthesis_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add services/intelligence/agents/synthesis_agent.py services/intelligence/tests/test_synthesis_prompt.py
git commit -m "feat(intelligence): synthesis prompt explains credibility/provenance/recency semantics"
```

---

## Phase 5 — Write Side (data-ingestion)

### Task 13: Shared provenance helper (facts only)

**Files:**
- Create: `services/data-ingestion/feeds/provenance.py`
- Test: `services/data-ingestion/tests/test_provenance_helper.py`

- [ ] **Step 1: Write the failing test**

`services/data-ingestion/tests/test_provenance_helper.py`:
```python
from __future__ import annotations

import pytest

from feeds.provenance import DATASET_PROVIDERS, dataset_provenance, provenance_fields


def test_provenance_fields_required():
    out = provenance_fields(source_type="rss", provider="reuters.com")
    assert out["source_type"] == "rss"
    assert out["provider"] == "reuters.com"
    assert "published_at" not in out  # omitted when None


def test_provenance_fields_optional_published():
    out = provenance_fields(
        source_type="rss", provider="bbc.com", published_at="2026-05-31T08:00:00+00:00",
    )
    assert out["published_at"] == "2026-05-31T08:00:00+00:00"


def test_invalid_source_type_raises():
    with pytest.raises(ValueError):
        provenance_fields(source_type="unknown", provider="x")  # not a write type
    with pytest.raises(ValueError):
        provenance_fields(source_type="rss", provider="")


def test_dataset_provenance_lookup():
    out = dataset_provenance("usgs")
    assert out == {"source_type": "dataset", "provider": "usgs.gov"}
    assert "firms" in DATASET_PROVIDERS


def test_dataset_provenance_unknown_source_raises():
    with pytest.raises(KeyError):
        dataset_provenance("not-a-dataset")
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_provenance_helper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feeds.provenance'`.

- [ ] **Step 3: Implement**

`services/data-ingestion/feeds/provenance.py`:
```python
"""Shared write-side provenance helper. Facts only — no credibility, no guessing.

Mirrors contracts/qdrant-provenance-v1.json. Credibility is read-side policy and
must NOT be written here.
"""
from __future__ import annotations

WRITE_SOURCE_TYPES = {"rss", "telegram", "gdelt", "notebooklm", "dataset"}

# Canonical provider id per single-provider dataset source.
DATASET_PROVIDERS: dict[str, str] = {
    "firms": "firms.modaps.eosdis.nasa.gov",
    "usgs": "usgs.gov",
    "ucdp": "ucdp.uu.se",
    "ofac": "ofac.treasury.gov",
    "hapi": "hapi.humdata.org",
    "noaa_nhc": "nhc.noaa.gov",
    "portwatch": "portwatch.imf.org",
    "eonet": "eonet.gsfc.nasa.gov",
    "gdacs": "gdacs.org",
}


def provenance_fields(
    *, source_type: str, provider: str, published_at: str | None = None,
) -> dict:
    """Validated canonical provenance facts. Raises ValueError on bad input."""
    if source_type not in WRITE_SOURCE_TYPES:
        raise ValueError(f"invalid write source_type: {source_type!r}")
    if not provider:
        raise ValueError("provider must be a non-empty canonical id")
    fields = {"source_type": source_type, "provider": provider}
    if published_at:
        fields["published_at"] = published_at
    return fields


def dataset_provenance(source: str, published_at: str | None = None) -> dict:
    """Canonical provenance for a known dataset source key. Raises KeyError if unknown."""
    return provenance_fields(
        source_type="dataset",
        provider=DATASET_PROVIDERS[source],
        published_at=published_at,
    )
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_provenance_helper.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add services/data-ingestion/feeds/provenance.py services/data-ingestion/tests/test_provenance_helper.py
git commit -m "feat(data-ingestion): shared write-side provenance helper (facts only)"
```

---

### Task 14: `_build_point` stamps canonical provenance for dataset collectors

**Files:**
- Modify: `services/data-ingestion/feeds/base.py`
- Test: `services/data-ingestion/tests/test_base_provenance.py` (create)

This covers the 7 `_build_point` users (firms, usgs, ucdp, ofac, hapi, noaa_nhc, portwatch) in ONE place — they already put `source` in their payload, and `_build_point` derives canonical provenance from it via `dataset_provenance`. No per-collector edits needed for these 7. Fail-fast: an unknown `source` raises (no guessing).

- [ ] **Step 1: Write the failing test**

`services/data-ingestion/tests/test_base_provenance.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.base import BaseCollector


class _Concrete(BaseCollector):
    async def collect(self) -> None:  # pragma: no cover
        ...


@pytest.fixture
def collector():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    with patch("feeds.base.QdrantClient", return_value=MagicMock()):
        c = _Concrete(settings=s)
    c._embed = AsyncMock(return_value=[0.0] * 1024)
    return c


@pytest.mark.asyncio
async def test_build_point_stamps_dataset_provenance(collector):
    point = await collector._build_point("text", {"source": "usgs"}, "abc123")
    assert point.payload["source_type"] == "dataset"
    assert point.payload["provider"] == "usgs.gov"
    assert "ingested_at" in point.payload
    # credibility is NOT written on the write path
    assert "credibility_score" not in point.payload


@pytest.mark.asyncio
async def test_build_point_unknown_source_raises(collector):
    with pytest.raises(KeyError):
        await collector._build_point("text", {"source": "mystery"}, "abc123")
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_base_provenance.py -v`
Expected: FAIL (`source_type` not in payload).

- [ ] **Step 3: Implement — edit `_build_point` in `feeds/base.py`**

Add import at the top of `feeds/base.py`:
```python
from feeds.provenance import dataset_provenance
```
Change `_build_point` (currently lines 109–118) to stamp provenance when not already present:
```python
    async def _build_point(
        self, text: str, payload: dict, content_hash: str
    ) -> PointStruct:
        vector = await self._embed(text)
        point_id = self._point_id(content_hash)
        # Canonical provenance facts. Dataset collectors carry `source`; derive
        # from the explicit table (fail-fast on unknown — never guess).
        if "source_type" not in payload:
            payload.update(dataset_provenance(str(payload.get("source", ""))))
        payload["content_hash"] = content_hash
        now = datetime.now(UTC)
        payload["ingested_at"] = now.isoformat()
        payload["ingested_epoch"] = now.timestamp()
        return PointStruct(id=point_id, vector=vector, payload=payload)
```

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_base_provenance.py -v`
Expected: PASS.

- [ ] **Step 5: Run the collector regression suite**

Run: `cd services/data-ingestion && uv run pytest tests/ -k "collector or base" -v`
Expected: ALL PASS. If any existing test builds a point with a `source` not in `DATASET_PROVIDERS`, that test's payload must add `source_type`/`provider` explicitly or use a known dataset source — fix the test data, not the helper.

- [ ] **Step 6: Commit**
```bash
git add services/data-ingestion/feeds/base.py services/data-ingestion/tests/test_base_provenance.py
git commit -m "feat(data-ingestion): _build_point stamps canonical dataset provenance"
```

---

### Task 15: Manual dataset writers (EONET, GDACS) stamp provenance

**Files:**
- Modify: `services/data-ingestion/feeds/eonet_collector.py`
- Modify: `services/data-ingestion/feeds/gdacs_collector.py`
- Test: `services/data-ingestion/tests/test_eonet_collector.py` (extend), `tests/test_gdacs_collector.py` (extend or create)

These writers bypass `_build_point`, so extract a small **pure payload builder** per writer and test the BUILT payload (red first), then have `collect()` call it. Event dates (`event_date`, `from_date`/`to_date`) are event times — they must NOT become `published_at`.

- [ ] **Step 1: Write the failing payload-builder tests**

Add to `services/data-ingestion/tests/test_eonet_collector.py`:
```python
def test_build_eonet_payload_stamps_provenance_and_no_published():
    from feeds.eonet_collector import build_eonet_payload
    event = {"eonet_id": "E1", "title": "Wildfire", "category": "wildfires",
             "status": "open", "latitude": 1.0, "longitude": 2.0,
             "event_date": "2026-05-31T00:00:00Z"}
    payload = build_eonet_payload(event, "desc text")
    assert payload["source_type"] == "dataset"
    assert payload["provider"] == "eonet.gsfc.nasa.gov"
    assert payload["description"] == "desc text"
    assert "published_at" not in payload      # event_date is NOT publication time
    assert "credibility_score" not in payload
```
Add to `services/data-ingestion/tests/test_gdacs_collector.py` (create if missing, mirroring the eonet test's imports):
```python
def test_build_gdacs_payload_stamps_provenance_and_no_published():
    from feeds.gdacs_collector import build_gdacs_payload
    event = {"gdacs_id": "EQ_1", "event_type": "EQ", "event_name": "Quake",
             "alert_level": "Orange", "severity": 5.0, "country": "X",
             "latitude": 1.0, "longitude": 2.0,
             "from_date": "2026-05-30", "to_date": "2026-05-31"}
    payload = build_gdacs_payload(event, "desc text")
    assert payload["source_type"] == "dataset"
    assert payload["provider"] == "gdacs.org"
    assert "published_at" not in payload
    assert "credibility_score" not in payload
```

- [ ] **Step 2: Run — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_eonet_collector.py tests/test_gdacs_collector.py -k "build_eonet_payload or build_gdacs_payload" -v`
Expected: FAIL with `ImportError: cannot import name 'build_eonet_payload'` (and `build_gdacs_payload`).

- [ ] **Step 3: Implement — EONET pure builder + wire it in**

In `feeds/eonet_collector.py`, ensure imports include `from datetime import UTC, datetime` and add:
```python
from feeds.provenance import dataset_provenance
```
Add the pure builder (module-level):
```python
def build_eonet_payload(event: dict, description: str) -> dict:
    """Pure EONET Qdrant payload builder (no I/O). event_date stays an event
    time; it is NOT published_at."""
    return {
        **dataset_provenance("eonet"),
        "source": "eonet",
        **event,
        "ingested_epoch": time.time(),
        "ingested_at": datetime.now(UTC).isoformat(),
        "description": description,
    }
```
Replace the inline manual payload block (lines 146–152) with:
```python
            payload = build_eonet_payload(event, description)
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
```

- [ ] **Step 4: Implement — GDACS pure builder + wire it in**

In `feeds/gdacs_collector.py`, ensure imports include `from datetime import UTC, datetime` and add:
```python
from feeds.provenance import dataset_provenance
```
Add the pure builder (module-level):
```python
def build_gdacs_payload(event: dict, description: str) -> dict:
    """Pure GDACS Qdrant payload builder (no I/O). from_date/to_date stay event
    times; they are NOT published_at."""
    return {
        **dataset_provenance("gdacs"),
        "source": "gdacs",
        **event,
        "ingested_epoch": time.time(),
        "ingested_at": datetime.now(UTC).isoformat(),
        "description": description,
    }
```
Replace the inline manual payload block (lines 139–146) with:
```python
            payload = build_gdacs_payload(event, description)
            point = PointStruct(id=point_id, vector=vector, payload=payload)
            points.append(point)
```

- [ ] **Step 5: Run the builder tests + collector regression suites**

Run: `cd services/data-ingestion && uv run pytest tests/test_eonet_collector.py tests/test_gdacs_collector.py -v`
Expected: ALL PASS (new builder tests green, existing collector tests still green).

- [ ] **Step 6: Commit**
```bash
git add services/data-ingestion/feeds/eonet_collector.py services/data-ingestion/feeds/gdacs_collector.py \
  services/data-ingestion/tests/test_eonet_collector.py services/data-ingestion/tests/test_gdacs_collector.py
git commit -m "feat(data-ingestion): EONET/GDACS manual writers stamp canonical provenance"
```

---

### Task 16: RSS writer — explicit per-feed provider + published_at=None semantics

**Files:**
- Modify: `services/data-ingestion/feeds/rss_collector.py`
- Test: `services/data-ingestion/tests/test_rss_provider.py` (create)

Per spec §3.4: each curated feed gets a **fixed, explicit** canonical `provider` id (no URL heuristics). For Google-News proxy feeds (`news.google.com/...?q=site:reuters.com`) the curator sets the publisher domain (`reuters.com`). When a feed entry has no parsable publication date, `published_at` is **`None`** — never `datetime.now()`.

- [ ] **Step 1: Write the failing curation-guard test**

`services/data-ingestion/tests/test_rss_provider.py`:
```python
from __future__ import annotations

from feeds.rss_collector import RSS_FEEDS


def test_every_feed_has_explicit_non_google_provider():
    for feed in RSS_FEEDS:
        prov = feed.get("provider")
        assert prov, f"feed {feed['name']!r} is missing an explicit provider id"
        assert prov != "news.google.com", f"{feed['name']!r} leaks the google proxy host"
        assert "://" not in prov and "/" not in prov, f"{feed['name']!r} provider must be a bare domain"


def test_known_feeds_have_expected_publisher_domains():
    by_name = {f["name"]: f for f in RSS_FEEDS}
    # Direct feeds use their own registrable domain.
    if "BBC World" in by_name:
        assert by_name["BBC World"]["provider"] == "bbc.co.uk"
    # Google-News proxy feeds resolve to the curated publisher domain, not google.
    if "Reuters (Google)" in by_name:
        assert by_name["Reuters (Google)"]["provider"] == "reuters.com"
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_rss_provider.py -v`
Expected: FAIL — feeds currently have only `name`/`url`, no `provider` key.

- [ ] **Step 3: Add an explicit `provider` to every `RSS_FEEDS` entry**

In `feeds/rss_collector.py`, add a `"provider"` key to each dict in `RSS_FEEDS`. The provider is the bare publisher domain (registrable domain, no scheme/path). Rules:
- Direct feed → publisher domain of the outlet (e.g. `{"name": "BBC World", "url": "https://feeds.bbci.co.uk/...", "provider": "bbc.co.uk"}`).
- Google-News proxy (`url` host is `news.google.com`) → the domain inside `site:<domain>` in the query (e.g. Reuters-via-Google → `"provider": "reuters.com"`, AP-via-Google → `"provider": "apnews.com"`).
- German gov/defence feeds → their own domain (`bmvg.de`, `bundeswehr.de`, `bundestag.de`, …).

Worked examples (apply the same pattern to ALL entries):
```python
RSS_FEEDS: list[dict[str, str]] = [
    {"name": "BMVg", "url": "https://www.bmvg.de/service/rss/de/17680/feed", "provider": "bmvg.de"},
    {"name": "Bundeswehr", "url": "https://www.bundeswehr.de/service/rss/de/517054/feed", "provider": "bundeswehr.de"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "provider": "bbc.co.uk"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "provider": "aljazeera.com"},
    {"name": "Reuters (Google)", "url": "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en", "provider": "reuters.com"},
    {"name": "AP News (Google)", "url": "https://news.google.com/rss/search?q=site:apnews.com+world+news&hl=en-US&gl=US&ceid=US:en", "provider": "apnews.com"},
    # ... set "provider" for EVERY remaining feed the same way ...
]
```
The Step-1 guard test is the completeness gate: it fails until **every** feed has a valid bare-domain provider.

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_rss_provider.py -v`
Expected: PASS (every feed now has an explicit provider).

- [ ] **Step 5: Write the failing pure-payload-builder test (wiring + published_at=None)**

Add to `services/data-ingestion/tests/test_rss_provider.py`:
```python
from feeds.rss_collector import build_rss_payload


def test_build_rss_payload_stamps_explicit_provenance():
    feed = {"name": "BBC World", "url": "https://feeds.bbci.co.uk/x", "provider": "bbc.co.uk"}
    payload = build_rss_payload(
        feed, title="Strike", link="https://bbc.co.uk/a",
        summary="body", published_at="2026-05-30T10:00:00+00:00",
        content_hash="h1", enrichment=None,
    )
    assert payload["source_type"] == "rss"
    assert payload["provider"] == "bbc.co.uk"
    assert payload["published_at"] == "2026-05-30T10:00:00+00:00"
    assert payload["feed_name"] == "BBC World"
    assert "credibility_score" not in payload


def test_build_rss_payload_published_none_when_missing():
    feed = {"name": "BBC World", "url": "https://feeds.bbci.co.uk/x", "provider": "bbc.co.uk"}
    payload = build_rss_payload(
        feed, title="t", link="https://bbc.co.uk/a", summary="s",
        published_at=None, content_hash="h2", enrichment=None,
    )
    # No publication date => no published_at key, and 'published' is None (never now()).
    assert "published_at" not in payload
    assert payload["published"] is None
```

- [ ] **Step 6: Run it — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_rss_provider.py -k build_rss_payload -v`
Expected: FAIL with `ImportError: cannot import name 'build_rss_payload'`.

- [ ] **Step 7: Implement the pure builder + fix the date fallback + wire it in**

In `feeds/rss_collector.py`, add import:
```python
from datetime import UTC, datetime

from feeds.provenance import provenance_fields
```
Add the pure payload builder (module-level, above the class):
```python
def build_rss_payload(
    feed: dict,
    *,
    title: str,
    link: str,
    summary: str,
    published_at: str | None,
    content_hash: str,
    enrichment: dict | None,
) -> dict:
    """Pure RSS Qdrant payload builder (unit-testable, no I/O).

    provider is the feed's explicit canonical domain. published_at is passed
    through verbatim — None stays None (never ingestion time)."""
    return {
        **provenance_fields(
            source_type="rss",
            provider=feed["provider"],
            published_at=published_at,
        ),
        "source": "rss",
        "feed_name": feed["name"],
        "title": title,
        "url": link,
        "summary": (summary or "")[:1000],
        "published": published_at,
        "content_hash": content_hash,
        "ingested_at": datetime.now(UTC).isoformat(),
        "codebook_type": enrichment["codebook_type"] if enrichment else "other.unclassified",
        "entities": enrichment["entities"] if enrichment else [],
    }
```
Fix the date computation in `_process_feed` (currently lines 195–203) so a missing date is `None`, NOT `datetime.now()`:
```python
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                published_dt = datetime(*published_parsed[:6], tzinfo=UTC).isoformat()
            except Exception:
                published_dt = None
        else:
            published_dt = None
```
Replace the inline `PointStruct(id=point_id, vector=vector, payload={...})` construction (lines 229–254) with a call to the builder:
```python
        points.append(
            PointStruct(
                id=point_id,
                vector=vector,
                payload=build_rss_payload(
                    feed_meta,
                    title=title,
                    link=link,
                    summary=summary or content,
                    published_at=published_dt,
                    content_hash=chash,
                    enrichment=enrichment,
                ),
            )
        )
```
(`feed_meta` is the per-feed dict passed into `_process_feed`; `title`/`link`/`summary`/`content`/`chash`/`enrichment`/`point_id`/`vector` are already in scope per the existing code.)

- [ ] **Step 8: Run the RSS tests**

Run: `cd services/data-ingestion && uv run pytest tests/test_rss_provider.py -v && uv run pytest tests/ -k rss -v`
Expected: ALL PASS.

- [ ] **Step 9: Commit**
```bash
git add services/data-ingestion/feeds/rss_collector.py services/data-ingestion/tests/test_rss_provider.py
git commit -m "feat(data-ingestion): RSS explicit per-feed provider + published_at=None when unknown"
```

---

### Task 17: Telegram writer — channel provider + published_at

**Files:**
- Modify: `services/data-ingestion/feeds/telegram_collector.py`
- Test: `services/data-ingestion/tests/test_telegram_provenance.py` (create)

Extract a **pure payload builder** so the constructed payload is unit-testable without Telethon/Qdrant I/O, then have `_embed_and_upsert` call it. `published` (the message date) IS publication time → it becomes `published_at`.

- [ ] **Step 1: Write the failing builder test**

`services/data-ingestion/tests/test_telegram_provenance.py`:
```python
from __future__ import annotations

from types import SimpleNamespace

from feeds.telegram_collector import build_telegram_payload


def _channel(handle="@Rybar"):
    return SimpleNamespace(handle=handle, source_bias="state", category="mil")


def test_build_telegram_payload_namespaced_provider_and_published():
    payload = build_telegram_payload(
        channel=_channel(), message_id=42, title="msg",
        url="https://t.me/Rybar/42", published="2026-05-31T08:00:00+00:00",
        content_hash="h1", enrichment=None, forwarded_from=None,
        has_media=False, media_paths=[], media_types=[], vision_status="none",
    )
    assert payload["source_type"] == "telegram"
    assert payload["provider"] == "telegram:rybar"          # @ stripped, lowercased
    assert payload["published_at"] == "2026-05-31T08:00:00+00:00"
    assert payload["telegram_message_id"] == 42
    assert "credibility_score" not in payload
```

- [ ] **Step 2: Run — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_telegram_provenance.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_telegram_payload'`.

- [ ] **Step 3: Implement the pure builder + wire it in**

In `feeds/telegram_collector.py`, add import:
```python
from feeds.provenance import provenance_fields
```
Add the pure builder (module-level):
```python
def build_telegram_payload(
    *, channel, message_id, title, url, published, content_hash, enrichment,
    forwarded_from, has_media, media_paths, media_types, vision_status,
) -> dict:
    """Pure Telegram Qdrant payload builder (no I/O). The Telegram message date
    (`published`) IS publication time."""
    return {
        **provenance_fields(
            source_type="telegram",
            provider=f"telegram:{channel.handle.lstrip('@').lower()}",
            published_at=published,
        ),
        "source": "telegram",
        "title": title,
        "url": url,
        "published": published,
        "content_hash": content_hash,
        "ingested_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "codebook_type": enrichment["codebook_type"] if enrichment else "other.unclassified",
        "entities": enrichment["entities"] if enrichment else [],
        "telegram_channel": channel.handle,
        "telegram_message_id": message_id,
        "source_bias": channel.source_bias,
        "source_category": channel.category,
        "forwarded_from": forwarded_from,
        "has_media": has_media,
        "media_paths": media_paths,
        "media_types": media_types,
        "vision_status": vision_status,
    }
```
In `_embed_and_upsert`, replace the inline `payload = {...}` block (lines 596–614) with a call:
```python
        payload = build_telegram_payload(
            channel=channel, message_id=message_id, title=title, url=url,
            published=published, content_hash=content_hash, enrichment=enrichment,
            forwarded_from=forwarded_from, has_media=has_media,
            media_paths=media_paths, media_types=media_types, vision_status=vision_status,
        )
```
(All of these names are already in scope inside `_embed_and_upsert`.)

- [ ] **Step 4: Run the telegram suite**

Run: `cd services/data-ingestion && uv run pytest tests/test_telegram_provenance.py -v && uv run pytest tests/ -k telegram -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**
```bash
git add services/data-ingestion/feeds/telegram_collector.py services/data-ingestion/tests/test_telegram_provenance.py
git commit -m "feat(data-ingestion): Telegram writer stamps telegram:<handle> provider + published_at"
```

---

### Task 18: GDELT-raw writer — origin domain provider

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/writers/qdrant_writer.py`
- Test: `services/data-ingestion/tests/test_gdelt_raw_provenance.py` (create)

- [ ] **Step 1: Write the failing test**

`services/data-ingestion/tests/test_gdelt_raw_provenance.py`:
```python
from __future__ import annotations

from gdelt_raw.writers.qdrant_writer import build_payload


def test_gdelt_payload_provenance_uses_origin_domain():
    p = build_payload({
        "doc_id": "d1", "url": "https://reuters.com/x",
        "source_name": "reuters.com", "published_at": "2026-05-31T00:00:00+00:00",
    })
    assert p["source_type"] == "gdelt"
    assert p["provider"] == "reuters.com"


def test_gdelt_payload_provenance_falls_back_to_gdelt():
    p = build_payload({"doc_id": "d2", "url": None, "source_name": None})
    assert p["source_type"] == "gdelt"
    assert p["provider"] == "gdelt"


def test_gdelt_published_at_passthrough_not_seendate():
    # gdelt_date (observation) must NOT become published_at
    p = build_payload({"doc_id": "d3", "gdelt_date": "20260531120000", "published_at": None})
    assert p.get("published_at") is None
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_raw_provenance.py -v`
Expected: FAIL (`source_type`/`provider` not in payload).

- [ ] **Step 3: Implement — extend `build_payload`**

In `gdelt_raw/writers/qdrant_writer.py`, add import:
```python
from feeds.provenance import provenance_fields
```
(If `gdelt_raw` cannot import from `feeds`, instead inline the two fields — but they share the same package root `services/data-ingestion`, so the import works.)
In `build_payload`, change the `return {...}` to merge provenance. Add before the return:
```python
    provider = row.get("source_name") or row.get("v2_source_common_name") or "gdelt"
```
and prepend to the returned dict:
```python
    return {
        **provenance_fields(
            source_type="gdelt",
            provider=provider,
            published_at=row.get("published_at"),
        ),
        "source": "gdelt_gkg",
        "doc_id": row["doc_id"],
        # ... (rest of the existing fields unchanged) ...
    }
```
Keep the existing `gdelt_date` field as-is (it stays an observation field, never `published_at`).

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_raw_provenance.py -v`
Expected: PASS.

- [ ] **Step 5: Run the gdelt_raw suite**

Run: `cd services/data-ingestion && uv run pytest tests/ -k gdelt -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**
```bash
git add services/data-ingestion/gdelt_raw/writers/qdrant_writer.py services/data-ingestion/tests/test_gdelt_raw_provenance.py
git commit -m "feat(data-ingestion): GDELT-raw writer stamps gdelt provenance with origin domain"
```

---

### Task 19: NLM writer — notebooklm provider

**Files:**
- Modify: `services/data-ingestion/nlm_ingest/ingest_qdrant.py`
- Test: `services/data-ingestion/tests/test_nlm_ingest_qdrant.py` (extend; this file is conftest-guarded by qdrant_client import)

- [ ] **Step 1: Write the failing test**

Add to `services/data-ingestion/tests/test_nlm_ingest_qdrant.py` (mirror existing fixtures/imports there for `Extraction`/claims):
```python
def test_claim_points_carry_notebooklm_provenance(monkeypatch):
    from nlm_ingest.ingest_qdrant import build_claim_points
    # build a minimal Extraction with one accepted claim using the file's existing helpers
    extraction = _make_extraction(notebook_id="nb-7", source_kind="report",
                                   source_id="rpt-1", statements=["a claim"])
    points = build_claim_points(
        extraction, "Notebook Title", embed=lambda t: [0.0] * 1024,
        source_name="RAND",
    )
    p = points[0].payload
    assert p["source_type"] == "notebooklm"
    assert p["provider"] == "notebooklm:nb-7"
    assert p["display_name"] == "RAND"
    assert "credibility_score" not in p
```
(If the test file has no `_make_extraction` helper, build the `Extraction` inline using the schema already imported in that file.)

- [ ] **Step 2: Run it — verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_nlm_ingest_qdrant.py -k provenance -v`
Expected: FAIL (`source_type` not in payload).

- [ ] **Step 3: Implement — edit `build_claim_points`**

In `nlm_ingest/ingest_qdrant.py`, add import:
```python
from feeds.provenance import provenance_fields
```
In the `payload = {...}` dict, prepend provenance and keep `source_name` as `display_name`:
```python
        payload = {
            **provenance_fields(
                source_type="notebooklm",
                provider=f"notebooklm:{extraction.notebook_id}",
            ),
            "display_name": source_name,
            "title": notebook_title,
            "source": source_name,
            "region": "N/A",
            "content": claim.statement,
            "entities": [{"name": n} for n in claim.entities_involved],
            "notebook_id": extraction.notebook_id,
            "source_kind": extraction.source_kind,
            "source_id": extraction.source_id,
            "claim_type": str(claim.type),
            "claim_hash": chash,
            "content_hash": chash,
            "ingested_at": ts,
            "ingested_epoch": datetime.fromisoformat(ts).timestamp(),
        }
```
(NotebookLM has no reliable primary publication date in Slice 1 → `published_at` omitted. NLM is a transformation path.)

- [ ] **Step 4: Run it — verify pass**

Run: `cd services/data-ingestion && uv run pytest tests/test_nlm_ingest_qdrant.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**
```bash
git add services/data-ingestion/nlm_ingest/ingest_qdrant.py services/data-ingestion/tests/test_nlm_ingest_qdrant.py
git commit -m "feat(data-ingestion): NLM writer stamps notebooklm:<id> provenance"
```

---

## Phase 6 — Full Verification

### Task 20: Both services green + lint

**Files:** none (verification only).

- [ ] **Step 1: Intelligence full suite**

Run: `cd services/intelligence && uv run pytest -q`
Expected: ALL PASS. Capture the summary line.

- [ ] **Step 2: Data-ingestion full suite**

Run: `cd services/data-ingestion && uv run pytest -q`
Expected: ALL PASS. Capture the summary line.

- [ ] **Step 3: Lint both**

Run: `cd services/intelligence && uv run ruff check . && cd ../data-ingestion && uv run ruff check .`
Expected: no errors (fix any introduced by new files).

- [ ] **Step 4: Guardrail self-check (manual grep)**

Run: `grep -n "credibility_score" services/data-ingestion/feeds/provenance.py services/data-ingestion/gdelt_raw/writers/qdrant_writer.py services/data-ingestion/nlm_ingest/ingest_qdrant.py`
Expected: NO matches (credibility must never be written on the write path).

Run: `grep -rn "list\[SourceRef\]\|SourceRef" services/backend services/frontend`
Expected: NO matches (API boundary unchanged; SourceRef stays internal to intelligence).

Run: `grep -n "sources_used\[:6\]\|\.sources_used\[:6\]" services/backend/app/routers/intel.py`
Expected: the `[:6]` cap is still present and unchanged.

- [ ] **Step 5: Commit any lint fixes**

NEVER `git add -A` / `git add .` — the working tree contains unrelated foreign changes (see `git status`) that must not be swept in. Stage only the explicit files ruff modified, e.g.:
```bash
# list exactly what changed, then add only Slice-1 files by path:
git status --short
git add services/intelligence/rag/evidence.py services/intelligence/rag/credibility.py \
        services/intelligence/agents/tools/qdrant_search.py services/intelligence/agents/tools/gdelt_query.py \
        services/intelligence/agents/tools/rss_fetch.py services/intelligence/graph/workflow.py \
        services/data-ingestion/feeds/provenance.py
git commit -m "chore: lint fixes for Slice 1 minimal viable evidence" || echo "nothing to commit"
```
Add/remove paths to match only the files this slice touched.

---

## Spec Coverage Map

| Spec section | Task(s) |
|---|---|
| §3.1 contract file + dual tests | 1 |
| §3.2 fields / §3.4 provider rules | 13, 16, 17, 18, 19 |
| §3.3 A (`_build_point` users) | 14 |
| §3.3 B (manual writers) | 15 (EONET/GDACS), 16 (RSS), 17 (Telegram), 18 (GDELT), 19 (NLM) |
| §3.3 C (exclusions) | n/a — legacy `gdelt_collector.py` untouched; verified by not importing it |
| §4 adapter (canonical/legacy/unknown, excerpt, time) | 5 |
| §4.4 source_ref_id | 4 |
| §5.1 models | 3 |
| §5.2 credibility registry | 2 |
| §6.1 lossless format | 6 |
| §6.2 whole-block budgeting | 6, 7 |
| §6.3 unified serializer (qdrant/gdelt/rss) | 7, 8, 9 |
| §6.4 sources_used = provider IDs, no contextvar, API stays list[str] | 10, 11 |
| §6.5 synthesis prompt | 12 |
| §7.1 data-ingestion tests | 13–19 |
| §7.2 intelligence tests | 2–10 |
| §7.3 API-compat boundary | 10, 20 (guardrail grep) |
| §8 success criterion (blind comparison) | post-implementation, manual — out of plan scope |
