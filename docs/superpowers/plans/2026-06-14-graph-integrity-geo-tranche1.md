# Graph Integrity & Geo — Tranche 1 (Report + Geo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Globe-Event-Layer beleben und die Incident-Insel auflösen, indem Events und Incidents an `:Location`-Knoten verdrahtet werden — plus ein `report`-Befehl, der Vorher/Nachher messbar macht.

**Architecture:** Neues, getestetes `graph_integrity/`-Paket in `data-ingestion` mit re-runnable, idempotenten Jobs (`report`, Geo-Backfills) — gespiegelt am bestehenden `gdelt_raw`-Writer- und `nlm_ingest/migrate`-Muster. Dazu Forward-Fixes in den Live-Writern (GDELT-Geo durch den Parquet-Contract, Incident-Writer im Backend, RSS-Country-Centroid in `pipeline.py`), damit der geheilte Zustand stabil bleibt. Identität von Locations einheitlich über `loc_key` (Single-Prop-MERGE-Key).

**Tech Stack:** Python 3.12, polars, neo4j (async bolt driver) + Neo4j HTTP tx-API (RSS-Pfad), Pydantic v2, pytest, structlog, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-14-graph-integrity-geo-connectivity-design.md` (Tranche 1 = Phase 1 + 2.1/2.2/2.3 + 3.1/3.2 + Geo-Acceptance).

**Verbindliche Regeln (CLAUDE.md):** Kein LLM-generiertes Cypher; nur parameter-gebundene Templates. Schreib-Jobs leben in `data-ingestion` (Ausnahme: Incident-Forward-Fix im Backend, da der Incident-Writer dort wohnt). TDD: Test zuerst (Red → Green → Refactor). Jeder Backfill: `--dry-run`, scoped, idempotent.

**`loc_key`-Konvention (für alle Tasks):**
- GDELT: `build_location_id(feature_id, country_code, fullname)` → `gdelt:loc:<feature_id>` bzw. `gdelt:loc:<cc>:<slug>`.
- Country-Centroid (RSS): `centroid:<iso2-lowercase>`.
- Incident: `incident:<slug(location)>` falls Ortsname vorhanden, sonst `geo:<lat|.3f>,<lon|.3f>`.

---

## File Structure

**Neu (`services/data-ingestion/graph_integrity/`):**
- `__init__.py`
- `neo4j_client.py` — schlanker async-bolt-Client (connect/close/run), gespiegelt an `gdelt_raw/writers/neo4j_writer.py::Neo4jWriter`.
- `report.py` — Read-only-Metriken (Cypher-Konstanten + reine Result-Shaping-Funktion).
- `loc_key.py` — reine `loc_key`-Builder (`centroid_key`, `incident_key`, `slug`).
- `country_centroids.py` — statische ISO-3166-2 → `(lat, lon)`-Tabelle + Lookup.
- `geo_incident.py` — Incident-Geo-Backfill (3.1).
- `geo_gdelt.py` — GDELT-Geo-Backfill via Raw-Export-Re-Fetch (3.2).
- `cli.py` — argparse-Subcommands: `report`, `backfill-incident-geo`, `backfill-gdelt-geo`.

**Geändert (Forward-Fix):**
- `services/backend/app/cypher/incident_write.py` — `INCIDENT_UPSERT` schreibt Location + `OCCURRED_AT`.
- `services/backend/app/services/incident_store.py` — `loc_key` + Geo-Params bauen.
- `services/data-ingestion/gdelt_raw/filter.py` — `action_geo_*`-Spalten behalten.
- `services/data-ingestion/gdelt_raw/transform.py` — Geo selektieren.
- `services/data-ingestion/gdelt_raw/schemas.py` — `GDELTEventWrite` Geo-Felder.
- `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py` — `MERGE_LOCATION` + `OCCURRED_AT`.
- `services/data-ingestion/pipeline.py` — RSS-Event → Country-Centroid-`OCCURRED_AT`.

**Tests:** je Modul ein `services/data-ingestion/tests/test_*.py` bzw. `services/backend/tests/...`.

---

## Task 1: `graph_integrity`-Paket-Scaffold + Neo4j-Client

**Files:**
- Create: `services/data-ingestion/graph_integrity/__init__.py`
- Create: `services/data-ingestion/graph_integrity/neo4j_client.py`
- Test: `services/data-ingestion/tests/test_graph_integrity_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_integrity_client.py
from graph_integrity.neo4j_client import Neo4jClient


def test_client_exposes_run_and_close():
    # Constructed lazily — no connection until first run().
    c = Neo4jClient("bolt://localhost:7687", "neo4j", "pw")
    assert hasattr(c, "run")
    assert hasattr(c, "close")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_graph_integrity_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graph_integrity'`

- [ ] **Step 3: Write minimal implementation**

```python
# graph_integrity/__init__.py
```
```python
# graph_integrity/neo4j_client.py
"""Async bolt client for graph-integrity jobs. Read + parametrised writes only."""
from __future__ import annotations

from typing import Any

from neo4j import AsyncGraphDatabase


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def run(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            return [r.data() async for r in result]

    async def close(self) -> None:
        await self._driver.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_graph_integrity_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/graph_integrity/__init__.py \
        services/data-ingestion/graph_integrity/neo4j_client.py \
        services/data-ingestion/tests/test_graph_integrity_client.py
git commit -m "feat(graph-integrity): scaffold package + async neo4j client"
```

---

## Task 2: `report` — Read-only-Integritätsmetriken

