# Timeline UX Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Slice-0 text-wall scrubber with a thin bottom **density-timeline**
(`§ CHRONIK`) coloured by codebook **category**, geolocated events as time-faded dots on
the globe (reusing the existing `EventLayer`), and a single click-to-open callout —
reusing the Slice-0 clock/contract unchanged.

**Architecture:** Two new READ-ONLY backend endpoints (`/api/timeline/histogram`
server-aggregates buckets + notables + geo_events; `/api/timeline/events/{id}` serves
callout detail), a shared deterministic `normalize_severity`, a presentational
`ChronikTimeline`, a `useTimeHistogram` hook, the existing `EventLayer` made time-aware,
and a rewired `ScrubberMount`. The old `TwoTierScrubber` UI is deleted.

**Tech Stack:** FastAPI + Pydantic v2 + Neo4j (`read_query`); React 19 + TS + CesiumJS +
Vitest.

**Spec:** `docs/superpowers/specs/2026-06-09-timeline-ux-redesign-design.md`

**Base branch:** worktree off `origin/main` (Slice 0 + #42 merged). Backend pytest needs
`NEO4J_PASSWORD=ci-test-password`; backend/ingestion deps via `uv sync --extra dev`.

---

## File Structure

**Backend (`services/backend`)**
- Create `app/services/severity.py` — `normalize_severity` + canonical order + tie-breaks.
- Modify `app/models/timeline.py` — histogram/notable/geo/detail models.
- Modify `app/routers/timeline.py` — `GET /timeline/histogram` + `GET /timeline/events/{id}`.
- Tests: `tests/unit/test_severity.py`, `tests/unit/test_timeline_histogram.py`,
  `tests/unit/test_timeline_event_detail.py`.

**Frontend (`services/frontend`)**
- Create `src/lib/severity.ts` (+ `__tests__`) — mirror of the canonical order for the tick.
- Modify `src/types/index.ts` — histogram/notable/geo/detail types.
- Modify `src/services/api.ts` — `getTimeHistogram`, `getEventDetail`.
- Create `src/hooks/useTimeHistogram.ts` (+ `__tests__`).
- Create `src/components/time/ChronikTimeline.tsx` (+ `__tests__`) — the strip (presentational).
- Create `src/components/time/EventCallout.tsx` — single callout.
- Modify `src/components/layers/EventLayer.tsx` — time-aware fade, fed by geo_events.
- Modify `src/components/time/ScrubberMount.tsx` — drive ChronikTimeline + EventLayer.
- Modify `src/pages/WorldviewPage.tsx` — wire histogram-driven EventLayer + scrubber mount.
- Delete `src/components/time/TwoTierScrubber.tsx` + its test (the text-wall).

---

## Backend

### Task 1: Shared severity normalizer (the data-integrity keystone)

**Files:**
- Create: `services/backend/app/services/severity.py`
- Test: `services/backend/tests/unit/test_severity.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/unit/test_severity.py
from app.services.severity import (
    CANONICAL_ORDER, dominant_category, normalize_severity, severity_rank,
)


def test_canonical_order_is_fixed():
    assert CANONICAL_ORDER == ["unknown", "low", "medium", "high", "critical"]


def test_known_values_map_case_insensitively():
    assert normalize_severity("Low") == "low"
    assert normalize_severity("HIGH") == "high"
    assert normalize_severity("critical") == "critical"


def test_synonyms_collapse_deterministically():
    assert normalize_severity("moderate") == "medium"
    assert normalize_severity("medium") == "medium"
    assert normalize_severity("elevated") == "high"
    assert normalize_severity("warning") == "low"
    assert normalize_severity("severe") == "critical"
    assert normalize_severity("extreme") == "critical"


def test_null_and_garbage_become_unknown_never_random():
    assert normalize_severity(None) == "unknown"
    assert normalize_severity("") == "unknown"
    assert normalize_severity("  ") == "unknown"
    assert normalize_severity("banana") == "unknown"
    assert normalize_severity(5) == "unknown"  # non-str


def test_severity_rank_orders_unknown_lowest_critical_highest():
    assert severity_rank("unknown") < severity_rank("low") < severity_rank("critical")
    # raw values are normalized first
    assert severity_rank("elevated") == severity_rank("high")


def test_dominant_category_is_modal_with_priority_tiebreak():
    # plurality wins (one outlier never repaints)
    assert dominant_category(["civil"] * 200 + ["military"]) == "civil"
    # exact tie -> fixed priority order (military outranks civil)
    assert dominant_category(["civil", "military"]) == "military"
    # empty -> "other"
    assert dominant_category([]) == "other"
    # None/blank categories ignored, fall back to "other" if nothing left
    assert dominant_category([None, ""]) == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_severity.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.severity`.

- [ ] **Step 3: Write the normalizer**

```python
# services/backend/app/services/severity.py
"""Deterministic severity + category normalization.

The real corpus mixes vocabularies (hotspots low/moderate/elevated/high/critical;
incidents low/elevated/high/critical; RSS low/medium/high/critical; GDACS numeric;
GDELT *none*). Everything severity-touching MUST go through normalize_severity so
colours/rankings are deterministic and null/unknown never produces a random value.
"""

from __future__ import annotations

# Canonical ordered scale (index = rank; unknown lowest, critical highest).
CANONICAL_ORDER: list[str] = ["unknown", "low", "medium", "high", "critical"]
_RANK = {s: i for i, s in enumerate(CANONICAL_ORDER)}

# Every known raw value (lower-cased) -> canonical level.
_SEVERITY_MAP: dict[str, str] = {
    "low": "low",
    "warning": "low",
    "moderate": "medium",
    "medium": "medium",
    "elevated": "high",
    "high": "high",
    "critical": "critical",
    "severe": "critical",
    "extreme": "critical",
}

# Fixed category priority for dominant-category tie-breaks (most → least salient).
_CATEGORY_PRIORITY: list[str] = [
    "military", "conflict", "posture", "cyber", "political", "economic",
    "humanitarian", "social", "civil", "infrastructure", "space",
    "environmental", "other",
]
_CAT_PRIO = {c: i for i, c in enumerate(_CATEGORY_PRIORITY)}


def normalize_severity(raw: object) -> str:
    """Map any raw severity to the canonical scale; null/unknown/garbage -> 'unknown'."""
    if not isinstance(raw, str):
        return "unknown"
    return _SEVERITY_MAP.get(raw.strip().lower(), "unknown")


def severity_rank(raw: object) -> int:
    """Rank of a (raw or canonical) severity; higher = more severe."""
    value = raw if isinstance(raw, str) and raw in _RANK else normalize_severity(raw)
    return _RANK[value]


def category_of(codebook_type: object) -> str:
    """First segment of a codebook_type (e.g. 'military.airstrike' -> 'military')."""
    if not isinstance(codebook_type, str) or not codebook_type.strip():
        return "other"
    return codebook_type.split(".")[0].strip().lower() or "other"


def dominant_category(categories: list[object]) -> str:
    """Modal category; exact ties broken by fixed priority then alphabetical.

    Blank/None entries are ignored; an empty/all-blank input -> 'other'.
    """
    counts: dict[str, int] = {}
    for raw in categories:
        cat = category_of(raw)
        if cat:
            counts[cat] = counts.get(cat, 0) + 1
    if not counts:
        return "other"
    # sort by (count desc, priority asc, name asc) -> deterministic
    return sorted(
        counts.items(),
        key=lambda kv: (-kv[1], _CAT_PRIO.get(kv[0], len(_CATEGORY_PRIORITY)), kv[0]),
    )[0][0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_severity.py -v`
Expected: PASS (7 passed). Then `uv run ruff check app/services/severity.py`.

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/services/severity.py services/backend/tests/unit/test_severity.py
git commit -m "feat(backend): deterministic severity + dominant-category normalizer"
```

---

### Task 2: Histogram + detail response models

**Files:**
- Modify: `services/backend/app/models/timeline.py`
- Test: `services/backend/tests/unit/test_timeline_models.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to services/backend/tests/unit/test_timeline_models.py
from app.models.timeline import (
    HistogramBucket, HistogramResponse, Notable, GeoEvent, EventDetail,
)


def test_histogram_bucket_defaults():
    b = HistogramBucket(ts="2026-06-01T00:00:00Z", count=3, dominant_category="civil")
    assert b.by_category == {} and b.by_severity == {}


def test_histogram_response_shape():
    r = HistogramResponse(
        t_start="a", t_end="b", bucket_ms=1000, buckets=[],
        notables=[], geo_events=[], total_count=0,
        geo_located_count=0, geo_truncated=False,
    )
    assert r.notables == [] and r.geo_truncated is False


def test_notable_and_geo_and_detail():
    n = Notable(id="e1", time="t", time_basis="indexed", severity="high",
                is_incident=False, rank=0)
    g = GeoEvent(id="e1", time="t", codebook_type="military.x", severity="high",
                 lat=1.0, lon=2.0, is_incident=False)
    d = EventDetail(id="e1", time="t", time_basis="indexed")
    assert n.severity == "high" and g.lat == 1.0 and d.title is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_models.py -v`
Expected: FAIL — names not importable.

- [ ] **Step 3: Add the models**

```python
# append to services/backend/app/models/timeline.py

class HistogramBucket(BaseModel):
    ts: str  # ISO-8601 UTC bucket start
    count: int
    dominant_category: str
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class Notable(BaseModel):
    id: str
    time: str
    time_basis: str
    severity: str
    title: str | None = None
    codebook_type: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_incident: bool = False
    rank: int = 0


class GeoEvent(BaseModel):
    id: str
    time: str
    codebook_type: str | None = None
    severity: str
    lat: float
    lon: float
    is_incident: bool = False


class HistogramResponse(BaseModel):
    t_start: str
    t_end: str
    bucket_ms: int
    buckets: list[HistogramBucket] = Field(default_factory=list)
    notables: list[Notable] = Field(default_factory=list)
    geo_events: list[GeoEvent] = Field(default_factory=list)
    total_count: int = 0
    geo_located_count: int = 0
    geo_truncated: bool = False


class EventDetail(BaseModel):
    id: str
    time: str
    time_basis: str
    title: str | None = None
    codebook_type: str | None = None
    severity: str | None = None
    source: str | None = None
    url: str | None = None
    location_name: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_models.py -v`
Expected: PASS. `uv run ruff check app/models/timeline.py`.

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/models/timeline.py services/backend/tests/unit/test_timeline_models.py
git commit -m "feat(backend): histogram/notable/geo/detail timeline models"
```

---

### Task 3: Histogram endpoint — buckets + by_category/by_severity + dominant_category

**Files:**
- Modify: `services/backend/app/routers/timeline.py`
- Test: `services/backend/tests/unit/test_timeline_histogram.py`

> The handler fetches **raw rows** (one per in-window event: `{ts, codebook_type, severity}`)
> via parameter-bound Cypher on the indexed `timeline_at`, then **bins + aggregates in
> Python** using `normalize_severity` / `dominant_category` / `category_of` from Task 1.
> Aggregating in Python (not Cypher) keeps the deterministic rules in one tested place.
> The notables + geo_events come from dedicated queries (Tasks 4-5).

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/unit/test_timeline_histogram.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

W = "?t_start=2026-06-01T00:00:00Z&t_end=2026-06-01T04:00:00Z&buckets=4"


@pytest.fixture
def client():
    return TestClient(app)


def _rows(*triples):
    # triples: (iso_time, codebook_type, severity)
    return [{"time": t, "codebook_type": c, "severity": s} for t, c, s in triples]


def test_histogram_bins_and_dominant_category_is_modal(client):
    rows = _rows(
        *[("2026-06-01T00:30:00Z", "civil.demonstration", "low")] * 200,
        ("2026-06-01T00:45:00Z", "military.airstrike", "critical"),  # outlier
        ("2026-06-01T02:30:00Z", "conflict.armed", None),
    )
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [rows, [], []]  # events, notables, geo
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bucket_ms"] == 3_600_000  # 4h / 4
    b0 = next(b for b in data["buckets"] if b["count"] == 201)
    assert b0["dominant_category"] == "civil"          # 200 civil beats 1 military
    assert b0["by_category"]["military"] == 1
    assert b0["by_severity"]["critical"] == 1 and b0["by_severity"]["low"] == 200
    # GDELT-style null severity -> 'unknown' bucket, never random
    b2 = next(b for b in data["buckets"] if b["count"] == 1)
    assert b2["by_severity"].get("unknown") == 1
    assert data["total_count"] == 202


def test_histogram_reversed_window_422(client):
    resp = client.get("/api/timeline/histogram?t_start=2026-06-02T00:00:00Z&t_end=2026-06-01T00:00:00Z")
    assert resp.status_code == 422


def test_histogram_buckets_over_cap_422(client):
    resp = client.get(f"/api/timeline/histogram{W}&buckets=999")
    assert resp.status_code == 422


def test_histogram_neo4j_down_503(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("boom")
        resp = client.get(f"/api/timeline/histogram{W}")
    assert resp.status_code == 503
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_histogram.py -v`
Expected: FAIL — route 404.

- [ ] **Step 3: Add the query + handler**

Add to `services/backend/app/routers/timeline.py` (imports: add `from app.services.severity import category_of, dominant_category, normalize_severity` and the new models `HistogramBucket, HistogramResponse`; `_MAX_BUCKETS = 240`):

```python
_HISTOGRAM_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
WITH ev, l
WHERE $bbox_off
   OR (l.lat IS NOT NULL AND l.lon IS NOT NULL
       AND l.lat >= $south AND l.lat <= $north
       AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
          OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) ))
