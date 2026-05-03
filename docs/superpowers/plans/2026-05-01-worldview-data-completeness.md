# Plan A: Static Infrastructure Atlas Enrichment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Worldview's thin pipeline dataset (10 features → ≥50), enrich the existing refineries dataset (199 → preserved + ≥80 with image_url+source_url+specs), and enrich the existing datacenters dataset (268 → preserved + ≥30 hyperscaler campus_verified entries) by adding a reusable `infra_atlas` Python package that **respects existing curation and uses Wikidata as an enrichment source — not a magic total replacement**.

**Architecture decisions (informed by review):**

- **Pipelines:** rebuild from a curated YAML seed (no Wikidata round-trip). Seed lives in the plan body, ≥50 entries, every entry has `source_url` (Wikipedia article).
- **Refineries:** load existing 199 → match each by `(name, country)` against a live Wikidata pull of `wd:Q12353044` (oil refinery) and `wd:Q15709854` (LNG terminal) → enrich `image_url`/`specs`/`qid`/`source_url` where matched → append Wikidata-only entries that aren't already in the dataset → write. Existing data is the source of truth for fields the seed already has (no overwrite of `name`/`operator`/`capacity_bpd`/coords from Wikidata to avoid drift).
- **Datacenters:** load existing 268 → match by `(name, country)` against a live Wikidata pull of `wd:Q671224` (data center) → for matched entries, set `qid`, `source_url`, and IF Wikidata's P625 coord differs from existing by >5 km, replace and mark `coord_quality: "wikidata_verified"`/`coord_source: "wikidata"` → merge a hand-curated hyperscaler seed on top with `coord_quality: "campus_verified"`/`coord_source: "<authoritative-url>"`.
- **Schema extension is explicit, not hidden:** Optional fields `source_url`, `qid`, `coord_quality`, `coord_source` get added to `RefineryProperties` and `DatacenterProperties`; `source_url` and `qid` get added to `PipelineProperties`. Hook tests are updated to cover both presence and absence.
- **Capacity is never invented:** Live check shows `wdt:P2197` (production rate) is empty across all 257 oil-refinery entities in Wikidata. The builder leaves `capacity_bpd` from the existing dataset untouched and writes `0` for new Wikidata-only refinery entries (the frontend's `RefineryProperties.capacity_bpd: number` is non-nullable). For datacenters, `capacity_mw` is **not** populated from Wikidata `wdt:P2109` — that property's unit is Watts, and using it without unit-conversion would give 1 000 000× wrong values; only the hyperscaler seed sets `capacity_mw` explicitly.
- **Q-IDs are verified live, not pulled from memory.** Constants live in `infra_atlas/constants.py` with the verified label as a comment; a CI test (`test_constants_resolve_live.py`, marked `@pytest.mark.live` to ride the existing `addopts = -m "not live"` exclusion in `pytest.ini`) re-verifies the labels via the live Wikidata API on demand.
- **Tests mock Wikidata.** Live SPARQL only runs from `odin-infra-atlas` CLI commands and the opt-in integration test. Normal `pytest` runs are deterministic.

**Tech Stack:** Python 3.12 + httpx (Wikidata SPARQL), pydantic v2 (validation), pytest + pytest-httpx (mocking, already in `[dependency-groups].dev`), click (CLI), PyYAML (curated seeds + existing GeoJSON load via stdlib `json`).

**Spec:** Inline (this plan covers a contained data-refresh sprint).

**Out of scope:** Live OSM Overpass for pipeline geometry, scheduler integration, CIA Almanac (Plan B).

---

## File Structure

**New (Python):**
- `services/data-ingestion/infra_atlas/__init__.py`
- `services/data-ingestion/infra_atlas/constants.py` — verified Wikidata Q-IDs / property IDs
- `services/data-ingestion/infra_atlas/wikidata.py` — SPARQL client + row helpers
- `services/data-ingestion/infra_atlas/cli.py` — `odin-infra-atlas` click entrypoint
- `services/data-ingestion/infra_atlas/build_pipelines.py`
- `services/data-ingestion/infra_atlas/build_refineries.py`
- `services/data-ingestion/infra_atlas/build_datacenters.py`
- `services/data-ingestion/infra_atlas/seeds/pipelines.yaml` — full ≥50 entry seed (content mandated below)
- `services/data-ingestion/infra_atlas/seeds/datacenters_hyperscaler.yaml` — hand-curated ≥30 hyperscaler campus seed (research mandated in Task 5)
- `services/data-ingestion/infra_atlas/seeds/known_city_centroids.json` — runtime data file used by the datacenter builder to reject lazy seed entries

**New (tests):**
- `services/data-ingestion/tests/test_wikidata.py`
- `services/data-ingestion/tests/test_build_pipelines.py`
- `services/data-ingestion/tests/test_build_refineries.py`
- `services/data-ingestion/tests/test_build_datacenters.py`
- `services/data-ingestion/tests/integration/test_constants_resolve_live.py`
- `services/data-ingestion/tests/fixtures/wikidata_refinery_sample.json`
- `services/data-ingestion/tests/fixtures/wikidata_datacenter_sample.json`
- `services/data-ingestion/tests/fixtures/existing_refineries_sample.geojson`
- `services/data-ingestion/tests/fixtures/existing_datacenters_sample.geojson`
- (the city-centroids list is **not** a test fixture — it lives at `infra_atlas/seeds/known_city_centroids.json` so the built CLI can find it)

**New (frontend tests):**
- (none — extend existing files below)

**Modified (Python packaging):**
- `services/data-ingestion/pyproject.toml` — add `infra_atlas/**/*.py` and `infra_atlas/seeds/*.yaml` to `[tool.hatch.build.targets.wheel].include`; register `odin-infra-atlas` script. Do NOT touch `[dependency-groups].dev` — `pytest-httpx>=0.36.2` is already there.

**Modified (frontend schema + tests):**
- `services/frontend/src/types/infrastructure.ts` — add optional `qid`, `source_url`, `coord_quality`, `coord_source` to both `DatacenterProperties` and `RefineryProperties`
- `services/frontend/src/types/pipeline.ts` — add optional `qid`, `source_url` to `PipelineProperties`
- `services/frontend/src/hooks/__tests__/useDatacenters.test.ts` — extend mock + add coverage for the new optional fields
- `services/frontend/src/hooks/__tests__/useRefineries.test.ts` — same

**Modified (data files, regenerated):**
- `services/frontend/public/data/pipelines.geojson`
- `services/frontend/public/data/refineries.geojson`
- `services/frontend/public/data/datacenters.geojson`

---

## Acceptance Criteria (hard)

- **Pipelines:** `services/frontend/public/data/pipelines.geojson` features count `≥50`. Every feature has `geometry.type` ∈ {`LineString`, `MultiLineString`}. Every feature properties has `source_url` populated (Wikipedia URL). No "TODO"/"placeholder" strings in the file.
- **Refineries:** features count `≥199` (≥ existing). Features with all three of `image_url`, `source_url`, `specs` populated `≥80`. No `capacity_bpd` value newly set to a non-zero number unless it was already in the existing file (no Wikidata-fabrication). Every existing `image_url` from the old file is still present in the new file (preservation test).
- **Datacenters:** features count `≥268` (≥ existing). Features with `tier == "hyperscaler"` AND `coord_quality == "campus_verified"` AND `source_url` populated `≥30`. Zero hyperscaler entries match a known city-centroid coord (Frankfurt 50.1109,8.6821; Dublin 53.3498,-6.2603; Amsterdam 52.3702,4.8952; Council Bluffs 41.2619,-95.8608; London 51.5074,-0.1278; Singapore 1.3521,103.8198 — these are listed in `infra_atlas/seeds/known_city_centroids.json` and tested explicitly). Wikidata-sourced features must come via `wdt:P31/wdt:P279* wd:Q671224` only.
- **Tests:** all `services/data-ingestion/tests/test_*.py` for `infra_atlas` pass with mocked Wikidata. The drift check (`tests/integration/test_constants_resolve_live.py`) is opt-in (existing `live` marker, excluded by `addopts`) and verifies the Q-ID/property labels haven't drifted.
- **Packaging:** `uv build` from `services/data-ingestion/` produces a wheel that contains `infra_atlas/__init__.py`, `infra_atlas/seeds/pipelines.yaml`, etc. (verifiable with `unzip -l dist/*.whl`).
- **Frontend:** `usePipelines`/`useDatacenters`/`useRefineries` hook tests pass. New fields are exercised by tests (presence and absence).
- **Visual smoke:** Worldview at the Vite dev port (5173 per `AGENTS.md`; 5174 if executing in this S2 worktree) shows ≥50 pipelines, refineries with images in InspectorPanel, and datacenters in correct positions including hyperscaler clusters around Ashburn, Frankfurt, Dublin, Singapore.

---

### Task 1: Foundation — Wikidata client, verified constants, packaging

**Files:**
- Create: `services/data-ingestion/infra_atlas/__init__.py`
- Create: `services/data-ingestion/infra_atlas/constants.py`
- Create: `services/data-ingestion/infra_atlas/wikidata.py`
- Create: `services/data-ingestion/tests/test_wikidata.py`
- Create: `services/data-ingestion/tests/integration/__init__.py`
- Create: `services/data-ingestion/tests/integration/test_constants_resolve_live.py`
- Modify: `services/data-ingestion/pyproject.toml`

- [ ] **Step 1: Add wheel-include and CLI script registration**

Open `services/data-ingestion/pyproject.toml`. Find `[tool.hatch.build.targets.wheel]` and replace its `include` line with:

```toml
[tool.hatch.build.targets.wheel]
include = [
  "*.py",
  "feeds/**/*.py",
  "feeds/**/*.yaml",
  "gdelt_raw/**/*.py",
  "nlm_ingest/**/*.py",
  "nlm_ingest/prompts/*.txt",
  "infra_atlas/**/*.py",
  "infra_atlas/seeds/*.yaml",
  "infra_atlas/seeds/*.json",
]
```

Find `[project.scripts]` and append:

```toml
odin-infra-atlas = "infra_atlas.cli:cli"
```

Do NOT add `pytest-httpx` anywhere — it's already in `[dependency-groups].dev` as `pytest-httpx>=0.36.2`.

- [ ] **Step 2: Sync deps and verify**

```bash
cd services/data-ingestion && uv sync
uv run python -c "import pytest_httpx; print(pytest_httpx.__version__)"
```

Expected: prints a version `>=0.36.2`. No `ModuleNotFoundError`.

- [ ] **Step 3: Create the package + verified constants**

Create `services/data-ingestion/infra_atlas/__init__.py`:

```python
"""infra_atlas — Wikidata-driven enrichment for Worldview infra layers."""
```

Create `services/data-ingestion/infra_atlas/constants.py`:

```python
"""Verified Wikidata identifiers used by the infra_atlas builders.

Every Q-ID and P-ID below has been resolved live against
https://www.wikidata.org/wiki/Special:EntityData/<id>.json on 2026-05-01 and
its English label is recorded inline. Do NOT add new IDs from memory — verify
each one and add the label as a comment, then ensure the integration test
(tests/integration/test_constants_resolve_live.py) covers it.
"""

from __future__ import annotations

# Class Q-IDs (used as wdt:P31 or wdt:P31/wdt:P279* targets in SPARQL).
QID_OIL_REFINERY = "Q12353044"           # oil refinery
QID_LNG_TERMINAL = "Q15709854"           # liquefied natural gas terminal
QID_DATA_CENTER = "Q671224"              # data center

# Property IDs.
PID_INSTANCE_OF = "P31"                  # instance of
PID_SUBCLASS_OF = "P279"                 # subclass of
PID_COORDINATE_LOCATION = "P625"         # coordinate location
PID_OPERATOR = "P137"                    # operator
PID_OWNED_BY = "P127"                    # owned by  (NOT the same as operator;
                                         # P127 owners and P137 operators
                                         # routinely differ — e.g. a property
                                         # company owns a building, AWS
                                         # operates the data center inside)
PID_COUNTRY = "P17"                      # country
PID_COUNTRY_ISO_ALPHA2 = "P297"          # ISO 3166-1 alpha-2 code
PID_LOCATED_IN = "P131"                  # located in the administrative
                                         # territorial entity
PID_IMAGE = "P18"                        # image
PID_NOMINAL_POWER = "P2109"              # nominal power output (W)
PID_PRODUCTION_RATE = "P2197"            # production rate
                                         # (NOTE: live coverage is 0 across
                                         # Q12353044 — never used as the
                                         # source for capacity_bpd.)

# Schema-extension constants used by builders.
COORD_QUALITY_CAMPUS_VERIFIED = "campus_verified"
COORD_QUALITY_WIKIDATA_VERIFIED = "wikidata_verified"
COORD_QUALITY_LEGACY = "legacy"          # default for unenriched existing entries

COORD_SOURCE_WIKIDATA = "wikidata"
```

- [ ] **Step 4: Write the failing client test**

Create `services/data-ingestion/tests/test_wikidata.py`:

```python
"""Tests for the shared Wikidata SPARQL client."""

import pytest
from pytest_httpx import HTTPXMock

from infra_atlas.wikidata import WikidataClient, WikidataRow


WIKIDATA_RESPONSE = {
    "head": {"vars": ["item", "itemLabel", "coord"]},
    "results": {
        "bindings": [
            {
                "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q42"},
                "itemLabel": {"type": "literal", "value": "Test Site"},
                "coord": {
                    "type": "literal",
                    "datatype": "http://www.opengis.net/ont/geosparql#wktLiteral",
                    "value": "Point(13.4 52.5)",
                },
            }
        ]
    },
}


def test_query_returns_parsed_rows(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=WIKIDATA_RESPONSE)
    client = WikidataClient()
    rows = client.query("SELECT ?item ?itemLabel ?coord WHERE { ?item wdt:P31 wd:Q42 }")
    assert len(rows) == 1
    assert rows[0]["itemLabel"] == "Test Site"
    assert rows[0]["item"] == "http://www.wikidata.org/entity/Q42"


def test_parse_wkt_point_extracts_lon_lat() -> None:
    lon, lat = WikidataRow.parse_wkt_point("Point(13.4 52.5)")
    assert lon == pytest.approx(13.4)
    assert lat == pytest.approx(52.5)


def test_parse_wkt_point_rejects_non_point() -> None:
    with pytest.raises(ValueError):
        WikidataRow.parse_wkt_point("LineString(0 0, 1 1)")


def test_qid_from_uri_extracts_qid() -> None:
    qid = WikidataRow.qid_from_uri("http://www.wikidata.org/entity/Q3417395")
    assert qid == "Q3417395"


def test_query_handles_empty_results(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    client = WikidataClient()
    rows = client.query("SELECT ?x WHERE { ?x wdt:P31 wd:Qnonexistent }")
    assert rows == []
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd services/data-ingestion && uv run pytest tests/test_wikidata.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'infra_atlas.wikidata'`.

- [ ] **Step 6: Implement the client**

Create `services/data-ingestion/infra_atlas/wikidata.py`:

```python
"""Wikidata SPARQL client.

Synchronous wrapper around https://query.wikidata.org/sparql. Always returns
JSON; flattens each binding into a {var: value} dict.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = (
    "ODIN-Worldview/0.1 "
    "(https://github.com/Hunter5Thompson/ODIN; ai.zero.shot@gmail.com)"
)
DEFAULT_TIMEOUT = 60.0


class WikidataRow:
    """Parsers for the value shapes Wikidata returns."""

    _WKT_POINT_RE = re.compile(r"^Point\(([-\d.]+)\s+([-\d.]+)\)$")
    _QID_RE = re.compile(r"/entity/(Q\d+)$")

    @classmethod
    def parse_wkt_point(cls, wkt: str) -> tuple[float, float]:
        """Return (lon, lat) from a Wikidata P625 WKT point string."""
        match = cls._WKT_POINT_RE.match(wkt.strip())
        if not match:
            raise ValueError(f"not a WKT Point: {wkt!r}")
        return float(match.group(1)), float(match.group(2))

    @classmethod
    def qid_from_uri(cls, uri: str) -> str:
        match = cls._QID_RE.search(uri)
        if not match:
            raise ValueError(f"not a Wikidata entity URI: {uri!r}")
        return match.group(1)


class WikidataClient:
    """Synchronous Wikidata SPARQL client."""

    def __init__(self, endpoint: str = WIKIDATA_SPARQL, timeout: float = DEFAULT_TIMEOUT):
        self._endpoint = endpoint
        self._timeout = timeout

    def query(self, sparql: str) -> list[dict[str, Any]]:
        resp = httpx.get(
            self._endpoint,
            params={"query": sparql, "format": "json"},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        return [
            {var: binding[var]["value"] for var in binding}
            for binding in payload["results"]["bindings"]
        ]
```

- [ ] **Step 7: Run client tests**

```bash
cd services/data-ingestion && uv run pytest tests/test_wikidata.py -v
```

Expected: 5 passed.

- [ ] **Step 8: Write the integration test for constants drift**

Create `services/data-ingestion/tests/integration/__init__.py` (empty file).

Create `services/data-ingestion/tests/integration/test_constants_resolve_live.py`:

```python
"""Live verification that constants.py Q/P-IDs still resolve to the labels we
recorded as comments. Marked `live` so it does NOT run on plain `pytest`
(pytest.ini has `addopts = -m "not live"` already). Run on demand:

    uv run pytest -m live tests/integration/test_constants_resolve_live.py
"""

from __future__ import annotations

import httpx
import pytest

from infra_atlas.constants import (
    PID_COORDINATE_LOCATION,
    PID_COUNTRY,
    PID_COUNTRY_ISO_ALPHA2,
    PID_IMAGE,
    PID_INSTANCE_OF,
    PID_LOCATED_IN,
    PID_NOMINAL_POWER,
    PID_OPERATOR,
    PID_OWNED_BY,
    PID_PRODUCTION_RATE,
    PID_SUBCLASS_OF,
    QID_DATA_CENTER,
    QID_LNG_TERMINAL,
    QID_OIL_REFINERY,
)

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{id}.json"
USER_AGENT = "ODIN-infra-atlas-integration-test/0.1 (ai.zero.shot@gmail.com)"

EXPECTED = [
    (QID_OIL_REFINERY, "oil refinery"),
    (QID_LNG_TERMINAL, "liquefied natural gas terminal"),
    (QID_DATA_CENTER, "data center"),
    (PID_INSTANCE_OF, "instance of"),
    (PID_SUBCLASS_OF, "subclass of"),
    (PID_COORDINATE_LOCATION, "coordinate location"),
    (PID_OPERATOR, "operator"),
    (PID_OWNED_BY, "owned by"),
    (PID_COUNTRY, "country"),
    (PID_COUNTRY_ISO_ALPHA2, "ISO 3166-1 alpha-2 code"),
    (PID_LOCATED_IN, "located in the administrative territorial entity"),
    (PID_IMAGE, "image"),
    (PID_NOMINAL_POWER, "nominal power output"),
    (PID_PRODUCTION_RATE, "production rate"),
]


@pytest.mark.live
@pytest.mark.parametrize("entity_id,expected_label", EXPECTED)
def test_constant_label_matches_live_wikidata(entity_id: str, expected_label: str) -> None:
    resp = httpx.get(
        WIKIDATA_ENTITY_URL.format(id=entity_id),
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
    )
    resp.raise_for_status()
    label = resp.json()["entities"][entity_id]["labels"]["en"]["value"]
    assert label == expected_label, (
        f"Wikidata label drifted for {entity_id}: "
        f"expected {expected_label!r}, got {label!r}. "
        "Update constants.py comment OR pick a different ID."
    )
```

- [ ] **Step 9: Confirm `live` marker setup (already present in pytest.ini)**

Check that `services/data-ingestion/pytest.ini` already contains:

```ini
markers =
    integration: requires local dev-compose services
    live: touches external GDELT CDN
    slow: backfill or performance tests
addopts = -m "not live"
```

The `live` marker is reused for our Wikidata drift check — it shares the "external network" semantic with the GDELT CDN tests. The `addopts` line means `live`-marked tests are excluded by default. **No change to pytest.ini needed.** If those lines are missing, fail loud — something has shifted under the worktree.

- [ ] **Step 10: Verify the live test is excluded from default runs**

```bash
cd services/data-ingestion && uv run pytest tests/test_wikidata.py tests/integration/ -v
```

Expected: 5 tests from test_wikidata.py pass; integration test cases are deselected (output mentions "14 deselected" for the integration file because they're marked `live`).

- [ ] **Step 11: Run live drift check once explicitly to baseline**

```bash
cd services/data-ingestion && uv run pytest -m live tests/integration/test_constants_resolve_live.py -v
```

Expected: all 14 parametrized cases pass (this is the live drift check). If any fail, STOP — `constants.py` needs the corrected ID for whichever entity drifted.

- [ ] **Step 12: Lint**

```bash
cd services/data-ingestion && uv run ruff check infra_atlas/ tests/test_wikidata.py tests/integration/
```

Expected: no errors.

- [ ] **Step 13: Commit**

```bash
git add services/data-ingestion/pyproject.toml \
        services/data-ingestion/infra_atlas/__init__.py \
        services/data-ingestion/infra_atlas/constants.py \
        services/data-ingestion/infra_atlas/wikidata.py \
        services/data-ingestion/tests/test_wikidata.py \
        services/data-ingestion/tests/integration/__init__.py \
        services/data-ingestion/tests/integration/test_constants_resolve_live.py
git commit -m "feat(data-ingestion): infra_atlas foundation (Wikidata client + verified constants)"
```

> Note: pytest.ini is intentionally NOT modified — the `live` marker semantic was reused.

---

### Task 2: Frontend Schema Extension

**Files:**
- Modify: `services/frontend/src/types/infrastructure.ts`
- Modify: `services/frontend/src/types/pipeline.ts`
- Modify: `services/frontend/src/hooks/__tests__/useDatacenters.test.ts`
- Modify: `services/frontend/src/hooks/__tests__/useRefineries.test.ts`
- Create: `services/frontend/src/hooks/__tests__/usePipelines.test.ts`
- Modify: `services/frontend/src/components/worldview/InspectorPanel.tsx` — render `source_url` link in the datacenter case (currently only the refinery case has one)
- Modify: `services/frontend/src/components/worldview/InspectorPanel.test.tsx` — assert the new datacenter Source link

The schema gains four optional fields on `RefineryProperties` and `DatacenterProperties`, two on `PipelineProperties`. Optional fields are non-breaking: existing GeoJSON files continue to validate, but the builder now has somewhere to record provenance.

- [ ] **Step 1: Extend `infrastructure.ts`**

Replace `services/frontend/src/types/infrastructure.ts` with:

```typescript
export type DatacenterTier = "III" | "IV" | "hyperscaler";
export type RefineryStatus = "active" | "planned" | "shutdown";
export type FacilityType = "refinery" | "lng_terminal" | "chemical_plant";

/**
 * coord_quality records how a feature's coordinates were sourced and validated.
 *  - "campus_verified"   — manually researched against an authoritative source
 *                          (operator press release, baxtel.com, DCD article);
 *                          source_url MUST be set.
 *  - "wikidata_verified" — coords match a live Wikidata wdt:P625 value within
 *                          5 km of the existing dataset's value (or replaced it).
 *  - "legacy"            — coords from the original hand-curated dataset, not
 *                          re-verified yet.
 */
export type CoordQuality = "campus_verified" | "wikidata_verified" | "legacy";

interface InfraProvenance {
  qid?: string;            // Wikidata Q-ID (e.g. "Q3417395")
  source_url?: string;     // canonical citation URL
  coord_quality?: CoordQuality;
  coord_source?: string;   // free-text describing where the coord came from
                           // (e.g. "wikidata", "https://baxtel.com/...")
}

export interface DatacenterProperties extends InfraProvenance {
  name: string;
  operator: string;
  tier: DatacenterTier;
  capacity_mw: number | null;
  country: string;
  city: string;
  latitude?: number;
  longitude?: number;
}

export interface RefineryProperties extends InfraProvenance {
  name: string;
  operator: string;
  capacity_bpd: number;
  country: string;
  status: RefineryStatus;
  facility_type?: FacilityType;
  capacity_text?: string;
  latitude?: number;
  longitude?: number;
  image_url?: string;
  specs?: string[];
}

export interface InfraFeature<T> {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number]; // [lon, lat]
  };
  properties: T;
}

export interface InfraGeoJSON<T> {
  type: "FeatureCollection";
  features: InfraFeature<T>[];
}

export type DatacenterGeoJSON = InfraGeoJSON<DatacenterProperties>;
export type RefineryGeoJSON = InfraGeoJSON<RefineryProperties>;
```

> Note: `RefineryProperties` previously had a top-level `source_url`; it now inherits from `InfraProvenance` so it remains the same field name and type — no migration of existing data needed.

- [ ] **Step 2: Extend `pipeline.ts`**

Edit `services/frontend/src/types/pipeline.ts`. Replace the `PipelineProperties` interface with:

```typescript
/** GeoJSON Feature properties for a pipeline segment. */
export interface PipelineProperties {
  name: string;
  tier: "major" | "regional" | "local";
  type: "oil" | "gas" | "lng" | "mixed";
  status: "active" | "planned" | "under_construction" | "shutdown";
  operator: string | null;
  capacity_bcm: number | null;
  length_km: number | null;
  countries: string[];
  qid?: string;
  source_url?: string;
}
```

Leave the rest of the file unchanged.

- [ ] **Step 3: Extend the useDatacenters hook test**

Open `services/frontend/src/hooks/__tests__/useDatacenters.test.ts`. Find the `MOCK_GEOJSON` constant and replace its single feature with two — one bare, one fully enriched:

```typescript
const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [-77.49, 39.04] },
      properties: {
        name: "Test DC",
        operator: "TestCorp",
        tier: "hyperscaler" as const,
        capacity_mw: 100,
        country: "US",
        city: "Ashburn",
      },
    },
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [8.55, 50.10] },
      properties: {
        name: "Enriched DC",
        operator: "TestCorp",
        tier: "hyperscaler" as const,
        capacity_mw: 200,
        country: "DE",
        city: "Frankfurt",
        qid: "Q1234567",
        source_url: "https://example.com/frankfurt-dc",
        coord_quality: "campus_verified" as const,
        coord_source: "https://example.com/frankfurt-dc",
      },
    },
  ],
};
```

Then add a new test case at the bottom of the `describe` block:

```typescript
  it("preserves optional provenance fields when present", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useDatacenters(true));
    await waitFor(() =>
      expect(result.current.datacenters?.features.length).toBe(2),
    );

    const bare = result.current.datacenters!.features[0]!.properties;
    const enriched = result.current.datacenters!.features[1]!.properties;

    expect(bare.qid).toBeUndefined();
    expect(bare.source_url).toBeUndefined();
    expect(enriched.qid).toBe("Q1234567");
    expect(enriched.coord_quality).toBe("campus_verified");
    expect(enriched.source_url).toBe("https://example.com/frankfurt-dc");
  });
```

- [ ] **Step 4: Extend the useRefineries hook test (analogous)**

Open `services/frontend/src/hooks/__tests__/useRefineries.test.ts`. Find its `MOCK_GEOJSON` and add a second feature with the new fields populated, then add a test analogous to Step 3 that asserts `qid`, `source_url`, `coord_quality`, `coord_source` are read through unchanged.

```typescript
// Add as the 2nd entry in MOCK_GEOJSON.features:
{
  type: "Feature" as const,
  geometry: { type: "Point" as const, coordinates: [50.158, 26.643] },
  properties: {
    name: "Enriched Refinery",
    operator: "Saudi Aramco",
    capacity_bpd: 550000,
    country: "SA",
    status: "active" as const,
    facility_type: "refinery" as const,
    image_url: "https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg",
    source_url: "https://www.wikidata.org/wiki/Q860840",
    qid: "Q860840",
    coord_quality: "wikidata_verified" as const,
    coord_source: "wikidata",
    specs: ["WGS84 position: 26°38'34\"N, 50°9'29\"E"],
  },
},
```

```typescript
// Add as a new test inside the describe block:
it("exposes Wikidata-enriched provenance fields", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => MOCK_GEOJSON,
  } as Response);

  const { result } = renderHook(() => useRefineries(true));
  await waitFor(() =>
    expect(result.current.refineries?.features.length).toBeGreaterThanOrEqual(2),
  );

  const enriched = result.current.refineries!.features.find(
    (f) => f.properties.name === "Enriched Refinery",
  )!;
  expect(enriched.properties.qid).toBe("Q860840");
  expect(enriched.properties.coord_quality).toBe("wikidata_verified");
  expect(enriched.properties.coord_source).toBe("wikidata");
});
```

- [ ] **Step 5: Add the missing usePipelines hook test**

Create `services/frontend/src/hooks/__tests__/usePipelines.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { usePipelines } from "../usePipelines";

const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: {
        type: "LineString" as const,
        coordinates: [[28.7, 60.5], [13.5, 54.1]],
      },
      properties: {
        name: "Nord Stream 1",
        tier: "major" as const,
        type: "gas" as const,
        status: "active" as const,
        operator: "Nord Stream AG",
        capacity_bcm: 55.0,
        length_km: 1224,
        countries: ["Russia", "Germany"],
        source_url: "https://en.wikipedia.org/wiki/Nord_Stream",
      },
    },
  ],
};

describe("usePipelines", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => usePipelines(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches GeoJSON when enabled and exposes source_url", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => usePipelines(true));
    await waitFor(() =>
      expect(result.current.pipelines?.features.length).toBe(1),
    );
    const props = result.current.pipelines!.features[0]!.properties;
    expect(props.name).toBe("Nord Stream 1");
    expect(props.source_url).toBe("https://en.wikipedia.org/wiki/Nord_Stream");
    expect(props.qid).toBeUndefined();
  });
});
```

> Note: `usePipelines` returns `{ pipelines: data, loading, lastUpdate }` — same shape pattern as `useDatacenters` / `useRefineries`. Verify the return key in `services/frontend/src/hooks/usePipelines.ts` before pasting; the test asserts against `result.current.pipelines`.

- [ ] **Step 6: Render `source_url` in the datacenter case of InspectorPanel**

Open `services/frontend/src/components/worldview/InspectorPanel.tsx`. Find the `case "datacenter":` block (around line 198). Replace it with:

```tsx
    case "datacenter": {
      const d = selected.data;
      return (
        <>
          <div style={titleStyle}>{d.name}</div>
          <Property label="§ Operator" value={d.operator || "-"} />
          <Property label="§ Tier" value={d.tier || "-"} />
          <Property label="§ Capacity" value={d.capacity_mw != null ? `${d.capacity_mw} MW` : "-"} />
          <Property label="§ Location" value={`${d.city}, ${d.country}`} />
          {d.coord_quality ? (
            <Property label="§ Coord quality" value={d.coord_quality} />
          ) : null}
          {d.source_url ? (
            <a href={d.source_url} target="_blank" rel="noreferrer" style={sourceLinkStyle}>
              Source
            </a>
          ) : null}
        </>
      );
    }
```

Imports and `sourceLinkStyle` are already defined in this file (the refinery branch uses them).

- [ ] **Step 7: Add an InspectorPanel test for the datacenter Source link**

Open `services/frontend/src/components/worldview/InspectorPanel.test.tsx`. Append this test inside the existing `describe("InspectorPanel", ...)` block:

```typescript
  it("renders a Source link for a datacenter with source_url", () => {
    render(
      <InspectorPanel
        selected={{
          type: "datacenter",
          data: {
            name: "AWS US-East-1 (Ashburn)",
            operator: "Amazon Web Services",
            tier: "hyperscaler",
            capacity_mw: 600,
            country: "US",
            city: "Ashburn",
            source_url: "https://baxtel.com/data-center/aws-us-east-1",
            coord_quality: "campus_verified",
            coord_source: "https://baxtel.com/data-center/aws-us-east-1",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    const link = screen.getByRole("link", { name: /Source/i });
    expect(link).toHaveAttribute("href", "https://baxtel.com/data-center/aws-us-east-1");
    expect(screen.getByText(/campus_verified/)).toBeInTheDocument();
  });

  it("hides the Source link when datacenter source_url is absent", () => {
    render(
      <InspectorPanel
        selected={{
          type: "datacenter",
          data: {
            name: "Legacy DC",
            operator: "Acme",
            tier: "III",
            capacity_mw: null,
            country: "DE",
            city: "Berlin",
          },
        }}
        onClose={vi.fn()}
        viewer={null}
      />,
    );
    expect(screen.queryByRole("link", { name: /Source/i })).toBeNull();
  });
```

- [ ] **Step 8: Run frontend type-check**

```bash
cd services/frontend && npm run type-check
```

Expected: no errors.

- [ ] **Step 9: Run hook + InspectorPanel tests**

```bash
cd services/frontend && npx vitest run \
  src/hooks/__tests__/useDatacenters.test.ts \
  src/hooks/__tests__/useRefineries.test.ts \
  src/hooks/__tests__/usePipelines.test.ts \
  src/components/worldview/InspectorPanel.test.tsx
```

Expected: all tests pass (existing + the new ones added in Steps 3, 4, 5, 7).

- [ ] **Step 10: Commit**

```bash
git add services/frontend/src/types/infrastructure.ts \
        services/frontend/src/types/pipeline.ts \
        services/frontend/src/hooks/__tests__/useDatacenters.test.ts \
        services/frontend/src/hooks/__tests__/useRefineries.test.ts \
        services/frontend/src/hooks/__tests__/usePipelines.test.ts \
        services/frontend/src/components/worldview/InspectorPanel.tsx \
        services/frontend/src/components/worldview/InspectorPanel.test.tsx
git commit -m "feat(frontend): extend infra schemas + render datacenter source_url in InspectorPanel"
```

---

### Task 3: Pipelines Builder + Full ≥50-Entry Curated Seed

**Files:**
- Create: `services/data-ingestion/infra_atlas/seeds/pipelines.yaml` — full ≥50 entries (content below; engineer copy-pastes verbatim)
- Create: `services/data-ingestion/infra_atlas/build_pipelines.py`
- Create: `services/data-ingestion/infra_atlas/cli.py`
- Create: `services/data-ingestion/tests/test_build_pipelines.py`
- Create: `services/data-ingestion/tests/fixtures/pipeline_seed_sample.yaml`
- Modify: `services/frontend/public/data/pipelines.geojson` (regenerate)

The seed below is the **complete** content the executor must paste into `seeds/pipelines.yaml`. Routes are simplified for globe-overview rendering (5–10 coord pairs per pipeline). Source URLs are Wikipedia article URLs that the executor or a reviewer can use to spot-check route accuracy. The seed has 52 entries.

- [ ] **Step 1: Write the test fixture (small, for unit tests)**

Create `services/data-ingestion/tests/fixtures/pipeline_seed_sample.yaml`:

```yaml
# Trimmed seed for unit tests. Real seed lives in infra_atlas/seeds/pipelines.yaml.
pipelines:
  - name: Nord Stream 1
    tier: major
    type: gas
    status: active
    operator: Nord Stream AG
    capacity_bcm: 55.0
    length_km: 1224
    countries: [Russia, Germany]
    source_url: https://en.wikipedia.org/wiki/Nord_Stream
    route:
      - [28.7, 60.5]
      - [25.0, 59.5]
      - [19.0, 57.5]
      - [13.5, 54.1]
  - name: Druzhba pipeline
    tier: major
    type: oil
    status: active
    operator: Transneft
    capacity_bcm: null
    length_km: 4000
    countries: [Russia, Belarus, Ukraine, Poland, Germany]
    source_url: https://en.wikipedia.org/wiki/Druzhba_pipeline
    route:
      - [52.5, 54.9]
      - [44.0, 53.5]
      - [29.3, 52.0]
      - [22.0, 52.4]
      - [14.3, 53.0]
```

- [ ] **Step 2: Write failing tests**

Create `services/data-ingestion/tests/test_build_pipelines.py`:

```python
"""Tests for the pipeline builder."""

import json
from pathlib import Path

import pytest

from infra_atlas.build_pipelines import (
    PipelineSeed,
    build_pipelines_from_seed,
    load_seed,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_load_seed_returns_seeds() -> None:
    seeds = load_seed(FIXTURE_DIR / "pipeline_seed_sample.yaml")
    assert len(seeds) == 2
    assert seeds[0].name == "Nord Stream 1"
    assert seeds[0].source_url.startswith("https://en.wikipedia.org/")
    assert seeds[0].route[0] == (28.7, 60.5)


def test_load_seed_rejects_route_with_one_point(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "pipelines:\n"
        "  - name: Bad\n"
        "    tier: major\n"
        "    type: oil\n"
        "    status: active\n"
        "    operator: X\n"
        "    capacity_bcm: null\n"
        "    length_km: null\n"
        "    countries: [X]\n"
        "    source_url: https://example.com\n"
        "    route: [[0, 0]]\n"
    )
    with pytest.raises(ValueError, match="route must have"):
        load_seed(bad)


def test_load_seed_rejects_missing_source_url(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "pipelines:\n"
        "  - name: Bad\n"
        "    tier: major\n"
        "    type: oil\n"
        "    status: active\n"
        "    operator: X\n"
        "    capacity_bcm: null\n"
        "    length_km: null\n"
        "    countries: [X]\n"
        "    route: [[0, 0], [1, 1]]\n"
    )
    with pytest.raises(KeyError, match="source_url"):
        load_seed(bad)


def test_build_emits_valid_geojson(tmp_path: Path) -> None:
    seeds = load_seed(FIXTURE_DIR / "pipeline_seed_sample.yaml")
    out = tmp_path / "pipelines.geojson"
    build_pipelines_from_seed(seeds, out)
    data = json.loads(out.read_text())

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2

    nord = data["features"][0]
    assert nord["type"] == "Feature"
    assert nord["geometry"]["type"] == "LineString"
    assert nord["geometry"]["coordinates"][0] == [28.7, 60.5]
    assert nord["properties"]["name"] == "Nord Stream 1"
    assert nord["properties"]["source_url"].startswith("https://en.wikipedia.org/")
    assert "qid" not in nord["properties"]  # Q-ID is optional, sample lacks it


def test_seed_dataclass_route_is_list_of_tuples() -> None:
    seeds = load_seed(FIXTURE_DIR / "pipeline_seed_sample.yaml")
    assert isinstance(seeds[0], PipelineSeed)
    assert all(isinstance(p, tuple) and len(p) == 2 for p in seeds[0].route)
```

- [ ] **Step 3: Run tests to verify failure**

```bash
cd services/data-ingestion && uv run pytest tests/test_build_pipelines.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 4: Implement the builder**

Create `services/data-ingestion/infra_atlas/build_pipelines.py`:

```python
"""Build pipelines.geojson from a curated YAML seed.

The seed is the source of truth: every pipeline carries name, tier, type,
status, operator, optional capacity/length, country list, mandatory
source_url (Wikipedia citation), and a simplified LineString route.

We do NOT round-trip Wikidata for pipelines — Wikidata's pipeline coverage
of route geometry is poor, and the curated seed is more accurate at the
globe-overview level we render.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

PipelineTier = Literal["major", "regional", "local"]
PipelineType = Literal["oil", "gas", "lng", "mixed"]
PipelineStatus = Literal["active", "planned", "under_construction", "shutdown"]


@dataclass(frozen=True)
class PipelineSeed:
    name: str
    tier: PipelineTier
    type: PipelineType
    status: PipelineStatus
    operator: str | None
    capacity_bcm: float | None
    length_km: float | None
    countries: list[str]
    source_url: str
    route: list[tuple[float, float]]
    qid: str | None = None


def load_seed(path: Path) -> list[PipelineSeed]:
    raw = yaml.safe_load(path.read_text())
    out: list[PipelineSeed] = []
    for entry in raw["pipelines"]:
        if "source_url" not in entry:
            raise KeyError(f"source_url is required: {entry.get('name', '?')}")
        route = [(float(lon), float(lat)) for lon, lat in entry["route"]]
        if len(route) < 2:
            raise ValueError(f"route must have ≥2 points: {entry['name']}")
        out.append(
            PipelineSeed(
                name=entry["name"],
                tier=entry["tier"],
                type=entry["type"],
                status=entry["status"],
                operator=entry.get("operator"),
                capacity_bcm=entry.get("capacity_bcm"),
                length_km=entry.get("length_km"),
                countries=list(entry["countries"]),
                source_url=entry["source_url"],
                qid=entry.get("qid"),
                route=route,
            )
        )
    return out


def build_pipelines_from_seed(seeds: list[PipelineSeed], out_path: Path) -> None:
    features = []
    for s in seeds:
        props: dict = {
            "name": s.name,
            "tier": s.tier,
            "type": s.type,
            "status": s.status,
            "operator": s.operator,
            "capacity_bcm": s.capacity_bcm,
            "length_km": s.length_km,
            "countries": s.countries,
            "source_url": s.source_url,
        }
        if s.qid:
            props["qid"] = s.qid
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lon, lat in s.route],
                },
            }
        )
    out_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )
```

- [ ] **Step 5: Create the unified CLI**

Create `services/data-ingestion/infra_atlas/cli.py`:

```python
"""odin-infra-atlas CLI — regenerate static infra GeoJSON datasets."""

from __future__ import annotations

from pathlib import Path

import click

from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS_DIR = Path(__file__).resolve().parent / "seeds"
FRONTEND_DATA = REPO_ROOT / "services" / "frontend" / "public" / "data"


@click.group()
def cli() -> None:
    """Regenerate Worldview infrastructure GeoJSON datasets."""


@cli.command()
@click.option(
    "--seed",
    type=click.Path(exists=True, path_type=Path),
    default=SEEDS_DIR / "pipelines.yaml",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=FRONTEND_DATA / "pipelines.geojson",
)
def pipelines(seed: Path, out: Path) -> None:
    """Build pipelines.geojson from the curated seed."""
    seeds = load_seed(seed)
    build_pipelines_from_seed(seeds, out)
    click.echo(f"Wrote {len(seeds)} pipelines → {out.relative_to(REPO_ROOT)}")
```

- [ ] **Step 6: Run unit tests**

```bash
cd services/data-ingestion && uv run pytest tests/test_build_pipelines.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Write the FULL curated seed**

Create `services/data-ingestion/infra_atlas/seeds/pipelines.yaml` with the EXACT content below (52 entries):

```yaml
# Curated pipeline routes for Worldview globe-overview rendering.
# Each entry has source_url (Wikipedia article) so coordinates and
# metadata can be spot-checked. Routes are simplified to 4-10 coord
# pairs each — Cesium PolylineCollection densifies between them.
# 52 entries; tier breakdown ~30 major + ~22 regional.
pipelines:
  # ───────── Russia / Europe gas ─────────────────────────────────────────
  - name: Nord Stream 1
    tier: major
    type: gas
    status: active
    operator: Nord Stream AG
    capacity_bcm: 55.0
    length_km: 1224
    countries: [Russia, Germany]
    source_url: https://en.wikipedia.org/wiki/Nord_Stream
    route: [[28.7,60.5],[25.0,59.5],[19.0,57.5],[15.0,55.5],[13.5,54.1]]
  - name: Nord Stream 2
    tier: major
    type: gas
    status: planned
    operator: Nord Stream 2 AG
    capacity_bcm: 55.0
    length_km: 1230
    countries: [Russia, Germany]
    source_url: https://en.wikipedia.org/wiki/Nord_Stream_2
    route: [[28.6,60.3],[25.0,59.3],[19.0,57.3],[15.0,55.3],[13.4,53.9]]
  - name: Yamal–Europe pipeline
    tier: major
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 33.0
    length_km: 4196
    countries: [Russia, Belarus, Poland, Germany]
    source_url: https://en.wikipedia.org/wiki/Yamal%E2%80%93Europe_pipeline
    route: [[68.9,67.5],[55.0,58.5],[40.0,55.0],[28.0,53.5],[19.0,52.2],[14.5,52.4]]
  - name: TurkStream
    tier: major
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 31.5
    length_km: 1100
    countries: [Russia, Turkey]
    source_url: https://en.wikipedia.org/wiki/TurkStream
    route: [[37.5,45.0],[35.0,43.5],[33.0,42.0],[30.5,41.6],[28.6,41.7]]
  - name: Blue Stream
    tier: major
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 16.0
    length_km: 1213
    countries: [Russia, Turkey]
    source_url: https://en.wikipedia.org/wiki/Blue_Stream
    route: [[37.9,43.4],[37.0,42.5],[36.0,41.8],[36.3,41.3],[35.0,40.0]]
  - name: Brotherhood pipeline
    tier: major
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 100.0
    length_km: 4451
    countries: [Russia, Ukraine, Slovakia, Czechia, Austria]
    source_url: https://en.wikipedia.org/wiki/Brotherhood_pipeline
    route: [[55.0,57.5],[40.0,54.0],[30.0,50.5],[24.0,49.0],[19.0,48.5],[16.4,48.2]]
  - name: Soyuz pipeline
    tier: major
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 32.0
    length_km: 2750
    countries: [Russia, Ukraine]
    source_url: https://en.wikipedia.org/wiki/Soyuz_gas_pipeline
    route: [[55.0,52.0],[45.0,50.0],[38.0,49.5],[32.0,49.0],[24.0,48.5]]
  # ───────── Russia / Europe oil ─────────────────────────────────────────
  - name: Druzhba pipeline
    tier: major
    type: oil
    status: active
    operator: Transneft
    capacity_bcm: null
    length_km: 4000
    countries: [Russia, Belarus, Ukraine, Poland, Germany]
    source_url: https://en.wikipedia.org/wiki/Druzhba_pipeline
    route: [[52.5,54.9],[44.0,53.5],[29.3,52.0],[22.0,52.4],[18.0,52.5],[14.3,53.0]]
  - name: Baltic Pipeline System
    tier: major
    type: oil
    status: active
    operator: Transneft
    capacity_bcm: null
    length_km: 1190
    countries: [Russia]
    source_url: https://en.wikipedia.org/wiki/Baltic_Pipeline_System
    route: [[55.0,57.0],[42.0,59.5],[36.0,59.7],[30.5,59.9],[28.5,59.4]]
  # ───────── Russia / Asia ───────────────────────────────────────────────
  - name: Power of Siberia
    tier: major
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 38.0
    length_km: 3000
    countries: [Russia, China]
    source_url: https://en.wikipedia.org/wiki/Power_of_Siberia
    route: [[114.0,60.0],[122.0,55.0],[127.0,52.0],[127.5,50.5],[127.0,47.5],[125.0,42.0],[116.4,39.9]]
  - name: Eastern Siberia – Pacific Ocean oil pipeline
    tier: major
    type: oil
    status: active
    operator: Transneft
    capacity_bcm: null
    length_km: 4857
    countries: [Russia]
    source_url: https://en.wikipedia.org/wiki/Eastern_Siberia%E2%80%93Pacific_Ocean_oil_pipeline
    route: [[98.0,56.0],[110.0,55.5],[122.0,54.5],[127.5,54.0],[133.5,48.5],[133.1,42.7]]
  - name: Sakhalin–Khabarovsk–Vladivostok pipeline
    tier: regional
    type: gas
    status: active
    operator: Gazprom
    capacity_bcm: 6.0
    length_km: 1830
    countries: [Russia]
    source_url: https://en.wikipedia.org/wiki/Sakhalin%E2%80%93Khabarovsk%E2%80%93Vladivostok_pipeline
    route: [[143.0,53.5],[140.5,50.5],[135.0,48.5],[132.0,45.0],[131.9,43.1]]
  # ───────── Caspian / Caucasus / Turkey ─────────────────────────────────
  - name: Baku–Tbilisi–Ceyhan pipeline
    tier: major
    type: oil
    status: active
    operator: BP
    capacity_bcm: null
    length_km: 1768
    countries: [Azerbaijan, Georgia, Turkey]
    source_url: https://en.wikipedia.org/wiki/Baku%E2%80%93Tbilisi%E2%80%93Ceyhan_pipeline
    route: [[49.7,40.4],[46.0,41.5],[44.8,41.7],[41.0,40.5],[37.0,38.5],[35.8,36.6]]
  - name: South Caucasus Pipeline
    tier: major
    type: gas
    status: active
    operator: BP
    capacity_bcm: 24.0
    length_km: 692
    countries: [Azerbaijan, Georgia, Turkey]
    source_url: https://en.wikipedia.org/wiki/South_Caucasus_Pipeline
    route: [[49.8,40.3],[46.0,41.4],[43.5,41.6],[41.0,40.5]]
  - name: Trans-Anatolian gas pipeline (TANAP)
    tier: major
    type: gas
    status: active
    operator: SOCAR
    capacity_bcm: 16.0
    length_km: 1841
    countries: [Turkey, Greece]
    source_url: https://en.wikipedia.org/wiki/Trans-Anatolian_gas_pipeline
    route: [[44.0,40.0],[40.0,39.5],[36.0,39.0],[32.0,40.0],[28.0,40.7],[26.0,40.9]]
  - name: Trans-Adriatic Pipeline (TAP)
    tier: major
    type: gas
    status: active
    operator: TAP AG
    capacity_bcm: 10.0
    length_km: 878
    countries: [Greece, Albania, Italy]
    source_url: https://en.wikipedia.org/wiki/Trans_Adriatic_Pipeline
    route: [[26.0,40.9],[22.0,40.7],[20.0,40.5],[19.5,40.5],[18.0,40.3],[17.5,40.4]]
  - name: Iran–Turkey gas pipeline (Tabriz–Ankara)
    tier: regional
    type: gas
    status: active
    operator: National Iranian Gas
    capacity_bcm: 14.0
    length_km: 2577
    countries: [Iran, Turkey]
    source_url: https://en.wikipedia.org/wiki/Iran%E2%80%93Turkey_pipeline
    route: [[51.4,35.7],[49.0,37.5],[46.3,38.1],[42.0,39.5],[36.0,39.5],[32.85,39.93]]
  # ───────── Middle East / Arabian Peninsula ─────────────────────────────
  - name: Dolphin gas pipeline
    tier: major
    type: gas
    status: active
    operator: Dolphin Energy
    capacity_bcm: 33.0
    length_km: 364
    countries: [Qatar, United Arab Emirates, Oman]
    source_url: https://en.wikipedia.org/wiki/Dolphin_Gas_Project
    route: [[51.5,25.5],[52.5,24.7],[53.5,24.5],[54.4,24.5],[56.5,24.0]]
  - name: Arab Gas Pipeline
    tier: regional
    type: gas
    status: active
    operator: Egyptian Natural Gas Holding
    capacity_bcm: 10.0
    length_km: 1200
    countries: [Egypt, Jordan, Syria, Lebanon]
    source_url: https://en.wikipedia.org/wiki/Arab_Gas_Pipeline
    route: [[33.6,30.6],[35.0,29.8],[35.9,31.9],[36.5,33.5],[35.5,33.9]]
  - name: SUMED pipeline
    tier: major
    type: oil
    status: active
    operator: Arab Petroleum Pipelines Company
    capacity_bcm: null
    length_km: 320
    countries: [Egypt]
    source_url: https://en.wikipedia.org/wiki/SUMED_pipeline
    route: [[32.5,29.9],[31.5,30.4],[30.5,30.7],[29.9,31.0],[29.5,31.2]]
  - name: Trans-Arabian Pipeline (Tapline)
    tier: regional
    type: oil
    status: shutdown
    operator: Aramco
    capacity_bcm: null
    length_km: 1213
    countries: [Saudi Arabia, Jordan, Lebanon]
    source_url: https://en.wikipedia.org/wiki/Trans-Arabian_Pipeline
    route: [[50.2,26.4],[44.0,28.5],[39.0,30.0],[36.0,32.5],[35.5,33.4]]
  - name: East–West (Petroline)
    tier: major
    type: oil
    status: active
    operator: Saudi Aramco
    capacity_bcm: null
    length_km: 1200
    countries: [Saudi Arabia]
    source_url: https://en.wikipedia.org/wiki/East-West_Crude_Oil_Pipeline
    route: [[50.2,26.4],[47.0,25.5],[44.0,24.5],[41.0,22.5],[39.5,21.5]]
  # ───────── Central Asia / China ────────────────────────────────────────
  - name: Central Asia – China gas pipeline
    tier: major
    type: gas
    status: active
    operator: PetroChina
    capacity_bcm: 55.0
    length_km: 3666
    countries: [Turkmenistan, Uzbekistan, Kazakhstan, China]
    source_url: https://en.wikipedia.org/wiki/Central_Asia%E2%80%93China_gas_pipeline
    route: [[57.0,38.5],[64.0,40.0],[69.5,41.5],[75.0,43.0],[80.5,44.5],[88.0,42.0]]
  - name: West–East Gas Pipeline (China)
    tier: major
    type: gas
    status: active
    operator: PetroChina
    capacity_bcm: 30.0
    length_km: 4843
    countries: [China]
    source_url: https://en.wikipedia.org/wiki/West%E2%80%93East_Gas_Pipeline
    route: [[80.5,44.0],[88.0,42.5],[100.0,38.0],[110.0,36.0],[118.0,33.5],[121.5,31.2]]
  - name: Kazakhstan–China oil pipeline
    tier: regional
    type: oil
    status: active
    operator: KazTransOil / CNPC
    capacity_bcm: null
    length_km: 2228
    countries: [Kazakhstan, China]
    source_url: https://en.wikipedia.org/wiki/Kazakhstan%E2%80%93China_oil_pipeline
    route: [[51.2,46.3],[60.0,47.0],[71.5,46.5],[79.0,44.5],[87.5,43.5]]
  # ───────── South Asia ──────────────────────────────────────────────────
  - name: Turkmenistan–Afghanistan–Pakistan–India pipeline (TAPI)
    tier: major
    type: gas
    status: under_construction
    operator: TAPI Pipeline Company
    capacity_bcm: 33.0
    length_km: 1814
    countries: [Turkmenistan, Afghanistan, Pakistan, India]
    source_url: https://en.wikipedia.org/wiki/Turkmenistan%E2%80%93Afghanistan%E2%80%93Pakistan%E2%80%93India_Pipeline
    route: [[62.0,38.5],[64.5,34.5],[68.0,31.5],[71.5,30.0],[74.5,29.5]]
  # ───────── North Africa / Mediterranean ────────────────────────────────
  - name: Trans-Mediterranean Pipeline (Transmed)
    tier: major
    type: gas
    status: active
    operator: Eni / Sonatrach
    capacity_bcm: 33.5
    length_km: 2475
    countries: [Algeria, Tunisia, Italy]
    source_url: https://en.wikipedia.org/wiki/Trans-Mediterranean_Pipeline
    route: [[3.3,32.9],[8.0,34.0],[10.5,36.5],[12.5,37.5],[14.0,40.0]]
  - name: Maghreb–Europe Gas Pipeline
    tier: major
    type: gas
    status: shutdown
    operator: Sonatrach
    capacity_bcm: 12.0
    length_km: 1620
    countries: [Algeria, Morocco, Spain]
    source_url: https://en.wikipedia.org/wiki/Maghreb%E2%80%93Europe_Gas_Pipeline
    route: [[3.3,32.9],[-1.5,34.5],[-5.5,35.7],[-5.4,36.3],[-4.5,37.0]]
  - name: Medgaz
    tier: major
    type: gas
    status: active
    operator: Medgaz
    capacity_bcm: 10.0
    length_km: 757
    countries: [Algeria, Spain]
    source_url: https://en.wikipedia.org/wiki/Medgaz
    route: [[-1.4,35.3],[-1.6,35.8],[-2.0,36.3],[-2.5,36.8]]
  - name: Greenstream pipeline
    tier: regional
    type: gas
    status: active
    operator: Eni / Mellitah Oil & Gas
    capacity_bcm: 8.0
    length_km: 540
    countries: [Libya, Italy]
    source_url: https://en.wikipedia.org/wiki/Greenstream_pipeline
    route: [[14.5,32.7],[14.0,34.5],[14.3,36.5],[14.5,37.4]]
  # ───────── Sub-Saharan Africa ──────────────────────────────────────────
  - name: Chad–Cameroon Petroleum Pipeline
    tier: regional
    type: oil
    status: active
    operator: COTCO
    capacity_bcm: null
    length_km: 1070
    countries: [Chad, Cameroon]
    source_url: https://en.wikipedia.org/wiki/Chad%E2%80%93Cameroon_pipeline
    route: [[16.0,8.5],[14.5,7.5],[12.5,5.5],[10.5,4.5],[9.7,4.0]]
  - name: West African Gas Pipeline
    tier: regional
    type: gas
    status: active
    operator: WAPCo
    capacity_bcm: 5.0
    length_km: 678
    countries: [Nigeria, Benin, Togo, Ghana]
    source_url: https://en.wikipedia.org/wiki/West_African_Gas_Pipeline
    route: [[3.4,6.5],[2.5,6.4],[1.5,6.3],[0.5,5.7],[-0.2,5.6]]
  - name: East African Crude Oil Pipeline (EACOP)
    tier: major
    type: oil
    status: under_construction
    operator: TotalEnergies
    capacity_bcm: null
    length_km: 1443
    countries: [Uganda, Tanzania]
    source_url: https://en.wikipedia.org/wiki/East_African_Crude_Oil_Pipeline
    route: [[31.5,1.5],[32.5,0.5],[34.0,-2.5],[36.0,-4.5],[38.5,-6.0],[39.0,-7.0]]
  # ───────── North America (oil) ─────────────────────────────────────────
  - name: Keystone Pipeline
    tier: major
    type: oil
    status: active
    operator: TC Energy
    capacity_bcm: null
    length_km: 3461
    countries: [Canada, United States]
    source_url: https://en.wikipedia.org/wiki/Keystone_Pipeline
    route: [[-110.0,53.0],[-104.0,49.0],[-99.0,45.0],[-96.0,40.0],[-94.0,35.0],[-93.5,29.5]]
  - name: Trans Mountain Pipeline
    tier: regional
    type: oil
    status: active
    operator: Trans Mountain Corporation
    capacity_bcm: null
    length_km: 1150
    countries: [Canada]
    source_url: https://en.wikipedia.org/wiki/Trans_Mountain_pipeline
    route: [[-113.5,53.5],[-117.0,52.5],[-120.0,51.0],[-122.5,49.5],[-122.9,49.3]]
  - name: Enbridge Mainline
    tier: major
    type: oil
    status: active
    operator: Enbridge
    capacity_bcm: null
    length_km: 5000
    countries: [Canada, United States]
    source_url: https://en.wikipedia.org/wiki/Enbridge_Mainline
    route: [[-113.5,53.5],[-105.0,50.5],[-97.0,49.0],[-92.0,46.5],[-85.0,42.5],[-79.5,42.5]]
  - name: Colonial Pipeline
    tier: major
    type: oil
    status: active
    operator: Colonial Pipeline Company
    capacity_bcm: null
    length_km: 8850
    countries: [United States]
    source_url: https://en.wikipedia.org/wiki/Colonial_Pipeline
    route: [[-95.0,29.7],[-88.0,32.5],[-84.5,33.7],[-78.5,36.0],[-77.0,38.9],[-74.0,40.7]]
  - name: Dakota Access Pipeline
    tier: regional
    type: oil
    status: active
    operator: Energy Transfer Partners
    capacity_bcm: null
    length_km: 1886
    countries: [United States]
    source_url: https://en.wikipedia.org/wiki/Dakota_Access_Pipeline
    route: [[-103.5,47.5],[-100.0,45.0],[-96.5,42.5],[-93.5,40.5],[-91.0,38.5]]
  - name: Permian Highway Pipeline
    tier: regional
    type: gas
    status: active
    operator: Kinder Morgan
    capacity_bcm: 21.0
    length_km: 692
    countries: [United States]
    source_url: https://en.wikipedia.org/wiki/Permian_Highway_Pipeline
    route: [[-104.0,32.0],[-101.5,31.0],[-99.0,30.5],[-97.0,29.5],[-96.0,29.0]]
  # ───────── North America (gas) ─────────────────────────────────────────
  - name: Rockies Express Pipeline
    tier: major
    type: gas
    status: active
    operator: Tallgrass Energy
    capacity_bcm: 18.0
    length_km: 2702
    countries: [United States]
    source_url: https://en.wikipedia.org/wiki/Rockies_Express_Pipeline
    route: [[-108.0,41.0],[-103.0,40.0],[-95.0,39.5],[-87.0,39.5],[-81.5,40.0]]
  - name: Mountain Valley Pipeline
    tier: regional
    type: gas
    status: active
    operator: Equitrans Midstream
    capacity_bcm: 20.0
    length_km: 487
    countries: [United States]
    source_url: https://en.wikipedia.org/wiki/Mountain_Valley_Pipeline
    route: [[-80.5,39.5],[-80.0,38.5],[-79.5,37.5],[-79.0,37.0],[-80.0,36.7]]
  - name: Atlantic Sunrise Pipeline
    tier: regional
    type: gas
    status: active
    operator: Williams Companies
    capacity_bcm: 18.0
    length_km: 320
    countries: [United States]
    source_url: https://en.wikipedia.org/wiki/Atlantic_Sunrise_Pipeline
    route: [[-77.0,41.7],[-76.5,41.0],[-76.5,40.0],[-76.5,39.0]]
  - name: Coastal GasLink Pipeline
    tier: regional
    type: gas
    status: active
    operator: TC Energy
    capacity_bcm: 14.0
    length_km: 670
    countries: [Canada]
    source_url: https://en.wikipedia.org/wiki/Coastal_GasLink_Pipeline
    route: [[-121.0,55.5],[-124.0,54.5],[-126.5,54.0],[-128.5,54.0],[-128.6,54.05]]
  # ───────── South America ──────────────────────────────────────────────
  - name: GASBOL (Bolivia–Brazil pipeline)
    tier: major
    type: gas
    status: active
    operator: TBG / GTB
    capacity_bcm: 11.0
    length_km: 3150
    countries: [Bolivia, Brazil]
    source_url: https://en.wikipedia.org/wiki/Bolivia%E2%80%93Brazil_pipeline
    route: [[-63.2,-17.8],[-58.0,-19.0],[-54.0,-22.0],[-49.0,-23.5],[-46.6,-23.5]]
  - name: OCENSA pipeline
    tier: regional
    type: oil
    status: active
    operator: Cenit / Ecopetrol
    capacity_bcm: null
    length_km: 829
    countries: [Colombia]
    source_url: https://en.wikipedia.org/wiki/OCENSA_pipeline
    route: [[-72.5,4.5],[-73.5,5.5],[-74.5,7.5],[-75.5,8.5],[-75.5,9.4]]
  - name: TGN gas pipeline
    tier: regional
    type: gas
    status: active
    operator: TGN
    capacity_bcm: 23.0
    length_km: 9000
    countries: [Argentina]
    source_url: https://en.wikipedia.org/wiki/Transportadora_de_Gas_del_Norte
    route: [[-67.5,-32.5],[-65.5,-30.5],[-64.0,-29.0],[-62.0,-29.5],[-58.5,-34.6]]
  # ───────── European intra-EU ──────────────────────────────────────────
  - name: Trans Austria Gas Pipeline
    tier: regional
    type: gas
    status: active
    operator: Gas Connect Austria
    capacity_bcm: 47.0
    length_km: 380
    countries: [Austria]
    source_url: https://en.wikipedia.org/wiki/Trans_Austria_Gas_Pipeline
    route: [[16.9,48.5],[15.5,48.0],[14.0,47.5],[12.5,47.5],[11.5,47.4]]
  - name: BBL Pipeline (Balgzand–Bacton Line)
    tier: regional
    type: gas
    status: active
    operator: BBL Company
    capacity_bcm: 19.2
    length_km: 235
    countries: [Netherlands, United Kingdom]
    source_url: https://en.wikipedia.org/wiki/BBL_Pipeline
    route: [[4.7,52.9],[3.5,53.0],[2.0,52.9],[1.4,52.7]]
  - name: Interconnector (UK–Belgium)
    tier: regional
    type: gas
    status: active
    operator: Interconnector (UK)
    capacity_bcm: 25.5
    length_km: 235
    countries: [United Kingdom, Belgium]
    source_url: https://en.wikipedia.org/wiki/Interconnector_(North_Sea)
    route: [[1.3,52.5],[2.0,52.0],[2.5,51.5],[3.2,51.3]]
  - name: Baltic Pipe
    tier: regional
    type: gas
    status: active
    operator: Energinet / Gaz-System
    capacity_bcm: 10.0
    length_km: 900
    countries: [Norway, Denmark, Poland]
    source_url: https://en.wikipedia.org/wiki/Baltic_Pipe
    route: [[5.7,57.5],[8.0,56.0],[10.5,55.5],[14.5,54.5],[16.4,54.2]]
  - name: GIPL (Poland–Lithuania interconnection)
    tier: regional
    type: gas
    status: active
    operator: Gaz-System / Amber Grid
    capacity_bcm: 2.4
    length_km: 508
    countries: [Poland, Lithuania]
    source_url: https://en.wikipedia.org/wiki/Gas_Interconnection_Poland%E2%80%93Lithuania
    route: [[22.0,53.5],[22.5,54.0],[23.0,54.5],[23.7,54.9]]
  - name: IGB (Greece–Bulgaria interconnector)
    tier: regional
    type: gas
    status: active
    operator: ICGB
    capacity_bcm: 3.0
    length_km: 182
    countries: [Greece, Bulgaria]
    source_url: https://en.wikipedia.org/wiki/Interconnector_Greece%E2%80%93Bulgaria
    route: [[24.4,40.9],[24.7,41.6],[25.0,42.1],[25.6,42.4]]
```

> **Engineer note:** The seed has 52 entries. Do not silently truncate it. If parsing fails on any entry, fix the entry, do not delete it.

- [ ] **Step 8: Run the builder against the real seed**

```bash
cd services/data-ingestion && uv run odin-infra-atlas pipelines
```

Expected: `Wrote 52 pipelines → services/frontend/public/data/pipelines.geojson`

- [ ] **Step 9: Validate the output**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.worktrees/odin-s2-worldview-port && \
  jq '.features | length' services/frontend/public/data/pipelines.geojson
```

Expected: `52`.

```bash
jq '[.features[] | select(.properties.source_url | not)] | length' \
  services/frontend/public/data/pipelines.geojson
```

Expected: `0` (every feature has source_url).

```bash
jq '[.features[] | select(.geometry.coordinates | length < 2)] | length' \
  services/frontend/public/data/pipelines.geojson
```

Expected: `0` (no degenerate routes).

- [ ] **Step 10: Frontend type-check + visual smoke**

```bash
cd services/frontend && npm run type-check
```

Expected: no errors (the `source_url` and `qid` fields you added in Task 2 are now exercised by real data).

Hard-reload the Vite dev server (port 5173 per `AGENTS.md`, or 5174 if you started it in this S2 worktree) and toggle Pipelines layer ON. Visually confirm the pipeline count is dense (now ≥50) and that lines span Russia→Europe, Caspian→Med, China west-east, North America, sub-Saharan Africa.

- [ ] **Step 11: Commit**

```bash
git add services/data-ingestion/infra_atlas/seeds/pipelines.yaml \
        services/data-ingestion/infra_atlas/build_pipelines.py \
        services/data-ingestion/infra_atlas/cli.py \
        services/data-ingestion/tests/test_build_pipelines.py \
        services/data-ingestion/tests/fixtures/pipeline_seed_sample.yaml \
        services/frontend/public/data/pipelines.geojson
git commit -m "feat(infra_atlas): regenerate pipelines.geojson from 52-entry curated seed"
```

---

### Task 4: Refineries Enrichment (existing 199 + Wikidata enrichment)

**Files:**
- Create: `services/data-ingestion/infra_atlas/build_refineries.py`
- Modify: `services/data-ingestion/infra_atlas/cli.py` — add `refineries` subcommand
- Create: `services/data-ingestion/tests/test_build_refineries.py`
- Create: `services/data-ingestion/tests/fixtures/wikidata_refinery_sample.json`
- Create: `services/data-ingestion/tests/fixtures/existing_refineries_sample.geojson`
- Modify: `services/frontend/public/data/refineries.geojson` (regenerate)

**Strategy:**
1. Load the existing `services/frontend/public/data/refineries.geojson` (199 features).
2. Live-query Wikidata for `?item wdt:P31/wdt:P279* wd:Q12353044` (oil refinery) and `?item wdt:P31/wdt:P279* wd:Q15709854` (LNG terminal), pulling: itemLabel, coord, operator, country code, image, English description.
3. Build a match index keyed by `normalized_name` (lowercase, alphanum only) + country.
4. For each existing entry: if the Wikidata index has a match, set `qid`, `source_url`, `image_url` (only if existing has none), and merge a sentence from the English description into `specs` if not already present. **Do NOT overwrite existing `name`, `operator`, `capacity_bpd`, or coords.**
5. For each Wikidata entry NOT matched against an existing one: append as a new feature with `coord_quality: "wikidata_verified"`, `coord_source: "wikidata"`, `capacity_bpd: 0` (we do NOT invent capacity — P2197 is empty in Wikidata).
6. Write the merged set.

- [ ] **Step 1: Write the existing-data fixture**

Create `services/data-ingestion/tests/fixtures/existing_refineries_sample.geojson`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [69.868889, 22.348056]},
      "properties": {
        "name": "Jamnagar Refinery",
        "operator": "Reliance Industries",
        "capacity_bpd": 1240000,
        "country": "IN",
        "status": "active",
        "facility_type": "refinery",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Existing_Jamnagar.jpg",
        "specs": ["Existing curated note about Jamnagar."]
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [50.158, 26.643]},
      "properties": {
        "name": "Ras Tanura Refinery",
        "operator": "Saudi Aramco",
        "capacity_bpd": 550000,
        "country": "SA",
        "status": "active",
        "facility_type": "refinery"
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [-95.255, 29.736]},
      "properties": {
        "name": "Baytown Refinery",
        "operator": "ExxonMobil",
        "capacity_bpd": 584000,
        "country": "US",
        "status": "active",
        "facility_type": "refinery"
      }
    }
  ]
}
```

- [ ] **Step 2: Write the Wikidata fixture**

Create `services/data-ingestion/tests/fixtures/wikidata_refinery_sample.json`:

```json
{
  "head": {"vars": ["item","itemLabel","coord","operatorLabel","countryCode","image","description","facility_type"]},
  "results": {
    "bindings": [
      {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q3417395"},
        "itemLabel": {"type": "literal", "value": "Jamnagar Refinery"},
        "coord": {"type": "literal", "value": "Point(69.868889 22.348056)"},
        "operatorLabel": {"type": "literal", "value": "Reliance Industries"},
        "countryCode": {"type": "literal", "value": "IN"},
        "image": {"type": "uri", "value": "https://commons.wikimedia.org/wiki/Special:FilePath/Wikidata_Jamnagar.jpg"},
        "description": {"type": "literal", "value": "Largest single-location refinery complex in the world."},
        "facility_type": {"type": "literal", "value": "refinery"}
      },
      {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q860840"},
        "itemLabel": {"type": "literal", "value": "Ras Tanura Refinery"},
        "coord": {"type": "literal", "value": "Point(50.158 26.643)"},
        "operatorLabel": {"type": "literal", "value": "Saudi Aramco"},
        "countryCode": {"type": "literal", "value": "SA"},
        "image": {"type": "uri", "value": "https://commons.wikimedia.org/wiki/Special:FilePath/Ras_Tanura.jpg"},
        "description": {"type": "literal", "value": "Major Saudi Aramco refinery on the Persian Gulf."},
        "facility_type": {"type": "literal", "value": "refinery"}
      },
      {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q9999999"},
        "itemLabel": {"type": "literal", "value": "New Wikidata Refinery"},
        "coord": {"type": "literal", "value": "Point(10.0 20.0)"},
        "operatorLabel": {"type": "literal", "value": "Acme Oil"},
        "countryCode": {"type": "literal", "value": "ZZ"},
        "facility_type": {"type": "literal", "value": "refinery"}
      }
    ]
  }
}
```

- [ ] **Step 3: Write failing tests**

Create `services/data-ingestion/tests/test_build_refineries.py`:

```python
"""Tests for the refinery enrichment builder."""

import json
from pathlib import Path

from pytest_httpx import HTTPXMock

from infra_atlas.build_refineries import build_refineries

FIXTURE = Path(__file__).parent / "fixtures"


def test_existing_image_is_preserved(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())

    jam = next(f for f in data["features"] if f["properties"]["name"] == "Jamnagar Refinery")
    # Existing image must NOT be overwritten by Wikidata's image
    assert jam["properties"]["image_url"].endswith("Existing_Jamnagar.jpg")
    # Wikidata enrichment still adds qid + source_url
    assert jam["properties"]["qid"] == "Q3417395"
    assert jam["properties"]["source_url"] == "https://www.wikidata.org/wiki/Q3417395"
    # Existing spec is preserved AND Wikidata description is appended
    specs = jam["properties"]["specs"]
    assert "Existing curated note about Jamnagar." in specs
    assert any("Largest" in s for s in specs)


def test_existing_capacity_and_operator_not_overwritten(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())

    jam = next(f for f in data["features"] if f["properties"]["name"] == "Jamnagar Refinery")
    assert jam["properties"]["operator"] == "Reliance Industries"
    assert jam["properties"]["capacity_bpd"] == 1240000


def test_existing_without_image_gets_wikidata_image(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())

    rt = next(f for f in data["features"] if f["properties"]["name"] == "Ras Tanura Refinery")
    assert rt["properties"]["image_url"].endswith("Ras_Tanura.jpg")
    assert rt["properties"]["qid"] == "Q860840"


def test_wikidata_only_entry_appended_with_zero_capacity(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    count = build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())
    # 3 existing + 1 wikidata-only = 4 (Jamnagar + Ras Tanura matched in-place)
    assert count == 4
    new_entry = next(f for f in data["features"] if f["properties"]["name"] == "New Wikidata Refinery")
    assert new_entry["properties"]["capacity_bpd"] == 0
    assert new_entry["properties"]["coord_quality"] == "wikidata_verified"
    assert new_entry["properties"]["coord_source"] == "wikidata"


def test_existing_unmatched_entry_marked_legacy(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_refinery_sample.json").read_text()))
    out = tmp_path / "refineries.geojson"
    build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    data = json.loads(out.read_text())
    bay = next(f for f in data["features"] if f["properties"]["name"] == "Baytown Refinery")
    # Baytown isn't in the wikidata fixture
    assert bay["properties"].get("qid") is None
    assert bay["properties"].get("coord_quality") == "legacy"


def test_count_never_falls_below_existing(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    """If Wikidata is empty, output must equal existing count exactly."""
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    out = tmp_path / "refineries.geojson"
    count = build_refineries(
        out,
        existing_path=FIXTURE / "existing_refineries_sample.geojson",
    )
    assert count == 3  # exactly the existing 3
```

- [ ] **Step 4: Run tests to verify failure**

```bash
cd services/data-ingestion && uv run pytest tests/test_build_refineries.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 5: Implement the builder**

Create `services/data-ingestion/infra_atlas/build_refineries.py`:

```python
"""Build refineries.geojson by enriching an existing dataset with Wikidata.

Matches existing entries to Wikidata by normalized (name, country). Wikidata
fills only fields the existing dataset is missing — never overwrites name,
operator, capacity_bpd, or coords. Wikidata-only entries are appended.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from infra_atlas.constants import (
    COORD_QUALITY_LEGACY,
    COORD_QUALITY_WIKIDATA_VERIFIED,
    COORD_SOURCE_WIKIDATA,
    QID_LNG_TERMINAL,
    QID_OIL_REFINERY,
)
from infra_atlas.wikidata import WikidataClient, WikidataRow


_NAME_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(name: str) -> str:
    return _NAME_NORMALIZE_RE.sub("", name.lower())


REFINERY_QUERY = f"""
SELECT DISTINCT ?item ?itemLabel ?coord ?operatorLabel
       ?countryCode ?image ?description ?facility_type WHERE {{
  VALUES ?type {{ wd:{QID_OIL_REFINERY} wd:{QID_LNG_TERMINAL} }}
  ?item wdt:P31/wdt:P279* ?type ;
        wdt:P625 ?coord .
  BIND(IF(?type = wd:{QID_OIL_REFINERY}, "refinery",
       IF(?type = wd:{QID_LNG_TERMINAL}, "lng_terminal", "chemical_plant"))
       AS ?facility_type)
  OPTIONAL {{ ?item wdt:P137 ?operator . ?operator rdfs:label ?operatorLabel
              FILTER(LANG(?operatorLabel) = "en") }}
  OPTIONAL {{ ?item wdt:P17 ?country . ?country wdt:P297 ?countryCode }}
  OPTIONAL {{ ?item wdt:P18 ?image }}
  OPTIONAL {{ ?item schema:description ?description
              FILTER(LANG(?description) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
ORDER BY ?itemLabel
"""


def _normalize_commons_image(url: str) -> str:
    if "Special:FilePath" in url:
        return url
    filename = url.rsplit("/", 1)[-1]
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}"


def _format_dms(lon: float, lat: float) -> str:
    def piece(v: float, pos: str, neg: str) -> str:
        d = abs(v)
        deg = int(d)
        m = (d - deg) * 60
        mi = int(m)
        sec = (m - mi) * 60
        return f"{deg}°{mi}'{sec:.0f}\"{pos if v >= 0 else neg}"
    return f"WGS84 position: {piece(lat, 'N', 'S')}, {piece(lon, 'E', 'W')}"


def _index_wikidata(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if "coord" not in row or "item" not in row:
            continue
        try:
            WikidataRow.parse_wkt_point(row["coord"])
        except ValueError:
            continue
        name = row.get("itemLabel", "")
        country = row.get("countryCode", "")
        if not name or not country:
            continue
        index[(_normalize(name), country)] = row
    return index


def _enrich_existing(
    feature: dict[str, Any],
    wd_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    props = dict(feature["properties"])
    key = (_normalize(props.get("name", "")), props.get("country", ""))
    match = wd_index.get(key)

    if match is None:
        props.setdefault("coord_quality", COORD_QUALITY_LEGACY)
        return {"type": "Feature", "geometry": feature["geometry"], "properties": props}

    qid = WikidataRow.qid_from_uri(match["item"])
    props.setdefault("qid", qid)
    props.setdefault("source_url", f"https://www.wikidata.org/wiki/{qid}")
    if "image_url" not in props and match.get("image"):
        props["image_url"] = _normalize_commons_image(match["image"])
    if match.get("description"):
        existing_specs = list(props.get("specs", []))
        if match["description"] not in existing_specs:
            existing_specs.append(match["description"])
        props["specs"] = existing_specs
    props.setdefault("coord_quality", COORD_QUALITY_WIKIDATA_VERIFIED)
    return {"type": "Feature", "geometry": feature["geometry"], "properties": props}


def _wikidata_only_feature(row: dict[str, Any]) -> dict[str, Any] | None:
    if "coord" not in row or "item" not in row:
        return None
    try:
        lon, lat = WikidataRow.parse_wkt_point(row["coord"])
    except ValueError:
        return None
    qid = WikidataRow.qid_from_uri(row["item"])
    specs = [_format_dms(lon, lat)]
    if row.get("description"):
        specs.append(row["description"])
    props: dict[str, Any] = {
        "name": row.get("itemLabel", qid),
        "operator": row.get("operatorLabel", "Unknown"),
        "capacity_bpd": 0,  # never invent capacity
        "country": row.get("countryCode", "??"),
        "status": "active",
        "facility_type": row.get("facility_type", "refinery"),
        "qid": qid,
        "source_url": f"https://www.wikidata.org/wiki/{qid}",
        "coord_quality": COORD_QUALITY_WIKIDATA_VERIFIED,
        "coord_source": COORD_SOURCE_WIKIDATA,
        "specs": specs,
    }
    if row.get("image"):
        props["image_url"] = _normalize_commons_image(row["image"])
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def build_refineries(out_path: Path, existing_path: Path) -> int:
    existing = json.loads(existing_path.read_text())
    rows = WikidataClient().query(REFINERY_QUERY)
    wd_index = _index_wikidata(rows)

    seen_keys: set[tuple[str, str]] = set()
    out_features: list[dict[str, Any]] = []

    for f in existing["features"]:
        enriched = _enrich_existing(f, wd_index)
        out_features.append(enriched)
        seen_keys.add(
            (_normalize(enriched["properties"]["name"]),
             enriched["properties"].get("country", ""))
        )

    for key, row in wd_index.items():
        if key in seen_keys:
            continue
        new = _wikidata_only_feature(row)
        if new is not None:
            out_features.append(new)
            seen_keys.add(key)

    out_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": out_features}, indent=2)
    )
    return len(out_features)
```

- [ ] **Step 6: Wire CLI subcommand**

Modify `services/data-ingestion/infra_atlas/cli.py`:

(a) Add the import beside the existing one. Replace:

```python
from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed
```

with:

```python
from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed
from infra_atlas.build_refineries import build_refineries
```

(b) Append at the end of the file (after the `pipelines` command):

```python
@cli.command()
@click.option(
    "--existing",
    type=click.Path(exists=True, path_type=Path),
    default=FRONTEND_DATA / "refineries.geojson",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=FRONTEND_DATA / "refineries.geojson",
)
def refineries(existing: Path, out: Path) -> None:
    """Enrich existing refineries.geojson with Wikidata image + provenance."""
    n = build_refineries(out, existing_path=existing)
    click.echo(f"Wrote {n} refineries → {out.relative_to(REPO_ROOT)}")
```

> Note: existing and out default to the same path so the file is regenerated in place.

- [ ] **Step 7: Run unit tests**

```bash
cd services/data-ingestion && uv run pytest tests/test_build_refineries.py -v
```

Expected: 6 passed.

- [ ] **Step 8: Backup current refineries file (sanity)**

```bash
cp services/frontend/public/data/refineries.geojson \
   /tmp/refineries.geojson.bak.$(date +%s)
```

- [ ] **Step 9: Run live builder against current dataset**

```bash
cd services/data-ingestion && uv run odin-infra-atlas refineries
```

Expected: `Wrote N refineries → services/frontend/public/data/refineries.geojson` where `N >= 199`.

- [ ] **Step 10: Validate hard acceptance criteria**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.worktrees/odin-s2-worldview-port

# Count must not drop
jq '.features | length' services/frontend/public/data/refineries.geojson
# Expected: >= 199

# Image+source+specs coverage
jq '[.features[] | select(.properties.image_url and .properties.source_url and (.properties.specs|length) > 0)] | length' \
  services/frontend/public/data/refineries.geojson
# Expected: >= 80

# Capacity preservation: no new non-zero capacities
jq '[.features[] | select((.properties.qid != null) and (.properties.coord_quality == "wikidata_verified") and (.properties.capacity_bpd > 0))] | length' \
  services/frontend/public/data/refineries.geojson
# This is the count of "wikidata-enriched existing entries" with non-zero
# capacity. They MUST equal the count of existing entries with non-zero
# capacity that matched in Wikidata. Manually compare with /tmp backup.
```

Then run a preservation diff:

```bash
diff <(jq -r '.features[] | select(.properties.image_url) | .properties.name + "|" + .properties.image_url' /tmp/refineries.geojson.bak.* | sort) \
     <(jq -r '.features[] | select(.properties.image_url) | .properties.name + "|" + .properties.image_url' services/frontend/public/data/refineries.geojson | sort) | head
```

Expected: no removed lines (`<`-prefix). New lines (`>`-prefix) are OK — those are Wikidata-added images.

- [ ] **Step 11: Visual smoke**

Reload Worldview, toggle Refineries ON. Click 3 random refineries; the InspectorPanel must render image + specs for at least one.

- [ ] **Step 12: Commit**

```bash
git add services/data-ingestion/infra_atlas/build_refineries.py \
        services/data-ingestion/infra_atlas/cli.py \
        services/data-ingestion/tests/test_build_refineries.py \
        services/data-ingestion/tests/fixtures/wikidata_refinery_sample.json \
        services/data-ingestion/tests/fixtures/existing_refineries_sample.geojson \
        services/frontend/public/data/refineries.geojson
git commit -m "feat(infra_atlas): enrich refineries.geojson with Wikidata (preserves existing curation)"
```

---

### Task 5: Datacenters Enrichment + Hyperscaler Campus Seed

**Files:**
- Create: `services/data-ingestion/infra_atlas/build_datacenters.py`
- Create: `services/data-ingestion/infra_atlas/seeds/datacenters_hyperscaler.yaml`
- Create: `services/data-ingestion/tests/test_build_datacenters.py`
- Create: `services/data-ingestion/tests/fixtures/wikidata_datacenter_sample.json`
- Create: `services/data-ingestion/tests/fixtures/existing_datacenters_sample.geojson`
- Create: `services/data-ingestion/infra_atlas/seeds/known_city_centroids.json` (lives under `seeds/` so it ships in the wheel — see Task 1 wheel-include)
- Modify: `services/data-ingestion/infra_atlas/cli.py` — add `datacenters` subcommand
- Modify: `services/frontend/public/data/datacenters.geojson` (regenerate)

**Strategy:**
1. Load the existing 268-feature dataset.
2. Live-query Wikidata for `?item wdt:P31/wdt:P279* wd:Q671224 ; wdt:P625 ?coord` (~70 entities).
3. For each existing entry: if Wikidata matches by normalized `(name, country)`, set `qid` + `source_url`. Compare existing coords with Wikidata's via haversine — if distance >5 km, replace with Wikidata's coord and set `coord_quality: "wikidata_verified"`/`coord_source: "wikidata"`. If ≤5 km, keep existing coord but mark `coord_quality: "wikidata_verified"`. Otherwise leave as `coord_quality: "legacy"`.
4. Append Wikidata-only entries (those not matched) with `coord_quality: "wikidata_verified"`.
5. Apply the hyperscaler seed (≥30 entries) on top: each seed entry MUST have `coord_quality: "campus_verified"` and a `coord_source` URL. Seed entries replace any same-`(name, country)` entry from the previous steps. **Reject seed entries whose coords match a known city centroid.**

- [ ] **Step 1: Add the known city-centroids data file**

Create `services/data-ingestion/infra_atlas/seeds/known_city_centroids.json` (under `seeds/` so it ships in the wheel and the CLI can find it from an installed package):

```json
{
  "centroids": [
    {"name": "Frankfurt am Main", "lat": 50.1109, "lon": 8.6821},
    {"name": "Dublin", "lat": 53.3498, "lon": -6.2603},
    {"name": "Amsterdam", "lat": 52.3702, "lon": 4.8952},
    {"name": "Council Bluffs", "lat": 41.2619, "lon": -95.8608},
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198},
    {"name": "Sydney", "lat": -33.8688, "lon": 151.2093},
    {"name": "São Paulo", "lat": -23.5505, "lon": -46.6333},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
    {"name": "Seoul", "lat": 37.5665, "lon": 126.9780}
  ],
  "tolerance_km": 1.0
}
```

- [ ] **Step 2: Add the existing-data fixture**

Create `services/data-ingestion/tests/fixtures/existing_datacenters_sample.geojson`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [-77.4875, 39.0438]},
      "properties": {
        "name": "AWS US-East-1 (Ashburn)",
        "operator": "Amazon Web Services",
        "tier": "hyperscaler",
        "capacity_mw": 600,
        "country": "US",
        "city": "Ashburn"
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [-0.5, 51.5]},
      "properties": {
        "name": "Equinix LD8",
        "operator": "Equinix",
        "tier": "III",
        "capacity_mw": null,
        "country": "GB",
        "city": "London"
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [4.0, 50.0]},
      "properties": {
        "name": "Random Existing DC",
        "operator": "RandomCo",
        "tier": "III",
        "capacity_mw": null,
        "country": "BE",
        "city": "Brussels"
      }
    }
  ]
}
```

- [ ] **Step 3: Add the Wikidata fixture**

Create `services/data-ingestion/tests/fixtures/wikidata_datacenter_sample.json`:

```json
{
  "head": {"vars": ["item","itemLabel","coord","operatorLabel","countryCode","city"]},
  "results": {
    "bindings": [
      {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q5234567"},
        "itemLabel": {"type": "literal", "value": "Equinix LD8"},
        "coord": {"type": "literal", "value": "Point(-0.0066 51.5142)"},
        "operatorLabel": {"type": "literal", "value": "Equinix"},
        "countryCode": {"type": "literal", "value": "GB"},
        "city": {"type": "literal", "value": "London"}
      },
      {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q5234568"},
        "itemLabel": {"type": "literal", "value": "Brand New DC"},
        "coord": {"type": "literal", "value": "Point(2.3522 48.8566)"},
        "operatorLabel": {"type": "literal", "value": "OVH"},
        "countryCode": {"type": "literal", "value": "FR"},
        "city": {"type": "literal", "value": "Paris"}
      }
    ]
  }
}
```

- [ ] **Step 4: Write failing tests**

Create `services/data-ingestion/tests/test_build_datacenters.py`:

```python
"""Tests for the datacenter enrichment builder."""

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from infra_atlas.build_datacenters import (
    CityCentroidViolation,
    build_datacenters,
    haversine_km,
)