**Files:**
- Create: `services/data-ingestion/graph_integrity/report.py`
- Test: `services/data-ingestion/tests/test_graph_integrity_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_integrity_report.py
from graph_integrity.report import (
    GEO_COVERAGE,
    ORPHAN_BY_LABEL,
    DUP_ACTOR_EDGES,
    shape_report,
)


def test_queries_are_read_only():
    for q in (GEO_COVERAGE, ORPHAN_BY_LABEL, DUP_ACTOR_EDGES):
        upper = q.upper()
        assert "CREATE" not in upper
        assert "MERGE" not in upper
        assert "DELETE" not in upper
        assert "SET " not in upper


def test_dup_actor_edges_is_allowlist_scoped():
    # Must not dedup-count observation edges like SPOTTED_AT/OCCURRED_AT.
    assert "ALLIED_WITH" in DUP_ACTOR_EDGES
    assert "SUPPLIES_TO" in DUP_ACTOR_EDGES
    assert "SPOTTED_AT" not in DUP_ACTOR_EDGES
    assert "OCCURRED_AT" not in DUP_ACTOR_EDGES


def test_shape_report_combines_sections():
    out = shape_report(
        orphans=[{"label": "Incident", "orphan": 1952, "total": 1952}],
        geo=[{"label": "Event", "located": 510, "total": 184633}],
        dup_edges=[{"rel": "ALLIED_WITH", "groups": 1, "extra": 8}],
    )
    assert out["orphans"][0]["label"] == "Incident"
    assert out["geo"][0]["located"] == 510
    assert out["dup_edges"][0]["extra"] == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_graph_integrity_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graph_integrity.report'`

- [ ] **Step 3: Write minimal implementation**

```python
# graph_integrity/report.py
"""Read-only graph-integrity metrics. Baseline for before/after acceptance."""
from __future__ import annotations

from typing import Any

# Actor-relation allowlist — the ONLY rel types eligible for dedup.
_ACTOR_RELS = [
    "ALLIED_WITH", "SUPPLIES_TO", "COMPETES_WITH", "MEMBER_OF",
    "OPERATES_IN", "TARGETS", "COMMANDS", "NEGOTIATES_WITH", "SANCTIONS",
]

ORPHAN_BY_LABEL = """
UNWIND $labels AS lbl
CALL (lbl) {
  MATCH (n) WHERE lbl IN labels(n)
  RETURN count(n) AS total,
         count(CASE WHEN NOT (n)--() THEN 1 END) AS orphan
}
RETURN lbl AS label, orphan, total
"""

GEO_COVERAGE = """
UNWIND ['Event', 'Incident'] AS lbl
CALL (lbl) {
  MATCH (n) WHERE lbl IN labels(n)
  RETURN count(n) AS total,
         count(CASE WHEN (n)-[:OCCURRED_AT]->(:Location) THEN 1 END) AS located
}
RETURN lbl AS label, located, total
"""

DUP_ACTOR_EDGES = f"""
MATCH (a)-[r]->(b)
WHERE type(r) IN {_ACTOR_RELS!r}
WITH type(r) AS rel, startNode(r) AS s, endNode(r) AS e, count(r) AS c
WHERE c > 1
RETURN rel, count(*) AS groups, sum(c - 1) AS extra
ORDER BY extra DESC
"""

REPORT_LABELS = [
    "Document", "GDELTDocument", "Event", "GDELTEvent", "Entity", "Theme",
    "Source", "Incident", "MilitaryAircraft", "Location",
]


def shape_report(
    orphans: list[dict[str, Any]],
    geo: list[dict[str, Any]],
    dup_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine raw query rows into one report dict (pure)."""
    return {"orphans": orphans, "geo": geo, "dup_edges": dup_edges}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_graph_integrity_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/graph_integrity/report.py \
        services/data-ingestion/tests/test_graph_integrity_report.py
git commit -m "feat(graph-integrity): read-only report metrics (orphans, geo, dup-edges)"
```

---

## Task 3: `loc_key`-Builder + Country-Centroid-Tabelle

**Files:**
- Create: `services/data-ingestion/graph_integrity/loc_key.py`
- Create: `services/data-ingestion/graph_integrity/country_centroids.py`
- Test: `services/data-ingestion/tests/test_loc_key.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loc_key.py
from graph_integrity.loc_key import centroid_key, incident_key, slug
from graph_integrity.country_centroids import centroid_for


def test_slug_is_deterministic_and_lowercase():
    assert slug("Donetsk Oblast") == "donetsk-oblast"
    assert slug("  São Paulo ") == "sao-paulo"


def test_centroid_key_uses_lowercase_iso2():
    assert centroid_key("UA") == "centroid:ua"
    assert centroid_key("us") == "centroid:us"


def test_incident_key_prefers_name_else_rounded_coords():
    assert incident_key("Donetsk", 48.0159, 37.8028) == "incident:donetsk"
    assert incident_key("", 48.0159, 37.8028) == "geo:48.016,37.803"
    assert incident_key(None, 48.0159, 37.8028) == "geo:48.016,37.803"


def test_centroid_for_known_country():
    lat, lon = centroid_for("UA")
    assert 40 < lat < 55 and 20 < lon < 45  # Ukraine centroid plausibility
    assert centroid_for("ZZ") is None  # unknown ISO2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_loc_key.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graph_integrity.loc_key'`

- [ ] **Step 3: Write minimal implementation**

```python
# graph_integrity/loc_key.py
"""Deterministic Location identity keys. Pure, no I/O."""
from __future__ import annotations

import re
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", norm.lower()).strip("-")


def centroid_key(iso2: str) -> str:
    return f"centroid:{iso2.lower()}"


def incident_key(name: str | None, lat: float, lon: float) -> str:
    if name and name.strip():
        return f"incident:{slug(name)}"
    return f"geo:{lat:.3f},{lon:.3f}"
```

```python
# graph_integrity/country_centroids.py
"""ISO-3166-1 alpha-2 → (lat, lon) country centroids.

Bulk data. Full 0..250-row table is generated once from the public
Google "country-centroids" dataset (CSV: country code, latitude, longitude;
https://developers.google.com/public-data/docs/canonical/countries_csv) and
pasted below verbatim. Coarse — `geo_basis="country_centroid"` marks it.
"""
from __future__ import annotations

# Representative entries shown; the implementer pastes the full ISO set here.
_CENTROIDS: dict[str, tuple[float, float]] = {
    "UA": (48.379433, 31.16558),
    "RU": (61.52401, 105.318756),
    "US": (37.09024, -95.712891),
    "IR": (32.427908, 53.688046),
    "IL": (31.046051, 34.851612),
    "CN": (35.86166, 104.195397),
    "DE": (51.165691, 10.451526),
    "TR": (38.963745, 35.243322),
    "SA": (23.885942, 45.079162),
    "LB": (33.854721, 35.862285),
    # ... full ISO-3166-1 alpha-2 set pasted from the cited dataset ...
}


def centroid_for(iso2: str) -> tuple[float, float] | None:
    return _CENTROIDS.get((iso2 or "").upper())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_loc_key.py -v`
