# T4 — Geo Correctness Implementation Plan (WP-05/06/07/11)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last 4 write-path geo defects so the globe/CHRONIK never silently plots wrong-country, ingest-anchored, collided, or null-island geo — and so the acceptance metric (`report.py`) stops masking them.

**Architecture:** Forward-fix every write path so NEW data is correct (single-distinct-country geo guard, GDELT `seendate` → `observed_at`, coordinate-bearing incident `loc_key`, `(0,0)` null-island guard on both writers). Then add idempotent, dry-run-first repair jobs for the two repairable legacy defects (WP-07 collided incident Locations, WP-11 null-island nodes) plus a `Location.loc_key` uniqueness constraint. WP-05 wrong-country edges and WP-06 mis-anchored GDELT timestamps are **re-ingestion-only** (per-event country / real seen-date were never stored) and are documented as such, never silently claimed fixed.

**Tech Stack:** Python 3.11 (data-ingestion + backend), pytest (`asyncio_mode = auto`), polars, Neo4j 5 Community (HTTP transactional API via `Neo4jClient` / httpx), structlog.

**Source of truth:** spec `docs/superpowers/specs/2026-06-15-writepath-graph-integrity-fixes-design.md` (§ T4, lines 227-265); audit `docs/writepath-graph-integrity-audit-2026-06-14.md` (WP-05/06/07/11). All line numbers below are the **current post-T1/T2/T3/T5 worktree** (the audit's numbers are pre-T1 and stale).

---

## Key facts established by grounding (do not re-derive)

- **WP-06 plumbing already exists:** `process_item` forwards `observed_at` → `_write_to_neo4j` (`pipeline.py:365-367`); `_resolve_timeline` honors `observed_at` at precedence 2 (`pipeline.py:78-85`). **The fix is collector-only** — `feeds/gdelt_collector.py` must normalize `seendate` and pass `observed_at=`.
- **WP-05 helper already imported:** `pipeline.py:24` imports `resolve_iso2` (and `centroid_for`); `build_event_geo_fragment(None)` already returns `None`. The fix is a one-block change to how `doc_country` is derived.
- **`resolve_iso2(value)`** (`graph_integrity/country_centroids.py:860`) → canonical uppercase ISO-2 or `None`; **idempotent** on an ISO-2 code (`resolve_iso2("UA") == "UA"`).
- **`gdelt_raw/geo.py` is confirmed dead** (only its own test imports `build_location_payload`; zero production callers). It is the only place that already drops `(0,0)`; the **live** writer `location_params_for` and the backfill `build_geo_row` both have the identical None-only gap.
- **Geo repair jobs use the `Neo4jClient.run(cypher, params)` interface** (like `geo_incident.run` / `geo_gdelt.run`), are wired as `cli.py` subcommands with `--dry-run`, and are tested with a `_FakeClient` that records `.calls`. The two new repair jobs follow this pattern (NOT the lower-level `driver.session()` pattern of `backfill_event_key.py`).
- **Vendored backend loc_key copy** is `services/backend/app/services/_loc_key.py` (imported by `app/services/incident_store.py:20`). Parity is guarded by mirror-assertion tests in `services/backend/tests/test_incident_write_geo.py` (backend cannot import data-ingestion).
- **Neo4j 5 Community supports single-property uniqueness constraints** (`REQUIRE l.loc_key IS UNIQUE`) — see the note in `migrations/neo4j_entity_name_type_unique.cypher`.
- **Cross-test imports work:** new data-ingestion tests use `from tests.test_pipeline import _make_settings` (package-qualified, as `test_pipeline_timeline_at.py:4` does).
- **Worktree root** (substitute for `<worktree-root>` in every `git` step): `/home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/t4-geo`. Always `cd` there before `git add` (avoids the cwd-doubling trap); stage only the named files, never `git add -A` (untracked cruft exists: `attachments/`, `backups/`, `test.html`, etc.).

---

## File Structure

**Forward fixes (re-ingestion-only legacy):**
- `services/data-ingestion/pipeline.py` — WP-05 single-distinct-country geo guard (modify ~`:565-567`).
- `services/data-ingestion/feeds/gdelt_collector.py` — WP-06 `_normalize_seendate` helper + `observed_at=` (modify ~`:164`, `:174-183`).

**Forward fixes (with repair):**
- `services/data-ingestion/graph_integrity/loc_key.py` — WP-07 coordinate-bearing `incident_key` (modify `:19-22`).
- `services/backend/app/services/_loc_key.py` — WP-07 identical change (modify `:16-19`).
- `services/data-ingestion/graph_integrity/geo_gdelt.py` — WP-11 `(0,0)`+empty-id guard in `build_geo_row` (modify `:49-63`) + docstring L6-a fix (`:1-3`).
- `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py` — WP-11 `(0,0)`+empty-id guard in `location_params_for` (modify `:113-127`).
- `services/data-ingestion/gdelt_raw/ids.py` — WP-11 `build_location_id` refuses all-empty tuple → `None` (modify `:28-35`).
- `services/data-ingestion/gdelt_raw/geo.py` — **delete** (dead code).
- `services/data-ingestion/graph_integrity/report.py` — honest GEO_COVERAGE + COORD_DISAGREEMENT + NULL_ISLAND queries, `shape_report` (modify).
- `services/data-ingestion/graph_integrity/cli.py` — wire new report queries + 2 new repair subcommands.

**Repair jobs + constraint (new):**
- `services/data-ingestion/graph_integrity/rekey_incident_locations.py` — WP-07 re-key/split (dry-run first).
- `services/data-ingestion/migrations/location_loc_key_unique.cypher` — constraint (apply after rekey + preflight).
- `services/data-ingestion/graph_integrity/cleanup_null_island.py` — WP-11 `(0,0)` node cleanup (dry-run first).

**Tests:** new `test_pipeline_geo_single_country.py`, `test_gdelt_seendate.py`, `test_rekey_incident_locations.py`, `test_cleanup_null_island.py`; modified `test_loc_key.py`, `test_geo_incident.py`, `test_geo_gdelt.py`, `test_gdelt_writer_geo.py`, `test_gdelt_ids.py`, `test_graph_integrity_report.py`, `test_collector_time_passthrough.py`; **deleted** `test_gdelt_geo.py`; backend `test_incident_write_geo.py` modified.

**Run tests:** `cd services/data-ingestion && python3 -m pytest tests/ -q` (asyncio auto, excludes `live`); `cd services/backend && python3 -m pytest tests/ -q`.

---

### Task 1: WP-05 — geo-stamp only single-distinct-country documents

**Files:**
- Modify: `services/data-ingestion/pipeline.py` (the `doc_country` derivation, currently one line just before the per-event loop, ~`:565-567`)
- Test: `services/data-ingestion/tests/test_pipeline_geo_single_country.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `services/data-ingestion/tests/test_pipeline_geo_single_country.py`:

```python
"""WP-05: a document is geo-stamped only when it resolves to exactly ONE distinct
country. Multi-country docs stay geoless (honest located:0) instead of plotting
every event onto the first location's country centroid."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipeline import _write_to_neo4j
from tests.test_pipeline import _make_settings


async def _geo_statements(events, locations):
    """Run _write_to_neo4j with the given locations; return posted Cypher statements."""
    captured = {}

    async def _post(url, json, auth):  # noqa: A002 — mirror httpx kwarg name
        captured["statements"] = json["statements"]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"results": [], "errors": []}
        return resp

    client = AsyncMock()
    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("pipeline.httpx.AsyncClient", return_value=cm):
        await _write_to_neo4j(
            events, [], "http://u", "doc title", "rss", _make_settings(),
            locations=locations,
        )
    return captured["statements"]


def _has_occurred_at(stmts):
    return any("OCCURRED_AT" in s["statement"] for s in stmts)


def _occurred_loc_key(stmts):
    for s in stmts:
        if "OCCURRED_AT" in s["statement"]:
            return s["parameters"].get("loc_key")
    return None


@pytest.mark.asyncio
async def test_single_country_single_location_stamps_centroid():
    stmts = await _geo_statements(
        [{"title": "Strike on Kyiv", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}],
    )
    assert _has_occurred_at(stmts)
    assert _occurred_loc_key(stmts) == "centroid:ua"


@pytest.mark.asyncio
async def test_single_country_multiple_locations_still_stamps():
    # multiple place names in the SAME country → still centroid-stampable
    stmts = await _geo_statements(
        [{"title": "Strikes across Ukraine", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}, {"name": "Odessa", "country": "Ukraine"}],
    )
    assert _has_occurred_at(stmts)
    assert _occurred_loc_key(stmts) == "centroid:ua"


@pytest.mark.asyncio
async def test_multi_country_document_is_geoless():
    stmts = await _geo_statements(
        [{"title": "Russia strikes Kyiv; US sanctions Iran", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}, {"name": "Tehran", "country": "Iran"}],
    )
    assert not _has_occurred_at(stmts)


@pytest.mark.asyncio
async def test_known_plus_unresolvable_country_is_geoless():
    # {UA, None} → 2 distinct → geoless (conservative; we are unsure)
    stmts = await _geo_statements(
        [{"title": "x", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}, {"name": "Nowhere", "country": "Atlantis"}],
    )
    assert not _has_occurred_at(stmts)


@pytest.mark.asyncio
async def test_empty_locations_is_geoless():
    stmts = await _geo_statements(
        [{"title": "x", "codebook_type": "conflict.armed_clash"}], [],
    )
    assert not _has_occurred_at(stmts)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_pipeline_geo_single_country.py -q`
Expected: `test_multi_country_document_is_geoless` and `test_known_plus_unresolvable_country_is_geoless` FAIL (current code stamps the first location's country regardless).

- [ ] **Step 3: Implement the single-distinct-country guard**

In `services/data-ingestion/pipeline.py`, replace the existing `doc_country` derivation:

```python
    # Derive coarse document country for geo-tagging events (country-centroid).
    doc_country = next((loc["country"] for loc in (locations or []) if loc.get("country")), None)
```

with:

```python
    # Geo-stamp events only when the document resolves to exactly ONE distinct
    # country (WP-05). Multiple place names within the same country stay
    # centroid-stampable, but a multi-country document is left geoless (honest
    # located:0) instead of collapsing every event onto whichever country the
    # LLM happened to emit first. resolve_iso2 maps name/code -> canonical
    # ISO-2 (or None) and is idempotent on an ISO-2 code.
    iso2s = {resolve_iso2(loc.get("country")) for loc in (locations or [])}
    doc_country = next(iter(iso2s)) if len(iso2s) == 1 else None
```

(When `iso2s == {None}` — a single unresolvable country — `doc_country` is `None` and `build_event_geo_fragment` already returns `None`, so the event stays geoless.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_pipeline_geo_single_country.py -q`
Expected: 5 passed.

- [ ] **Step 5: Run the broader pipeline suite + ruff (no regressions)**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_pipeline.py tests/test_pipeline_dual_write.py tests/test_pipeline_rss_geo.py tests/test_pipeline_timeline_at.py -q && python3 -m ruff check pipeline.py tests/test_pipeline_geo_single_country.py`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/pipeline.py services/data-ingestion/tests/test_pipeline_geo_single_country.py
git commit -m "fix(ingestion): geo-stamp events only for single-distinct-country docs (WP-05)"
```

---

### Task 2: WP-06 — forward GDELT `seendate` as `observed_at`

**Files:**
- Modify: `services/data-ingestion/feeds/gdelt_collector.py` (add `_normalize_seendate`; pass `observed_at=` in the `process_item` call ~`:174-183`)
- Test: `services/data-ingestion/tests/test_gdelt_seendate.py` (create); `services/data-ingestion/tests/test_collector_time_passthrough.py` (add a passthrough assertion)

- [ ] **Step 1: Write the failing normalizer tests**

Create `services/data-ingestion/tests/test_gdelt_seendate.py`:

```python
"""WP-06: GDELT ArtList seendate -> ISO-8601 observed_at. Empty/malformed -> None
(falls back to the ingested basis; never fabricates a fake instant)."""
from feeds.gdelt_collector import _normalize_seendate


def test_full_timestamp_to_iso():
    assert _normalize_seendate("20260610T120000Z") == "2026-06-10T12:00:00+00:00"


def test_date_only_anchors_to_utc_midnight():
    # lower-resolution but correct DAY -> correct CHRONIK bucket; strictly better
    # than drifting to ingest-time. (Real GDELT seendate is the full timestamp.)
    assert _normalize_seendate("20260610") == "2026-06-10T00:00:00+00:00"


def test_empty_is_none():
    assert _normalize_seendate("") is None
    assert _normalize_seendate(None) is None


def test_malformed_is_none():
    assert _normalize_seendate("last tuesday") is None
    assert _normalize_seendate("2026-06-10") is None  # dashed form is not GDELT's
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_gdelt_seendate.py -q`
Expected: FAIL with `ImportError: cannot import name '_normalize_seendate'`.

- [ ] **Step 3: Implement `_normalize_seendate`**

In `services/data-ingestion/feeds/gdelt_collector.py`, add a module-level helper (place it near the top, after imports — `datetime` and `UTC` are already imported, used by `datetime.now(UTC)`):

```python
def _normalize_seendate(seendate: str | None) -> str | None:
    """GDELT ArtList seendate ('20260610T120000Z' or '20260610') -> ISO-8601 UTC,
    or None when empty/malformed. Never fabricates: an unparseable value returns
    None so the pipeline's _resolve_timeline falls back to the ingested basis."""
    if not seendate or not isinstance(seendate, str):
        return None
    s = seendate.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
    return None
```

- [ ] **Step 4: Run to verify the normalizer passes**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_gdelt_seendate.py -q`
Expected: 4 passed.

- [ ] **Step 5: Forward `observed_at` in the collector**

In `services/data-ingestion/feeds/gdelt_collector.py`, in the `process_item(...)` call inside `_ingest_articles`, add the `observed_at` kwarg (the `seendate` local is already read at `:164`):

```python
                enrichment = await process_item(
                    title=title,
                    text=embed_text,
                    url=url,
                    source="gdelt",
                    settings=settings,
                    redis_client=self._redis,
                    observed_at=_normalize_seendate(seendate),
                    content_hash=chash,
                    raise_on_write_error=True,
                )
```

- [ ] **Step 6: Add the passthrough assertion**

In `services/data-ingestion/tests/test_collector_time_passthrough.py`, extend the collector import (line 12) to include `gdelt_collector`:

```python
from feeds import firms_collector, gdelt_collector, rss_collector, usgs_collector
```

and add the assertion:

```python
def test_gdelt_passes_observed_at():
    assert "observed_at" in _process_item_kwargs(gdelt_collector)
```

- [ ] **Step 7: Run collector + timeline suites + ruff**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_gdelt_seendate.py tests/test_gdelt_collector.py tests/test_collector_time_passthrough.py tests/test_pipeline_timeline_at.py -q && python3 -m ruff check feeds/gdelt_collector.py tests/test_gdelt_seendate.py`
Expected: all pass, ruff clean.

- [ ] **Step 8: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/feeds/gdelt_collector.py services/data-ingestion/tests/test_gdelt_seendate.py services/data-ingestion/tests/test_collector_time_passthrough.py
git commit -m "fix(ingestion): forward GDELT seendate as observed_at timeline basis (WP-06)"
```

---

### Task 3: WP-07 forward — coordinate-bearing incident `loc_key`

**Files:**
- Modify: `services/data-ingestion/graph_integrity/loc_key.py` (`incident_key` `:19-22`)
- Modify: `services/backend/app/services/_loc_key.py` (`incident_key` `:16-19`, identical)
- Modify tests: `services/data-ingestion/tests/test_loc_key.py`, `services/data-ingestion/tests/test_geo_incident.py`, `services/backend/tests/test_incident_write_geo.py`

- [ ] **Step 1: Update the canonical loc_key tests (red)**

In `services/data-ingestion/tests/test_loc_key.py`, replace `test_incident_key_prefers_name_else_rounded_coords` with:

```python
def test_incident_key_is_coordinate_bearing():
    # name + coords -> name AND coords (WP-07): distinct coords => distinct key
    assert incident_key("Donetsk", 48.0159, 37.8028) == "incident:donetsk@48.016,37.803"
    # same name, different coords must NOT collide (the bug this fixes)
    assert incident_key("Donetsk", 48.0159, 37.8028) != incident_key("Donetsk", 49.0, 38.0)
    # no name -> coord key (unchanged)
    assert incident_key("", 48.0159, 37.8028) == "geo:48.016,37.803"
    assert incident_key(None, 48.0159, 37.8028) == "geo:48.016,37.803"
```

In `services/data-ingestion/tests/test_geo_incident.py`, update `test_build_wire_params_uses_incident_key` so the expected `loc_key` is coordinate-bearing:

```python
def test_build_wire_params_uses_incident_key():
    row = {"id": "inc1", "location": "Donetsk", "lat": 48.0, "lon": 37.8}
    p = build_wire_params(row)
    assert p == {
        "incident_id": "inc1", "loc_key": "incident:donetsk@48.000,37.800",
        "lat": 48.0, "lon": 37.8, "location": "Donetsk",
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_loc_key.py tests/test_geo_incident.py -q`
Expected: FAIL (`incident:donetsk` != `incident:donetsk@48.016,37.803`).

- [ ] **Step 3: Implement the coordinate-bearing key (canonical)**

In `services/data-ingestion/graph_integrity/loc_key.py`, replace `incident_key`:

```python
def incident_key(name: str | None, lat: float, lon: float) -> str:
    # Coordinates are ALWAYS part of the identity, even when a name is present
    # (WP-07): two distinct incidents that share a location slug but sit at
    # different coordinates must NOT collapse onto the same :Location node.
    if name and name.strip():
        return f"incident:{slug(name)}@{lat:.3f},{lon:.3f}"
    return f"geo:{lat:.3f},{lon:.3f}"
```

- [ ] **Step 4: Run to verify canonical passes**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_loc_key.py tests/test_geo_incident.py -q`
Expected: passed.

- [ ] **Step 5: Update the backend parity tests (red)**

In `services/backend/tests/test_incident_write_geo.py`, update both expectations to the coordinate-bearing form:

```python
def test_vendored_loc_key_matches_canonical():
    assert incident_key("Donetsk", 48.0, 37.8) == "incident:donetsk@48.000,37.800"
    assert incident_key("", 48.0, 37.8) == "geo:48.000,37.800"
```

```python
def test_upsert_params_sets_loc_key():
    assert incident_key("Donetsk", 48.0, 37.8) == "incident:donetsk@48.000,37.800"
    assert incident_key("", 48.0, 37.8) == "geo:48.000,37.800"
```

- [ ] **Step 6: Implement the identical change in the vendored copy**

In `services/backend/app/services/_loc_key.py`, replace `incident_key` with the **byte-identical** body (keeping the vendored module's own docstring/header):

```python
def incident_key(name: str | None, lat: float, lon: float) -> str:
    # Coordinates are ALWAYS part of the identity, even when a name is present
    # (WP-07): two distinct incidents that share a location slug but sit at
    # different coordinates must NOT collapse onto the same :Location node.
    if name and name.strip():
        return f"incident:{slug(name)}@{lat:.3f},{lon:.3f}"
    return f"geo:{lat:.3f},{lon:.3f}"
```

- [ ] **Step 7: Run backend + data-ingestion loc_key suites + ruff**

Run:
```
cd services/data-ingestion && python3 -m pytest tests/test_loc_key.py tests/test_geo_incident.py -q && python3 -m ruff check graph_integrity/loc_key.py
cd ../backend && python3 -m pytest tests/test_incident_write_geo.py -q && python3 -m ruff check app/services/_loc_key.py
```
Expected: all pass, ruff clean.

- [ ] **Step 8: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/graph_integrity/loc_key.py services/data-ingestion/tests/test_loc_key.py services/data-ingestion/tests/test_geo_incident.py services/backend/app/services/_loc_key.py services/backend/tests/test_incident_write_geo.py
git commit -m "fix(geo): coordinate-bearing incident loc_key on both write paths (WP-07 forward)"
```

> **Note for the repair task (Task 6):** after this change, an incident re-upserted before the repair runs will temporarily hold OCCURRED_AT edges to both its old name-only Location and the new coord-bearing one. Task 6's rewire deletes the stale edges and cleans orphaned `incident:`-prefixed Locations.

---

### Task 4: WP-11 forward — drop `(0,0)` null-island + empty-id locations on both writers; delete dead `geo.py`

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/ids.py` (`build_location_id` `:28-35`)
- Modify: `services/data-ingestion/graph_integrity/geo_gdelt.py` (`build_geo_row` `:49-63` + module docstring `:1-3`)
- Modify: `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py` (`location_params_for` `:113-127`)
- Delete: `services/data-ingestion/gdelt_raw/geo.py`, `services/data-ingestion/tests/test_gdelt_geo.py`
- Modify tests: `services/data-ingestion/tests/test_gdelt_ids.py`, `tests/test_geo_gdelt.py`, `tests/test_gdelt_writer_geo.py`

- [ ] **Step 1: Write failing tests for all three guards**

In `services/data-ingestion/tests/test_gdelt_ids.py`, add:

```python
def test_location_id_all_empty_tuple_is_none():
    # no feature_id, no country, no name -> no usable identity (WP-11);
    # must NOT return a shared 'gdelt:loc::' key.
    assert build_location_id(feature_id="", country_code="", name="") is None
```

In `services/data-ingestion/tests/test_geo_gdelt.py`, add:

```python
def test_build_geo_row_null_island_is_none():
    raw = {"global_event_id": 7, "action_geo_lat": 0.0, "action_geo_long": 0.0,
           "action_geo_feature_id": "", "action_geo_country_code": "", "action_geo_fullname": ""}
    assert build_geo_row(raw) is None


def test_build_geo_row_valid_coords_but_empty_ids_is_none():
    raw = {"global_event_id": 8, "action_geo_lat": 12.3, "action_geo_long": 45.6,
           "action_geo_feature_id": "", "action_geo_country_code": "", "action_geo_fullname": ""}
    assert build_geo_row(raw) is None
```

In `services/data-ingestion/tests/test_gdelt_writer_geo.py`, add (mirror the existing `GDELTEventWrite` construction style):

```python
def test_location_params_null_island_is_none():
    ev = GDELTEventWrite(
        event_id="gdelt:event:3", cameo_code="010", cameo_root=1, quad_class=1,
        goldstein=0.0, avg_tone=0.0, num_mentions=1, num_sources=1, num_articles=1,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://z", codebook_type="other.unclassified", filter_reason="tactical",
        action_geo_lat=0.0, action_geo_long=0.0, action_geo_fullname="",
        action_geo_country_code="", action_geo_feature_id="",
    )
    assert location_params_for(ev) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_gdelt_ids.py tests/test_geo_gdelt.py tests/test_gdelt_writer_geo.py -q`
Expected: the 4 new tests FAIL (current None-only guards let `(0,0)` and the shared empty key through).

- [ ] **Step 3: `build_location_id` refuses the all-empty tuple**

In `services/data-ingestion/gdelt_raw/ids.py`, replace `build_location_id`:

```python
def build_location_id(
    feature_id: str = "",
    country_code: str = "",
    name: str = "",
) -> str | None:
    """gdelt:loc:<feature_id>  OR  gdelt:loc:<cc>:<slugged_name> as fallback.

    Returns None for an all-empty id tuple (WP-11): without any of feature_id,
    country_code or name there is no meaningful identity, and a shared
    'gdelt:loc::' key would collapse every such location onto one node."""
    if feature_id:
        return f"gdelt:loc:{feature_id}"
    if not country_code and not name:
        return None
    return f"gdelt:loc:{country_code.lower()}:{_slug(name)}"
```

- [ ] **Step 4: `build_geo_row` — `(0,0)` guard + None-loc_key guard + docstring fix**

In `services/data-ingestion/graph_integrity/geo_gdelt.py`, fix the module docstring (L6-a):

```python
"""GDELT-Event-Geo backfill. Events ingested before the geo-carrying transform
landed (2026-06-14) are geoless in Neo4j even though the RAW export carries valid
action_geo, so re-fetch the RAW export slices, parse action_geo, and write
OCCURRED_AT for those pre-existing events. Idempotent + resumable (per-slice)."""
```

and replace `build_geo_row`:

```python
def build_geo_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    lat = raw.get("action_geo_lat")
    lon = raw.get("action_geo_long")
    if lat is None or lon is None:
        return None
    if lat == 0.0 and lon == 0.0:  # GDELT null-island sentinel (WP-11) — not a real place
        return None
    loc_key = build_location_id(
        str(raw.get("action_geo_feature_id") or ""),
        raw.get("action_geo_country_code") or "",
        raw.get("action_geo_fullname") or "",
    )
    if loc_key is None:  # no usable identity -> geoless rather than a shared empty key
        return None
    return {
        "event_id": build_event_id(raw["global_event_id"]),
        "loc_key": loc_key,
        "name": raw.get("action_geo_fullname"),
        "country": raw.get("action_geo_country_code"),
        "lat": lat,
        "lon": lon,
    }
```

- [ ] **Step 5: `location_params_for` — identical guards on the live writer**

In `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py`, replace `location_params_for`:

```python
def location_params_for(ev: GDELTEventWrite) -> dict[str, Any] | None:
    if ev.action_geo_lat is None or ev.action_geo_long is None:
        return None
    if ev.action_geo_lat == 0.0 and ev.action_geo_long == 0.0:  # null-island (WP-11)
        return None
    loc_key = build_location_id(
        ev.action_geo_feature_id or "",
        ev.action_geo_country_code or "",
        ev.action_geo_fullname or "",
    )
    if loc_key is None:
        return None
    return {
        "event_id": ev.event_id,
        "loc_key": loc_key,
        "name": ev.action_geo_fullname,
        "country": ev.action_geo_country_code,
        "lat": ev.action_geo_lat,
        "lon": ev.action_geo_long,
    }
```

- [ ] **Step 6: Delete the dead `geo.py` + its test**

```bash
cd <worktree-root>
git rm services/data-ingestion/gdelt_raw/geo.py services/data-ingestion/tests/test_gdelt_geo.py
```

(The valuable `(0,0)` assertion from `test_gdelt_geo.py` is now covered on the live paths by Steps 1–5.)

- [ ] **Step 7: Run to verify all guards pass + dead-code grep clean**

Run:
```
cd services/data-ingestion && python3 -m pytest tests/test_gdelt_ids.py tests/test_geo_gdelt.py tests/test_gdelt_writer_geo.py -q
grep -rnE "gdelt_raw.geo|build_location_payload" --include=*.py services/data-ingestion || echo "no references — clean"
python3 -m ruff check gdelt_raw/ids.py graph_integrity/geo_gdelt.py gdelt_raw/writers/neo4j_writer.py
```
Expected: tests pass; grep finds no remaining references; ruff clean.

- [ ] **Step 8: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/gdelt_raw/ids.py services/data-ingestion/graph_integrity/geo_gdelt.py services/data-ingestion/gdelt_raw/writers/neo4j_writer.py services/data-ingestion/tests/test_gdelt_ids.py services/data-ingestion/tests/test_geo_gdelt.py services/data-ingestion/tests/test_gdelt_writer_geo.py
git commit -m "fix(geo): drop (0,0) null-island + empty-id locations on both write paths, delete dead geo.py (WP-11)"
```

---

### Task 5: Honest geo metrics — `report.py` excludes null-island, flags coord-disagreement

**Files:**
- Modify: `services/data-ingestion/graph_integrity/report.py` (`GEO_COVERAGE`, new `COORD_DISAGREEMENT` + `NULL_ISLAND`, `shape_report`)
- Modify: `services/data-ingestion/graph_integrity/cli.py` (run new queries, pass to `shape_report`)
- Modify test: `services/data-ingestion/tests/test_graph_integrity_report.py`

- [ ] **Step 1: Write failing report tests**

In `services/data-ingestion/tests/test_graph_integrity_report.py`, extend the imports and add tests:

```python
from graph_integrity.report import (
    ACTOR_RELS,
    COORD_DISAGREEMENT,
    DUP_ACTOR_EDGES,
    GEO_COVERAGE,
    NULL_ISLAND,
    ORPHAN_BY_LABEL,
    shape_report,
)
```

```python
def test_new_geo_queries_are_read_only():
    for q in (GEO_COVERAGE, COORD_DISAGREEMENT, NULL_ISLAND):
        upper = q.upper()
        assert "CREATE" not in upper
        assert "MERGE" not in upper
        assert "DELETE" not in upper
        assert "SET " not in upper


def test_geo_coverage_excludes_null_island():
    # the located count must not credit (0,0) Locations
    assert "0.0" in GEO_COVERAGE
    assert "l.lat = 0.0 AND l.lon = 0.0" in GEO_COVERAGE


def test_shape_report_includes_geo_health_sections():
    out = shape_report(
        orphans=[{"label": "Event", "orphan": 0, "total": 1}],
        geo=[{"label": "Event", "located": 1, "total": 1}],
        dup_edges=[],
        coord_disagreements=[{"coord_disagreements": 0}],
        null_island=[{"null_island_locations": 0, "attached_nodes": 0}],
    )
    assert out["coord_disagreements"] == [{"coord_disagreements": 0}]
    assert out["null_island"] == [{"null_island_locations": 0, "attached_nodes": 0}]
```

If the file's existing `test_shape_report_combines_sections` calls `shape_report` positionally with 3 args, leave it — the new params default to `None`/`[]` so it stays green; the assertion above covers the new sections.

- [ ] **Step 2: Run to verify failure**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_graph_integrity_report.py -q`
Expected: FAIL (`ImportError: cannot import name 'COORD_DISAGREEMENT'`).

- [ ] **Step 3: Implement the honest queries + extended `shape_report`**

In `services/data-ingestion/graph_integrity/report.py`, replace `GEO_COVERAGE` and add the two new constants + extend `shape_report`:

```python
# Labels are intentionally hardcoded to the geo-semantic labels (Event, Incident).
# located = nodes with an OCCURRED_AT to a REAL Location; (0,0) null-island
# Locations are excluded so the acceptance metric stops crediting WP-11 nodes.
GEO_COVERAGE = """
UNWIND ['Event', 'Incident'] AS lbl
CALL (lbl) {
  MATCH (n) WHERE lbl IN labels(n)
  RETURN count(n) AS total,
         count(CASE WHEN EXISTS {
           MATCH (n)-[:OCCURRED_AT]->(l:Location)
           WHERE NOT (l.lat = 0.0 AND l.lon = 0.0)
         } THEN 1 END) AS located
}
RETURN lbl AS label, located, total
"""

# Incidents whose own lat/lon disagree with the :Location they MERGEd onto —
# the WP-07 collision symptom (a name-keyed Location froze the first incident's
# coords). Read-only audit; expects 0 after the loc_key rekey repair.
COORD_DISAGREEMENT = """
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE i.lat IS NOT NULL AND i.lon IS NOT NULL
  AND (abs(i.lat - l.lat) > 0.01 OR abs(i.lon - l.lon) > 0.01)
RETURN count(*) AS coord_disagreements
"""

# (0,0) null-island Locations and how many nodes still hang off them (WP-11).
NULL_ISLAND = """
MATCH (l:Location) WHERE l.lat = 0.0 AND l.lon = 0.0
OPTIONAL MATCH (n)-[:OCCURRED_AT]->(l)
RETURN count(DISTINCT l) AS null_island_locations, count(n) AS attached_nodes
"""
```

Replace `shape_report`:

```python
def shape_report(
    orphans: list[dict[str, Any]],
    geo: list[dict[str, Any]],
    dup_edges: list[dict[str, Any]],
    coord_disagreements: list[dict[str, Any]] | None = None,
    null_island: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine raw query rows into one report dict (pure)."""
    return {
        "orphans": orphans,
        "geo": geo,
        "dup_edges": dup_edges,
        "coord_disagreements": coord_disagreements or [],
        "null_island": null_island or [],
    }
```

- [ ] **Step 4: Wire the new queries into the report CLI**

In `services/data-ingestion/graph_integrity/cli.py`, in the `report` branch (`:30-34`), replace the body with:

```python
        if args.command == "report":
            orphans = await client.run(report.ORPHAN_BY_LABEL, {"labels": report.REPORT_LABELS})
            geo = await client.run(report.GEO_COVERAGE)
            dup = await client.run(report.DUP_ACTOR_EDGES, {"actor_rels": report.ACTOR_RELS})
            coord_dis = await client.run(report.COORD_DISAGREEMENT)
            null_island = await client.run(report.NULL_ISLAND)
            print(report.shape_report(orphans, geo, dup, coord_dis, null_island))
```

- [ ] **Step 5: Run report tests + ruff**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_graph_integrity_report.py -q && python3 -m ruff check graph_integrity/report.py graph_integrity/cli.py`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/graph_integrity/report.py services/data-ingestion/graph_integrity/cli.py services/data-ingestion/tests/test_graph_integrity_report.py
git commit -m "feat(graph-integrity): honest geo metrics — exclude null-island, flag coord-disagreement (WP-11/WP-07 report, L6-a)"
```

---

### Task 6: WP-07 repair — re-key/split collided incident Locations + `Location.loc_key` constraint

**Files:**
- Create: `services/data-ingestion/graph_integrity/rekey_incident_locations.py`
- Create: `services/data-ingestion/migrations/location_loc_key_unique.cypher`
- Modify: `services/data-ingestion/graph_integrity/cli.py` (add `rekey-incident-locations --dry-run` subcommand)
- Test: `services/data-ingestion/tests/test_rekey_incident_locations.py` (create)

**Operational order (documented in the module + cypher header):** run `--dry-run` (review counts) → run apply → `verify_no_duplicate_loc_keys` must return `[]` → apply `location_loc_key_unique.cypher`.

- [ ] **Step 1: Write failing tests for the pure plan + the dry-run/apply behavior**

Create `services/data-ingestion/tests/test_rekey_incident_locations.py`:

```python
"""WP-07 repair: re-key collided incident Locations onto coordinate-bearing keys."""
import asyncio

from graph_integrity.rekey_incident_locations import (
    FETCH_INCIDENT_LOCATIONS,
    IncidentLoc,
    plan_rekey,
    run,
)


def _row(incident_id, location, lat, lon, current_loc_key):
    return IncidentLoc(incident_id, location, lat, lon, current_loc_key)


def test_plan_rekey_splits_same_name_different_coords():
    # both currently collapsed onto the old name-only key
    rows = [
        _row("a", "Donetsk", 48.0, 37.8, "incident:donetsk"),
        _row("b", "Donetsk", 49.0, 38.0, "incident:donetsk"),
    ]
    plan = plan_rekey(rows)
    assert plan.rewire_count == 2
    new_keys = {new for (_id, _old, new) in plan.rewires}
    assert new_keys == {"incident:donetsk@48.000,37.800", "incident:donetsk@49.000,38.000"}


def test_plan_rekey_noop_when_already_coordinate_bearing():
    rows = [_row("a", "Donetsk", 48.0, 37.8, "incident:donetsk@48.000,37.800")]
    assert plan_rekey(rows).rewire_count == 0


class _FakeClient:
    def __init__(self, fetch_rows):
        self._fetch_rows = fetch_rows
        self.calls = []

    async def run(self, cypher, params=None):
        self.calls.append((cypher, params))
        if cypher == FETCH_INCIDENT_LOCATIONS:
            return self._fetch_rows
        return []


_RAW = [
    {"incident_id": "a", "location": "Donetsk", "lat": 48.0, "lon": 37.8,
     "current_loc_key": "incident:donetsk"},
    {"incident_id": "b", "location": "Donetsk", "lat": 49.0, "lon": 38.0,
     "current_loc_key": "incident:donetsk"},
]


def test_dry_run_counts_without_writing():
    client = _FakeClient(_RAW)
    n = asyncio.run(run(client, dry_run=True))
    assert n == 2
    # only the read fetch ran; no rewire/cleanup writes
    assert [c[0] for c in client.calls] == [FETCH_INCIDENT_LOCATIONS]


def test_apply_rewires_and_cleans_orphans():
    client = _FakeClient(_RAW)
    n = asyncio.run(run(client, dry_run=False))
    assert n == 2
    cyphers = [c[0] for c in client.calls]
    assert cyphers[0] == FETCH_INCIDENT_LOCATIONS
    # one rewire per incident + a final orphan cleanup
    assert sum("MERGE (i)-[:OCCURRED_AT]->(l)" in c for c in cyphers) == 2
    assert any("NOT ()-[:OCCURRED_AT]->(l)" in c for c in cyphers)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_rekey_incident_locations.py -q`
Expected: FAIL with `ModuleNotFoundError: graph_integrity.rekey_incident_locations`.

- [ ] **Step 3: Implement the repair module**

Create `services/data-ingestion/graph_integrity/rekey_incident_locations.py`:

```python
"""WP-07 repair: re-key collided incident :Location nodes onto coordinate-bearing
keys and clean the orphaned old nodes. Idempotent + dry-run-first.

Two distinct incidents that shared a location slug at different coordinates were
MERGEd onto ONE name-keyed :Location (the second silently inheriting the first's
coords). With the coordinate-bearing incident_key now live, this job rewires each
incident's OCCURRED_AT onto the correct coord-bearing Location and deletes the
orphaned 'incident:'-prefixed nodes left behind.

Operational order:
  1. run --dry-run               (review the rewire count)
  2. run (apply)                 (rewire + orphan cleanup; re-runnable)
  3. verify_no_duplicate_loc_keys(client) MUST return []
  4. apply migrations/location_loc_key_unique.cypher
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from graph_integrity.loc_key import incident_key

log = structlog.get_logger(__name__)

FETCH_INCIDENT_LOCATIONS = """
MATCH (i:Incident)-[:OCCURRED_AT]->(l:Location)
WHERE l.loc_key STARTS WITH 'incident:'
RETURN i.id AS incident_id, i.location AS location,
       i.lat AS lat, i.lon AS lon, l.loc_key AS current_loc_key
"""

REWIRE = """
MATCH (i:Incident {id: $incident_id})
MERGE (l:Location {loc_key: $new_key})
  ON CREATE SET l.lat = $lat, l.lon = $lon, l.name = $location,
                l.geo_basis = 'incident_report'
MERGE (i)-[:OCCURRED_AT]->(l)
WITH i, l
MATCH (i)-[r:OCCURRED_AT]->(old:Location) WHERE old <> l
DELETE r
"""

CLEANUP_ORPHAN_INCIDENT_LOCATIONS = """
MATCH (l:Location)
WHERE l.loc_key STARTS WITH 'incident:' AND NOT ()-[:OCCURRED_AT]->(l)
DELETE l
RETURN count(l) AS deleted
"""

DUP_LOC_KEY_PREFLIGHT = """
MATCH (l:Location)
WITH l.loc_key AS key, count(*) AS c
WHERE key IS NOT NULL AND c > 1
RETURN key, c ORDER BY c DESC
"""


@dataclass
class IncidentLoc:
    incident_id: str
    location: str | None
    lat: float
    lon: float
    current_loc_key: str

    def desired_loc_key(self) -> str:
        return incident_key(self.location, self.lat, self.lon)


@dataclass
class RekeyPlan:
    rewires: list[tuple[str, str, str]] = field(default_factory=list)  # (id, old, new)

    @property
    def rewire_count(self) -> int:
        return len(self.rewires)


def plan_rekey(rows: list[IncidentLoc]) -> RekeyPlan:
    """Pure: which incidents need their Location re-keyed (current != desired)."""
    plan = RekeyPlan()
    for r in rows:
        new = r.desired_loc_key()
        if new != r.current_loc_key:
            plan.rewires.append((r.incident_id, r.current_loc_key, new))
    return plan


async def _fetch_rows(client) -> list[IncidentLoc]:
    raw = await client.run(FETCH_INCIDENT_LOCATIONS)
    return [
        IncidentLoc(
            incident_id=row["incident_id"], location=row.get("location"),
            lat=row["lat"], lon=row["lon"], current_loc_key=row["current_loc_key"],
        )
        for row in raw
    ]


async def run(client, *, dry_run: bool = False) -> int:
    """Re-key collided incident Locations. Returns the rewire count."""
    rows = await _fetch_rows(client)
    plan = plan_rekey(rows)
    by_id = {r.incident_id: r for r in rows}
    log.info("rekey_incident_locations_plan", rewires=plan.rewire_count, dry_run=dry_run)
    if dry_run:
        return plan.rewire_count
    for incident_id, _old_key, new_key in plan.rewires:
        r = by_id[incident_id]
        await client.run(REWIRE, {
            "incident_id": incident_id, "new_key": new_key,
            "lat": r.lat, "lon": r.lon, "location": r.location,
        })
    await client.run(CLEANUP_ORPHAN_INCIDENT_LOCATIONS)
    return plan.rewire_count


async def verify_no_duplicate_loc_keys(client) -> list[tuple[str, int]]:
    """Preflight before applying location_loc_key_unique.cypher — MUST return []."""
    rows = await client.run(DUP_LOC_KEY_PREFLIGHT)
    return [(row["key"], row["c"]) for row in rows]
```

- [ ] **Step 4: Create the constraint cypher**

Create `services/data-ingestion/migrations/location_loc_key_unique.cypher`:

```cypher
// Apply ONLY after rekey_incident_locations.run(apply) has run and
// verify_no_duplicate_loc_keys(client) returns []. Neo4j 5 Community supports
// single-property uniqueness constraints. Unique constraints allow NULLs, so
// any Location without a loc_key is unaffected.
CREATE CONSTRAINT location_loc_key_unique IF NOT EXISTS
FOR (l:Location) REQUIRE l.loc_key IS UNIQUE;
```

- [ ] **Step 5: Wire the CLI subcommand**

In `services/data-ingestion/graph_integrity/cli.py`:
- import the module: `from graph_integrity import geo_gdelt, geo_incident, rekey_incident_locations, report`
- in `build_parser`, add:

```python
    rk = sub.add_parser("rekey-incident-locations")
    rk.add_argument("--dry-run", action="store_true")
```

- in `_amain`, add a branch:

```python
        elif args.command == "rekey-incident-locations":
            n = await rekey_incident_locations.run(client, dry_run=args.dry_run)
            print(f"rekey-incident-locations: {n} incidents {'(dry-run)' if args.dry_run else 'rewired'}")
```

- [ ] **Step 6: Run the repair tests + ruff + read-template guard**

Run:
```
cd services/data-ingestion && python3 -m pytest tests/test_rekey_incident_locations.py tests/test_graph_integrity_report.py -q
python3 -m ruff check graph_integrity/rekey_incident_locations.py graph_integrity/cli.py
grep -nP "[^\x09\x0a\x20-\x7e]" services/data-ingestion/migrations/location_loc_key_unique.cypher && echo "NON-ASCII FOUND" || echo "ascii clean"
```
Expected: tests pass, ruff clean, cypher ASCII-clean.

- [ ] **Step 7: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/graph_integrity/rekey_incident_locations.py services/data-ingestion/migrations/location_loc_key_unique.cypher services/data-ingestion/graph_integrity/cli.py services/data-ingestion/tests/test_rekey_incident_locations.py
git commit -m "feat(migration): rekey collided incident Locations + loc_key uniqueness constraint (WP-07 repair)"
```

---

### Task 7: WP-11 repair — null-island `(0,0)` Location cleanup (dry-run first)

**Files:**
- Create: `services/data-ingestion/graph_integrity/cleanup_null_island.py`
- Modify: `services/data-ingestion/graph_integrity/cli.py` (add `cleanup-null-island --dry-run`)
- Test: `services/data-ingestion/tests/test_cleanup_null_island.py` (create)

- [ ] **Step 1: Write failing dry-run/apply tests**

Create `services/data-ingestion/tests/test_cleanup_null_island.py`:

```python
"""WP-11 repair: detach + delete shared (0,0) null-island :Location nodes."""
import asyncio

from graph_integrity.cleanup_null_island import (
    COUNT_NULL_ISLAND,
    DELETE_NULL_ISLAND,
    run,
)


class _FakeClient:
    def __init__(self, locations=2, attached=5, deleted=2):
        self._count = {"null_island_locations": locations, "attached_nodes": attached}
        self._deleted = {"deleted": deleted}
        self.calls = []

    async def run(self, cypher, params=None):
        self.calls.append((cypher, params))
        if cypher == COUNT_NULL_ISLAND:
            return [self._count]
        return [self._deleted]


def test_dry_run_counts_without_deleting():
    client = _FakeClient(locations=2, attached=5)
    n = asyncio.run(run(client, dry_run=True))
    assert n == 2
    assert [c[0] for c in client.calls] == [COUNT_NULL_ISLAND]


def test_apply_detach_deletes_null_island_nodes():
    client = _FakeClient(locations=2, deleted=2)
    n = asyncio.run(run(client, dry_run=False))
    assert n == 2
    cyphers = [c[0] for c in client.calls]
    assert COUNT_NULL_ISLAND in cyphers
    assert DELETE_NULL_ISLAND in cyphers
    assert "DETACH DELETE" in DELETE_NULL_ISLAND


def test_delete_query_is_scoped_to_zero_zero():
    assert "l.lat = 0.0 AND l.lon = 0.0" in DELETE_NULL_ISLAND
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_cleanup_null_island.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the cleanup module**

Create `services/data-ingestion/graph_integrity/cleanup_null_island.py`:

```python
"""WP-11 repair: detach and delete the shared (0,0) null-island :Location nodes.

Pre-fix writers MERGEd every (0,0)-with-no-ids event onto a single Location in
the Gulf of Guinea. With both writers now dropping (0,0), this job detaches the
events (they become honestly geoless) and deletes the (0,0) nodes. Idempotent:
a second run finds 0 null-island nodes and is a no-op.

Operational order: run --dry-run (review counts) -> run (apply).
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

COUNT_NULL_ISLAND = """
MATCH (l:Location) WHERE l.lat = 0.0 AND l.lon = 0.0
OPTIONAL MATCH (n)-[:OCCURRED_AT]->(l)
RETURN count(DISTINCT l) AS null_island_locations, count(n) AS attached_nodes
"""

DELETE_NULL_ISLAND = """
MATCH (l:Location) WHERE l.lat = 0.0 AND l.lon = 0.0
DETACH DELETE l
RETURN count(l) AS deleted
"""


async def run(client, *, dry_run: bool = False) -> int:
    """Delete (0,0) Locations. Returns the count of null-island nodes found/deleted."""
    counts = await client.run(COUNT_NULL_ISLAND)
    found = int(counts[0]["null_island_locations"]) if counts else 0
    attached = int(counts[0]["attached_nodes"]) if counts else 0
    log.info("cleanup_null_island_plan", null_island_locations=found,
             attached_nodes=attached, dry_run=dry_run)
    if dry_run:
        return found
    result = await client.run(DELETE_NULL_ISLAND)
    deleted = int(result[0]["deleted"]) if result else 0
    log.info("cleanup_null_island_done", deleted=deleted)
    return deleted
```

- [ ] **Step 4: Wire the CLI subcommand**

In `services/data-ingestion/graph_integrity/cli.py`:
- import: `from graph_integrity import cleanup_null_island, geo_gdelt, geo_incident, rekey_incident_locations, report`
- in `build_parser`, add:

```python
    cn = sub.add_parser("cleanup-null-island")
    cn.add_argument("--dry-run", action="store_true")
```

- in `_amain`, add a branch:

```python
        elif args.command == "cleanup-null-island":
            n = await cleanup_null_island.run(client, dry_run=args.dry_run)
            print(f"cleanup-null-island: {n} (0,0) locations {'(dry-run)' if args.dry_run else 'deleted'}")
```

- [ ] **Step 5: Run tests + ruff**

Run: `cd services/data-ingestion && python3 -m pytest tests/test_cleanup_null_island.py -q && python3 -m ruff check graph_integrity/cleanup_null_island.py graph_integrity/cli.py`
Expected: pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
cd <worktree-root>
git add services/data-ingestion/graph_integrity/cleanup_null_island.py services/data-ingestion/graph_integrity/cli.py services/data-ingestion/tests/test_cleanup_null_island.py
git commit -m "feat(migration): null-island (0,0) Location cleanup, dry-run counts first (WP-11 repair)"
```

---

## Final verification (after all tasks)

- [ ] **Full suites both services:**
  `cd services/data-ingestion && python3 -m pytest tests/ -q` (expect all green, 0 new skips)
  `cd services/backend && python3 -m pytest tests/ -q`
- [ ] **Ruff full repo paths touched:** `cd services/data-ingestion && python3 -m ruff check . && cd ../backend && python3 -m ruff check .`
- [ ] **`graph-rag-auditor` agent** on the report/migration changes (read/write-path separation: confirm `report.py` queries stay read-only and the repair jobs live OUTSIDE the live read-path).
- [ ] **Two-stage review per task** (spec-compliance + quality) — never skip.

## Re-ingestion-only (explicit, documented — never silently claimed fixed)

- **WP-05** wrong-country edges for existing multi-country documents: per-event country was never stored, so legacy edges cannot be re-derived. The forward guard prevents new ones; legacy correctness requires re-ingestion. (No detection query is shipped: the graph never recorded per-event country, so multi-country collapse is not reliably detectable post-hoc — claiming otherwise would be dishonest. The honest signal is `report.py` `located` counts + `COORD_DISAGREEMENT`.)
- **WP-06** mis-anchored GDELT `time_basis='ingested'` for existing events: real `seendate` is only in the Qdrant payload, not Neo4j. Forward fix anchors new events to `observed`; legacy requires re-ingestion. *Optional stretch (not in this plan):* backfill `timeline_at` from the Qdrant `seen_date` payload by `content_hash`.

## Deploy (no GPU swap)

Ingestion-only code (T4): rebuild the ingestion image. Run repairs against live Neo4j, dry-run first:
`graph-integrity rekey-incident-locations --dry-run` → apply → preflight `[]` → apply `migrations/location_loc_key_unique.cypher`; then `graph-integrity cleanup-null-island --dry-run` → apply. `report.py`/`cli.py` ship with the ingestion image. No backend rebuild needed for the report (the `_loc_key.py` change does require a backend image rebuild for WP-07 forward).