FIXTURE = Path(__file__).parent / "fixtures"
SEEDS_DIR = Path(__file__).resolve().parents[1] / "infra_atlas" / "seeds"


def test_existing_coord_replaced_when_wikidata_distance_exceeds_5km(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_datacenter_sample.json").read_text()))
    seed = tmp_path / "seed.yaml"
    seed.write_text("datacenters: []\n")
    out = tmp_path / "datacenters.geojson"

    build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    data = json.loads(out.read_text())

    ld8 = next(f for f in data["features"] if f["properties"]["name"] == "Equinix LD8")
    # Wikidata says (-0.0066, 51.5142); existing said (-0.5, 51.5). Distance > 5 km.
    assert ld8["geometry"]["coordinates"] == [-0.0066, 51.5142]
    assert ld8["properties"]["coord_quality"] == "wikidata_verified"
    assert ld8["properties"]["coord_source"] == "wikidata"
    assert ld8["properties"]["qid"] == "Q5234567"


def test_existing_unmatched_marked_legacy(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_datacenter_sample.json").read_text()))
    seed = tmp_path / "seed.yaml"
    seed.write_text("datacenters: []\n")
    out = tmp_path / "datacenters.geojson"

    build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    data = json.loads(out.read_text())
    rand = next(f for f in data["features"] if f["properties"]["name"] == "Random Existing DC")
    assert rand["properties"]["coord_quality"] == "legacy"


def test_seed_overrides_existing_and_marks_campus_verified(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json=json.loads((FIXTURE / "wikidata_datacenter_sample.json").read_text()))
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "datacenters:\n"
        "  - name: AWS US-East-1 (Ashburn)\n"
        "    operator: Amazon Web Services\n"
        "    tier: hyperscaler\n"
        "    capacity_mw: 700\n"
        "    country: US\n"
        "    city: Ashburn\n"
        "    lon: -77.4575\n"
        "    lat: 39.0260\n"
        "    coord_source: https://baxtel.com/data-center/aws-us-east-1\n"
    )
    out = tmp_path / "datacenters.geojson"

    build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    data = json.loads(out.read_text())
    aws = next(f for f in data["features"] if f["properties"]["name"] == "AWS US-East-1 (Ashburn)")
    assert aws["geometry"]["coordinates"] == [-77.4575, 39.0260]
    assert aws["properties"]["capacity_mw"] == 700
    assert aws["properties"]["coord_quality"] == "campus_verified"
    assert aws["properties"]["coord_source"].startswith("https://")


def test_seed_with_city_centroid_coords_is_rejected(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "datacenters:\n"
        "  - name: Lazy DC\n"
        "    operator: Acme\n"
        "    tier: hyperscaler\n"
        "    capacity_mw: 100\n"
        "    country: DE\n"
        "    city: Frankfurt\n"
        "    lon: 8.6821\n"
        "    lat: 50.1109\n"
        "    coord_source: https://example.com\n"
    )
    out = tmp_path / "datacenters.geojson"

    with pytest.raises(CityCentroidViolation, match="Frankfurt"):
        build_datacenters(
            out,
            existing_path=FIXTURE / "existing_datacenters_sample.geojson",
            seed_path=seed,
            centroids_path=SEEDS_DIR / "known_city_centroids.json",
        )


def test_seed_without_coord_source_is_rejected(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "datacenters:\n"
        "  - name: Unsourced DC\n"
        "    operator: Acme\n"
        "    tier: hyperscaler\n"
        "    capacity_mw: 100\n"
        "    country: US\n"
        "    city: Somewhere\n"
        "    lon: -100.0\n"
        "    lat: 40.0\n"
    )
    out = tmp_path / "datacenters.geojson"

    with pytest.raises(KeyError, match="coord_source"):
        build_datacenters(
            out,
            existing_path=FIXTURE / "existing_datacenters_sample.geojson",
            seed_path=seed,
            centroids_path=SEEDS_DIR / "known_city_centroids.json",
        )


def test_count_never_falls_below_existing(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    seed = tmp_path / "seed.yaml"
    seed.write_text("datacenters: []\n")
    out = tmp_path / "datacenters.geojson"
    count = build_datacenters(
        out,
        existing_path=FIXTURE / "existing_datacenters_sample.geojson",
        seed_path=seed,
        centroids_path=SEEDS_DIR / "known_city_centroids.json",
    )
    assert count == 3


def test_haversine_known_distance() -> None:
    # London to Paris ≈ 344 km
    d = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340 < d < 350
```

- [ ] **Step 5: Run tests to verify failure**

```bash
cd services/data-ingestion && uv run pytest tests/test_build_datacenters.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 6: Implement the builder**

Create `services/data-ingestion/infra_atlas/build_datacenters.py`:

```python
"""Build datacenters.geojson by enriching existing data with Wikidata + seed."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import yaml

from infra_atlas.constants import (
    COORD_QUALITY_CAMPUS_VERIFIED,
    COORD_QUALITY_LEGACY,
    COORD_QUALITY_WIKIDATA_VERIFIED,
    COORD_SOURCE_WIKIDATA,
    QID_DATA_CENTER,
)
from infra_atlas.wikidata import WikidataClient, WikidataRow

WIKIDATA_DRIFT_THRESHOLD_KM = 5.0
_NAME_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class CityCentroidViolation(ValueError):
    pass


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalize(name: str) -> str:
    return _NAME_NORMALIZE_RE.sub("", name.lower())


DATACENTER_QUERY = f"""
SELECT DISTINCT ?item ?itemLabel ?coord ?operatorLabel
       ?countryCode ?city WHERE {{
  ?item wdt:P31/wdt:P279* wd:{QID_DATA_CENTER} ;
        wdt:P625 ?coord .
  OPTIONAL {{ ?item wdt:P137 ?operator . ?operator rdfs:label ?operatorLabel
              FILTER(LANG(?operatorLabel) = "en") }}
  OPTIONAL {{ ?item wdt:P17 ?country . ?country wdt:P297 ?countryCode }}
  OPTIONAL {{ ?item wdt:P131 ?cityEntity .
              ?cityEntity rdfs:label ?city
              FILTER(LANG(?city) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
ORDER BY ?itemLabel
"""
# capacity_mw is intentionally NOT pulled from P2109 — that property's unit is
# Watts and Wikidata returns the raw value without conversion. Mixing W and MW
# would silently produce 1 000 000× errors. Hyperscaler seed sets capacity
# explicitly; Wikidata-only entries get None.


def _load_centroids(path: Path) -> tuple[list[dict[str, Any]], float]:
    raw = json.loads(path.read_text())
    return raw["centroids"], float(raw["tolerance_km"])


def _check_centroid(
    name: str, lon: float, lat: float, centroids: list[dict[str, Any]], tol_km: float
) -> None:
    for c in centroids:
        if haversine_km(lat, lon, c["lat"], c["lon"]) <= tol_km:
            raise CityCentroidViolation(
                f"seed entry {name!r} coord ({lon}, {lat}) matches city centroid {c['name']!r}; "
                f"replace with the actual datacenter campus coords."
            )


def _seed_features(seed_path: Path, centroids_path: Path) -> list[dict[str, Any]]:
    centroids, tol = _load_centroids(centroids_path)
    raw = yaml.safe_load(seed_path.read_text())
    out: list[dict[str, Any]] = []
    for entry in raw.get("datacenters", []) or []:
        if "coord_source" not in entry:
            raise KeyError(f"coord_source is required: {entry.get('name', '?')}")
        lon = float(entry["lon"])
        lat = float(entry["lat"])
        _check_centroid(entry["name"], lon, lat, centroids, tol)
        out.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": entry["name"],
                    "operator": entry["operator"],
                    "tier": entry["tier"],
                    "capacity_mw": entry.get("capacity_mw"),
                    "country": entry["country"],
                    "city": entry["city"],
                    "coord_quality": COORD_QUALITY_CAMPUS_VERIFIED,
                    "coord_source": entry["coord_source"],
                    "source_url": entry["coord_source"],
                },
            }
        )
    return out


def _index_wikidata(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if "coord" not in row or "item" not in row:
            continue
        try:
            WikidataRow.parse_wkt_point(row["coord"])
        except ValueError:
            continue
        name = row.get("itemLabel", "")
        country = row.get("countryCode", "")
        if not name or not country:
            continue
        index[(_normalize(name), country)] = row
    return index


def _enrich_existing(
    feature: dict[str, Any],
    wd_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    props = dict(feature["properties"])
    geom = dict(feature["geometry"])
    key = (_normalize(props.get("name", "")), props.get("country", ""))
    match = wd_index.get(key)

    if match is None:
        props.setdefault("coord_quality", COORD_QUALITY_LEGACY)
        return {"type": "Feature", "geometry": geom, "properties": props}

    qid = WikidataRow.qid_from_uri(match["item"])
    props.setdefault("qid", qid)
    props.setdefault("source_url", f"https://www.wikidata.org/wiki/{qid}")

    wd_lon, wd_lat = WikidataRow.parse_wkt_point(match["coord"])
    cur_lon, cur_lat = geom["coordinates"]
    distance = haversine_km(cur_lat, cur_lon, wd_lat, wd_lon)
    if distance > WIKIDATA_DRIFT_THRESHOLD_KM:
        geom = {"type": "Point", "coordinates": [wd_lon, wd_lat]}
        props["coord_source"] = COORD_SOURCE_WIKIDATA
    props["coord_quality"] = COORD_QUALITY_WIKIDATA_VERIFIED
    return {"type": "Feature", "geometry": geom, "properties": props}


def _wikidata_only_feature(row: dict[str, Any]) -> dict[str, Any] | None:
    if "coord" not in row or "item" not in row:
        return None
    try:
        lon, lat = WikidataRow.parse_wkt_point(row["coord"])
    except ValueError:
        return None
    qid = WikidataRow.qid_from_uri(row["item"])
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "name": row.get("itemLabel", qid),
            "operator": row.get("operatorLabel", "Unknown"),
            "tier": "III",
            "capacity_mw": None,  # Wikidata's P2109 is in Watts; never inferred.
            "country": row.get("countryCode", "??"),
            "city": row.get("city", ""),
            "qid": qid,
            "source_url": f"https://www.wikidata.org/wiki/{qid}",
            "coord_quality": COORD_QUALITY_WIKIDATA_VERIFIED,
            "coord_source": COORD_SOURCE_WIKIDATA,
        },
    }


def build_datacenters(
    out_path: Path,
    existing_path: Path,
    seed_path: Path,
    centroids_path: Path,
) -> int:
    seed_features = _seed_features(seed_path, centroids_path)
    seed_keys = {
        (_normalize(f["properties"]["name"]), f["properties"]["country"])
        for f in seed_features
    }

    existing = json.loads(existing_path.read_text())
    rows = WikidataClient().query(DATACENTER_QUERY)
    wd_index = _index_wikidata(rows)

    out_features: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for f in existing["features"]:
        key = (_normalize(f["properties"].get("name", "")),
               f["properties"].get("country", ""))
        if key in seed_keys:
            continue  # seed wins for these
        enriched = _enrich_existing(f, wd_index)
        out_features.append(enriched)
        seen_keys.add(key)

    for key, row in wd_index.items():
        if key in seen_keys or key in seed_keys:
            continue
        new = _wikidata_only_feature(row)
        if new is not None:
            out_features.append(new)
            seen_keys.add(key)

    out_features.extend(seed_features)
    out_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": out_features}, indent=2)
    )
    return len(out_features)
```

- [ ] **Step 7: Wire CLI subcommand**

Modify `services/data-ingestion/infra_atlas/cli.py`:

(a) Add the import beside the others. Replace:

```python
from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed
from infra_atlas.build_refineries import build_refineries
```

with:

```python
from infra_atlas.build_pipelines import build_pipelines_from_seed, load_seed
from infra_atlas.build_refineries import build_refineries
from infra_atlas.build_datacenters import build_datacenters
```

(b) Append at the end of the file:

```python
@cli.command()
@click.option(
    "--existing",
    type=click.Path(exists=True, path_type=Path),
    default=FRONTEND_DATA / "datacenters.geojson",
)
@click.option(
    "--seed",
    type=click.Path(exists=True, path_type=Path),
    default=SEEDS_DIR / "datacenters_hyperscaler.yaml",
)
@click.option(
    "--centroids",
    type=click.Path(exists=True, path_type=Path),
    default=SEEDS_DIR / "known_city_centroids.json",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=FRONTEND_DATA / "datacenters.geojson",
)
def datacenters(existing: Path, seed: Path, centroids: Path, out: Path) -> None:
    """Enrich existing datacenters.geojson + apply hyperscaler seed."""
    n = build_datacenters(
        out, existing_path=existing, seed_path=seed, centroids_path=centroids
    )
    click.echo(f"Wrote {n} datacenters → {out.relative_to(REPO_ROOT)}")
```

> Centroids live under `infra_atlas/seeds/` so they ship in the wheel (Task 1 wheel-include adds `infra_atlas/seeds/*.json`). The default resolves through `SEEDS_DIR` already declared at the top of cli.py.

- [ ] **Step 8: Run unit tests**

```bash
cd services/data-ingestion && uv run pytest tests/test_build_datacenters.py -v
```

Expected: 7 passed.

- [ ] **Step 9: Build the hyperscaler seed (≥30 entries — research task)**

Create `services/data-ingestion/infra_atlas/seeds/datacenters_hyperscaler.yaml` and populate it with **at least 30 hyperscaler region/campus entries**. Each entry MUST satisfy:

- `coord_source` is a real, citable URL (operator press release, baxtel.com, datacenters.com, DCD article, Wikipedia infobox).
- `lon`/`lat` are the actual datacenter campus, NOT a city centroid. The unit test enforces this against `infra_atlas/seeds/known_city_centroids.json` — if you accidentally use a centroid, the build fails with `CityCentroidViolation`.
- `tier: hyperscaler`.

Suggested coverage (research each, do not copy guesses):

- AWS regions: us-east-1 (Ashburn area), us-east-2 (Columbus area), us-west-2 (Boardman), eu-west-1 (Dublin area), eu-central-1 (Frankfurt area — *not* Frankfurt centroid), ap-northeast-1 (Tokyo area), ap-southeast-1 (Singapore area), ap-southeast-2 (Sydney area), sa-east-1 (São Paulo area).
- Azure regions: East US (Boydton), South Central US (San Antonio), West Europe (Amsterdam area), North Europe (Dublin area), UK South (London area), Japan East (Tokyo area).
- GCP regions: us-central1 (Council Bluffs area), us-east1 (Moncks Corner), europe-west4 (Eemshaven), europe-west1 (St. Ghislain), asia-east1 (Changhua County).
- Meta: Lulea (Sweden), Prineville (OR), Forest City (NC), Altoona (IA), Eagle Mountain (UT), Fort Worth (TX), Clonee (Ireland), Odense (Denmark).
- Apple: Maiden (NC), Reno (NV), Mesa (AZ), Viborg (Denmark).
- That's 35+ candidates — pick ≥30 with verifiable campus coords.

Example entry format (use this verbatim, fill the values from your research):

```yaml
datacenters:
  - name: AWS US-East-1 (Ashburn)
    operator: Amazon Web Services
    tier: hyperscaler
    capacity_mw: 600
    country: US
    city: Ashburn
    lon: -77.4575
    lat: 39.0260
    coord_source: https://baxtel.com/data-center/aws-us-east-1
  # ... 29+ more entries
```

> **Engineer note:** This is the only research-heavy step in the plan. Do not skip it. Do not put placeholder coords. Each entry's `coord_source` URL must actually contain the campus coords or describe the location precisely. The validation in Step 10 enforces ≥30 hyperscaler entries with `coord_quality: campus_verified`.

- [ ] **Step 10: Backup current datacenters file and run live builder**

```bash
cp services/frontend/public/data/datacenters.geojson \
   /tmp/datacenters.geojson.bak.$(date +%s)
cd services/data-ingestion && uv run odin-infra-atlas datacenters
```

Expected: `Wrote N datacenters → services/frontend/public/data/datacenters.geojson` where `N >= 268`. If `CityCentroidViolation` is raised, fix the seed entry it names.

- [ ] **Step 11: Validate hard acceptance criteria**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/.worktrees/odin-s2-worldview-port

# Count must not drop
jq '.features | length' services/frontend/public/data/datacenters.geojson
# Expected: >= 268

# Hyperscaler campus_verified count
jq '[.features[] | select(.properties.tier == "hyperscaler" and .properties.coord_quality == "campus_verified" and .properties.source_url)] | length' \
  services/frontend/public/data/datacenters.geojson
# Expected: >= 30

# No hyperscaler within 1 km of a known city centroid
python3 - <<'PY'
import json, math
data = json.load(open("services/frontend/public/data/datacenters.geojson"))
centroids = json.load(open("services/data-ingestion/infra_atlas/seeds/known_city_centroids.json"))
def hav(lat1, lon1, lat2, lon2):
    r=6371.0; p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))