Expected: PASS

- [ ] **Step 5: Populate the full centroid table**

Download the cited CSV, convert every row to a `"<ISO2>": (lat, lon),` line, and replace the `# ...` placeholder block in `country_centroids.py`. Re-run the test (still PASS). This is bulk data, not logic — no behavioural change.

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/graph_integrity/loc_key.py \
        services/data-ingestion/graph_integrity/country_centroids.py \
        services/data-ingestion/tests/test_loc_key.py
git commit -m "feat(graph-integrity): loc_key builders + ISO country-centroid table"
```

---

## Task 4: Incident-Geo Forward-Fix (Backend-Writer)

**Files:**
- Modify: `services/backend/app/cypher/incident_write.py`
- Modify: `services/backend/app/services/incident_store.py:75-95` (`_upsert_params`) + import
- Create: `services/backend/app/services/_loc_key.py` (vendored `slug`/`incident_key`)
- Test: `services/backend/tests/test_incident_write_geo.py`

- [ ] **Step 1: Write the failing test**

```python
# services/backend/tests/test_incident_write_geo.py
from datetime import UTC, datetime

from app.cypher.incident_write import INCIDENT_UPSERT
from app.models.incident import Incident, IncidentStatus
from app.services._loc_key import incident_key
from app.services.incident_store import _upsert_params


def test_incident_upsert_wires_location():
    # Must MERGE a Location by loc_key and an OCCURRED_AT edge.
    assert "loc_key" in INCIDENT_UPSERT
    assert ":Location" in INCIDENT_UPSERT
    assert "OCCURRED_AT" in INCIDENT_UPSERT
    assert "country_centroid" not in INCIDENT_UPSERT  # incidents are precise
    assert "geo_basis" in INCIDENT_UPSERT


def test_incident_upsert_location_is_conditional_on_coords():
    # Null lat/lon → no Location (FOREACH-guard pattern), never a null-coord node.
    assert "FOREACH" in INCIDENT_UPSERT


def test_upsert_params_sets_loc_key():
    # The actual runtime risk: the param the Cypher needs must be produced here.
    rec = Incident(
        id="inc1", kind="manual", title="t", severity="low",
        coords=(48.0, 37.8), location="Donetsk", status=IncidentStatus.OPEN,
        trigger_ts=datetime.now(UTC), sources=[], layer_hints=[], timeline=[],
    )
    params = _upsert_params(rec, 0)
    assert params["loc_key"] == "incident:donetsk"
    assert params["lat"] == 48.0 and params["lon"] == 37.8


def test_vendored_loc_key_matches_canonical():
    # Backend vendors incident_key (separate Docker build context) — keep in sync.
    assert incident_key("Donetsk", 48.0, 37.8) == "incident:donetsk"
    assert incident_key("", 48.0, 37.8) == "geo:48.000,37.800"
```

> **Vendoring-Entscheidung (firm, nicht optional):** Der Backend-Build-Kontext kann
> `graph_integrity` nicht importieren (eigenes Image, wie bei `nlm_ingest/write_templates.py`).
> Daher wird `slug`/`incident_key` nach `services/backend/app/services/_loc_key.py`
> **vendored**; `test_vendored_loc_key_matches_canonical` hält beide Kopien deckungsgleich.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/backend && uv run pytest tests/test_incident_write_geo.py -v`
Expected: FAIL — assertions on missing `loc_key`/`OCCURRED_AT`.

- [ ] **Step 3: Write minimal implementation**

Append the Location wiring to `INCIDENT_UPSERT` (before the `RETURN`). The `FOREACH(_ IN CASE WHEN ... )` idiom is the standard Cypher conditional-write guard:

```python
# incident_write.py — extend INCIDENT_UPSERT, inserting before "RETURN":
    "  i.updated_at = datetime($now) "
    # --- geo wiring: only when coordinates are present ---
    "FOREACH (_ IN CASE WHEN $lat IS NULL OR $lon IS NULL THEN [] ELSE [1] END | "
    "  MERGE (l:Location {loc_key: $loc_key}) "
    "    ON CREATE SET l.lat = $lat, l.lon = $lon, l.name = $location, "
    "                  l.geo_basis = 'incident_report' "
    "  MERGE (i)-[:OCCURRED_AT]->(l) "
    ") "
    "RETURN "
```

Create the vendored helper:

```python
# services/backend/app/services/_loc_key.py
"""Vendored from graph_integrity.loc_key — backend has a separate build context
and cannot import data-ingestion. Kept in sync by test_vendored_loc_key_matches_canonical."""
from __future__ import annotations

import re
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", norm.lower()).strip("-")


def incident_key(name: str | None, lat: float, lon: float) -> str:
    if name and name.strip():
        return f"incident:{slug(name)}"
    return f"geo:{lat:.3f},{lon:.3f}"
```

In `incident_store.py`, import it and add `loc_key` to the returned dict of
`_upsert_params` (lat/lon come from `record.coords`, which is always present):

```python
# top of incident_store.py
from app.services._loc_key import incident_key
# inside _upsert_params(...) — add to the returned dict:
        "loc_key": incident_key(record.location, record.coords[0], record.coords[1]),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/backend && uv run pytest tests/test_incident_write_geo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/cypher/incident_write.py \
        services/backend/app/services/incident_store.py \
        services/backend/app/services/_loc_key.py \
        services/backend/tests/test_incident_write_geo.py
git commit -m "feat(backend): incident writer wires Location + OCCURRED_AT (loc_key)"
```

---

## Task 5: Incident-Geo Backfill (3.1)