WITH DISTINCT ev
RETURN toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity
"""


@router.get("/histogram", response_model=HistogramResponse)
async def get_histogram(
    t_start: str,
    t_end: str,
    buckets: int = 120,
    domain: str = "events",
    bbox: str | None = None,
) -> HistogramResponse:
    if domain != "events":
        raise HTTPException(status_code=422, detail="histogram supports domain=events only")
    if not (1 <= buckets <= _MAX_BUCKETS):
        raise HTTPException(status_code=422, detail=f"buckets must be in [1,{_MAX_BUCKETS}]")
    start, end = validate_window(t_start, t_end)
    box = parse_bbox(bbox)
    params = {"t_start": t_start, "t_end": t_end, **_bbox_params(box)}

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    span = max(end_ms - start_ms, 1)
    bucket_ms = max(span // buckets, 1)

    try:
        rows = await read_query(_HISTOGRAM_QUERY, params)
    except Exception as exc:
        log.error("timeline_histogram_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc

    # Bin in Python so the deterministic rules live in one tested place.
    cats: dict[int, list[str | None]] = {}
    sevs: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    for r in rows:
        t = r.get("time")
        if not t:
            continue
        ts_ms = int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp() * 1000)
        bi = min(int((ts_ms - start_ms) // bucket_ms), buckets - 1)
        bi = max(bi, 0)
        counts[bi] = counts.get(bi, 0) + 1
        cats.setdefault(bi, []).append(r.get("codebook_type"))
        sevs.setdefault(bi, []).append(normalize_severity(r.get("severity")))

    bucket_list: list[HistogramBucket] = []
    for bi in sorted(counts):
        bcats = cats[bi]
        by_cat: dict[str, int] = {}
        for c in bcats:
            by_cat[category_of(c)] = by_cat.get(category_of(c), 0) + 1
        by_sev: dict[str, int] = {}
        for s in sevs[bi]:
            by_sev[s] = by_sev.get(s, 0) + 1
        bucket_list.append(HistogramBucket(
            ts=datetime.fromtimestamp((start_ms + bi * bucket_ms) / 1000, tz=UTC).isoformat(),
            count=counts[bi],
            dominant_category=dominant_category(bcats),
            by_category=by_cat,
            by_severity=by_sev,
        ))

    notables = await _histogram_notables(t_start, t_end, box)        # Task 4
    geo_events, geo_count, geo_trunc = await _histogram_geo(t_start, t_end, box)  # Task 5

    return HistogramResponse(
        t_start=t_start, t_end=t_end, bucket_ms=bucket_ms, buckets=bucket_list,
        notables=notables, geo_events=geo_events, total_count=len(rows),
        geo_located_count=geo_count, geo_truncated=geo_trunc,
    )
```

Add temporary stubs so the module imports (replaced in Tasks 4-5):
```python
async def _histogram_notables(*a, **k): return []
async def _histogram_geo(*a, **k): return [], 0, False
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_histogram.py -v`
Expected: PASS (4 passed — notables/geo are stubbed empty, fine for these asserts).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_histogram.py
git commit -m "feat(backend): /timeline/histogram buckets + by_category/by_severity + dominant_category"
```

---

### Task 4: Notables — :Event(high/critical) ∪ :Incident, cap 40, ranked

**Files:**
- Modify: `services/backend/app/routers/timeline.py` (replace `_histogram_notables` stub)
- Test: `services/backend/tests/unit/test_timeline_histogram.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_notables_union_capped_and_ranked(client):
    events = [{"id": f"ev{i}", "time": "2026-06-01T01:00:00Z", "time_basis": "indexed",
               "severity": "high", "title": "T", "codebook_type": "conflict.armed",
               "lat": None, "lon": None} for i in range(50)]
    incidents = [{"id": "inc-1", "time": "2026-06-01T02:00:00Z", "time_basis": "occurred",
                  "severity": "critical", "title": "Strike", "codebook_type": None,
                  "lat": 50.0, "lon": 30.0}]
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], events, incidents, []]  # hist-events, notable-events, incidents, geo
        resp = client.get(f"/api/timeline/histogram{W}")
    data = resp.json()
    notables = data["notables"]
    assert len(notables) <= 40                       # cap
    assert notables[0]["severity"] == "critical"     # critical > high
    assert notables[0]["is_incident"] is True
    assert all(notables[i]["rank"] <= notables[i + 1]["rank"] for i in range(len(notables) - 1))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_histogram.py::test_notables_union_capped_and_ranked -v`
Expected: FAIL — stub returns `[]`.

- [ ] **Step 3: Replace the stub**

```python
_NOTABLE_EVENTS_QUERY = """
MATCH (ev:Event)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
  AND ev.severity IS NOT NULL
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       ev.severity AS severity, ev.title AS title, ev.codebook_type AS codebook_type,
       l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at DESC