violations = []
for f in data["features"]:
    if f["properties"].get("tier") != "hyperscaler": continue
    lon, lat = f["geometry"]["coordinates"]
    for c in centroids["centroids"]:
        if hav(lat, lon, c["lat"], c["lon"]) <= centroids["tolerance_km"]:
            violations.append((f["properties"]["name"], c["name"]))
print(f"violations: {len(violations)}")
for v in violations: print("  ", v)
assert not violations, "hyperscaler entries match city centroids"
PY
# Expected: violations: 0
```

- [ ] **Step 12: Visual smoke**

Reload Worldview, toggle Datacenters ON. Hyperscaler dots near Ashburn, Boydton, Frankfurt area (NOT Frankfurt centroid), Dublin area, Singapore area, etc. Click a hyperscaler — InspectorPanel shows operator + source_url.

- [ ] **Step 13: Run the full infra_atlas test suite**

```bash
cd services/data-ingestion && uv run pytest tests/test_wikidata.py tests/test_build_pipelines.py tests/test_build_refineries.py tests/test_build_datacenters.py -v
```

Expected: all pass.

- [ ] **Step 14: Build the wheel and verify packaging**

```bash
cd services/data-ingestion && uv build 2>&1 | tail -5
unzip -l dist/*.whl | grep -E "infra_atlas/(constants|wikidata|build_|cli|seeds/.*\.(yaml|json))"
```

Expected: every one of these paths must appear in the listing — `infra_atlas/__init__.py`, `infra_atlas/constants.py`, `infra_atlas/wikidata.py`, `infra_atlas/build_pipelines.py`, `infra_atlas/build_refineries.py`, `infra_atlas/build_datacenters.py`, `infra_atlas/cli.py`, `infra_atlas/seeds/pipelines.yaml`, `infra_atlas/seeds/datacenters_hyperscaler.yaml`, **`infra_atlas/seeds/known_city_centroids.json`**.

Also explicitly assert the JSON seed shipped (the regex above includes it, but make it impossible to miss):

```bash
unzip -l dist/*.whl | grep "known_city_centroids.json" || \
  { echo "FAIL: city-centroid seed not in wheel — wheel-include is wrong"; exit 1; }
```

Expected: one matching line, no FAIL output.

- [ ] **Step 15: Frontend hook tests sanity check**

```bash
cd services/frontend && npx vitest run \
  src/hooks/__tests__/useDatacenters.test.ts \
  src/hooks/__tests__/useRefineries.test.ts \
  src/hooks/__tests__/usePipelines.test.ts \
  src/components/worldview/InspectorPanel.test.tsx
```

Expected: all pass (the schema extension from Task 2 is exercised by hook mocks, the new pipeline hook test, the InspectorPanel datacenter source-link test, and the regenerated real data).

- [ ] **Step 16: Commit**

```bash
git add services/data-ingestion/infra_atlas/build_datacenters.py \
        services/data-ingestion/infra_atlas/seeds/datacenters_hyperscaler.yaml \
        services/data-ingestion/infra_atlas/seeds/known_city_centroids.json \
        services/data-ingestion/infra_atlas/cli.py \
        services/data-ingestion/tests/test_build_datacenters.py \
        services/data-ingestion/tests/fixtures/wikidata_datacenter_sample.json \
        services/data-ingestion/tests/fixtures/existing_datacenters_sample.geojson \
        services/frontend/public/data/datacenters.geojson
git commit -m "feat(infra_atlas): enrich datacenters.geojson + hyperscaler campus seed (≥30 verified)"
```

---

## Plan-File Location Note

This plan currently lives at:

```
.worktrees/odin-s2-worldview-port/docs/superpowers/plans/2026-05-01-worldview-data-completeness.md
```

— inside the S2 worktree, not in the main checkout. That is intentional for the duration of S2 development (the plan and its implementation belong to the same branch). When the S2 branch lands on `main`, this file will be promoted naturally.

If you need the plan visible from the main checkout *before* S2 lands, copy it manually:

```bash
cp .worktrees/odin-s2-worldview-port/docs/superpowers/plans/2026-05-01-worldview-data-completeness.md \
   /home/deadpool-ultra/ODIN/OSINT/docs/superpowers/plans/
```

…and commit on whichever branch you want it visible from.