**Files:**
- Create: `services/data-ingestion/graph_integrity/geo_incident.py`
- Test: `services/data-ingestion/tests/test_geo_incident.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geo_incident.py
from graph_integrity.geo_incident import (
    SELECT_UNWIRED_INCIDENTS,
    WIRE_INCIDENT_LOCATION,
    build_wire_params,
)


def test_select_only_unwired_with_coords():
    q = SELECT_UNWIRED_INCIDENTS.upper()
    assert "OCCURRED_AT" in q
    assert "NOT" in q                 # only incidents lacking the edge
    assert "I.LAT IS NOT NULL" in q


def test_wire_template_is_parametrised_and_idempotent():
    assert "$loc_key" in WIRE_INCIDENT_LOCATION
    assert "MERGE (l:Location {loc_key: $loc_key})" in WIRE_INCIDENT_LOCATION
    assert "MERGE (i)-[:OCCURRED_AT]->(l)" in WIRE_INCIDENT_LOCATION


def test_build_wire_params_uses_incident_key():
    row = {"id": "inc1", "location": "Donetsk", "lat": 48.0, "lon": 37.8}
    p = build_wire_params(row)
    assert p == {
        "incident_id": "inc1", "loc_key": "incident:donetsk",
        "lat": 48.0, "lon": 37.8, "location": "Donetsk",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_geo_incident.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# graph_integrity/geo_incident.py
"""Backfill: wire existing Incidents to :Location via OCCURRED_AT (idempotent)."""
from __future__ import annotations

from typing import Any

from graph_integrity.loc_key import incident_key
from graph_integrity.neo4j_client import Neo4jClient

SELECT_UNWIRED_INCIDENTS = """
MATCH (i:Incident)
WHERE i.lat IS NOT NULL AND i.lon IS NOT NULL
  AND NOT (i)-[:OCCURRED_AT]->(:Location)
RETURN i.id AS id, i.location AS location, i.lat AS lat, i.lon AS lon
"""

WIRE_INCIDENT_LOCATION = """
MATCH (i:Incident {id: $incident_id})
MERGE (l:Location {loc_key: $loc_key})
  ON CREATE SET l.lat = $lat, l.lon = $lon, l.name = $location,
                l.geo_basis = 'incident_report'
MERGE (i)-[:OCCURRED_AT]->(l)
"""


def build_wire_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "incident_id": row["id"],
        "loc_key": incident_key(row.get("location"), row["lat"], row["lon"]),
        "lat": row["lat"], "lon": row["lon"], "location": row.get("location"),
    }


async def run(client: Neo4jClient, dry_run: bool = False) -> int:
    rows = await client.run(SELECT_UNWIRED_INCIDENTS)
    if dry_run:
        return len(rows)
    for row in rows:
        await client.run(WIRE_INCIDENT_LOCATION, build_wire_params(row))
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_geo_incident.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/graph_integrity/geo_incident.py \
        services/data-ingestion/tests/test_geo_incident.py
git commit -m "feat(graph-integrity): incident geo backfill (idempotent, dry-run)"
```

---

## Task 6: GDELT-Geo — Filter behält `action_geo_*`

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/filter.py:~96` (`events_for_join` select)
- Test: `services/data-ingestion/tests/test_gdelt_filter_geo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gdelt_filter_geo.py
import polars as pl
from gdelt_raw.filter import apply_filters
from gdelt_raw.tests_fixtures import minimal_events_df, minimal_gkg_df, minimal_mentions_df
# ^ If no shared fixture module exists, build the three DataFrames inline in the
#   test using EVENT_POLARS_SCHEMA columns (see Step 3 note).


def test_filtered_events_retain_action_geo_columns():
    out = apply_filters(minimal_events_df(), minimal_gkg_df(), minimal_mentions_df())
    cols = out.events.columns
    for c in ("action_geo_lat", "action_geo_long", "action_geo_fullname",
              "action_geo_country_code", "action_geo_feature_id"):
        assert c in cols, f"{c} dropped by filter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_filter_geo.py -v`
Expected: FAIL — geo columns absent from `out.events`.

- [ ] **Step 3: Write minimal implementation**

Read `filter.py` around line 96 (`events_for_join = events_filtered.select([...])`) and the `events_filtered` annotate block (line 76). Ensure the `action_geo_*` columns survive into `events_filtered` (they come straight from the raw parse, so just do **not** drop them; if there is an explicit `.select(...)` whitelist on `events_filtered`, add the five `action_geo_*` columns to it). `events_for_join` is the mentions-join projection and may stay geo-free.

> **Fixture note:** if `gdelt_raw.tests_fixtures` does not exist, construct the three
> input DataFrames inline from `gdelt_raw.polars_schemas.EVENT_POLARS_SCHEMA` (events),
> with two rows (one tactical CAMEO root, one non-tactical) and real `action_geo_lat/long`
> values, plus minimal gkg/mentions frames. Keep the fixture in the test file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_filter_geo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/filter.py \
        services/data-ingestion/tests/test_gdelt_filter_geo.py