LIMIT 400
"""

_NOTABLE_INCIDENTS_QUERY = """
MATCH (i:Incident)
WHERE datetime(i.trigger_ts) >= datetime($t_start)
  AND datetime(i.trigger_ts) <= datetime($t_end)
RETURN i.incident_id AS id, toString(i.trigger_ts) AS time, 'occurred' AS time_basis,
       i.severity AS severity, i.title AS title, i.lat AS lat, i.lon AS lon
ORDER BY i.trigger_ts DESC
LIMIT 200
"""

_NOTABLE_CAP = 40


async def _histogram_notables(t_start: str, t_end: str, box: BBox | None) -> list[Notable]:
    params = {"t_start": t_start, "t_end": t_end}
    ev_rows = await read_query(_NOTABLE_EVENTS_QUERY, params)
    inc_rows = await read_query(_NOTABLE_INCIDENTS_QUERY, params)

    candidates: list[dict] = []
    for r in ev_rows:
        sev = normalize_severity(r.get("severity"))
        if sev in ("high", "critical"):
            candidates.append({**r, "severity": sev, "is_incident": False})
    for r in inc_rows:
        candidates.append({
            **r, "severity": normalize_severity(r.get("severity")),
            "codebook_type": None, "is_incident": True,
        })

    # rank key: critical(0) > promoted-incident(1) > high(2) > recency
    def _key(c: dict) -> tuple:
        sev = c["severity"]
        tier = 0 if sev == "critical" else (1 if c["is_incident"] else (2 if sev == "high" else 3))
        return (tier, _neg_iso(c.get("time")))

    candidates.sort(key=_key)
    out: list[Notable] = []
    seen: set[str] = set()
    for rank, c in enumerate(candidates[:_NOTABLE_CAP]):
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        out.append(Notable(
            id=str(c["id"]), time=str(c.get("time") or ""),
            time_basis=str(c.get("time_basis") or "indexed"), severity=c["severity"],
            title=c.get("title"), codebook_type=c.get("codebook_type"),
            lat=float(c["lat"]) if c.get("lat") is not None else None,
            lon=float(c["lon"]) if c.get("lon") is not None else None,
            is_incident=bool(c["is_incident"]), rank=rank,
        ))
    return out


def _neg_iso(t: object) -> str:
    # newer time sorts first within a tier (descending)
    s = str(t or "")
    return "".join(chr(255 - ord(ch)) if ch.isprintable() else ch for ch in s)
```

> Note: `_neg_iso` gives descending-by-time within a tier deterministically without
> parsing. (A simpler `datetime.fromisoformat` + negative timestamp is equivalent; keep
> whichever the engineer prefers as long as the test's rank-monotonicity holds.)

Also update the histogram test's first `mock.side_effect` lists to include the extra
queries (`[hist_rows, notable_events, incidents, geo]`) — already reflected in the Task-4
test; update the Task-3 tests to `mock.side_effect = [rows, [], [], []]`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_histogram.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_histogram.py
git commit -m "feat(backend): histogram notables (events high/critical + incidents) capped+ranked"
```

---

### Task 5: geo_events — geo-located, cap 200, ranked

**Files:**
- Modify: `services/backend/app/routers/timeline.py` (replace `_histogram_geo` stub)
- Test: `services/backend/tests/unit/test_timeline_histogram.py` (extend)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_geo_events_capped_ranked_and_truncated(client):
    geo = [{"id": f"g{i}", "time": "2026-06-01T01:00:00Z", "codebook_type": "military.x",
            "severity": "low", "lat": 1.0 + i, "lon": 2.0} for i in range(205)]
    geo[0]["severity"] = "critical"
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [], [], geo]  # hist, notable-events, incidents, geo
        resp = client.get(f"/api/timeline/histogram{W}")
    data = resp.json()
    assert len(data["geo_events"]) == 200          # cap
    assert data["geo_truncated"] is True
    assert data["geo_located_count"] == 205
    assert data["geo_events"][0]["severity"] == "critical"   # severity-ranked
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_histogram.py::test_geo_events_capped_ranked_and_truncated -v`
Expected: FAIL — stub returns empty.

- [ ] **Step 3: Replace the stub**

```python
_GEO_EVENTS_QUERY = """
MATCH (ev:Event)-[:OCCURRED_AT]->(l:Location)
WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
  AND l.lat IS NOT NULL AND l.lon IS NOT NULL
  AND ($bbox_off
       OR (l.lat >= $south AND l.lat <= $north
           AND ( ($west <= $east AND l.lon >= $west AND l.lon <= $east)
              OR ($west >  $east AND (l.lon >= $west OR l.lon <= $east)) )))
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity, l.lat AS lat, l.lon AS lon
"""

_GEO_CAP = 200


async def _histogram_geo(t_start: str, t_end: str, box: BBox | None):
    params = {"t_start": t_start, "t_end": t_end, **_bbox_params(box)}
    rows = await read_query(_GEO_EVENTS_QUERY, params)
    total = len(rows)
    ranked = sorted(
        rows,
        key=lambda r: (-severity_rank(r.get("severity")), _neg_iso(r.get("time"))),
    )
    out = [
        GeoEvent(
            id=str(r["id"]), time=str(r.get("time") or ""),
            codebook_type=r.get("codebook_type"),
            severity=normalize_severity(r.get("severity")),
            lat=float(r["lat"]), lon=float(r["lon"]),
            is_incident=False,
        )
        for r in ranked[:_GEO_CAP]
    ]
    return out, total, total > _GEO_CAP
```

(Add `severity_rank, GeoEvent` to the imports.)

- [ ] **Step 4: Run to verify it passes**

Run full histogram suite: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_histogram.py -v && uv run ruff check app/`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_histogram.py
git commit -m "feat(backend): histogram geo_events (geo-located, capped 200, severity-ranked)"
```

---

### Task 6: Event detail endpoint `GET /timeline/events/{id}`

**Files:**
- Modify: `services/backend/app/routers/timeline.py`
- Test: `services/backend/tests/unit/test_timeline_event_detail.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/unit/test_timeline_event_detail.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_event_detail_returns_payload(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.return_value = [{
            "id": "gdelt:1", "title": None, "codebook_type": "military.airstrike",
            "severity": None, "time": "2026-06-01T00:00:00Z", "time_basis": "indexed",
            "source": "gdelt", "url": "http://x", "location_name": "Kyiv",
            "country": "UA", "lat": 50.4, "lon": 30.5,
        }]
        resp = client.get("/api/timeline/events/gdelt:1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["id"] == "gdelt:1" and d["source"] == "gdelt" and d["country"] == "UA"


def test_event_detail_unknown_404(client):
    with patch("app.routers.timeline.read_query", new_callable=AsyncMock) as mock:
        mock.return_value = []
        resp = client.get("/api/timeline/events/nope")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_event_detail.py -v`
Expected: FAIL — 404 for both (route missing).

- [ ] **Step 3: Add the handler**

```python
_EVENT_DETAIL_QUERY = """
MATCH (ev:Event)
WHERE coalesce(ev.id, ev.event_id, toString(elementId(ev))) = $id
OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
OPTIONAL MATCH (d:Document)-[:DESCRIBES]->(ev)
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       coalesce(d.source, ev.source) AS source, coalesce(d.url, ev.source_url) AS url,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
LIMIT 1
"""


@router.get("/events/{event_id}", response_model=EventDetail)
async def get_event_detail(event_id: str) -> EventDetail:
    try:
        rows = await read_query(_EVENT_DETAIL_QUERY, {"id": event_id})
    except Exception as exc:
        log.error("timeline_event_detail_neo4j_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="neo4j unreachable") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="event not found")
    r = rows[0]
    return EventDetail(
        id=str(r.get("id") or event_id),
        time=str(r.get("time") or ""), time_basis=str(r.get("time_basis") or "indexed"),
        title=r.get("title"), codebook_type=r.get("codebook_type"),
        severity=r.get("severity"), source=r.get("source"), url=r.get("url"),
        location_name=r.get("location_name"), country=r.get("country"),
        lat=float(r["lat"]) if r.get("lat") is not None else None,
        lon=float(r["lon"]) if r.get("lon") is not None else None,
    )
```

(Add `EventDetail` to the imports.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest tests/unit/test_timeline_event_detail.py -v`
Expected: PASS. Then full backend suite + ruff:
`NEO4J_PASSWORD=ci-test-password uv run pytest -q && uv run ruff check app/ tests/`

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/routers/timeline.py services/backend/tests/unit/test_timeline_event_detail.py
git commit -m "feat(backend): /timeline/events/{id} callout detail endpoint (+404)"
```

---

## Frontend

### Task 7: Frontend severity mirror + window/histogram types + api clients

**Files:**
- Create: `services/frontend/src/lib/severity.ts` (+ `__tests__/severity.test.ts`)
- Modify: `services/frontend/src/types/index.ts`, `services/frontend/src/services/api.ts`

- [ ] **Step 1: severity.ts test (RED)**

```ts
// services/frontend/src/lib/__tests__/severity.test.ts
import { describe, it, expect } from "vitest";
import { normalizeSeverity, severityRank, SEVERITY_ORDER } from "../severity";

describe("severity (frontend mirror)", () => {
  it("canonical order matches backend", () => {
    expect(SEVERITY_ORDER).toEqual(["unknown", "low", "medium", "high", "critical"]);
  });
  it("maps synonyms + null deterministically", () => {
    expect(normalizeSeverity("Elevated")).toBe("high");
    expect(normalizeSeverity("moderate")).toBe("medium");
    expect(normalizeSeverity(null)).toBe("unknown");
    expect(normalizeSeverity("banana")).toBe("unknown");
  });
  it("ranks unknown lowest", () => {
    expect(severityRank("unknown")).toBeLessThan(severityRank("critical"));
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/frontend && npx vitest run src/lib/__tests__/severity.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `severity.ts`**

```ts
// services/frontend/src/lib/severity.ts
export const SEVERITY_ORDER = ["unknown", "low", "medium", "high", "critical"] as const;
export type Severity = (typeof SEVERITY_ORDER)[number];

const MAP: Record<string, Severity> = {
  low: "low", warning: "low", moderate: "medium", medium: "medium",
  elevated: "high", high: "high", critical: "critical", severe: "critical", extreme: "critical",
};

export function normalizeSeverity(raw: unknown): Severity {
  if (typeof raw !== "string") return "unknown";
  return MAP[raw.trim().toLowerCase()] ?? "unknown";
}

export function severityRank(raw: unknown): number {
  const v = typeof raw === "string" && (SEVERITY_ORDER as readonly string[]).includes(raw)
    ? (raw as Severity) : normalizeSeverity(raw);
  return SEVERITY_ORDER.indexOf(v);
}
```

- [ ] **Step 4: Add types + api clients**

Append to `src/types/index.ts`:
```ts
export interface HistogramBucket {
  ts: string;
  count: number;
  dominant_category: string;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}
export interface TimelineNotable {
  id: string; time: string; time_basis: string; severity: string;
  title?: string | null; codebook_type?: string | null;
  lat?: number | null; lon?: number | null; is_incident: boolean; rank: number;
}
export interface TimelineGeoEvent {
  id: string; time: string; codebook_type?: string | null; severity: string;
  lat: number; lon: number; is_incident: boolean;
}
export interface HistogramResponse {
  t_start: string; t_end: string; bucket_ms: number;
  buckets: HistogramBucket[]; notables: TimelineNotable[]; geo_events: TimelineGeoEvent[];
  total_count: number; geo_located_count: number; geo_truncated: boolean;
}
export interface TimelineEventDetail {
  id: string; time: string; time_basis: string;
  title?: string | null; codebook_type?: string | null; severity?: string | null;
  source?: string | null; url?: string | null;
  location_name?: string | null; country?: string | null;
  lat?: number | null; lon?: number | null;
}
```

Append to `src/services/api.ts` (add the types to the import block):
```ts
export async function getTimeHistogram(
  q: { tStart: string; tEnd: string; buckets?: number; bbox?: [number, number, number, number] },
  signal?: AbortSignal,
): Promise<HistogramResponse> {
  const p = new URLSearchParams({ t_start: q.tStart, t_end: q.tEnd, domain: "events" });
  if (q.buckets) p.set("buckets", String(q.buckets));
  if (q.bbox) p.set("bbox", q.bbox.join(","));
  return fetchJSON<HistogramResponse>(`/timeline/histogram?${p.toString()}`, { signal });
}

export async function getEventDetail(id: string, signal?: AbortSignal): Promise<TimelineEventDetail> {
  return fetchJSON<TimelineEventDetail>(`/timeline/events/${encodeURIComponent(id)}`, { signal });
}
```

- [ ] **Step 5: Run + type-check**

Run: `cd services/frontend && npx vitest run src/lib/__tests__/severity.test.ts && npm run type-check`
Expected: PASS, types clean.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/lib/severity.ts services/frontend/src/lib/__tests__/severity.test.ts services/frontend/src/types/index.ts services/frontend/src/services/api.ts
git commit -m "feat(frontend): severity mirror + histogram/detail types + api clients"
```

---

### Task 8: `useTimeHistogram` hook

**Files:**
- Create: `services/frontend/src/hooks/useTimeHistogram.ts` (+ `__tests__`)

- [ ] **Step 1: Test (RED)** — mirror the `useTimeWindow` test pattern
  (`src/hooks/__tests__/useTimeWindow.test.ts`): fetch-when-enabled with params, no-fetch
  when disabled, abort-on-unmount. Spy on `api.getTimeHistogram`.

```ts
// services/frontend/src/hooks/__tests__/useTimeHistogram.test.ts
import { afterEach, describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useTimeHistogram } from "../useTimeHistogram";

afterEach(() => vi.restoreAllMocks());
const RESP = { t_start: "a", t_end: "b", bucket_ms: 1, buckets: [{ ts: "a", count: 1, dominant_category: "civil", by_category: {}, by_severity: {} }], notables: [], geo_events: [], total_count: 1, geo_located_count: 0, geo_truncated: false } as const;

describe("useTimeHistogram", () => {
  it("fetches when enabled", async () => {
    const spy = vi.spyOn(api, "getTimeHistogram").mockResolvedValue(RESP as never);
    const { result } = renderHook(() => useTimeHistogram(true, { tStart: "a", tEnd: "b", buckets: 120 }));
    await waitFor(() => expect(result.current.data?.buckets.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });
  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getTimeHistogram").mockResolvedValue(RESP as never);
    renderHook(() => useTimeHistogram(false, { tStart: "a", tEnd: "b" }));
    expect(spy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run (RED)** — `npx vitest run src/hooks/__tests__/useTimeHistogram.test.ts` → fails.

- [ ] **Step 3: Implement** — copy the structure of `src/hooks/useTimeWindow.ts` verbatim,
  swapping the call to `getTimeHistogram` and the type to `HistogramResponse`, keeping the
  AbortController + sequence guard + `refreshMs` + skip-when-hidden + the `[enabled, key, refreshMs]`
  dep array (the `key = JSON.stringify(query)` pattern). Returns `{ data, loading }`.

- [ ] **Step 4: Run (GREEN)** + `npm run type-check`.

- [ ] **Step 5: Commit** — `feat(frontend): useTimeHistogram hook (abort + seq guard)`.

---

### Task 9: `ChronikTimeline` — presentational density strip

**Files:**
- Create: `services/frontend/src/components/time/ChronikTimeline.tsx` (+ `__tests__`)

The component is **pure/presentational**: it owns NO data fetching and NO clock. Props:
```ts
interface ChronikTimelineProps {
  buckets: HistogramBucket[];
  notables: TimelineNotable[];
  rangeStartMs: number; rangeEndMs: number;
  cursorMs: number; mode: "live" | "replay"; playing: boolean;
  preset: "24h" | "7d" | "30d";
  geoLocatedCount: number; totalCount: number;
  onSeek: (ms: number) => void;                 // click on strip
  onBrush: (startMs: number, endMs: number) => void;  // drag on strip
  onSelectNotable: (id: string) => void;        // click a notable dot
  onTogglePlay: () => void;
  onNow: () => void;
  onPreset: (p: "24h" | "7d" | "30d") => void;
}
```
Rendering rules (HARD, spec §4/§5): bar height ∝ `count` (max-normalized), bar colour =
`EVENT_COLORS[dominant_category]` (import the map from `EventLayer.tsx`), an x-pixel ←→
time linear map across `[rangeStartMs, rangeEndMs]`, notable dots positioned by time +
coloured/sized by `severityRank`, a playhead at `cursorMs`, controls (▶/⏸, ⏭ NOW, presets),
and the "located: geoLocatedCount / totalCount" honesty line (§8).

- [ ] **Step 1: Test (RED)**

```tsx
// services/frontend/src/components/time/__tests__/ChronikTimeline.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChronikTimeline } from "../ChronikTimeline";
import { EVENT_COLORS } from "../../layers/EventLayer";
import type { HistogramBucket, TimelineNotable } from "../../../types";

const buckets: HistogramBucket[] = [
  { ts: "2026-06-01T00:00:00Z", count: 200, dominant_category: "civil", by_category: { civil: 200, military: 1 }, by_severity: { low: 200, critical: 1 } },
  { ts: "2026-06-01T01:00:00Z", count: 10, dominant_category: "military", by_category: { military: 10 }, by_severity: { high: 10 } },
];
const notables: TimelineNotable[] = [
  { id: "n1", time: "2026-06-01T00:45:00Z", time_basis: "indexed", severity: "critical", title: "Strike", is_incident: true, rank: 0 },
];
const base = {
  buckets, notables, rangeStartMs: Date.parse("2026-06-01T00:00:00Z"),
  rangeEndMs: Date.parse("2026-06-01T02:00:00Z"), cursorMs: Date.parse("2026-06-01T01:00:00Z"),
  mode: "live" as const, playing: true, preset: "7d" as const,
  geoLocatedCount: 3, totalCount: 210,
  onSeek: vi.fn(), onBrush: vi.fn(), onSelectNotable: vi.fn(),
  onTogglePlay: vi.fn(), onNow: vi.fn(), onPreset: vi.fn(),
};

describe("ChronikTimeline", () => {
  it("colours bars by dominant_category via EVENT_COLORS (NOT severity)", () => {
    render(<ChronikTimeline {...base} />);
    const bars = screen.getAllByTestId("chronik-bar");
    expect(bars[0]).toHaveStyle(`background: ${EVENT_COLORS.civil}`);   // civil, not critical
    expect(bars[1]).toHaveStyle(`background: ${EVENT_COLORS.military}`);
  });
  it("renders one notable dot and selecting it calls onSelectNotable", () => {
    render(<ChronikTimeline {...base} />);
    const dot = screen.getByRole("button", { name: /Strike/i });
    fireEvent.click(dot);
    expect(base.onSelectNotable).toHaveBeenCalledWith("n1");
  });
  it("shows the located honesty line", () => {
    render(<ChronikTimeline {...base} />);
    expect(screen.getByText(/3\s*\/\s*210/)).toBeInTheDocument();
  });
  it("click on the strip seeks (does not brush)", () => {
    render(<ChronikTimeline {...base} />);
    const strip = screen.getByTestId("chronik-strip");
    fireEvent.mouseDown(strip, { clientX: 10 });
    fireEvent.mouseUp(strip, { clientX: 10 });   // no drag -> click
    expect(base.onSeek).toHaveBeenCalledTimes(1);
    expect(base.onBrush).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run (RED)** — module missing.

- [ ] **Step 3: Implement `ChronikTimeline.tsx`** — bars (`data-testid="chronik-bar"`,
  height = `count / maxCount`, `background: EVENT_COLORS[dominant_category] ?? DEFAULT_COLOR`),
  the strip container (`data-testid="chronik-strip"`) with `onMouseDown`/`onMouseMove`/`onMouseUp`
  that distinguish click (no/small drag → `onSeek(xToMs(clientX))`) from drag (≥6px →
  `onBrush(start,end)`), notable dots as `<button>` labelled by `title ?? codebook_type ?? id`
  positioned via `msToX(time)` and coloured by `severityRank`, the playhead at `msToX(cursorMs)`,
  the controls row (`▶/⏸` → `onTogglePlay`, `⏭ NOW` → `onNow`, preset chips → `onPreset`),
  and the `located: {geoLocatedCount} / {totalCount}` line. Pure inline Hlíðskjalf tokens
  (final visuals in Task 14's frontend-design pass).

- [ ] **Step 4: Run (GREEN)** + `npm run type-check` + eslint on the new files.

- [ ] **Step 5: Commit** — `feat(frontend): ChronikTimeline density strip (category bars + notable dots + click/brush)`.

---

### Task 10: Make `EventLayer` time-aware (fade by window/cursor), fed by geo_events

**Files:**
- Modify: `services/frontend/src/components/layers/EventLayer.tsx`
- Test: `services/frontend/src/components/layers/__tests__/EventLayer.fade.test.ts`

Add two optional props (keeping the existing `{viewer, events, visible}` contract so the
component still works if unused): `getTimeMs?: () => number` and
`window?: { startMs: number; endMs: number } | null`. When `window` is provided, each
billboard's alpha is governed by the §7 fade rule, recomputed on the existing
`clock.onTick` (add a tick subscription mirroring `MilAircraftLayer`):
- event time inside `[startMs, endMs]` **and** within the cursor band → full alpha;
- within a small falloff band around the cursor → linear alpha;
- outside `[startMs, endMs]` → alpha 0 (hidden).

- [ ] **Step 1: Test (RED)** — extract the pure fade function and test it:

```ts
// services/frontend/src/components/layers/__tests__/EventLayer.fade.test.ts
import { describe, it, expect } from "vitest";
import { fadeAlpha } from "../EventLayer";

describe("EventLayer fadeAlpha (§7)", () => {
  const win = { startMs: 0, endMs: 100 };
  it("outside the window -> 0", () => {
    expect(fadeAlpha(-1, 50, win, 10)).toBe(0);
    expect(fadeAlpha(101, 50, win, 10)).toBe(0);
  });
  it("at the cursor -> full", () => {
    expect(fadeAlpha(50, 50, win, 10)).toBeCloseTo(1);
  });
  it("near the cursor -> linear falloff", () => {
    expect(fadeAlpha(55, 50, win, 10)).toBeCloseTo(0.5);
  });
  it("in-window but far from cursor -> floor (still faintly visible)", () => {
    expect(fadeAlpha(90, 50, win, 10)).toBeGreaterThan(0);
    expect(fadeAlpha(90, 50, win, 10)).toBeLessThan(0.5);
  });
});
```

- [ ] **Step 2: Run (RED)** — `fadeAlpha` not exported.

- [ ] **Step 3: Implement** — export the pure `fadeAlpha`:

```ts
// add to EventLayer.tsx
export function fadeAlpha(
  eventMs: number, cursorMs: number,
  window: { startMs: number; endMs: number }, falloffMs: number,
): number {
  if (eventMs < window.startMs || eventMs > window.endMs) return 0;
  const d = Math.abs(eventMs - cursorMs);
  if (d <= falloffMs) return 1 - 0.5 * (d / Math.max(falloffMs, 1)); // 1.0 → 0.5 across the band
  const FLOOR = 0.18;  // in-window but far: faint
  return FLOOR;
}
```

Then wire it: add a `clock.onTick` effect (only when `getTimeMs` + `window` present) that
sets each placement's billboard `.color = base.withAlpha(fadeAlpha(eventMs, getTimeMs(), window, falloffMs))`,
with `falloffMs = (window.endMs - window.startMs) * 0.05`. Keep the existing pulse logic;
the alpha multiplies onto it. When `window` is null, behave exactly as today.

- [ ] **Step 4: Run (GREEN)** — fade test + existing `EventLayer` tests + `npm run type-check`.

- [ ] **Step 5: Commit** — `feat(frontend): time-aware EventLayer fade (§7) without breaking live use`.

---

### Task 11: `EventCallout` (single, detail-fetched)

**Files:**
- Create: `services/frontend/src/components/time/EventCallout.tsx` (+ `__tests__`)

A controlled component: prop `eventId: string | null` and `onClose`. On `eventId` change it
calls `getEventDetail(id)` (AbortController; clears on null), renders a single Hlíðskjalf box
(`title ?? codebook_type ?? id`, `time · time_basis · source · severity`, a `→ Inspector`
button via an `onInspect` callback), and a loading state while the detail resolves.

- [ ] **Step 1: Test (RED)** — render with `eventId="e1"`, mock `getEventDetail` resolving
  `{id:"e1", title:"Strike", time:"…", time_basis:"indexed", source:"gdelt", severity:"critical"}`;
  `waitFor` the title; assert one box; assert `eventId={null}` renders nothing.
- [ ] **Step 2: Run (RED).**
- [ ] **Step 3: Implement** `EventCallout.tsx` (mirror the abort pattern from `useTimeWindow`).
- [ ] **Step 4: Run (GREEN)** + type-check.
- [ ] **Step 5: Commit** — `feat(frontend): single EventCallout (detail-fetched)`.

---

### Task 12: Rewire `ScrubberMount` to drive ChronikTimeline + delete TwoTierScrubber

**Files:**
- Modify: `services/frontend/src/components/time/ScrubberMount.tsx`
- Delete: `services/frontend/src/components/time/TwoTierScrubber.tsx` + `__tests__/TwoTierScrubber.test.tsx`
- Test: `services/frontend/src/components/time/__tests__/ScrubberMount.test.tsx` (update)

`ScrubberMount` (already a `useTime()` consumer) now:
- calls `useTimeHistogram(true, { tStart: coarse.tStart, tEnd: coarse.tEnd, buckets: 120 }, 30_000)`
  over the rolling coarse window (keep the existing 60s roll + preset state; add `preset`
  state defaulting `"7d"` controlling the coarse span: 24h/7d/30d);
- renders `<ChronikTimeline>` with `{buckets, notables, …}` and callbacks:
  - `onSeek={(ms) => { pause(); seek(ms); }}` (HARD §5 — pause so the cursor holds in live),
  - `onBrush={(s,e) => { setReplayWindow(s,e); setMode("replay"); seek(s); }}`,
  - `onSelectNotable={(id) => setSelectedEventId(id)}` (lifts selection to WorldviewPage in Task 13),
  - `onTogglePlay={() => (playing ? pause() : play())}`,
  - `onNow={() => { setMode("live"); play(); }}`,
  - `onPreset={setPreset}` (changes coarse span only — must NOT reset selection/mode/playing);
- exposes `geo_events` (from the histogram) upward so WorldviewPage feeds `EventLayer` (Task 13).

- [ ] **Step 1: Update the test (RED)** — replace the TwoTierScrubber-based assertions with:
  click a bar/strip → `seek` called after `pause`; toggle preset → histogram refetched with
  new span, mode/selection unchanged; render uses ChronikTimeline (query `chronik-strip`).
  (Reuse the fake-viewer + `getTimeHistogram` mock patterns.)
- [ ] **Step 2: Run (RED).**
- [ ] **Step 3: Implement** the rewire; `git rm` the `TwoTierScrubber.tsx` + its test;
  ensure no remaining import of `TwoTierScrubber` (grep).
- [ ] **Step 4: Run (GREEN)** + `npm run type-check`.
- [ ] **Step 5: Commit** — `feat(frontend): ScrubberMount drives ChronikTimeline; remove TwoTierScrubber text-wall`.

---

### Task 13: Wire WorldviewPage — histogram-driven EventLayer + callout + bottom layout

**Files:**
- Modify: `services/frontend/src/pages/WorldviewPage.tsx`
- Test: manual (browser) — see Final Verification.

- [ ] **Step 1:** Lift `selectedEventId` + `geoEvents` + the active `window` into the
  `GlobeChildren`/`WorldviewPage` boundary (inside `<TimeProvider>`), threaded from
  `ScrubberMount`. Replace the `useEvents`→`EventLayer` feed: build `EventLayer.events`
  from the histogram `geo_events` (mapped to the `IntelEvent` shape) and pass
  `getTimeMs` + the active `window` (replay brush, or a live trailing band ~6h ending now).
  Keep the `layers.events` visibility toggle.
- [ ] **Step 2:** Mount `<EventCallout eventId={selectedEventId} onClose={() => setSelectedEventId(null)} onInspect={…open InspectorPanel…} />`.
- [ ] **Step 3:** Raise the bottom-left panels' `bottom` offset so nothing overlaps the
  full-width `§ CHRONIK` strip; mount the strip via `ScrubberMount` at the very bottom.
- [ ] **Step 4:** `cd services/frontend && npm run type-check && npm run test && npm run build`
  — all green.
- [ ] **Step 5: Commit** — `feat(frontend): wire histogram-driven EventLayer + ChronikTimeline + callout in WorldviewPage`.

---

### Task 14: frontend-design pass (visual polish)

**Files:** `ChronikTimeline.tsx`, `EventCallout.tsx`, `EventLayer.tsx` styling only.

- [ ] Invoke the **frontend-design** skill to finalize: bar/dot styling within Hlíðskjalf-Noir
  (using `EVENT_COLORS` for category, `severityRank` for dot emphasis), the playhead +
  brush handles, the callout box + connector line, the controls/preset chips, the strip's
  glass/scanline treatment. No behavioural changes; keep all tests green.
- [ ] Run `npm run type-check && npm run test && npm run build`; commit
  `style(frontend): Hlíðskjalf-Noir polish for ChronikTimeline + callout`.

---

## Final Verification (end-to-end)

- [ ] **Backend:** `cd services/backend && NEO4J_PASSWORD=ci-test-password uv run pytest -q && uv run ruff check app/ tests/`
- [ ] **Frontend:** `cd services/frontend && npm run type-check && npm run test && npm run build`
- [ ] **Browser (`npm run dev`, against the deployed stack):**
  - the globe is **clear** — no text wall; the `§ CHRONIK` strip is a thin bottom bar.
  - bars are **category-coloured** (civil/military/…); a dense GDELT bucket is NOT painted
    by a lone critical; severity surfaces only as notable dots + the optional tick.
  - clicking the strip **pauses live + seeks** (cursor holds, doesn't snap to now); `⏭ NOW`
    resumes live; dragging brushes a window → replay; preset 24h/7d/30d changes span only.
  - geo-events appear as **time-faded dots on the globe** (in-window full, near falloff,
    outside hidden); clicking a notable/dot opens **one** callout (detail-fetched).
  - the "located: X / Y" line is honest about non-geo events.

---

## Self-Review

**Spec coverage:** §3 architecture → Tasks 1,3,6,8,9,10,11,12,13. §4 bars (dominant_category
modal, EVENT_COLORS) → Tasks 1,3,9. §4 notables (cap40/rank/incident-union) → Task 4.
§5 cursor=pause+seek / drag=brush / preset-no-reset → Tasks 9,12. §6 single callout +
detail endpoint → Tasks 6,11,13. §7 geo_events + EventLayer fade → Tasks 5,10,13. §8 non-geo
honesty line → Tasks 3,9. §9.1 histogram → Tasks 3,4,5. §9.2 detail → Task 6. §11 tests →
each task. §12 severity normalizer keystone → Task 1; incident-union → Task 4; EventLayer
repurpose → Tasks 10,12,13.

**Type consistency:** `HistogramResponse/HistogramBucket/TimelineNotable/TimelineGeoEvent/
TimelineEventDetail` field names match backend models (Tasks 2,7). `normalizeSeverity/
severityRank` mirror `normalize_severity/severity_rank`. `EVENT_COLORS` imported from
`EventLayer.tsx` is the single category-colour source (Tasks 9,13). `fadeAlpha` signature
matches between Task 10 export and its WorldviewPage use.

**Known follow-ups (not blockers):** the Slice-0 phase-3 `CALL {}` deprecation; event geo
backfill (Slice 1) would make the globe denser; civil movements (Slice 2).