git commit -m "feat(gdelt): retain action_geo_* columns through filter"
```

---

## Task 7: GDELT-Geo — Transform selektiert Geo + Schema/Contract

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/transform.py:42-62` (`canonicalize_events`)
- Modify: `services/data-ingestion/gdelt_raw/schemas.py:15-36` (`GDELTEventWrite`)
- Test: `services/data-ingestion/tests/test_gdelt_transform_geo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gdelt_transform_geo.py
import polars as pl
from gdelt_raw.transform import canonicalize_events
from gdelt_raw.schemas import GDELTEventWrite


def test_canonical_events_carry_geo():
    raw = pl.DataFrame({
        "event_id": ["gdelt:event:1"], "event_code": ["193"],
        "event_root_code": [19], "quad_class": [4], "goldstein_scale": [-6.5],
        "avg_tone": [-4.0], "num_mentions": [3], "num_sources": [2],
        "num_articles": [3], "date_added": [20260613221500], "fraction_date": [2026.4],
        "actor1_code": ["RUS"], "actor1_name": ["RUSSIA"],
        "actor2_code": ["UKR"], "actor2_name": ["UKRAINE"],
        "source_url": ["https://x"], "codebook_type": ["conflict.armed"],
        "filter_reason": ["tactical"],
        "action_geo_lat": [48.0], "action_geo_long": [37.8],
        "action_geo_fullname": ["Donetsk, Ukraine"],
        "action_geo_country_code": ["UP"], "action_geo_feature_id": ["-1044367"],
    })
    out = canonicalize_events(raw)
    assert out["action_geo_lat"][0] == 48.0
    assert out["action_geo_fullname"][0] == "Donetsk, Ukraine"


def test_contract_accepts_optional_geo():
    ev = GDELTEventWrite(
        event_id="gdelt:event:1", cameo_code="193", cameo_root=19, quad_class=4,
        goldstein=-6.5, avg_tone=-4.0, num_mentions=3, num_sources=2, num_articles=3,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://x", codebook_type="conflict.armed", filter_reason="tactical",
        action_geo_lat=48.0, action_geo_long=37.8, action_geo_fullname="Donetsk, Ukraine",
        action_geo_country_code="UP", action_geo_feature_id="-1044367",
    )
    assert ev.action_geo_lat == 48.0
    # geo is optional — GDELT permits geoless events
    ev2 = GDELTEventWrite(
        event_id="gdelt:event:2", cameo_code="010", cameo_root=1, quad_class=1,
        goldstein=0.0, avg_tone=0.0, num_mentions=1, num_sources=1, num_articles=1,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://y", codebook_type="other.unclassified", filter_reason="tactical",
    )
    assert ev2.action_geo_lat is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_transform_geo.py -v`
Expected: FAIL — `canonicalize_events` drops geo; `GDELTEventWrite` rejects extra geo fields (`extra="forbid"`).

- [ ] **Step 3: Write minimal implementation**

Add the five geo columns to the `canonicalize_events` select (after `filter_reason`):

```python
# transform.py — inside canonicalize_events(...).select([ ... ]) append:
        pl.col("action_geo_lat"),
        pl.col("action_geo_long"),
        pl.col("action_geo_fullname"),
        pl.col("action_geo_country_code"),
        pl.col("action_geo_feature_id"),
```

Add the optional geo fields to the contract:

```python
# schemas.py — inside GDELTEventWrite, after filter_reason:
    action_geo_lat: float | None = None
    action_geo_long: float | None = None
    action_geo_fullname: str | None = None
    action_geo_country_code: str | None = None
    action_geo_feature_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_transform_geo.py -v`
Expected: PASS

- [ ] **Step 5: Run the full gdelt suite (regression)**

Run: `cd services/data-ingestion && uv run pytest tests/ -k gdelt -v`
Expected: PASS (existing writer/filter tests unaffected; parquet now carries 24 columns).

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/gdelt_raw/transform.py \
        services/data-ingestion/gdelt_raw/schemas.py \
        services/data-ingestion/tests/test_gdelt_transform_geo.py
git commit -m "feat(gdelt): carry action_geo through transform + write contract"
```

---

## Task 8: GDELT-Geo — Writer MERGEt Location + OCCURRED_AT (Forward-Fix)

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py` (add `MERGE_LOCATION`, call in `write_events`)
- Test: `services/data-ingestion/tests/test_gdelt_writer_geo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gdelt_writer_geo.py
from gdelt_raw.writers.neo4j_writer import MERGE_LOCATION, location_params_for
from gdelt_raw.schemas import GDELTEventWrite


def test_merge_location_template():
    assert "MERGE (l:Location {loc_key: $loc_key})" in MERGE_LOCATION
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in MERGE_LOCATION
    assert "gdelt_actiongeo" in MERGE_LOCATION


def test_location_params_uses_build_location_id():
    ev = GDELTEventWrite(
        event_id="gdelt:event:1", cameo_code="193", cameo_root=19, quad_class=4,
        goldstein=-6.5, avg_tone=-4.0, num_mentions=3, num_sources=2, num_articles=3,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://x", codebook_type="conflict.armed", filter_reason="tactical",
        action_geo_lat=48.0, action_geo_long=37.8, action_geo_fullname="Donetsk, Ukraine",
        action_geo_country_code="UP", action_geo_feature_id="-1044367",
    )
    p = location_params_for(ev)
    assert p["loc_key"] == "gdelt:loc:-1044367"
    assert p["event_id"] == "gdelt:event:1"
    assert p["lat"] == 48.0


def test_location_params_none_when_no_coords():
    ev = GDELTEventWrite(
        event_id="gdelt:event:2", cameo_code="010", cameo_root=1, quad_class=1,
        goldstein=0.0, avg_tone=0.0, num_mentions=1, num_sources=1, num_articles=1,
        date_added="2026-06-13T22:15:00Z", fraction_date=2026.4,
        source_url="https://y", codebook_type="other.unclassified", filter_reason="tactical",
    )
    assert location_params_for(ev) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_writer_geo.py -v`
Expected: FAIL — `MERGE_LOCATION` / `location_params_for` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# neo4j_writer.py — add import + template + helper, call in write_events
from gdelt_raw.ids import build_location_id

MERGE_LOCATION = """
MATCH (ev:GDELTEvent {event_id: $event_id})
MERGE (l:Location {loc_key: $loc_key})
  ON CREATE SET l.name = $name, l.country = $country,
                l.lat = $lat, l.lon = $lon, l.geo_basis = 'gdelt_actiongeo'
MERGE (ev)-[:OCCURRED_AT]->(l)
"""


def location_params_for(ev: GDELTEventWrite) -> dict[str, Any] | None:
    if ev.action_geo_lat is None or ev.action_geo_long is None:
        return None
    return {
        "event_id": ev.event_id,
        "loc_key": build_location_id(
            ev.action_geo_feature_id or "",
            ev.action_geo_country_code or "",
            ev.action_geo_fullname or "",
        ),
        "name": ev.action_geo_fullname,
        "country": ev.action_geo_country_code,
        "lat": ev.action_geo_lat,
        "lon": ev.action_geo_long,
    }
```

In `write_events`, after the `MERGE_EVENT` run, add the conditional location write inside the same transaction:

```python
                for ev in events:
                    await tx.run(MERGE_EVENT, render_event_params(ev))
                    loc = location_params_for(ev)
                    if loc is not None:
                        await tx.run(MERGE_LOCATION, loc)
                await tx.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_writer_geo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/writers/neo4j_writer.py \
        services/data-ingestion/tests/test_gdelt_writer_geo.py
git commit -m "feat(gdelt): writer MERGEs Location + OCCURRED_AT from action_geo"
```

---

## Task 9: GDELT-Geo Backfill via Raw-Export-Re-Fetch (3.2)

**Files:**
- Create: `services/data-ingestion/graph_integrity/geo_gdelt.py`
- Test: `services/data-ingestion/tests/test_geo_gdelt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geo_gdelt.py
import asyncio

from graph_integrity import geo_gdelt
from graph_integrity.geo_gdelt import (
    BACKFILL_OCCURRED_AT,
    build_geo_row,
    export_url_for,
    slice_ids_from_parquet,
)


class _FakeClient:
    def __init__(self):
        self.writes: list = []

    async def run(self, cypher, params=None):
        self.writes.append(params)
        return []


def _seed_one_slice(tmp_path):
    d = tmp_path / "events" / "date=20260613"
    d.mkdir(parents=True)
    (d / "20260613221500.parquet").touch()


def test_slice_ids_from_parquet(tmp_path):
    (tmp_path / "events" / "date=20260613").mkdir(parents=True)
    (tmp_path / "events" / "date=20260613" / "20260613221500.parquet").touch()
    (tmp_path / "events" / "date=20260613" / "20260613224500.parquet").touch()
    ids = slice_ids_from_parquet(tmp_path)
    assert ids == ["20260613221500", "20260613224500"]


def test_export_url_for():
    assert export_url_for("20260613221500") == (
        "http://data.gdeltproject.org/gdeltv2/20260613221500.export.CSV.zip"
    )


def test_backfill_template_scoped_to_existing_geoless_events():
    q = BACKFILL_OCCURRED_AT
    assert "MATCH (ev:GDELTEvent {event_id: $event_id})" in q
    assert "MERGE (l:Location {loc_key: $loc_key})" in q
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in q
    assert "gdelt_actiongeo" in q


def test_build_geo_row_from_raw():
    raw = {
        "global_event_id": 12345, "action_geo_lat": 48.0, "action_geo_long": 37.8,
        "action_geo_fullname": "Donetsk, Ukraine", "action_geo_country_code": "UP",
        "action_geo_feature_id": "-1044367",
    }
    row = build_geo_row(raw)
    assert row["event_id"] == "gdelt:event:12345"
    assert row["loc_key"] == "gdelt:loc:-1044367"
    assert row["lat"] == 48.0
    assert build_geo_row({"global_event_id": 9, "action_geo_lat": None}) is None


def test_run_dry_run_counts_geo_rows_without_writing(tmp_path):
    _seed_one_slice(tmp_path)
    rows = [
        {"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
         "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
         "action_geo_feature_id": "-1"},
        {"global_event_id": 2, "action_geo_lat": None, "action_geo_long": None},  # dropped
    ]
    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=True, fetch=lambda _slice: rows,
    ))
    assert n == 1            # only the geo-eligible row is counted
    assert client.writes == []  # dry-run must never write


def test_run_live_writes_each_geo_row(tmp_path):
    _seed_one_slice(tmp_path)
    rows = [{"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
             "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
             "action_geo_feature_id": "-1"}]
    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=False, fetch=lambda _slice: rows,
    ))
    assert n == 1
    assert client.writes[0]["event_id"] == "gdelt:event:1"


def test_run_skips_missing_slice_without_aborting(tmp_path):
    _seed_one_slice(tmp_path)

    def boom(_slice):
        raise FileNotFoundError("410 gone")

    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=False, fetch=boom, skip_missing=True,
    ))
    assert n == 0            # slice skipped, loop survived
    assert client.writes == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_geo_gdelt.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# graph_integrity/geo_gdelt.py
"""GDELT-Event-Geo backfill. The stored canonical parquet is geo-stripped, so
re-fetch the RAW export slices, parse action_geo, and write OCCURRED_AT for
events that already exist in Neo4j. Idempotent + resumable (per-slice)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from gdelt_raw.ids import build_event_id, build_location_id
from graph_integrity.neo4j_client import Neo4jClient

_BASE = "http://data.gdeltproject.org/gdeltv2"

BACKFILL_OCCURRED_AT = """
MATCH (ev:GDELTEvent {event_id: $event_id})
WHERE NOT (ev)-[:OCCURRED_AT]->(:Location)
MERGE (l:Location {loc_key: $loc_key})
  ON CREATE SET l.name = $name, l.country = $country,
                l.lat = $lat, l.lon = $lon, l.geo_basis = 'gdelt_actiongeo'
MERGE (ev)-[:OCCURRED_AT]->(l)
"""


def slice_ids_from_parquet(parquet_base: str | Path) -> list[str]:
    base = Path(parquet_base) / "events"
    return sorted(p.stem for p in base.glob("date=*/*.parquet"))


def export_url_for(slice_id: str) -> str:
    return f"{_BASE}/{slice_id}.export.CSV.zip"


def build_geo_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("action_geo_lat") is None or raw.get("action_geo_long") is None:
        return None
    return {
        "event_id": build_event_id(raw["global_event_id"]),
        "loc_key": build_location_id(
            str(raw.get("action_geo_feature_id") or ""),
            raw.get("action_geo_country_code") or "",
            raw.get("action_geo_fullname") or "",
        ),
        "name": raw.get("action_geo_fullname"),
        "country": raw.get("action_geo_country_code"),
        "lat": raw["action_geo_lat"],
        "lon": raw["action_geo_long"],
    }
```

Add the resumable, injectable-fetch loop. `fetch` is a seam so tests inject synthetic
rows; the default `_fetch_and_parse` reuses `gdelt_raw`'s real download + parse:

```python
import structlog
log = structlog.get_logger(__name__)


def _fetch_and_parse(slice_id: str) -> list[dict]:
    """Default fetch: download the raw export slice and parse action_geo columns.
    Reuses gdelt_raw.run.download_slice + polars_schemas.EVENT_POLARS_SCHEMA.
    Raises on missing/410 slice (caught by run() when skip_missing=True)."""
    import polars as pl
    from gdelt_raw.polars_schemas import EVENT_POLARS_SCHEMA  # raw col names + dtypes
    # download_slice writes the unzipped CSV to a temp path; read with the raw schema,
    # keep only the columns build_geo_row needs.
    raise NotImplementedError  # implemented against gdelt_raw.run.download_slice


async def run(
    client,
    parquet_base,
    dry_run: bool = False,
    *,
    fetch=_fetch_and_parse,
    skip_missing: bool = True,
) -> int:
    """Re-fetch each already-ingested slice, write OCCURRED_AT for geoless events.
    Returns the number of geo-eligible rows (written, or counted under dry_run)."""
    count = 0
    skipped = 0
    for slice_id in slice_ids_from_parquet(parquet_base):
        try:
            rows = fetch(slice_id)
        except Exception as exc:  # noqa: BLE001 — missing/410 slice must not abort
            if not skip_missing:
                raise
            skipped += 1
            log.warning("gdelt_geo_slice_skipped", slice_id=slice_id, error=str(exc))
            continue
        for raw in rows:
            geo = build_geo_row(raw)
            if geo is None:
                continue
            count += 1
            if not dry_run:
                await client.run(BACKFILL_OCCURRED_AT, geo)
    if skipped:
        log.warning("gdelt_geo_slices_skipped_total", skipped=skipped)
    return count
```

> `_fetch_and_parse`'s body is the only part touching the network and is left as a thin
> wrapper around `gdelt_raw.run.download_slice` — it is **not** unit-tested (I/O seam);
> the three `run(...)` tests above inject `fetch` and cover counting, writing, and
> skip-on-missing. Verify the exact `download_slice` signature when implementing.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_geo_gdelt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/graph_integrity/geo_gdelt.py \
        services/data-ingestion/tests/test_geo_gdelt.py
git commit -m "feat(graph-integrity): GDELT geo backfill via raw export re-fetch"
```

---

## Task 10: RSS-Event-Geo via Country-Centroid (Forward-Fix)

**Files:**
- Modify: `services/data-ingestion/pipeline.py:398` (`_write_to_neo4j` signature + event-create block)
- Test: `services/data-ingestion/tests/test_pipeline_rss_geo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_rss_geo.py
from pipeline import build_event_geo_fragment


def test_event_geo_fragment_for_known_country():
    frag = build_event_geo_fragment(country="UA")
    assert frag is not None
    # Fragment continues an existing `WITH ev` chain — NO standalone MATCH/id(ev).
    assert "MATCH" not in frag["cypher"].upper()
    assert "id(ev)" not in frag["cypher"]
    assert "MERGE (l:Location {loc_key: $loc_key})" in frag["cypher"]
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in frag["cypher"]
    assert frag["parameters"]["loc_key"] == "centroid:ua"
    assert frag["parameters"]["geo_basis"] == "country_centroid"
    assert frag["parameters"]["geo_precision"] == "country"


def test_event_geo_fragment_none_for_unknown_country():
    assert build_event_geo_fragment(country="ZZ") is None
    assert build_event_geo_fragment(country=None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_rss_geo.py -v`
Expected: FAIL — `build_event_geo_fragment` not defined.

- [ ] **Step 3: Write minimal implementation**

The event is created with `CREATE (ev:Event {...})` and the handle `ev` is in scope; extend that statement so the same `WITH ev` chain also wires the centroid Location. Add a helper that returns the geo fragment + params (or None):

```python
# pipeline.py
from graph_integrity.country_centroids import centroid_for  # or vendored copy
from graph_integrity.loc_key import centroid_key

def build_event_geo_fragment(country: str | None) -> dict | None:
    """Cypher FRAGMENT appended to an event-create statement where `ev` is
    already bound (after `MERGE (d)-[:DESCRIBES]->(ev)`). It does NOT re-MATCH
    the event — no node-id round-trip. Returns None when country is unknown."""
    if not country:
        return None
    cc = centroid_for(country)
    if cc is None:
        return None
    lat, lon = cc
    return {
        "cypher": (
            " MERGE (l:Location {loc_key: $loc_key}) "
            "   ON CREATE SET l.lat = $lat, l.lon = $lon, "
            "                 l.geo_basis = $geo_basis, l.geo_precision = $geo_precision "
            " MERGE (ev)-[:OCCURRED_AT]->(l)"
        ),
        "parameters": {
            "loc_key": centroid_key(country), "lat": lat, "lon": lon,
            "geo_basis": "country_centroid", "geo_precision": "country",
        },
    }
```

> **Integration (covered by the unit test above + acceptance Task 12):** `ev` stays
> bound after `MERGE (d)-[:DESCRIBES]->(ev)`, so the fragment's `MERGE (ev)-[:OCCURRED_AT]`
> resolves without a re-MATCH. Wiring:
> 1. Add a `locations` parameter to `_write_to_neo4j` (caller `process_item` already has it).
> 2. Before the events loop: `doc_country = next((l["country"] for l in locations if l.get("country")), None)`.
> 3. Inside the events loop, for each event statement: `frag = build_event_geo_fragment(doc_country)`;
>    if `frag` is not None, append `frag["cypher"]` to that statement's Cypher string and
>    `statements[-1]["parameters"].update(frag["parameters"])`.
> Result: one statement per event, no node-id round-trip, param keys (`loc_key`, `lat`,
> `lon`, `geo_basis`, `geo_precision`) never collide with the event's own params.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_pipeline_rss_geo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/pipeline.py \
        services/data-ingestion/tests/test_pipeline_rss_geo.py
git commit -m "feat(pipeline): RSS events get country-centroid OCCURRED_AT"
```

---

## Task 11: CLI-Verdrahtung (`report`, `backfill-incident-geo`, `backfill-gdelt-geo`)

**Files:**
- Create: `services/data-ingestion/graph_integrity/cli.py`
- Test: `services/data-ingestion/tests/test_graph_integrity_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_integrity_cli.py
from graph_integrity.cli import build_parser


def test_parser_has_three_subcommands():
    p = build_parser()
    sub = p.parse_args(["report"])
    assert sub.command == "report"
    assert p.parse_args(["backfill-incident-geo", "--dry-run"]).dry_run is True
    assert p.parse_args(["backfill-gdelt-geo"]).dry_run is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_graph_integrity_cli.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# graph_integrity/cli.py
"""CLI for graph-integrity jobs. Reads Neo4j creds + parquet path from Settings."""
from __future__ import annotations

import argparse
import asyncio

from config import Settings  # existing data-ingestion settings module
from graph_integrity import geo_gdelt, geo_incident, report
from graph_integrity.neo4j_client import Neo4jClient


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="graph-integrity")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("report")
    inc = sub.add_parser("backfill-incident-geo")
    inc.add_argument("--dry-run", action="store_true")
    gd = sub.add_parser("backfill-gdelt-geo")
    gd.add_argument("--dry-run", action="store_true")
    return p


async def _amain(args: argparse.Namespace) -> None:
    s = Settings()
    client = Neo4jClient(s.neo4j_url, s.neo4j_user, s.neo4j_password)
    try:
        if args.command == "report":
            orphans = await client.run(report.ORPHAN_BY_LABEL, {"labels": report.REPORT_LABELS})
            geo = await client.run(report.GEO_COVERAGE)
            dup = await client.run(report.DUP_ACTOR_EDGES)
            print(report.shape_report(orphans, geo, dup))
        elif args.command == "backfill-incident-geo":
            n = await geo_incident.run(client, dry_run=args.dry_run)
            print(f"incident-geo: {n} incidents {'(dry-run)' if args.dry_run else 'wired'}")
        elif args.command == "backfill-gdelt-geo":
            n = await geo_gdelt.run(client, s.gdelt_parquet_path, dry_run=args.dry_run)
            print(f"gdelt-geo: {n} events {'(dry-run)' if args.dry_run else 'wired'}")
    finally:
        await client.close()


def main() -> None:
    asyncio.run(_amain(build_parser().parse_args()))


if __name__ == "__main__":
    main()
```

> Confirm the exact Settings attribute names (`neo4j_url`/`neo4j_user`/`neo4j_password`,
> parquet path) against `data-ingestion/config.py` and `gdelt_raw/config.py`; adjust if the
> GDELT parquet path lives in `gdelt_raw`'s settings rather than the top-level `Settings`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_graph_integrity_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/graph_integrity/cli.py \
        services/data-ingestion/tests/test_graph_integrity_cli.py
git commit -m "feat(graph-integrity): CLI for report + geo backfills"
```

---

## Task 12: Acceptance — Vorher/Nachher + Idempotenz + Dry-run

**Files:** none (operational verification against live Neo4j).

> ⚠️ Vor den Backfills: `docker exec osint-neo4j-1 neo4j-admin database dump neo4j` (oder
> Volume-Snapshot) — Rollback-Sicherung (Spec Phase 4).

- [ ] **Step 1: Baseline-Report**

Run: `cd services/data-ingestion && uv run python -m graph_integrity.cli report`
Erwartet (Ist-Werte aus dem Audit): Incident orphan ≈ 1952/1952; Event located ≈ 510/184633.

- [ ] **Step 2: Dry-run beider Backfills**

Run:
```bash
uv run python -m graph_integrity.cli backfill-incident-geo --dry-run
uv run python -m graph_integrity.cli backfill-gdelt-geo --dry-run
```
Erwartet: Incident-Count ≈ 1952; GDELT-Count > 0 (Events mit `action_geo`).

- [ ] **Step 3: Incident-Backfill live + Re-Report**

Run:
```bash
uv run python -m graph_integrity.cli backfill-incident-geo
uv run python -m graph_integrity.cli report
```
Erwartet: Incident orphan → 0.

- [ ] **Step 4: GDELT-Backfill live + Re-Report**

Run:
```bash
uv run python -m graph_integrity.cli backfill-gdelt-geo
uv run python -m graph_integrity.cli report
```
Erwartet: Event located steigt deutlich (Größenordnung der GDELT-Events mit `action_geo`).

- [ ] **Step 5: Idempotenz-Test**

Run beide Backfills ein zweites Mal.
Erwartet: Live-Count = 0 changes (Dry-run-Count = 0), Report unverändert.

- [ ] **Step 6: Globe-Check (manuell)**

`/api/timeline/histogram` bzw. der WorldView-Globe zeigen jetzt Event-Geo-Dots (`geo_events > 0`). Notiere Vorher/Nachher in der Spec/Task-Notes.

---

## Self-Review (vom Plan-Autor ausgefüllt)

- **Spec-Coverage:** Phase 1 → Task 2/11; 2.1 → Task 6/7/8; 2.2 → Task 4; 2.3 → Task 3/10; 3.1 → Task 5; 3.2 → Task 9; Acceptance → Task 12. ✓ Vollständig für Tranche 1.
- **Out-of-Scope bestätigt:** kein entity_key/Dedup/Mention-Task (Tranche 2).
- **Typ-Konsistenz:** `loc_key`-Format einheitlich (`gdelt:loc:`, `centroid:`, `incident:`/`geo:`); `geo_basis`-Werte konsistent (`gdelt_actiongeo`, `country_centroid`, `incident_report`); `build_location_id`/`build_event_id` aus `gdelt_raw.ids` durchgängig.
- **Bekannte Verifikations-Punkte beim Ausführen:** (a) `gdelt_raw.filter`-Select-Whitelist real prüfen (Task 6); (b) Settings-Attributnamen + GDELT-Parquet-Pfad (Task 11); (c) `graph_integrity`-Importbarkeit aus Backend-Build-Kontext (Task 4 — sonst vendored copy).
