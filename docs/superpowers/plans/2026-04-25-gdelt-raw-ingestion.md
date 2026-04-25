# GDELT Raw Files Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Implementation-ready (review round 2 must-fix + should-fix applied, 2026-04-25)

**Goal:** Ingest GDELT 2.0 raw CSVs (Events / Mentions / GKG) every 15 minutes into Parquet (truth) + Neo4j (graph projection) + Qdrant (semantic projection) — with Nuclear-Override filter, per-slice Redis state, recovery from Parquet.

**Architecture:** Parquet-first write order. Polars streaming parser with strict + line-level-fallback. Two-stage filter (tactical CAMEO + Nuclear-Theme UNION). Neo4j and Qdrant are independent projections — both rehydrate from Parquet. Scoped `:GDELTEvent`/`:GDELTDocument` constraints (Community-edition UNIQUE; EXISTS enforced via Pydantic contract in writer).

**Tech Stack:** Python 3.12 · uv · Polars 1.x · pyarrow · httpx · pydantic v2 · qdrant-client · neo4j (Python driver) · structlog · APScheduler · click · pytest · Redis.

**Spec:** `docs/superpowers/specs/2026-04-25-gdelt-raw-ingestion-design.md`

---

## File Structure

```
services/data-ingestion/
├── gdelt_raw/                       # NEW module
│   ├── __init__.py
│   ├── cli.py                       # Task 24 — click CLI
│   ├── config.py                    # Task 0 — Pydantic Settings
│   ├── ids.py                       # Task 1 — build_event_id, build_doc_id, qdrant_point_id
│   ├── cameo_mapping.py             # Task 2 — CAMEO root → codebook_type
│   ├── theme_matching.py            # Task 3 — prefix-aware theme matcher
│   ├── normalize.py                 # Task 4 — entity normalization
│   ├── geo.py                       # Task 5 — location point helper
│   ├── schemas.py                   # Task 6 — Pydantic contracts
│   ├── polars_schemas.py            # Task 7 — CSV column lists + type hints
│   ├── parser.py                    # Task 8 — two-stage parser
│   ├── downloader.py                # Task 9 — lastupdate + ZIP fetch + MD5 (verify_md5 opt-out for backfill)
│   ├── filter.py                    # Task 10 — multi-stage filter with nuclear override
│   ├── transform.py                 # Task 10.5 — canonical transform raw → pydantic-writer schema
│   ├── state.py                     # Task 11 — Redis per-slice + summary state
│   ├── writers/
│   │   ├── __init__.py
│   │   ├── parquet_writer.py        # Task 12 — atomic .tmp+rename
│   │   ├── neo4j_writer.py          # Task 13 — Cypher MERGE templates
│   │   └── qdrant_writer.py         # Task 14 — embed + upsert from parquet
│   ├── recovery.py                  # Task 15 — pending-scan + replay
│   ├── run.py                       # Tasks 16-17 — run_forward, run_backfill
│   ├── migrations/
│   │   ├── __init__.py
│   │   ├── phase1_constraints.cypher # Task 18
│   │   ├── phase2_indexes.cypher     # Task 19
│   │   └── apply.py                 # Task 18 — with preflight
│   └── schemas_parquet/
│       ├── events.schema.json       # Task 12 snapshots
│       ├── gkg.schema.json
│       └── mentions.schema.json
│
├── feeds/gdelt_raw_collector.py     # Task 25 — thin scheduler wrapper
├── tests/
│   ├── test_gdelt_ids.py
│   ├── test_gdelt_cameo_mapping.py
│   ├── test_gdelt_theme_matching.py
│   ├── test_gdelt_normalize.py
│   ├── test_gdelt_geo.py
│   ├── test_gdelt_schemas.py
│   ├── test_gdelt_parser.py
│   ├── test_gdelt_downloader.py
│   ├── test_gdelt_filter.py
│   ├── test_gdelt_transform.py
│   ├── test_gdelt_state.py
│   ├── test_gdelt_parquet_writer.py
│   ├── test_gdelt_neo4j_writer.py
│   ├── test_gdelt_qdrant_writer.py
│   ├── test_gdelt_recovery.py
│   ├── test_gdelt_forward.py
│   ├── test_gdelt_backfill.py
│   ├── test_gdelt_migrations.py
│   ├── test_gdelt_cli.py
│   ├── test_gdelt_integration.py    # -m integration
│   ├── test_gdelt_duckdb_smoke.py   # analytics smoke
│   ├── test_gdelt_live.py           # -m live
│   └── fixtures/gdelt/
│       ├── slice_20260425_full.export.CSV
│       ├── slice_20260425_full.gkg.csv
│       ├── slice_20260425_full.mentions.CSV
│       ├── slice_malformed.export.CSV
│       ├── slice_unicode_edge.gkg.csv
│       └── gdelt_master_sample.txt
├── scheduler.py                     # Task 25 — add gdelt_forward job
├── pyproject.toml                   # Task 0 — polars/pyarrow + entry point
└── pytest.ini                       # Task 0 — markers

docker-compose.yml                   # Task 26 — gdelt_parquet volume
.env.example                         # Task 0 — GDELT_* vars
odin.sh                              # Task 25 — gdelt subcommand
```

---

## Task 0: Foundation — Dependencies, Config, Pytest markers

**Files:**
- Modify: `services/data-ingestion/pyproject.toml`
- Modify: `services/data-ingestion/pytest.ini` (create if missing)
- Create: `services/data-ingestion/gdelt_raw/__init__.py` (empty)
- Create: `services/data-ingestion/gdelt_raw/config.py`
- Modify: `.env.example`
- Create: `services/data-ingestion/tests/test_gdelt_config.py`

- [ ] **Step 1: Write failing config test**

```python
# services/data-ingestion/tests/test_gdelt_config.py
from gdelt_raw.config import GDELTSettings


def test_defaults_loadable():
    s = GDELTSettings(_env_file=None)
    assert s.base_url == "http://data.gdeltproject.org/gdeltv2"
    assert s.forward_interval_seconds == 900
    assert s.parquet_path == "/data/gdelt"
    assert s.filter_mode == "alpha"
    assert s.cameo_root_allowlist == [15, 18, 19, 20]
    assert "ARMEDCONFLICT" in s.theme_allowlist
    assert "NUCLEAR" in s.theme_allowlist
    assert s.max_parse_error_pct == 5.0
    assert s.backfill_parallel_slices == 4


def test_allowlist_parses_from_csv_env(monkeypatch):
    monkeypatch.setenv("GDELT_CAMEO_ROOT_ALLOWLIST", "18,19")
    monkeypatch.setenv("GDELT_THEME_ALLOWLIST", "ARMEDCONFLICT,NUCLEAR")
    s = GDELTSettings()
    assert s.cameo_root_allowlist == [18, 19]
    assert s.theme_allowlist == ["ARMEDCONFLICT", "NUCLEAR"]
```

- [ ] **Step 2: Run test — expect import failure**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gdelt_raw'`

- [ ] **Step 3: Create module + config**

```python
# services/data-ingestion/gdelt_raw/__init__.py
"""GDELT Raw Files Ingestion module."""
```

```python
# services/data-ingestion/gdelt_raw/config.py
"""Settings for GDELT raw files ingestion — loaded from env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GDELTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GDELT_", extra="ignore")

    base_url: str = "http://data.gdeltproject.org/gdeltv2"
    forward_interval_seconds: int = 900
    download_timeout: float = 60.0
    max_parse_error_pct: float = 5.0
    parquet_path: str = "/data/gdelt"
    filter_mode: str = "alpha"  # "alpha" | "delta"
    cameo_root_allowlist: list[int] = Field(default_factory=lambda: [15, 18, 19, 20])
    theme_allowlist: list[str] = Field(
        default_factory=lambda: [
            "ARMEDCONFLICT", "KILL",
            "CRISISLEX_*", "TERROR", "TERROR_*",
            "MILITARY", "NUCLEAR", "WMD",
            "WEAPONS_*", "WEAPONS_PROLIFERATION",
            "SANCTIONS", "CYBER_ATTACK", "ESPIONAGE", "COUP",
            "HUMAN_RIGHTS_ABUSES", "REFUGEE", "DISPLACEMENT",
        ]
    )
    nuclear_override_themes: list[str] = Field(
        default_factory=lambda: ["NUCLEAR", "WMD", "WEAPONS_PROLIFERATION", "WEAPONS_*"]
    )
    backfill_parallel_slices: int = 4
    backfill_default_days: int = 30

    @field_validator("cameo_root_allowlist", mode="before")
    @classmethod
    def _split_int_csv(cls, v):
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    @field_validator("theme_allowlist", "nuclear_override_themes", mode="before")
    @classmethod
    def _split_str_csv(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> GDELTSettings:
    return GDELTSettings()
```

- [ ] **Step 4: Update pyproject.toml deps + entry point**

Modify `services/data-ingestion/pyproject.toml`:
```toml
# Under [project.dependencies] add (skip any already present):
"polars>=1.0",
"pyarrow>=17.0",
"click>=8.0",
"pydantic-settings>=2.0",       # base class for GDELTSettings

# Under [project.scripts] add:
odin-ingest-gdelt = "gdelt_raw.cli:main"
```

**Note on list-from-env parsing (implemented pattern):** pydantic-settings v2 defaults to JSON-decoding list-typed env vars. Our CSV-style env (`GDELT_CAMEO_ROOT_ALLOWLIST=15,18,19,20`) is not JSON. The implementation uses a belt-and-suspenders combination of `Annotated[list[..], NoDecode]` (disables the JSON decoder for that field) **plus** a `@field_validator(mode="before")` that splits the raw CSV string into a list — verified by the test `test_allowlist_parses_from_csv_env`. Either mechanism alone would work; we keep both so the code stays robust across pydantic-settings upgrades:
```python
from pydantic_settings import NoDecode
from typing import Annotated
cameo_root_allowlist: Annotated[list[int], NoDecode] = Field(...)
```

- [ ] **Step 5: Add pytest markers**

Create or modify `services/data-ingestion/pytest.ini`:
```ini
[pytest]
markers =
    integration: requires local dev-compose services
    live: touches external GDELT CDN
    slow: backfill or performance tests
```

- [ ] **Step 6: Sync deps and re-run tests**

Run:
```bash
cd services/data-ingestion && uv sync && uv run pytest tests/test_gdelt_config.py -v
```
Expected: 2 passed

- [ ] **Step 7: Update .env.example**

Append to `.env.example`:
```bash

# ── GDELT Raw Files Ingestion ──
GDELT_BASE_URL=http://data.gdeltproject.org/gdeltv2
GDELT_FORWARD_INTERVAL_SECONDS=900
GDELT_DOWNLOAD_TIMEOUT=60
GDELT_MAX_PARSE_ERROR_PCT=5
GDELT_PARQUET_PATH=/data/gdelt
GDELT_FILTER_MODE=alpha
GDELT_CAMEO_ROOT_ALLOWLIST=15,18,19,20
GDELT_THEME_ALLOWLIST=ARMEDCONFLICT,KILL,CRISISLEX_*,TERROR,TERROR_*,MILITARY,NUCLEAR,WMD,WEAPONS_*,WEAPONS_PROLIFERATION,SANCTIONS,CYBER_ATTACK,ESPIONAGE,COUP,HUMAN_RIGHTS_ABUSES,REFUGEE,DISPLACEMENT
GDELT_NUCLEAR_OVERRIDE_THEMES=NUCLEAR,WMD,WEAPONS_PROLIFERATION,WEAPONS_*
GDELT_BACKFILL_PARALLEL_SLICES=4
GDELT_BACKFILL_DEFAULT_DAYS=30
```

- [ ] **Step 8: Commit**

```bash
git add services/data-ingestion/gdelt_raw/__init__.py \
        services/data-ingestion/gdelt_raw/config.py \
        services/data-ingestion/pyproject.toml \
        services/data-ingestion/pytest.ini \
        services/data-ingestion/tests/test_gdelt_config.py \
        .env.example
git commit -m "feat(gdelt): scaffold module + config + pytest markers"
```

---

## Task 1: ID generation (deterministic)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/ids.py`
- Create: `services/data-ingestion/tests/test_gdelt_ids.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_ids.py
from uuid import UUID

from gdelt_raw.ids import (
    build_event_id, build_doc_id, build_location_id,
    qdrant_point_id_for_doc,
)


def test_event_id_format():
    assert build_event_id(1300904663) == "gdelt:event:1300904663"
    assert build_event_id("1300904664") == "gdelt:event:1300904664"


def test_doc_id_format():
    assert build_doc_id("20260425121500-42") == "gdelt:gkg:20260425121500-42"


def test_location_id_with_feature():
    assert build_location_id(feature_id="-3365797") == "gdelt:loc:-3365797"


def test_location_id_fallback_without_feature():
    # Country-only (no feature_id): use a slugged fallback
    lid = build_location_id(feature_id="", country_code="UA", name="Kyiv")
    assert lid == "gdelt:loc:ua:kyiv"


def test_qdrant_point_id_is_deterministic_uuid5():
    doc_id = "gdelt:gkg:20260425121500-42"
    pid_a = qdrant_point_id_for_doc(doc_id)
    pid_b = qdrant_point_id_for_doc(doc_id)
    assert pid_a == pid_b
    # RFC-4122 Version 5
    parsed = UUID(pid_a)
    assert parsed.version == 5
```

- [ ] **Step 2: Run — expect FAIL (module not found)**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_ids.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/ids.py
"""Deterministic ID generation for GDELT entities.

Stable contracts — changing these requires a data migration.
"""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("-", s.lower()).strip("-")


def build_event_id(global_event_id: int | str) -> str:
    """gdelt:event:<GlobalEventID>"""
    return f"gdelt:event:{global_event_id}"


def build_doc_id(gkg_record_id: str) -> str:
    """gdelt:gkg:<GKGRecordID>"""
    return f"gdelt:gkg:{gkg_record_id}"


def build_location_id(
    feature_id: str = "",
    country_code: str = "",
    name: str = "",
) -> str:
    """gdelt:loc:<feature_id>  OR  gdelt:loc:<cc>:<slugged_name> as fallback."""
    if feature_id:
        return f"gdelt:loc:{feature_id}"
    return f"gdelt:loc:{country_code.lower()}:{_slug(name)}"


def qdrant_point_id_for_doc(doc_id: str) -> str:
    """Deterministic UUIDv5 from canonical doc_id → Qdrant point-ID (str form)."""
    return str(uuid5(NAMESPACE_URL, doc_id))
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_ids.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/ids.py services/data-ingestion/tests/test_gdelt_ids.py
git commit -m "feat(gdelt): deterministic ID helpers (event/doc/location/qdrant)"
```

---

## Task 2: CAMEO root → codebook_type mapping

**Files:**
- Create: `services/data-ingestion/gdelt_raw/cameo_mapping.py`
- Create: `services/data-ingestion/tests/test_gdelt_cameo_mapping.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_cameo_mapping.py
import pytest

from gdelt_raw.cameo_mapping import CAMEO_ROOT_TO_CODEBOOK, map_cameo_root


@pytest.mark.parametrize("root,expected", [
    (14, "civil.protest"),
    (15, "posture.military"),
    (17, "conflict.coercion"),
    (18, "conflict.assault"),
    (19, "conflict.armed"),
    (20, "conflict.mass_violence"),
])
def test_mapped_roots(root, expected):
    assert map_cameo_root(root) == expected


@pytest.mark.parametrize("root", [1, 2, 13, 16, 99])
def test_unmapped_roots_return_none(root):
    assert map_cameo_root(root) is None


def test_all_allowlisted_roots_are_mapped():
    """The default allowlist {15,18,19,20} MUST have mappings — otherwise Events
    silently get codebook_type=None and become invisible to downstream tools."""
    from gdelt_raw.config import GDELTSettings
    s = GDELTSettings(_env_file=None)
    for root in s.cameo_root_allowlist:
        assert map_cameo_root(root) is not None, f"root {root} is allowlisted but unmapped"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_cameo_mapping.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/cameo_mapping.py
"""CAMEO EventRootCode → internal codebook_type mapping.

Why broader than the current allowlist: widening filter to root 14/17
later should be a pure config change, not a code change.
"""

from __future__ import annotations

CAMEO_ROOT_TO_CODEBOOK: dict[int, str] = {
    14: "civil.protest",            # not in default allowlist (analytics-only)
    15: "posture.military",         # Troop movements, mobilization   (active)
    17: "conflict.coercion",        # Sanctions, asset freezes         (future)
    18: "conflict.assault",         # Assaults, assassinations         (active)
    19: "conflict.armed",           # Firefights, artillery            (active)
    20: "conflict.mass_violence",   # Massacres, WMD, ethnic cleansing (active)
}


def map_cameo_root(root: int) -> str | None:
    """Return internal codebook_type for a CAMEO root code, or None."""
    return CAMEO_ROOT_TO_CODEBOOK.get(root)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_cameo_mapping.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/cameo_mapping.py \
        services/data-ingestion/tests/test_gdelt_cameo_mapping.py
git commit -m "feat(gdelt): CAMEO root → codebook_type mapping"
```

---

## Task 3: Theme matching (prefix-aware)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/theme_matching.py`
- Create: `services/data-ingestion/tests/test_gdelt_theme_matching.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_theme_matching.py
from gdelt_raw.theme_matching import compile_patterns, matches_any, any_match_in_themes


def test_exact_match():
    matcher = compile_patterns(["NUCLEAR", "ARMEDCONFLICT"])
    assert matches_any("NUCLEAR", matcher)
    assert matches_any("ARMEDCONFLICT", matcher)
    assert not matches_any("CYBER_ATTACK", matcher)


def test_prefix_match_star():
    matcher = compile_patterns(["CRISISLEX_*", "WEAPONS_*"])
    assert matches_any("CRISISLEX_T03_DEAD", matcher)
    assert matches_any("CRISISLEX_CRISISLEXREC", matcher)
    assert matches_any("WEAPONS_PROLIFERATION", matcher)
    assert not matches_any("UNRELATED_THEME", matcher)


def test_mixed_exact_and_prefix():
    matcher = compile_patterns(["NUCLEAR", "CRISISLEX_*"])
    assert matches_any("NUCLEAR", matcher)
    assert matches_any("CRISISLEX_T11_UPDATESSYMPATHY", matcher)
    # prefix must anchor at START — avoid false positives:
    assert not matches_any("PRE_NUCLEAR_FALLOUT", matcher)


def test_any_match_in_themes_list():
    matcher = compile_patterns(["NUCLEAR", "CRISISLEX_*"])
    assert any_match_in_themes(
        ["FOO", "BAR", "CRISISLEX_T03_DEAD"], matcher
    )
    assert not any_match_in_themes(["FOO", "BAR"], matcher)
    assert not any_match_in_themes([], matcher)


def test_case_sensitive_exact():
    # GDELT themes are always upper-case; we enforce case-sensitive match.
    matcher = compile_patterns(["NUCLEAR"])
    assert not matches_any("nuclear", matcher)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_theme_matching.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/theme_matching.py
"""Prefix-aware theme matcher for GDELT V2Themes.

Patterns:
  "NUCLEAR"        — exact match only
  "CRISISLEX_*"    — prefix match (starts with "CRISISLEX_")

Why not regex: faster, safer, no accidental backtracking, explicit semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeMatcher:
    exacts: frozenset[str]
    prefixes: tuple[str, ...]


def compile_patterns(patterns: list[str]) -> ThemeMatcher:
    exacts: set[str] = set()
    prefixes: list[str] = []
    for p in patterns:
        if p.endswith("*"):
            prefixes.append(p[:-1])  # strip trailing "*"
        else:
            exacts.add(p)
    return ThemeMatcher(exacts=frozenset(exacts), prefixes=tuple(prefixes))


def matches_any(theme: str, matcher: ThemeMatcher) -> bool:
    if theme in matcher.exacts:
        return True
    return any(theme.startswith(p) for p in matcher.prefixes)


def any_match_in_themes(themes: list[str], matcher: ThemeMatcher) -> bool:
    return any(matches_any(t, matcher) for t in themes)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_theme_matching.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/theme_matching.py \
        services/data-ingestion/tests/test_gdelt_theme_matching.py
git commit -m "feat(gdelt): prefix-aware theme matcher (ThemeMatcher)"
```

---

## Task 4: Entity normalization

**Files:**
- Create: `services/data-ingestion/gdelt_raw/normalize.py`
- Create: `services/data-ingestion/tests/test_gdelt_normalize.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_normalize.py
from gdelt_raw.normalize import normalize_entity_name


def test_lowercases_and_collapses_whitespace():
    assert normalize_entity_name("Vladimir   Putin") == "vladimir putin"


def test_strips_surrounding_punctuation():
    assert normalize_entity_name("NATO (Alliance)") == "nato alliance"


def test_keeps_alphanum_and_spaces_only():
    assert normalize_entity_name("Jean-Claude Van Damme!!!") == "jean claude van damme"


def test_does_not_drop_tokens():
    # This is normalization, not entity-resolution — all tokens stay.
    assert normalize_entity_name("Dr. Vladimir Putin") == "dr vladimir putin"


def test_unicode_preserved():
    assert normalize_entity_name("Владимир Путин") == "владимир путин"


def test_empty_and_whitespace_return_empty():
    assert normalize_entity_name("") == ""
    assert normalize_entity_name("   ") == ""
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_normalize.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/normalize.py
"""Entity name normalization for MERGE keys.

Rule: lowercase + collapse whitespace + replace non-alphanumeric with space.
NEVER drops tokens — that would be entity resolution, not normalization.
"""

from __future__ import annotations

import re
import unicodedata


_NON_ALNUM_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+", flags=re.UNICODE)


def normalize_entity_name(raw: str) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw).lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_normalize.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/normalize.py \
        services/data-ingestion/tests/test_gdelt_normalize.py
git commit -m "feat(gdelt): entity-name normalization (lowercase+collapse)"
```

---

## Task 5: Geo / Location point helper

**Files:**
- Create: `services/data-ingestion/gdelt_raw/geo.py`
- Create: `services/data-ingestion/tests/test_gdelt_geo.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_geo.py
from gdelt_raw.geo import build_location_payload


def test_full_fields_produces_point_dict():
    p = build_location_payload(
        feature_id="-3365797", name="Kyiv", country_code="UA",
        lat=50.4501, lon=30.5234,
    )
    assert p["feature_id"] == "-3365797"
    assert p["name"] == "Kyiv"
    assert p["country_code"] == "UA"
    assert p["lat"] == 50.4501
    assert p["lon"] == 30.5234
    assert p["geo"] == {"latitude": 50.4501, "longitude": 30.5234, "crs": "wgs-84"}


def test_missing_feature_id_falls_back_to_slug():
    p = build_location_payload(
        feature_id="", name="Kyiv", country_code="UA",
        lat=50.45, lon=30.52,
    )
    assert p["feature_id"].startswith("gdelt:loc:ua:"), p["feature_id"]


def test_missing_coords_returns_none():
    p = build_location_payload(
        feature_id="-3365797", name="Kyiv", country_code="UA",
        lat=None, lon=None,
    )
    assert p is None


def test_zero_zero_coords_treated_as_missing():
    # GDELT uses 0/0 for "unknown" in some places — skip these.
    p = build_location_payload(
        feature_id="XYZ", name="Null Island", country_code="",
        lat=0.0, lon=0.0,
    )
    assert p is None
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_geo.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/geo.py
"""Location payload builder — produces Neo4j-point-ready dict."""

from __future__ import annotations

from typing import Any

from gdelt_raw.ids import build_location_id


def build_location_payload(
    feature_id: str,
    name: str,
    country_code: str,
    lat: float | None,
    lon: float | None,
) -> dict[str, Any] | None:
    """Return dict ready for Cypher MERGE, or None if coords missing/zero."""
    if lat is None or lon is None:
        return None
    if lat == 0.0 and lon == 0.0:
        return None

    fid = feature_id or build_location_id(
        feature_id="", country_code=country_code, name=name,
    )
    return {
        "feature_id": fid,
        "name": name,
        "country_code": country_code,
        "lat": lat,
        "lon": lon,
        "geo": {"latitude": lat, "longitude": lon, "crs": "wgs-84"},
    }
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_geo.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/geo.py \
        services/data-ingestion/tests/test_gdelt_geo.py
git commit -m "feat(gdelt): location payload builder with wgs-84 point"
```

---

## Task 6: Pydantic schemas (Writer contracts)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/schemas.py`
- Create: `services/data-ingestion/tests/test_gdelt_schemas.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_schemas.py
import pytest
from pydantic import ValidationError

from gdelt_raw.schemas import GDELTEventWrite, GDELTDocumentWrite


def _valid_event() -> dict:
    return {
        "event_id": "gdelt:event:1300904663",
        "cameo_code": "193", "cameo_root": 19, "quad_class": 4,
        "goldstein": -6.5, "avg_tone": -4.2,
        "num_mentions": 12, "num_sources": 8, "num_articles": 11,
        "date_added": "2026-04-25T12:15:00Z", "fraction_date": 2026.3164,
        "actor1_code": "MIL", "actor1_name": "MILITARY",
        "actor2_code": "REB", "actor2_name": "REBELS",
        "source_url": "https://example.com/x",
        "codebook_type": "conflict.armed",
        "source": "gdelt",
        "filter_reason": "tactical",
    }


def _valid_doc() -> dict:
    return {
        "doc_id": "gdelt:gkg:20260425121500-42",
        "url": "https://example.com/a",
        "source_name": "reuters.com",
        "gdelt_date": "2026-04-25T12:15:00Z",
        "published_at": None,
        "themes": ["ARMEDCONFLICT"],
        "persons": [], "organizations": [],
        "tone_polarity": 8.4, "word_count": 599,
        "source": "gdelt_gkg",
    }


def test_event_valid():
    GDELTEventWrite(**_valid_event())


def test_event_rejects_missing_event_id():
    d = _valid_event(); del d["event_id"]
    with pytest.raises(ValidationError):
        GDELTEventWrite(**d)


def test_event_rejects_wrong_event_id_pattern():
    d = _valid_event(); d["event_id"] = "not-canonical"
    with pytest.raises(ValidationError):
        GDELTEventWrite(**d)


def test_event_rejects_unknown_fields():
    d = _valid_event(); d["rogue_field"] = "x"
    with pytest.raises(ValidationError):
        GDELTEventWrite(**d)


def test_doc_valid():
    GDELTDocumentWrite(**_valid_doc())


def test_doc_rejects_missing_doc_id():
    d = _valid_doc(); del d["doc_id"]
    with pytest.raises(ValidationError):
        GDELTDocumentWrite(**d)


def test_doc_rejects_wrong_doc_id_pattern():
    d = _valid_doc(); d["doc_id"] = "gkg-20260425121500-42"
    with pytest.raises(ValidationError):
        GDELTDocumentWrite(**d)


def test_doc_published_at_is_optional():
    d = _valid_doc(); d["published_at"] = None
    GDELTDocumentWrite(**d)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_schemas.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/schemas.py
"""Writer-layer Pydantic contracts — enforce event_id/doc_id at the gateway.

Why: Neo4j Community edition does not support NOT NULL / NODE KEY constraints.
These contracts are the application-side replacement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GDELTEventWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    event_id: str = Field(pattern=r"^gdelt:event:\d+$")
    source: Literal["gdelt"] = "gdelt"
    cameo_code: str
    cameo_root: int = Field(ge=1, le=20)
    quad_class: int = Field(ge=1, le=4)
    goldstein: float
    avg_tone: float
    num_mentions: int
    num_sources: int
    num_articles: int
    date_added: datetime
    fraction_date: float
    actor1_code: str | None = None
    actor1_name: str | None = None
    actor2_code: str | None = None
    actor2_name: str | None = None
    source_url: str
    codebook_type: str
    filter_reason: Literal["tactical", "nuclear_override"]


class GDELTDocumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    doc_id: str = Field(pattern=r"^gdelt:gkg:\S+$")
    source: Literal["gdelt_gkg"] = "gdelt_gkg"
    url: str
    source_name: str
    gdelt_date: datetime
    published_at: datetime | None = None
    themes: list[str] = Field(default_factory=list)
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    tone_positive: float = 0.0
    tone_negative: float = 0.0
    tone_polarity: float = 0.0
    tone_activity: float = 0.0
    tone_self_group: float = 0.0
    word_count: int = 0
    sharp_image_url: str | None = None
    quotations: list[str] = Field(default_factory=list)
    # Materialized join fields (may be empty if doc had no Mentions)
    linked_event_ids: list[str] = Field(default_factory=list)
    goldstein_min: float | None = None
    goldstein_avg: float | None = None
    cameo_roots_linked: list[int] = Field(default_factory=list)
    codebook_types_linked: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_schemas.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/schemas.py \
        services/data-ingestion/tests/test_gdelt_schemas.py
git commit -m "feat(gdelt): Pydantic writer contracts (event_id/doc_id required)"
```

---

## Task 7: Polars column schemas

**Files:**
- Create: `services/data-ingestion/gdelt_raw/polars_schemas.py`
- No test file — covered by parser tests in Task 8

- [ ] **Step 1: Implement column lists (no test — this is declarative data)**

```python
# services/data-ingestion/gdelt_raw/polars_schemas.py
"""Polars column definitions for GDELT 2.0 CSVs.

Columns are tab-separated, no header. Order matches GDELT codebook.
"""

from __future__ import annotations

import polars as pl

# ── Events (export.CSV) — 61 columns ────────────────────────────────────────
EVENT_COLUMNS: list[str] = [
    "global_event_id", "day", "month_year", "year", "fraction_date",
    "actor1_code", "actor1_name", "actor1_country_code",
    "actor1_known_group_code", "actor1_ethnic_code",
    "actor1_religion1_code", "actor1_religion2_code",
    "actor1_type1_code", "actor1_type2_code", "actor1_type3_code",
    "actor2_code", "actor2_name", "actor2_country_code",
    "actor2_known_group_code", "actor2_ethnic_code",
    "actor2_religion1_code", "actor2_religion2_code",
    "actor2_type1_code", "actor2_type2_code", "actor2_type3_code",
    "is_root_event", "event_code", "event_base_code", "event_root_code",
    "quad_class", "goldstein_scale",
    "num_mentions", "num_sources", "num_articles", "avg_tone",
    "actor1_geo_type", "actor1_geo_fullname", "actor1_geo_country_code",
    "actor1_geo_adm1_code", "actor1_geo_adm2_code",
    "actor1_geo_lat", "actor1_geo_long", "actor1_geo_feature_id",
    "actor2_geo_type", "actor2_geo_fullname", "actor2_geo_country_code",
    "actor2_geo_adm1_code", "actor2_geo_adm2_code",
    "actor2_geo_lat", "actor2_geo_long", "actor2_geo_feature_id",
    "action_geo_type", "action_geo_fullname", "action_geo_country_code",
    "action_geo_adm1_code", "action_geo_adm2_code",
    "action_geo_lat", "action_geo_long", "action_geo_feature_id",
    "date_added", "source_url",
]

EVENT_POLARS_SCHEMA: dict[str, pl.DataType] = {
    "global_event_id": pl.Int64,
    "day": pl.Int32, "month_year": pl.Int32, "year": pl.Int32,
    "fraction_date": pl.Float64,
    "is_root_event": pl.Int8,
    "event_code": pl.Utf8, "event_base_code": pl.Utf8, "event_root_code": pl.Int32,
    "quad_class": pl.Int8, "goldstein_scale": pl.Float64,
    "num_mentions": pl.Int32, "num_sources": pl.Int32,
    "num_articles": pl.Int32, "avg_tone": pl.Float64,
    "actor1_geo_lat": pl.Float64, "actor1_geo_long": pl.Float64,
    "actor2_geo_lat": pl.Float64, "actor2_geo_long": pl.Float64,
    "action_geo_lat": pl.Float64, "action_geo_long": pl.Float64,
    "date_added": pl.Int64,  # YYYYMMDDHHMMSS
}


# ── Mentions (mentions.CSV) — 16 columns ────────────────────────────────────
MENTION_COLUMNS: list[str] = [
    "global_event_id", "event_time_date", "mention_time_date",
    "mention_type", "mention_source_name", "mention_identifier",
    "sentence_id", "actor1_char_offset", "actor2_char_offset",
    "action_char_offset", "in_raw_text", "confidence",
    "mention_doc_len", "mention_doc_tone",
    "mention_doc_translation_info", "extras",
]

MENTION_POLARS_SCHEMA: dict[str, pl.DataType] = {
    "global_event_id": pl.Int64,
    "event_time_date": pl.Int64,
    "mention_time_date": pl.Int64,
    "mention_type": pl.Int8,
    "sentence_id": pl.Int32,
    "actor1_char_offset": pl.Int32,
    "actor2_char_offset": pl.Int32,
    "action_char_offset": pl.Int32,
    "in_raw_text": pl.Int8,
    "confidence": pl.Int32,
    "mention_doc_len": pl.Int32,
    "mention_doc_tone": pl.Float64,
}


# ── GKG (gkg.csv) — 27 columns ──────────────────────────────────────────────
GKG_COLUMNS: list[str] = [
    "gkg_record_id", "v21_date", "v2_source_collection_identifier",
    "v2_source_common_name", "v2_document_identifier",
    "v1_counts", "v21_counts",
    "v1_themes", "v2_enhanced_themes",
    "v1_locations", "v2_enhanced_locations",
    "v1_persons", "v2_enhanced_persons",
    "v1_organizations", "v2_enhanced_organizations",
    "v15_tone", "v21_enhanced_dates",
    "v2_gcam",
    "v21_sharp_image", "v21_related_images",
    "v21_social_image_embeds", "v21_social_video_embeds",
    "v21_quotations", "v21_all_names", "v21_amounts",
    "v21_translation_info", "v2_extras_xml",
]

GKG_POLARS_SCHEMA: dict[str, pl.DataType] = {
    "gkg_record_id": pl.Utf8,
    "v21_date": pl.Int64,
    "v2_document_identifier": pl.Utf8,
}
```

- [ ] **Step 2: Commit (no test yet — this is declarative; covered in Task 8)**

```bash
git add services/data-ingestion/gdelt_raw/polars_schemas.py
git commit -m "feat(gdelt): polars column lists + type overrides for 3 streams"
```

---

## Task 8: Two-stage parser (strict + line-level fallback)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/parser.py`
- Create: `services/data-ingestion/tests/fixtures/gdelt/slice_20260425_full.export.CSV` (download from GDELT)
- Create: `services/data-ingestion/tests/fixtures/gdelt/slice_malformed.export.CSV`
- Create: `services/data-ingestion/tests/test_gdelt_parser.py`

- [ ] **Step 1: Create fixtures (run from repo root)**

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
FIX_DIR="$REPO_ROOT/services/data-ingestion/tests/fixtures/gdelt"
mkdir -p "$FIX_DIR"

# Pull a known slice from GDELT — take first 10 rows as a small fixture
TMP="$(mktemp -d)"
curl -s -o "$TMP/events.zip" http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip
unzip -o -d "$TMP" "$TMP/events.zip"
head -10 "$TMP"/20260425120000.export.CSV > "$FIX_DIR/slice_20260425_full.export.CSV"

# Also pull mentions + gkg small fixtures for later tests
curl -s -o "$TMP/mentions.zip" http://data.gdeltproject.org/gdeltv2/20260425120000.mentions.CSV.zip
unzip -o -d "$TMP" "$TMP/mentions.zip"
head -20 "$TMP"/20260425120000.mentions.CSV > "$FIX_DIR/slice_20260425_full.mentions.CSV"

curl -s -o "$TMP/gkg.zip" http://data.gdeltproject.org/gdeltv2/20260425120000.gkg.csv.zip
unzip -o -d "$TMP" "$TMP/gkg.zip"
head -10 "$TMP"/20260425120000.gkg.csv > "$FIX_DIR/slice_20260425_full.gkg.csv"

rm -rf "$TMP"
```

Create the malformed fixture (manually — mimic real bad row):
```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
FIX_DIR="$REPO_ROOT/services/data-ingestion/tests/fixtures/gdelt"
cat > "$FIX_DIR/slice_malformed.export.CSV" <<'EOF'
1300904663	20260425	202604	2026	2026.3164						MIL		MILITARY	AUS	AUSTRALIA	AUS	0	043	043	04	1	2.5	5	3	5	-2.1	4	Australia	AUS						Australia	AUS	-25.0	135.0	AS	20260425120000	https://example.com/a
THIS_IS_A_BROKEN_ROW_WITH_TOO_FEW_COLUMNS
1300904664	20260425	202604	2026	2026.3164						REB		REBELS	USA	NEW YORK	USA	0	190	190	19	4	-6.5	12	8	11	-4.2	4	New York	USA						New York	USA	40.7	-74.0	NY	20260425120000	https://example.com/b
EOF
```

- [ ] **Step 2: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_parser.py
from pathlib import Path

import polars as pl
import pytest

from gdelt_raw.parser import parse_events, parse_mentions, parse_gkg, ParseResult

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"


def test_parser_uses_tab_separator():
    """Regression: sanity-check strict parse uses tabs."""
    res = parse_events(FIXTURES / "slice_20260425_full.export.CSV")
    assert isinstance(res.df, pl.DataFrame)
    assert res.df.height >= 1
    # Column names match EVENT_COLUMNS
    assert "global_event_id" in res.df.columns
    assert "quad_class" in res.df.columns


def test_strict_parse_fallback_quarantines_bad_rows(tmp_path):
    quarantine = tmp_path / "quarantine" / "slice"
    res = parse_events(
        FIXTURES / "slice_malformed.export.CSV",
        quarantine_dir=quarantine,
    )
    # Expect: 2 valid rows parsed, 1 line quarantined
    assert res.df.height == 2
    assert res.quarantine_count == 1
    qfile = quarantine / "events.jsonl"
    assert qfile.exists()
    content = qfile.read_text()
    assert "THIS_IS_A_BROKEN_ROW" in content


def test_parse_error_pct_computed():
    res = parse_events(FIXTURES / "slice_malformed.export.CSV")
    # 1 bad / 3 total = 33.3% — above default 5% threshold
    assert res.parse_error_pct > 30.0
    assert res.parse_error_pct < 40.0
```

- [ ] **Step 3: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_parser.py -v`
Expected: FAIL (parser module missing)

- [ ] **Step 4: Implement**

```python
# services/data-ingestion/gdelt_raw/parser.py
"""Two-stage CSV parser for GDELT streams.

Stage 1: Strict Polars parse (fast path, ~95%).
Stage 2: Fallback — line-level pre-validation, bad rows → quarantine,
         then re-parse only valid lines.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import structlog

from gdelt_raw.polars_schemas import (
    EVENT_COLUMNS, EVENT_POLARS_SCHEMA,
    MENTION_COLUMNS, MENTION_POLARS_SCHEMA,
    GKG_COLUMNS, GKG_POLARS_SCHEMA,
)

log = structlog.get_logger(__name__)


@dataclass
class ParseResult:
    df: pl.DataFrame
    total_lines: int
    quarantine_count: int

    @property
    def parse_error_pct(self) -> float:
        return 0.0 if self.total_lines == 0 else 100.0 * self.quarantine_count / self.total_lines


def _parse_strict(path: Path, cols: list[str], schema: dict) -> pl.DataFrame:
    return pl.read_csv(
        str(path),
        separator="\t",
        has_header=False,
        new_columns=cols,
        schema_overrides=schema,
        ignore_errors=False,
        null_values=[""],
    )


def _parse_with_fallback(
    path: Path,
    cols: list[str],
    schema: dict,
    stream_name: str,
    quarantine_dir: Path | None,
) -> ParseResult:
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(raw_lines)
    expected_cols = len(cols)

    valid: list[str] = []
    bad: list[tuple[int, str]] = []
    for idx, ln in enumerate(raw_lines, start=1):
        if not ln.strip():
            continue
        if ln.count("\t") + 1 == expected_cols:
            valid.append(ln)
        else:
            bad.append((idx, ln))

    if bad and quarantine_dir is not None:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        qfile = quarantine_dir / f"{stream_name}.jsonl"
        with qfile.open("w", encoding="utf-8") as fh:
            for line_no, content in bad:
                fh.write(json.dumps({"line": line_no, "content": content}) + "\n")

    if not valid:
        return ParseResult(df=pl.DataFrame(schema={c: pl.Utf8 for c in cols}),
                           total_lines=total, quarantine_count=len(bad))

    df = pl.read_csv(
        io.StringIO("\n".join(valid)),
        separator="\t",
        has_header=False,
        new_columns=cols,
        schema_overrides=schema,
        ignore_errors=True,   # we already filtered — be forgiving now
        null_values=[""],
    )
    return ParseResult(df=df, total_lines=total, quarantine_count=len(bad))


def _parse_stream(
    path: Path, cols: list[str], schema: dict,
    stream_name: str, quarantine_dir: Path | None,
) -> ParseResult:
    try:
        df = _parse_strict(path, cols, schema)
        total = df.height
        return ParseResult(df=df, total_lines=total, quarantine_count=0)
    except (pl.exceptions.ComputeError, pl.exceptions.SchemaFieldNotFoundError,
            pl.exceptions.NoDataError) as e:
        log.warning("gdelt_parser_fallback", stream=stream_name, error=str(e))
        return _parse_with_fallback(path, cols, schema, stream_name, quarantine_dir)


def parse_events(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    return _parse_stream(path, EVENT_COLUMNS, EVENT_POLARS_SCHEMA, "events", quarantine_dir)


def parse_mentions(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    return _parse_stream(path, MENTION_COLUMNS, MENTION_POLARS_SCHEMA, "mentions", quarantine_dir)


def parse_gkg(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    return _parse_stream(path, GKG_COLUMNS, GKG_POLARS_SCHEMA, "gkg", quarantine_dir)
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_parser.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add services/data-ingestion/gdelt_raw/parser.py \
        services/data-ingestion/tests/test_gdelt_parser.py \
        services/data-ingestion/tests/fixtures/gdelt/slice_20260425_full.export.CSV \
        services/data-ingestion/tests/fixtures/gdelt/slice_malformed.export.CSV
git commit -m "feat(gdelt): two-stage parser (strict + quarantine fallback)"
```

---

## Task 9: Downloader (lastupdate + ZIP fetch + MD5)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/downloader.py`
- Create: `services/data-ingestion/tests/test_gdelt_downloader.py`

- [ ] **Step 1: Write failing tests (httpx mock)**

```python
# services/data-ingestion/tests/test_gdelt_downloader.py
import hashlib
from pathlib import Path

import httpx
import pytest

from gdelt_raw.downloader import (
    LastUpdateEntry, parse_lastupdate, slice_id_from_url, download_slice,
)


LASTUPDATE_SAMPLE = """\
75054 0729f01aacfec7ae2beb068c6cc9a47e http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip
142297 0c76d7ef20465fcab808d99ee2256496 http://data.gdeltproject.org/gdeltv2/20260425120000.mentions.CSV.zip
5885170 d9c68dd9f253f50775ef1479e4ad509b http://data.gdeltproject.org/gdeltv2/20260425120000.gkg.csv.zip
"""


def test_parse_lastupdate():
    entries = parse_lastupdate(LASTUPDATE_SAMPLE)
    assert len(entries) == 3
    assert entries[0].stream == "events"
    assert entries[0].md5 == "0729f01aacfec7ae2beb068c6cc9a47e"
    assert entries[0].slice_id == "20260425120000"
    assert entries[1].stream == "mentions"
    assert entries[2].stream == "gkg"


def test_slice_id_extraction():
    assert slice_id_from_url(
        "http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip"
    ) == "20260425120000"


@pytest.mark.asyncio
async def test_download_slice_verifies_md5(tmp_path, httpx_mock):
    # Construct a payload and its real MD5
    payload = b"fake-zip-content"
    real_md5 = hashlib.md5(payload).hexdigest()
    url = "http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip"
    httpx_mock.add_response(url=url, content=payload)

    entry = LastUpdateEntry(
        size=len(payload), md5=real_md5, url=url,
        stream="events", slice_id="20260425120000",
    )
    out = await download_slice(entry, tmp_path)
    assert out.exists()
    assert out.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_slice_rejects_wrong_md5(tmp_path, httpx_mock):
    payload = b"actual-payload"
    wrong_md5 = "0" * 32
    url = "http://data.gdeltproject.org/gdeltv2/20260425120000.export.CSV.zip"
    httpx_mock.add_response(url=url, content=payload)

    entry = LastUpdateEntry(
        size=len(payload), md5=wrong_md5, url=url,
        stream="events", slice_id="20260425120000",
    )
    from gdelt_raw.downloader import MD5MismatchError
    with pytest.raises(MD5MismatchError):
        await download_slice(entry, tmp_path)


@pytest.mark.asyncio
async def test_backfill_downloads_historical_slice_without_md5(tmp_path, httpx_mock):
    """Backfill path: MD5 is '' because we don't fetch lastupdate for history.
    download_slice must accept verify_md5=False."""
    payload = b"historical-zip-payload"
    url = "http://data.gdeltproject.org/gdeltv2/20260101000000.export.CSV.zip"
    httpx_mock.add_response(url=url, content=payload)

    entry = LastUpdateEntry(
        size=0, md5="", url=url,
        stream="events", slice_id="20260101000000",
    )
    out = await download_slice(entry, tmp_path, verify_md5=False)
    assert out.read_bytes() == payload
```

- [ ] **Step 2: Add dev deps and run — expect FAIL**

Run:
```bash
cd services/data-ingestion && uv add --dev pytest-httpx pytest-asyncio
uv run pytest tests/test_gdelt_downloader.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/downloader.py
"""Download GDELT raw zips with MD5 verification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from gdelt_raw.config import get_settings

log = structlog.get_logger(__name__)


class MD5MismatchError(Exception):
    pass


@dataclass(frozen=True)
class LastUpdateEntry:
    size: int
    md5: str
    url: str
    stream: str       # "events" | "mentions" | "gkg"
    slice_id: str     # "20260425120000"


def _stream_from_url(url: str) -> str:
    if ".export.CSV.zip" in url:
        return "events"
    if ".mentions.CSV.zip" in url:
        return "mentions"
    if ".gkg.csv.zip" in url:
        return "gkg"
    raise ValueError(f"Unknown GDELT stream in URL: {url}")


def slice_id_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1].split(".", 1)[0]


def parse_lastupdate(text: str) -> list[LastUpdateEntry]:
    entries: list[LastUpdateEntry] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        size_s, md5, url = ln.split(maxsplit=2)
        entries.append(LastUpdateEntry(
            size=int(size_s), md5=md5, url=url,
            stream=_stream_from_url(url),
            slice_id=slice_id_from_url(url),
        ))
    return entries


async def fetch_lastupdate() -> list[LastUpdateEntry]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.download_timeout) as client:
        resp = await client.get(f"{settings.base_url}/lastupdate.txt")
        resp.raise_for_status()
        return parse_lastupdate(resp.text)


async def download_slice(
    entry: LastUpdateEntry, out_dir: Path, *, verify_md5: bool = True,
) -> Path:
    """Download a single slice file. If verify_md5=True and entry.md5 is non-empty,
    validate and raise MD5MismatchError on drift. Backfill sets verify_md5=False
    because we don't have MD5s for historical slices (they're not in lastupdate.txt)."""
    settings = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / entry.url.rsplit("/", 1)[-1]
    async with httpx.AsyncClient(timeout=settings.download_timeout) as client:
        resp = await client.get(entry.url)
        resp.raise_for_status()
        content = resp.content
    if verify_md5 and entry.md5:
        actual_md5 = hashlib.md5(content).hexdigest()
        if actual_md5 != entry.md5:
            raise MD5MismatchError(
                f"expected={entry.md5} actual={actual_md5} url={entry.url}"
            )
    out_path.write_bytes(content)
    log.info("gdelt_downloaded",
             stream=entry.stream, slice=entry.slice_id, bytes=len(content),
             md5_verified=(verify_md5 and bool(entry.md5)))
    return out_path
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_downloader.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/downloader.py \
        services/data-ingestion/tests/test_gdelt_downloader.py \
        services/data-ingestion/pyproject.toml services/data-ingestion/uv.lock
git commit -m "feat(gdelt): download with MD5 verification + lastupdate parser"
```

---

## Task 10: Multi-stage filter with Nuclear-Override

**Files:**
- Create: `services/data-ingestion/gdelt_raw/filter.py`
- Create: `services/data-ingestion/tests/test_gdelt_filter.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_filter.py
import polars as pl

from gdelt_raw.filter import apply_filters, FilterResult


def _events_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [1, 2, 3, 4],
        "event_root_code": [19, 3, 18, 1],  # only 19,18 tactical
        "quad_class": [4, 1, 4, 1],
        "goldstein_scale": [-6.5, 1.0, -4.2, 0.5],
        "avg_tone": [-4.0, 2.0, -3.5, 1.0],
        "num_mentions": [10, 5, 3, 2],
        "num_sources": [8, 3, 2, 1],
        "num_articles": [9, 4, 2, 1],
        "date_added": [20260425120000] * 4,
        "fraction_date": [2026.3164] * 4,
        "event_code": ["193", "030", "180", "010"],
        "source_url": [f"https://ex.com/{i}" for i in range(4)],
    })


def _mentions_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [3, 4, 4],
        "mention_identifier": ["https://nuc.com/a", "https://nuc.com/a", "https://other.com"],
        "mention_doc_tone": [-5.0, -3.0, 0.0],
        "confidence": [100, 100, 90],
        "action_char_offset": [10, 20, 30],
    })


def _gkg_df() -> pl.DataFrame:
    return pl.DataFrame({
        "gkg_record_id": ["r1", "r2"],
        "v21_date": [20260425120000, 20260425120000],
        "v2_document_identifier": ["https://nuc.com/a", "https://ex.com/2"],
        "v1_themes": ["NUCLEAR;WMD", "ARMEDCONFLICT;KILL"],
        "v2_source_common_name": ["nuc.com", "ex.com"],
    })


def test_tactical_filter_keeps_roots_18_19():
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    assert set(res.events.get_column("global_event_id").to_list()) >= {1, 3}


def test_nuclear_theme_override_keeps_event_outside_cameo_allowlist():
    """Event 4 has event_root_code=1 (not in allowlist) but is referenced
    by GKG doc r1 which has NUCLEAR theme → must be kept."""
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    kept = set(res.events.get_column("global_event_id").to_list())
    assert 4 in kept, f"nuclear-override failed, kept={kept}"
    # And filter_reason distinguishes
    rows = res.events.filter(pl.col("global_event_id") == 4).to_dicts()
    assert rows[0]["filter_reason"] == "nuclear_override"


def test_gkg_join_does_not_duplicate_docs_with_multiple_events():
    """GKG doc r1 is referenced by multiple events (via mentions fixture).
    After materialized-join we MUST still have doc_id unique."""
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    doc_ids = res.gkg.get_column("gkg_record_id").to_list()
    assert len(doc_ids) == len(set(doc_ids))


def test_gkg_linked_fields_are_lists():
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    # doc r1 links to events 3+4
    row = res.gkg.filter(pl.col("gkg_record_id") == "r1").to_dicts()[0]
    assert isinstance(row["linked_event_ids"], list)
    assert isinstance(row["cameo_roots_linked"], list)
    assert set(row["linked_event_ids"]) == {"gdelt:event:3", "gdelt:event:4"}
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_filter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/filter.py
"""Multi-stage filter with Nuclear-Override UNION semantics.

1. tactical_event_ids  := events where event_root_code ∈ allowlist
2. gkg_alpha           := gkg where themes match alpha-set
3. gkg_nuclear         := gkg where themes match nuclear-override set
4. nuclear_event_ids   := mentions where url ∈ gkg_nuclear.urls
5. final_event_ids     := tactical ∪ nuclear
6. events_filtered     := events ∩ final, with filter_reason column
7. gkg_filtered        := alpha ∪ nuclear (deduped on gkg_record_id)
                          with materialized linked-event aggregates
8. mentions_filtered   := mentions where event_id ∈ final
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from gdelt_raw.cameo_mapping import map_cameo_root
from gdelt_raw.ids import build_event_id, build_doc_id
from gdelt_raw.theme_matching import any_match_in_themes, compile_patterns


@dataclass
class FilterResult:
    events: pl.DataFrame
    mentions: pl.DataFrame
    gkg: pl.DataFrame


def _themes_list(col: pl.Expr) -> pl.Expr:
    return col.fill_null("").str.split(";")


def _gkg_theme_match(df: pl.DataFrame, matcher) -> pl.Series:
    themes = df.get_column("v1_themes").fill_null("").str.split(";").to_list()
    return pl.Series([any_match_in_themes(t, matcher) for t in themes])


def apply_filters(
    events_df: pl.DataFrame,
    mentions_df: pl.DataFrame,
    gkg_df: pl.DataFrame,
    *,
    cameo_roots: list[int],
    theme_alpha: list[str],
    theme_nuclear_override: list[str],
) -> FilterResult:
    # 1. tactical events
    tactical_ids = set(
        events_df.filter(pl.col("event_root_code").is_in(cameo_roots))
        .get_column("global_event_id").to_list()
    )

    # 2. gkg alpha
    alpha_matcher = compile_patterns(theme_alpha)
    gkg_alpha_mask = _gkg_theme_match(gkg_df, alpha_matcher)
    gkg_alpha = gkg_df.filter(gkg_alpha_mask)

    # 3. gkg nuclear
    nuclear_matcher = compile_patterns(theme_nuclear_override)
    gkg_nuclear_mask = _gkg_theme_match(gkg_df, nuclear_matcher)
    gkg_nuclear = gkg_df.filter(gkg_nuclear_mask)

    # 4. nuclear event ids via mentions → gkg_nuclear.urls
    nuclear_urls = set(gkg_nuclear.get_column("v2_document_identifier").to_list())
    nuclear_ids = set(
        mentions_df.filter(pl.col("mention_identifier").is_in(nuclear_urls))
        .get_column("global_event_id").to_list()
    )

    # 5. union
    final_ids = tactical_ids | nuclear_ids

    # 6. filter events and annotate
    events_filtered = (
        events_df.filter(pl.col("global_event_id").is_in(final_ids))
        .with_columns([
            pl.when(pl.col("global_event_id").is_in(tactical_ids))
              .then(pl.lit("tactical"))
              .otherwise(pl.lit("nuclear_override"))
              .alias("filter_reason"),
            pl.col("event_root_code")
              .map_elements(lambda r: map_cameo_root(int(r)) or "", return_dtype=pl.Utf8)
              .alias("codebook_type"),
            pl.col("global_event_id")
              .map_elements(lambda i: build_event_id(int(i)), return_dtype=pl.Utf8)
              .alias("event_id"),
        ])
    )

    # 7. gkg union and materialized join
    gkg_union = pl.concat([gkg_alpha, gkg_nuclear]).unique(subset=["gkg_record_id"])

    # Aggregate mentions+events per mention_url to avoid N:N duplicate explosion
    events_for_join = events_filtered.select([
        "global_event_id", "event_id", "event_root_code",
        "goldstein_scale", "codebook_type",
    ])
    mentions_scoped = mentions_df.filter(pl.col("global_event_id").is_in(final_ids))
    linked_agg = (
        mentions_scoped.join(events_for_join, on="global_event_id")
        .group_by("mention_identifier")
        .agg([
            pl.col("event_id").unique().alias("linked_event_ids"),
            pl.col("goldstein_scale").min().alias("goldstein_min"),
            pl.col("goldstein_scale").mean().alias("goldstein_avg"),
            pl.col("event_root_code").unique().alias("cameo_roots_linked"),
            pl.col("codebook_type").unique().alias("codebook_types_linked"),
        ])
    )

    gkg_with_join = gkg_union.join(
        linked_agg,
        left_on="v2_document_identifier", right_on="mention_identifier",
        how="left",
    ).with_columns([
        pl.col("gkg_record_id")
          .map_elements(build_doc_id, return_dtype=pl.Utf8)
          .alias("doc_id"),
    ])

    # Invariant: doc_id unique
    assert gkg_with_join.n_unique("gkg_record_id") == gkg_with_join.height

    # 8. mentions
    mentions_filtered = mentions_scoped

    return FilterResult(
        events=events_filtered,
        mentions=mentions_filtered,
        gkg=gkg_with_join,
    )
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_filter.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/filter.py \
        services/data-ingestion/tests/test_gdelt_filter.py
git commit -m "feat(gdelt): multi-stage filter with nuclear-override UNION"
```

---

## Task 10.5: Canonical Transform Layer (raw GDELT → Pydantic-writer schema)

**Why:** Filter output still carries raw GDELT column names (`event_code`, `goldstein_scale`, `v21_date`, `v2_document_identifier`, `v1_themes` string). But `GDELTEventWrite` / `GDELTDocumentWrite` expect canonical fields (`cameo_code`, `goldstein`, `gdelt_date`, `url`, `themes: list[str]`). Without a transform step, `Neo4jWriter.write_from_parquet()` would fail with a `ValidationError` on every single row. This task adds the transform that closes that gap — called between filter and parquet-write, so Parquet holds the canonical schema.

**Files:**
- Create: `services/data-ingestion/gdelt_raw/transform.py`
- Create: `services/data-ingestion/tests/test_gdelt_transform.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_transform.py
from datetime import datetime

import polars as pl

from gdelt_raw.transform import (
    canonicalize_events, canonicalize_gkg, canonicalize_mentions,
)


def _raw_filtered_events() -> pl.DataFrame:
    """Minimal raw-filtered events DataFrame as produced by filter.apply_filters."""
    return pl.DataFrame({
        "global_event_id": [1300904663],
        "event_id": ["gdelt:event:1300904663"],
        "event_code": ["193"],
        "event_root_code": [19],
        "quad_class": [4],
        "goldstein_scale": [-6.5],
        "avg_tone": [-4.2],
        "num_mentions": [12],
        "num_sources": [8],
        "num_articles": [11],
        "date_added": [20260425121500],
        "fraction_date": [2026.3164],
        "actor1_code": ["MIL"], "actor1_name": ["MILITARY"],
        "actor2_code": ["REB"], "actor2_name": ["REBELS"],
        "source_url": ["https://ex.com/a"],
        "codebook_type": ["conflict.armed"],
        "filter_reason": ["tactical"],
    })


def _raw_filtered_gkg() -> pl.DataFrame:
    return pl.DataFrame({
        "gkg_record_id": ["20260425121500-42"],
        "doc_id": ["gdelt:gkg:20260425121500-42"],
        "v21_date": [20260425121500],
        "v2_document_identifier": ["https://ex.com/a"],
        "v2_source_common_name": ["ex.com"],
        "v1_themes": ["ARMEDCONFLICT;KILL;MILITARY"],
        "v1_persons": ["Vladimir Putin;Joe Biden"],
        "v1_organizations": ["NATO;UN"],
        "v15_tone": ["2.1,5.0,-3.0,8.0,3.5,1.1,599"],
        "v21_sharp_image": ["https://ex.com/img.jpg"],
        "v21_quotations": [""],
        "linked_event_ids": [["gdelt:event:1", "gdelt:event:2"]],
        "goldstein_min": [-6.5],
        "goldstein_avg": [-6.0],
        "cameo_roots_linked": [[18, 19]],
        "codebook_types_linked": [["conflict.assault", "conflict.armed"]],
    })


def _raw_filtered_mentions() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [1300904663],
        "mention_identifier": ["https://ex.com/a"],
        "mention_doc_tone": [-6.1],
        "confidence": [100],
        "action_char_offset": [1664],
    })


def test_canonicalize_events_renames_and_adds_source():
    out = canonicalize_events(_raw_filtered_events())
    row = out.to_dicts()[0]
    assert row["event_id"] == "gdelt:event:1300904663"
    assert row["source"] == "gdelt"
    assert row["cameo_code"] == "193"
    assert row["cameo_root"] == 19
    assert row["goldstein"] == -6.5
    assert isinstance(row["date_added"], datetime)
    assert row["date_added"].year == 2026
    assert row["date_added"].month == 4
    assert row["codebook_type"] == "conflict.armed"
    assert row["filter_reason"] == "tactical"


def test_canonicalize_events_drops_raw_columns():
    out = canonicalize_events(_raw_filtered_events())
    assert "global_event_id" not in out.columns
    assert "event_code" not in out.columns
    assert "event_root_code" not in out.columns
    assert "goldstein_scale" not in out.columns


def test_canonicalize_gkg_parses_themes_into_list():
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    assert row["themes"] == ["ARMEDCONFLICT", "KILL", "MILITARY"]
    assert row["persons"] == ["Vladimir Putin", "Joe Biden"]
    assert row["organizations"] == ["NATO", "UN"]


def test_canonicalize_gkg_renames_url_and_dates():
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    assert row["doc_id"] == "gdelt:gkg:20260425121500-42"
    assert row["url"] == "https://ex.com/a"
    assert row["source_name"] == "ex.com"
    assert row["source"] == "gdelt_gkg"
    assert isinstance(row["gdelt_date"], datetime)
    assert row["published_at"] is None


def test_canonicalize_gkg_parses_v15_tone_seven_fields():
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    # V1.5 tone format: avgTone,posTone,negTone,polarity,actRef,selfGrpRef,wordCount
    assert row["tone_positive"] == 5.0
    assert row["tone_negative"] == -3.0
    assert row["tone_polarity"] == 8.0
    assert row["word_count"] == 599


def test_canonicalize_gkg_handles_empty_list_fields():
    df = _raw_filtered_gkg().with_columns([
        pl.lit("").alias("v1_persons"),
        pl.lit("").alias("v1_organizations"),
    ])
    out = canonicalize_gkg(df)
    row = out.to_dicts()[0]
    assert row["persons"] == []
    assert row["organizations"] == []


def test_canonicalize_mentions_renames_and_builds_canonical_event_id():
    out = canonicalize_mentions(_raw_filtered_mentions())
    row = out.to_dicts()[0]
    assert row["event_id"] == "gdelt:event:1300904663"
    assert row["mention_url"] == "https://ex.com/a"
    assert row["tone"] == -6.1
    assert row["confidence"] == 100
    assert row["char_offset"] == 1664


def test_canonical_event_validates_against_pydantic_writer_contract():
    """Integration check: canonical output must pass GDELTEventWrite."""
    from gdelt_raw.schemas import GDELTEventWrite
    out = canonicalize_events(_raw_filtered_events())
    row = out.to_dicts()[0]
    GDELTEventWrite.model_validate(row)  # raises if schema mismatch


def test_canonical_doc_validates_against_pydantic_writer_contract():
    from gdelt_raw.schemas import GDELTDocumentWrite
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    GDELTDocumentWrite.model_validate(row)
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_transform.py -v`
Expected: FAIL

- [ ] **Step 3: Implement transform.py**

```python
# services/data-ingestion/gdelt_raw/transform.py
"""Canonical transform: raw-filtered GDELT DataFrames → Pydantic-writer schema.

Without this layer, Parquet would hold raw GDELT column names while
Neo4j/Qdrant writers expect canonical field names. This is the single place
where that translation happens. Everything downstream speaks canonical.
"""

from __future__ import annotations

import polars as pl

from gdelt_raw.ids import build_event_id


def _parse_gdelt_datetime(col: str) -> pl.Expr:
    """GDELT date_added / v21_date is int YYYYMMDDHHMMSS → parse to datetime."""
    return (
        pl.col(col).cast(pl.Utf8)
        .str.strptime(pl.Datetime, format="%Y%m%d%H%M%S", strict=False)
    )


def _split_semicolon_list(col: str) -> pl.Expr:
    """GDELT semicolon-delimited strings (e.g. V1Themes) → list[str], empties dropped."""
    return (
        pl.col(col).fill_null("")
        .str.split(";")
        .list.eval(pl.element().filter(pl.element().str.len_chars() > 0))
    )


def canonicalize_events(df: pl.DataFrame) -> pl.DataFrame:
    """Raw-filtered events DataFrame → canonical events DataFrame.

    Input columns (from filter.apply_filters): global_event_id, event_id,
    event_code, event_root_code, quad_class, goldstein_scale, avg_tone,
    num_mentions, num_sources, num_articles, date_added (int), fraction_date,
    actor1_*, actor2_*, source_url, codebook_type, filter_reason.

    Output schema matches GDELTEventWrite exactly.
    """
    return df.select([
        pl.col("event_id"),
        pl.lit("gdelt").alias("source"),
        pl.col("event_code").alias("cameo_code"),
        pl.col("event_root_code").alias("cameo_root"),
        pl.col("quad_class"),
        pl.col("goldstein_scale").alias("goldstein"),
        pl.col("avg_tone"),
        pl.col("num_mentions"),
        pl.col("num_sources"),
        pl.col("num_articles"),
        _parse_gdelt_datetime("date_added").alias("date_added"),
        pl.col("fraction_date"),
        pl.col("actor1_code"),
        pl.col("actor1_name"),
        pl.col("actor2_code"),
        pl.col("actor2_name"),
        pl.col("source_url"),
        pl.col("codebook_type"),
        pl.col("filter_reason"),
    ])


def canonicalize_gkg(df: pl.DataFrame) -> pl.DataFrame:
    """Raw-filtered GKG → canonical GKG. Output matches GDELTDocumentWrite.

    v15_tone is 7-field comma-separated: avgTone, posTone, negTone, polarity,
    activityRef, selfGroupRef, wordCount.
    """
    # Split v15_tone once, then extract by position
    tone_parts = pl.col("v15_tone").fill_null("0,0,0,0,0,0,0").str.split(",")

    return df.select([
        pl.col("doc_id"),
        pl.lit("gdelt_gkg").alias("source"),
        pl.col("v2_document_identifier").alias("url"),
        pl.col("v2_source_common_name").alias("source_name"),
        _parse_gdelt_datetime("v21_date").alias("gdelt_date"),
        pl.lit(None, dtype=pl.Datetime).alias("published_at"),
        _split_semicolon_list("v1_themes").alias("themes"),
        _split_semicolon_list("v1_persons").alias("persons"),
        _split_semicolon_list("v1_organizations").alias("organizations"),
        tone_parts.list.get(1).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_positive"),
        tone_parts.list.get(2).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_negative"),
        tone_parts.list.get(3).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_polarity"),
        tone_parts.list.get(4).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_activity"),
        tone_parts.list.get(5).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_self_group"),
        tone_parts.list.get(6).cast(pl.Int64, strict=False).fill_null(0)
            .alias("word_count"),
        pl.col("v21_sharp_image").alias("sharp_image_url"),
        _split_semicolon_list("v21_quotations").alias("quotations"),
        pl.col("linked_event_ids").fill_null([]),
        pl.col("goldstein_min"),
        pl.col("goldstein_avg"),
        pl.col("cameo_roots_linked").fill_null([]),
        pl.col("codebook_types_linked").fill_null([]),
    ])


def canonicalize_mentions(df: pl.DataFrame) -> pl.DataFrame:
    """Raw mentions → canonical (event_id, mention_url, tone, confidence, char_offset)."""
    return df.select([
        pl.col("global_event_id")
          .map_elements(lambda i: build_event_id(int(i)), return_dtype=pl.Utf8)
          .alias("event_id"),
        pl.col("mention_identifier").alias("mention_url"),
        pl.col("mention_doc_tone").alias("tone"),
        pl.col("confidence"),
        pl.col("action_char_offset").alias("char_offset"),
    ])
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_transform.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/transform.py \
        services/data-ingestion/tests/test_gdelt_transform.py
git commit -m "feat(gdelt): canonical transform layer (raw → pydantic-writer schema)"
```

---

## Task 11: Redis state (per-stream + per-slice + summary)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/state.py`
- Create: `services/data-ingestion/tests/test_gdelt_state.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_state.py
import fakeredis.aioredis
import pytest

from gdelt_raw.state import GDELTState


@pytest.fixture
async def state():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return GDELTState(r)


@pytest.mark.asyncio
async def test_stream_state_roundtrip(state):
    s = await state
    await s.set_stream_parquet("20260425120000", "events", "done")
    assert await s.get_stream_parquet("20260425120000", "events") == "done"


@pytest.mark.asyncio
async def test_store_state_transition(state):
    s = await state
    await s.set_store_state("20260425120000", "neo4j", "pending")
    await s.add_pending("neo4j", "20260425120000")
    assert "20260425120000" in await s.list_pending("neo4j")
    await s.set_store_state("20260425120000", "neo4j", "done")
    await s.remove_pending("neo4j", "20260425120000")
    assert "20260425120000" not in await s.list_pending("neo4j")


@pytest.mark.asyncio
async def test_summary_last_slice(state):
    s = await state
    await s.set_last_slice("neo4j", "20260425120000")
    assert await s.get_last_slice("neo4j") == "20260425120000"


@pytest.mark.asyncio
async def test_slice_is_fully_done_requires_all_three_streams_plus_stores(state):
    s = await state
    # Only one stream done — not fully done
    await s.set_stream_parquet("20260425120000", "events", "done")
    assert not await s.is_slice_fully_done("20260425120000")
    # All three plus both stores → done
    await s.set_stream_parquet("20260425120000", "gkg", "done")
    await s.set_stream_parquet("20260425120000", "mentions", "done")
    await s.set_store_state("20260425120000", "neo4j", "done")
    await s.set_store_state("20260425120000", "qdrant", "done")
    assert await s.is_slice_fully_done("20260425120000")
```

- [ ] **Step 2: Add fakeredis dev-dep and run — expect FAIL**

Run:
```bash
cd services/data-ingestion && uv add --dev fakeredis
uv run pytest tests/test_gdelt_state.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/state.py
"""Redis-backed state for GDELT ingestion.

Two layers:
  - Per-slice per-stream/store state (primary truth)
  - Summary last-slice keys (for fast UI/status)
"""

from __future__ import annotations

from typing import Literal


StreamName = Literal["events", "mentions", "gkg"]
StoreName = Literal["parquet", "neo4j", "qdrant"]


def _stream_key(slice_id: str, stream: StreamName) -> str:
    return f"gdelt:slice:{slice_id}:{stream}:parquet"


def _store_key(slice_id: str, store: Literal["neo4j", "qdrant"]) -> str:
    return f"gdelt:slice:{slice_id}:{store}"


def _pending_key(store: Literal["neo4j", "qdrant"]) -> str:
    return f"gdelt:pending:{store}"


def _last_slice_key(store: StoreName) -> str:
    return f"gdelt:forward:last_slice:{store}"


class GDELTState:
    def __init__(self, redis_client):
        self.r = redis_client

    async def set_stream_parquet(self, slice_id: str, stream: StreamName, value: str):
        await self.r.set(_stream_key(slice_id, stream), value)

    async def get_stream_parquet(self, slice_id: str, stream: StreamName) -> str | None:
        return await self.r.get(_stream_key(slice_id, stream))

    async def set_store_state(
        self, slice_id: str, store: Literal["neo4j", "qdrant"], value: str
    ):
        await self.r.set(_store_key(slice_id, store), value)

    async def get_store_state(
        self, slice_id: str, store: Literal["neo4j", "qdrant"]
    ) -> str | None:
        return await self.r.get(_store_key(slice_id, store))

    async def add_pending(self, store: Literal["neo4j", "qdrant"], slice_id: str):
        await self.r.zadd(_pending_key(store), {slice_id: int(slice_id)})

    async def remove_pending(self, store: Literal["neo4j", "qdrant"], slice_id: str):
        await self.r.zrem(_pending_key(store), slice_id)

    async def list_pending(
        self, store: Literal["neo4j", "qdrant"], limit: int = 10
    ) -> list[str]:
        return await self.r.zrange(_pending_key(store), 0, limit - 1)

    async def set_last_slice(self, store: StoreName, slice_id: str):
        await self.r.set(_last_slice_key(store), slice_id)

    async def get_last_slice(self, store: StoreName) -> str | None:
        return await self.r.get(_last_slice_key(store))

    async def is_slice_fully_done(self, slice_id: str) -> bool:
        for st in ("events", "mentions", "gkg"):
            if await self.get_stream_parquet(slice_id, st) != "done":
                return False
        for store in ("neo4j", "qdrant"):
            if await self.get_store_state(slice_id, store) != "done":
                return False
        return True
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_state.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/state.py \
        services/data-ingestion/tests/test_gdelt_state.py \
        services/data-ingestion/pyproject.toml services/data-ingestion/uv.lock
git commit -m "feat(gdelt): redis state — per-stream/store + summary + pending set"
```

---

## Task 12: Parquet writer (atomic .tmp+rename)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/writers/__init__.py` (empty)
- Create: `services/data-ingestion/gdelt_raw/writers/parquet_writer.py`
- Create: `services/data-ingestion/tests/test_gdelt_parquet_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_parquet_writer.py
from pathlib import Path

import polars as pl
import pytest

from gdelt_raw.writers.parquet_writer import write_stream_parquet


def test_atomic_rename_produces_final_file(tmp_path):
    df = pl.DataFrame({"a": [1, 2, 3]})
    final = write_stream_parquet(
        df, base_path=tmp_path, stream="events",
        date="2026-04-25", slice_id="20260425120000",
    )
    assert final.exists()
    assert final.name == "20260425120000.parquet"
    assert not (final.parent / "20260425120000.parquet.tmp").exists()
    loaded = pl.read_parquet(final)
    assert loaded.height == 3


def test_incomplete_tmp_parquet_is_not_marked_done(tmp_path, monkeypatch):
    """If rename fails we must NOT leave a final file behind."""
    df = pl.DataFrame({"a": [1]})

    # Force a rename failure
    original_replace = Path.replace
    def _fail(self, target):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(Path, "replace", _fail)

    with pytest.raises(OSError):
        write_stream_parquet(
            df, base_path=tmp_path, stream="events",
            date="2026-04-25", slice_id="20260425120000",
        )

    monkeypatch.setattr(Path, "replace", original_replace)
    # The final file must NOT exist
    assert not (tmp_path / "events" / "date=2026-04-25" / "20260425120000.parquet").exists()


def test_partitioned_layout(tmp_path):
    df = pl.DataFrame({"a": [1]})
    out = write_stream_parquet(
        df, base_path=tmp_path, stream="gkg",
        date="2026-04-25", slice_id="20260425120000",
    )
    assert out.parent.name == "date=2026-04-25"
    assert out.parent.parent.name == "gkg"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_parquet_writer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/writers/__init__.py
"""GDELT writers: parquet, neo4j, qdrant."""
```

```python
# services/data-ingestion/gdelt_raw/writers/parquet_writer.py
"""Atomic Parquet writer — .tmp + fsync + rename."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import structlog

log = structlog.get_logger(__name__)


def write_stream_parquet(
    df: pl.DataFrame,
    *,
    base_path: Path,
    stream: str,          # "events" | "mentions" | "gkg"
    date: str,            # "2026-04-25"
    slice_id: str,        # "20260425120000"
) -> Path:
    partition = Path(base_path) / stream / f"date={date}"
    partition.mkdir(parents=True, exist_ok=True)
    final = partition / f"{slice_id}.parquet"
    tmp = partition / f"{slice_id}.parquet.tmp"

    # Write into .tmp first
    df.write_parquet(tmp, compression="snappy")

    # fsync the file and the directory for durability on crash
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    dir_fd = os.open(str(partition), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    # Atomic rename — either fully visible or not at all
    tmp.replace(final)
    log.info("parquet_written",
             stream=stream, slice=slice_id, rows=df.height, path=str(final))
    return final
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_parquet_writer.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/writers/__init__.py \
        services/data-ingestion/gdelt_raw/writers/parquet_writer.py \
        services/data-ingestion/tests/test_gdelt_parquet_writer.py
git commit -m "feat(gdelt): atomic parquet writer (.tmp + fsync + rename)"
```

---

## Task 13: Neo4j writer (MERGE templates + contract validation)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py`
- Create: `services/data-ingestion/tests/test_gdelt_neo4j_writer.py`

- [ ] **Step 1: Write failing tests (integration test deferred to Task 22)**

```python
# services/data-ingestion/tests/test_gdelt_neo4j_writer.py
import pytest
from pydantic import ValidationError

from gdelt_raw.writers.neo4j_writer import (
    render_event_params, render_doc_params,
    MERGE_EVENT, MERGE_DOC, MERGE_SOURCE, MERGE_THEME,
)
from gdelt_raw.schemas import GDELTEventWrite, GDELTDocumentWrite


def test_event_template_has_secondary_label():
    assert ":Event:GDELTEvent" in MERGE_EVENT


def test_doc_template_has_secondary_label():
    assert ":Document:GDELTDocument" in MERGE_DOC


def test_writer_rejects_event_without_event_id():
    with pytest.raises(ValidationError):
        GDELTEventWrite.model_validate({
            "cameo_code": "193", "cameo_root": 19, "quad_class": 4,
            "goldstein": -6.5, "avg_tone": -4.2,
            "num_mentions": 12, "num_sources": 8, "num_articles": 11,
            "date_added": "2026-04-25T12:15:00Z", "fraction_date": 2026.3164,
            "source_url": "https://example.com/x",
            "codebook_type": "conflict.armed",
            "filter_reason": "tactical",
        })


def test_writer_rejects_doc_without_doc_id():
    with pytest.raises(ValidationError):
        GDELTDocumentWrite.model_validate({
            "url": "https://example.com/a",
            "source_name": "ex.com",
            "gdelt_date": "2026-04-25T12:15:00Z",
        })


def test_render_event_params_passes_through_fields():
    ev = GDELTEventWrite(
        event_id="gdelt:event:42",
        cameo_code="193", cameo_root=19, quad_class=4,
        goldstein=-6.5, avg_tone=-4.2,
        num_mentions=12, num_sources=8, num_articles=11,
        date_added="2026-04-25T12:15:00Z", fraction_date=2026.3164,
        source_url="https://ex.com",
        codebook_type="conflict.armed",
        filter_reason="tactical",
    )
    params = render_event_params(ev)
    assert params["event_id"] == "gdelt:event:42"
    assert params["cameo_root"] == 19
    assert params["codebook_type"] == "conflict.armed"


def test_render_doc_params_handles_optional_published_at():
    doc = GDELTDocumentWrite(
        doc_id="gdelt:gkg:r1",
        url="https://ex.com",
        source_name="ex.com",
        gdelt_date="2026-04-25T12:15:00Z",
    )
    params = render_doc_params(doc)
    assert params["doc_id"] == "gdelt:gkg:r1"
    assert params["published_at"] is None


def test_merge_theme_template_is_idempotent():
    """MERGE on the :ABOUT relationship must not carry a counter —
    otherwise replay increments it unboundedly."""
    assert "r.count = r.count + 1" not in MERGE_THEME
    # Still writes themes
    assert "UNWIND $themes" in MERGE_THEME
    assert ":ABOUT" in MERGE_THEME


def test_merge_mention_sets_properties_on_match_too():
    """Replay must not leave stale tone/confidence; ON MATCH re-sets them."""
    from gdelt_raw.writers.neo4j_writer import MERGE_MENTION
    assert "ON MATCH" in MERGE_MENTION
    assert "r.tone = $tone" in MERGE_MENTION
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_neo4j_writer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/writers/neo4j_writer.py
"""Neo4j writer — deterministic Cypher MERGE templates.

Writers validate via Pydantic contracts before any Neo4j call.
No LLM-generated Cypher on the write-path (CLAUDE.md rule).
"""

from __future__ import annotations

from typing import Any

import polars as pl
import structlog
from neo4j import AsyncGraphDatabase

from gdelt_raw.schemas import GDELTEventWrite, GDELTDocumentWrite

log = structlog.get_logger(__name__)


MERGE_EVENT = """
MERGE (e:Event:GDELTEvent {event_id: $event_id})
  ON CREATE SET
    e.source = 'gdelt',
    e.cameo_code = $cameo_code,
    e.cameo_root = $cameo_root,
    e.quad_class = $quad_class,
    e.goldstein = $goldstein,
    e.avg_tone = $avg_tone,
    e.num_mentions = $num_mentions,
    e.num_sources = $num_sources,
    e.num_articles = $num_articles,
    e.date_added = datetime($date_added),
    e.fraction_date = $fraction_date,
    e.actor1_code = $actor1_code,
    e.actor1_name = $actor1_name,
    e.actor2_code = $actor2_code,
    e.actor2_name = $actor2_name,
    e.source_url = $source_url,
    e.codebook_type = $codebook_type,
    e.filter_reason = $filter_reason
  ON MATCH SET
    e.num_mentions = $num_mentions,
    e.num_sources = $num_sources,
    e.num_articles = $num_articles
"""

MERGE_DOC = """
MERGE (d:Document:GDELTDocument {doc_id: $doc_id})
  ON CREATE SET
    d.source = 'gdelt_gkg',
    d.url = $url,
    d.source_name = $source_name,
    d.gdelt_date = datetime($gdelt_date),
    d.published_at = CASE WHEN $published_at IS NULL THEN NULL ELSE datetime($published_at) END,
    d.themes = $themes,
    d.tone_polarity = $tone_polarity,
    d.word_count = $word_count,
    d.sharp_image_url = $sharp_image_url,
    d.quotations = $quotations
"""

MERGE_SOURCE = """
MERGE (s:Source {name: $name})
  ON CREATE SET s.quality_tier = 'unverified', s.updated_at = datetime()
  ON MATCH SET  s.updated_at = datetime()
WITH s
MATCH (d:GDELTDocument {doc_id: $doc_id})
MERGE (d)-[:FROM_SOURCE]->(s)
"""

MERGE_THEME = """
MATCH (d:GDELTDocument {doc_id: $doc_id})
UNWIND $themes AS tcode
MERGE (t:Theme {theme_code: tcode})
MERGE (d)-[:ABOUT]->(t)
"""
# Idempotency: MERGE on the relationship is set-semantic — no count
# increment on replay. If theme-frequency is ever needed, store it in
# d.themes (list) and query with list functions.

MERGE_MENTION = """
MATCH (d:Document {url: $doc_url})
MATCH (e:GDELTEvent {event_id: $event_id})
MERGE (d)-[r:MENTIONS]->(e)
  ON CREATE SET r.tone = $tone, r.confidence = $confidence, r.char_offset = $char_offset
  ON MATCH  SET r.tone = $tone, r.confidence = $confidence, r.char_offset = $char_offset
"""
# ON MATCH also SETs — last-write-wins on properties, but edge count stays 1.


def render_event_params(ev: GDELTEventWrite) -> dict[str, Any]:
    d = ev.model_dump(mode="json")  # datetime → iso
    return d


def render_doc_params(doc: GDELTDocumentWrite) -> dict[str, Any]:
    d = doc.model_dump(mode="json")
    return d


class Neo4jWriter:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self._driver.close()

    async def write_events(self, events: list[GDELTEventWrite]):
        async with self._driver.session() as session:
            async with await session.begin_transaction() as tx:
                for ev in events:
                    await tx.run(MERGE_EVENT, render_event_params(ev))
                await tx.commit()

    async def write_docs(self, docs: list[GDELTDocumentWrite]):
        async with self._driver.session() as session:
            async with await session.begin_transaction() as tx:
                for d in docs:
                    params = render_doc_params(d)
                    await tx.run(MERGE_DOC, params)
                    await tx.run(MERGE_SOURCE, {"name": d.source_name, "doc_id": d.doc_id})
                    if d.themes:
                        await tx.run(MERGE_THEME, {"themes": d.themes, "doc_id": d.doc_id})
                await tx.commit()

    async def write_mentions(self, mentions: list[dict]):
        """mentions: list of canonical dicts with event_id, mention_url, tone,
        confidence, char_offset. Requires corresponding Documents + GDELTEvents
        to already exist in the graph."""
        async with self._driver.session() as session:
            async with await session.begin_transaction() as tx:
                for m in mentions:
                    await tx.run(MERGE_MENTION, {
                        "doc_url": m["mention_url"],
                        "event_id": m["event_id"],
                        "tone": m.get("tone"),
                        "confidence": m.get("confidence"),
                        "char_offset": m.get("char_offset"),
                    })
                await tx.commit()

    async def write_from_parquet(self, parquet_base, slice_id: str, date: str):
        """Read the three canonical parquet streams and write in dependency order:
        Events → Documents (+ Sources, + Themes) → Mentions (Doc→Event edges).

        Phase 1 scope: Events, Documents, Sources, Themes, Mentions.
        Deferred to Phase 2 (separate spec): Entities (from V2Persons/V2Orgs),
        Locations (from V2Locations), INVOLVES edges, OCCURRED_AT edges."""
        from pathlib import Path
        ev_path = Path(parquet_base) / "events" / f"date={date}" / f"{slice_id}.parquet"
        gkg_path = Path(parquet_base) / "gkg" / f"date={date}" / f"{slice_id}.parquet"
        mentions_path = Path(parquet_base) / "mentions" / f"date={date}" / f"{slice_id}.parquet"

        if ev_path.exists():
            ev_df = pl.read_parquet(ev_path)
            events = [GDELTEventWrite.model_validate(r) for r in ev_df.to_dicts()]
            await self.write_events(events)

        if gkg_path.exists():
            gkg_df = pl.read_parquet(gkg_path)
            docs = [GDELTDocumentWrite.model_validate(r) for r in gkg_df.to_dicts()]
            await self.write_docs(docs)

        # Mentions require both Events and Docs to already exist — only write
        # if both parquet streams were present.
        if mentions_path.exists() and ev_path.exists() and gkg_path.exists():
            m_df = pl.read_parquet(mentions_path)
            await self.write_mentions(m_df.to_dicts())
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_neo4j_writer.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/writers/neo4j_writer.py \
        services/data-ingestion/tests/test_gdelt_neo4j_writer.py
git commit -m "feat(gdelt): neo4j writer — scoped merge templates + contract validation + mentions"
```

---

## Task 14: Qdrant writer (embed + upsert from Parquet)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/writers/qdrant_writer.py`
- Create: `services/data-ingestion/tests/test_gdelt_qdrant_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_qdrant_writer.py
from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

from gdelt_raw.writers.qdrant_writer import (
    build_embed_text, build_payload, QdrantWriter,
)


def test_embed_text_is_deterministic():
    row = {
        "doc_id": "gdelt:gkg:r1",
        "title": "Strike in Donbas",
        "themes": ["ARMEDCONFLICT", "KILL"],
        "persons": ["Foo"],
        "organizations": ["NATO"],
    }
    a = build_embed_text(row)
    b = build_embed_text(row)
    assert a == b
    assert len(a) <= 1500


def test_payload_uses_canonical_doc_id():
    row = {
        "doc_id": "gdelt:gkg:r1",
        "url": "https://ex.com",
        "v2_source_common_name": "ex.com",
        "v1_themes": "ARMEDCONFLICT;KILL",
        "themes": ["ARMEDCONFLICT", "KILL"],
        "persons": [],
        "organizations": [],
        "linked_event_ids": ["gdelt:event:1", "gdelt:event:2"],
        "goldstein_min": -6.0,
        "goldstein_avg": -4.0,
        "cameo_roots_linked": [18, 19],
        "codebook_types_linked": ["conflict.assault", "conflict.armed"],
        "v21_date": 20260425120000,
        "tone_polarity": 8.4,
        "word_count": 599,
    }
    p = build_payload(row)
    assert p["doc_id"] == "gdelt:gkg:r1"
    assert p["source"] == "gdelt_gkg"
    assert isinstance(p["linked_event_ids"], list)
    assert isinstance(p["cameo_roots_linked"], list)


def test_payload_linked_fields_are_lists():
    row = {
        "doc_id": "gdelt:gkg:r2", "url": "https://ex.com",
        "v2_source_common_name": "ex.com", "v1_themes": "",
        "themes": [], "persons": [], "organizations": [],
        "linked_event_ids": None, "goldstein_min": None, "goldstein_avg": None,
        "cameo_roots_linked": None, "codebook_types_linked": None,
        "v21_date": 20260425120000, "tone_polarity": 0.0, "word_count": 0,
    }
    p = build_payload(row)
    assert p["linked_event_ids"] == []
    assert p["cameo_roots_linked"] == []


@pytest.mark.asyncio
async def test_qdrant_can_upsert_when_neo4j_failed_but_parquet_exists(tmp_path):
    """Qdrant reads only from GKG parquet — it must NOT require Neo4j state."""
    df = pl.DataFrame({
        "doc_id": ["gdelt:gkg:r1"],
        "url": ["https://ex.com"],
        "v2_source_common_name": ["ex.com"],
        "v1_themes": ["ARMEDCONFLICT;KILL"],
        "themes": [["ARMEDCONFLICT", "KILL"]],
        "persons": [["A"]],
        "organizations": [[]],
        "linked_event_ids": [["gdelt:event:1"]],
        "goldstein_min": [-6.0],
        "goldstein_avg": [-6.0],
        "cameo_roots_linked": [[19]],
        "codebook_types_linked": [["conflict.armed"]],
        "v21_date": [20260425120000],
        "tone_polarity": [8.4],
        "word_count": [599],
    })
    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    df.write_parquet(gkg_dir / "20260425120000.parquet")

    mock_client = MagicMock()
    mock_client.upsert = AsyncMock()
    embedder = AsyncMock(return_value=[0.1] * 1024)

    w = QdrantWriter(client=mock_client, embed=embedder, collection="test")
    n = await w.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")
    assert n == 1
    mock_client.upsert.assert_called_once()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_qdrant_writer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/writers/qdrant_writer.py
"""Qdrant writer — embeds GKG docs and upserts points.

Reads ONLY from GKG parquet. Independent of Neo4j state.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import polars as pl
import structlog
from qdrant_client.models import PointStruct

from gdelt_raw.ids import qdrant_point_id_for_doc

log = structlog.get_logger(__name__)


def build_embed_text(row: dict[str, Any]) -> str:
    title = row.get("title") or row.get("doc_id", "")
    themes = ", ".join(row.get("themes") or [])
    persons = ", ".join(row.get("persons") or [])
    orgs = ", ".join(row.get("organizations") or [])
    actors = (persons + (", " if persons and orgs else "") + orgs).strip(", ")
    return f"{title}\nThemes: {themes}\nActors: {actors}"[:1500]


def build_payload(row: dict[str, Any]) -> dict[str, Any]:
    gdelt_date_int = row.get("v21_date")
    if gdelt_date_int:
        gdelt_date_iso = datetime.strptime(str(gdelt_date_int), "%Y%m%d%H%M%S") \
                                  .replace(tzinfo=timezone.utc).isoformat()
    else:
        gdelt_date_iso = None

    return {
        "source": "gdelt_gkg",
        "doc_id": row["doc_id"],
        "url": row.get("url"),
        "source_name": row.get("v2_source_common_name"),
        "title": row.get("title") or row["doc_id"],
        "themes": row.get("themes") or [],
        "persons": row.get("persons") or [],
        "organizations": row.get("organizations") or [],
        "tone_polarity": row.get("tone_polarity") or 0.0,
        "linked_event_ids": row.get("linked_event_ids") or [],
        "goldstein_min": row.get("goldstein_min"),
        "goldstein_avg": row.get("goldstein_avg"),
        "cameo_roots_linked": row.get("cameo_roots_linked") or [],
        "codebook_types_linked": row.get("codebook_types_linked") or [],
        "gdelt_date": gdelt_date_iso,
        "published_at": row.get("published_at"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


async def default_tei_embed(text: str, tei_url: str, http_timeout: float = 30.0) -> list[float]:
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        resp = await client.post(f"{tei_url}/embed", json={"inputs": text})
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data[0], list) else data


class QdrantWriter:
    def __init__(self, client, embed: Callable[[str], Awaitable[list[float]]], collection: str):
        self._client = client
        self._embed = embed
        self._collection = collection

    async def upsert_from_parquet(
        self, parquet_base: Path, slice_id: str, date: str,
    ) -> int:
        path = Path(parquet_base) / "gkg" / f"date={date}" / f"{slice_id}.parquet"
        if not path.exists():
            return 0
        df = pl.read_parquet(path)
        points: list[PointStruct] = []
        for row in df.to_dicts():
            text = build_embed_text(row)
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            vector = await self._embed(text)
            payload = build_payload(row)
            payload["content_hash"] = content_hash
            points.append(PointStruct(
                id=qdrant_point_id_for_doc(row["doc_id"]),
                vector=vector,
                payload=payload,
            ))
        if points:
            await self._client.upsert(collection_name=self._collection, points=points)
        log.info("qdrant_written", slice=slice_id, count=len(points))
        return len(points)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_qdrant_writer.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/writers/qdrant_writer.py \
        services/data-ingestion/tests/test_gdelt_qdrant_writer.py
git commit -m "feat(gdelt): qdrant writer (parquet-only, neo4j-independent)"
```

---

## Task 15: Recovery flow (pending-replay from Parquet)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/recovery.py`
- Create: `services/data-ingestion/tests/test_gdelt_recovery.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_recovery.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import polars as pl
import pytest

from gdelt_raw.recovery import replay_pending
from gdelt_raw.state import GDELTState


@pytest.mark.asyncio
async def test_pending_store_replay_from_parquet(tmp_path):
    """Slice S was parquet-done but neo4j failed. Replay must succeed
    without re-downloading."""
    # Create parquet fixtures for slice 20260425120000 date=2026-04-25
    slice_id = "20260425120000"
    date = "2026-04-25"
    for stream, df in [
        ("events", pl.DataFrame({"event_id": ["gdelt:event:1"]})),
        ("gkg", pl.DataFrame({"doc_id": ["gdelt:gkg:r1"]})),
        ("mentions", pl.DataFrame({"event_id": ["gdelt:event:1"]})),
    ]:
        p = tmp_path / stream / f"date={date}"
        p.mkdir(parents=True)
        df.write_parquet(p / f"{slice_id}.parquet")

    # Setup state: parquet done, neo4j pending
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    for st in ("events", "gkg", "mentions"):
        await state.set_stream_parquet(slice_id, st, "done")
    await state.set_store_state(slice_id, "neo4j", "pending")
    await state.add_pending("neo4j", slice_id)

    neo4j = MagicMock()
    neo4j.write_from_parquet = AsyncMock()
    qdrant = MagicMock()
    qdrant.upsert_from_parquet = AsyncMock(return_value=0)

    await replay_pending(state, parquet_base=tmp_path, neo4j_writer=neo4j,
                        qdrant_writer=qdrant)

    neo4j.write_from_parquet.assert_awaited_once()
    assert await state.get_store_state(slice_id, "neo4j") == "done"
    assert slice_id not in await state.list_pending("neo4j")


@pytest.mark.asyncio
async def test_qdrant_recovery_independent_of_neo4j(tmp_path):
    """Qdrant can replay even if Neo4j is still pending."""
    slice_id = "20260425120000"
    date = "2026-04-25"
    p = tmp_path / "gkg" / f"date={date}"
    p.mkdir(parents=True)
    pl.DataFrame({"doc_id": ["gdelt:gkg:r1"]}).write_parquet(p / f"{slice_id}.parquet")

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await state.set_stream_parquet(slice_id, "gkg", "done")
    await state.set_store_state(slice_id, "qdrant", "pending_embed")
    await state.add_pending("qdrant", slice_id)
    # Leave neo4j unresolved on purpose

    neo4j = MagicMock(); neo4j.write_from_parquet = AsyncMock()
    qdrant = MagicMock()
    qdrant.upsert_from_parquet = AsyncMock(return_value=1)

    await replay_pending(state, parquet_base=tmp_path, neo4j_writer=neo4j,
                        qdrant_writer=qdrant)
    qdrant.upsert_from_parquet.assert_awaited_once()
    assert await state.get_store_state(slice_id, "qdrant") == "done"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_recovery.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# services/data-ingestion/gdelt_raw/recovery.py
"""Pending-replay: re-hydrate Neo4j and Qdrant from Parquet.

Neo4j and Qdrant replay independently — Qdrant never blocks on Neo4j.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from gdelt_raw.state import GDELTState

log = structlog.get_logger(__name__)


def _slice_date(slice_id: str) -> str:
    # 20260425120000 → 2026-04-25
    return f"{slice_id[0:4]}-{slice_id[4:6]}-{slice_id[6:8]}"


def _parquet_exists(parquet_base: Path, stream: str, slice_id: str) -> bool:
    p = parquet_base / stream / f"date={_slice_date(slice_id)}" / f"{slice_id}.parquet"
    return p.exists()


async def replay_pending(
    state: GDELTState,
    *,
    parquet_base: Path,
    neo4j_writer,
    qdrant_writer,
    limit: int = 10,
) -> None:
    # Neo4j recovery — needs all three parquet streams
    for slice_id in await state.list_pending("neo4j", limit=limit):
        if not all(_parquet_exists(parquet_base, s, slice_id)
                   for s in ("events", "gkg", "mentions")):
            log.info("neo4j_recovery_skipped_parquet_missing", slice=slice_id)
            continue
        try:
            await neo4j_writer.write_from_parquet(
                parquet_base, slice_id, _slice_date(slice_id))
            await state.set_store_state(slice_id, "neo4j", "done")
            await state.remove_pending("neo4j", slice_id)
            log.info("neo4j_recovery_done", slice=slice_id)
        except Exception as e:
            log.error("neo4j_recovery_retry_failed", slice=slice_id, error=str(e))

    # Qdrant recovery — needs only GKG parquet
    for slice_id in await state.list_pending("qdrant", limit=limit):
        if not _parquet_exists(parquet_base, "gkg", slice_id):
            log.info("qdrant_recovery_skipped_parquet_missing", slice=slice_id)
            continue
        try:
            await qdrant_writer.upsert_from_parquet(
                parquet_base, slice_id, _slice_date(slice_id))
            await state.set_store_state(slice_id, "qdrant", "done")
            await state.remove_pending("qdrant", slice_id)
            log.info("qdrant_recovery_done", slice=slice_id)
        except Exception as e:
            log.error("qdrant_recovery_retry_failed", slice=slice_id, error=str(e))
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_recovery.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/recovery.py \
        services/data-ingestion/tests/test_gdelt_recovery.py
git commit -m "feat(gdelt): recovery — replay pending from parquet, neo4j/qdrant independent"
```

---

## Task 16: Forward flow (run_forward)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/run.py`
- Create: `services/data-ingestion/tests/test_gdelt_forward.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_forward.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from gdelt_raw.run import run_forward_slice
from gdelt_raw.state import GDELTState
from gdelt_raw.downloader import LastUpdateEntry


@pytest.mark.asyncio
async def test_parquet_written_before_external_stores(tmp_path, monkeypatch):
    """Order invariant: parquet-state done before neo4j/qdrant are even called."""
    call_log: list[str] = []

    # Mocks
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)

    async def fake_download(entry, out_dir):
        f = out_dir / entry.url.rsplit("/", 1)[-1]
        f.write_bytes(b"x")
        return f

    # Stub the pipeline pieces
    neo4j = MagicMock(); neo4j.write_from_parquet = AsyncMock(
        side_effect=lambda *a, **k: call_log.append("neo4j"))
    qdrant = MagicMock(); qdrant.upsert_from_parquet = AsyncMock(
        side_effect=lambda *a, **k: call_log.append("qdrant") or 0)

    with patch("gdelt_raw.run.download_slice", side_effect=fake_download), \
         patch("gdelt_raw.run._extract_and_parse", new=AsyncMock(return_value=MagicMock(
            events_df=MagicMock(), mentions_df=MagicMock(), gkg_df=MagicMock(),
            stream_states={"events":"done","mentions":"done","gkg":"done"},
         ))), \
         patch("gdelt_raw.run._filter_and_write_parquet", new=AsyncMock(
            side_effect=lambda *a, **k: call_log.append("parquet"))):

        entries = [
            LastUpdateEntry(0, "m", "http://x/y.export.CSV.zip", "events", "20260425120000"),
            LastUpdateEntry(0, "m", "http://x/y.mentions.CSV.zip", "mentions", "20260425120000"),
            LastUpdateEntry(0, "m", "http://x/y.gkg.csv.zip", "gkg", "20260425120000"),
        ]
        await run_forward_slice(
            entries, state=state, parquet_base=tmp_path,
            neo4j_writer=neo4j, qdrant_writer=qdrant, tmp_dir=tmp_path / "work",
        )

    assert call_log.index("parquet") < call_log.index("neo4j")
    assert call_log.index("parquet") < call_log.index("qdrant")


@pytest.mark.asyncio
async def test_store_state_not_advanced_on_failure(tmp_path, monkeypatch):
    """If Neo4j raises, neo4j state must stay 'failed:*' and NOT advance
    last_slice:neo4j. Parquet last_slice must still advance (truth-layer)."""
    import fakeredis.aioredis
    from gdelt_raw.run import run_forward_slice
    from gdelt_raw.state import GDELTState
    from gdelt_raw.downloader import LastUpdateEntry

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)

    # Stub download + parse + filter — mark parquet streams as done
    async def fake_download(entry, out_dir, **kwargs):
        f = out_dir / entry.url.rsplit("/", 1)[-1]
        f.write_bytes(b"z")
        return f

    async def fake_extract(entries, work):
        from gdelt_raw.run import ParsedSlice
        import polars as pl
        return ParsedSlice(
            events_df=pl.DataFrame({"global_event_id": []}),
            mentions_df=pl.DataFrame({"global_event_id": []}),
            gkg_df=pl.DataFrame({"gkg_record_id": []}),
            stream_states={"events": "done", "mentions": "done", "gkg": "done"},
        )

    async def fake_filter_write(parsed, slice_id, *, state, parquet_base):
        for st in ("events", "mentions", "gkg"):
            await state.set_stream_parquet(slice_id, st, "done")
        return None

    monkeypatch.setattr("gdelt_raw.run.download_slice", fake_download)
    monkeypatch.setattr("gdelt_raw.run._extract_and_parse", fake_extract)
    monkeypatch.setattr("gdelt_raw.run._filter_and_write_parquet", fake_filter_write)

    # Neo4j writer that raises, Qdrant writer that succeeds
    from unittest.mock import MagicMock, AsyncMock
    neo4j = MagicMock()
    neo4j.write_from_parquet = AsyncMock(side_effect=RuntimeError("boom"))
    qdrant = MagicMock()
    qdrant.upsert_from_parquet = AsyncMock(return_value=0)

    entries = [
        LastUpdateEntry(0, "m", "http://x/y.export.CSV.zip", "events", "20260425120000"),
        LastUpdateEntry(0, "m", "http://x/y.mentions.CSV.zip", "mentions", "20260425120000"),
        LastUpdateEntry(0, "m", "http://x/y.gkg.csv.zip", "gkg", "20260425120000"),
    ]
    await run_forward_slice(
        entries, state=state, parquet_base=tmp_path,
        neo4j_writer=neo4j, qdrant_writer=qdrant, tmp_dir=tmp_path / "work",
    )

    # Neo4j failed — state reflects it, last_slice:neo4j NOT advanced
    n_state = await state.get_store_state("20260425120000", "neo4j")
    assert n_state and n_state.startswith("failed")
    assert "20260425120000" in await state.list_pending("neo4j")
    assert await state.get_last_slice("neo4j") is None

    # Qdrant succeeded — independent of Neo4j
    assert await state.get_store_state("20260425120000", "qdrant") == "done"
    assert await state.get_last_slice("qdrant") == "20260425120000"

    # Parquet last_slice DID advance — truth layer moves forward
    assert await state.get_last_slice("parquet") == "20260425120000"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_forward.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `run_forward`**

```python
# services/data-ingestion/gdelt_raw/run.py
"""Forward and backfill orchestration for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import structlog

from gdelt_raw.config import get_settings
from gdelt_raw.downloader import (
    LastUpdateEntry, download_slice, fetch_lastupdate,
)
from gdelt_raw.filter import apply_filters, FilterResult
from gdelt_raw.parser import parse_events, parse_mentions, parse_gkg
from gdelt_raw.recovery import replay_pending
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.parquet_writer import write_stream_parquet

log = structlog.get_logger(__name__)


@dataclass
class ParsedSlice:
    events_df: pl.DataFrame
    mentions_df: pl.DataFrame
    gkg_df: pl.DataFrame
    stream_states: dict[str, str]   # "done" | "failed"


def _slice_date(slice_id: str) -> str:
    return f"{slice_id[0:4]}-{slice_id[4:6]}-{slice_id[6:8]}"


async def _extract_and_parse(
    entries: list[LastUpdateEntry], tmp_dir: Path,
    *, verify_md5: bool = True,
) -> ParsedSlice:
    settings = get_settings()
    downloads = await asyncio.gather(*[
        download_slice(e, tmp_dir, verify_md5=verify_md5) for e in entries
    ])
    extracted: dict[str, Path] = {}
    for entry, zpath in zip(entries, downloads):
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp_dir)
            names = z.namelist()
            extracted[entry.stream] = tmp_dir / names[0]

    stream_states = {}
    quarantine = tmp_dir / "quarantine"
    ev_res = parse_events(extracted["events"], quarantine_dir=quarantine)
    me_res = parse_mentions(extracted["mentions"], quarantine_dir=quarantine)
    gk_res = parse_gkg(extracted["gkg"], quarantine_dir=quarantine)
    for name, res in [("events", ev_res), ("mentions", me_res), ("gkg", gk_res)]:
        stream_states[name] = (
            "failed" if res.parse_error_pct > settings.max_parse_error_pct else "done"
        )

    return ParsedSlice(
        events_df=ev_res.df, mentions_df=me_res.df, gkg_df=gk_res.df,
        stream_states=stream_states,
    )


async def _filter_and_write_parquet(
    parsed: ParsedSlice, slice_id: str, *,
    state: GDELTState, parquet_base: Path,
) -> FilterResult | None:
    from gdelt_raw.transform import (
        canonicalize_events, canonicalize_gkg, canonicalize_mentions,
    )
    settings = get_settings()
    fr = apply_filters(
        parsed.events_df, parsed.mentions_df, parsed.gkg_df,
        cameo_roots=settings.cameo_root_allowlist,
        theme_alpha=settings.theme_allowlist,
        theme_nuclear_override=settings.nuclear_override_themes,
    )
    # Canonicalize BEFORE persisting — parquet holds writer-schema directly.
    canonical = {
        "events": canonicalize_events(fr.events) if parsed.stream_states["events"] == "done"
                  else None,
        "gkg": canonicalize_gkg(fr.gkg) if parsed.stream_states["gkg"] == "done"
               else None,
        "mentions": canonicalize_mentions(fr.mentions) if parsed.stream_states["mentions"] == "done"
                    else None,
    }
    date = _slice_date(slice_id)
    for stream, df in canonical.items():
        if df is None:
            await state.set_stream_parquet(slice_id, stream, "failed")
            continue
        write_stream_parquet(df, base_path=parquet_base, stream=stream,
                             date=date, slice_id=slice_id)
        await state.set_stream_parquet(slice_id, stream, "done")
    return fr


async def run_forward_slice(
    entries: list[LastUpdateEntry],
    *,
    state: GDELTState,
    parquet_base: Path,
    neo4j_writer,
    qdrant_writer,
    tmp_dir: Path,
    verify_md5: bool = True,
) -> None:
    slice_id = entries[0].slice_id
    date = _slice_date(slice_id)
    log.info("gdelt_forward_start", slice=slice_id, verify_md5=verify_md5)

    work = tmp_dir / slice_id
    work.mkdir(parents=True, exist_ok=True)

    parsed = await _extract_and_parse(entries, work, verify_md5=verify_md5)
    await _filter_and_write_parquet(parsed, slice_id, state=state,
                                    parquet_base=parquet_base)

    # Advance parquet last_slice as soon as ALL 3 streams are persisted.
    # Truth-layer progress is INDEPENDENT of Neo4j/Qdrant outcomes — otherwise
    # a down Qdrant would cause forward() to re-download the same slice forever.
    all_parquet_done = all(
        await state.get_stream_parquet(slice_id, s) == "done"
        for s in ("events", "mentions", "gkg")
    )
    if all_parquet_done:
        await state.set_last_slice("parquet", slice_id)

    # Neo4j
    try:
        await neo4j_writer.write_from_parquet(parquet_base, slice_id, date)
        await state.set_store_state(slice_id, "neo4j", "done")
        await state.set_last_slice("neo4j", slice_id)
    except Exception as e:
        log.error("gdelt_neo4j_write_failed", slice=slice_id, error=str(e))
        await state.set_store_state(slice_id, "neo4j", f"failed:{e}")
        await state.add_pending("neo4j", slice_id)

    # Qdrant — INDEPENDENT of Neo4j outcome
    try:
        await qdrant_writer.upsert_from_parquet(parquet_base, slice_id, date)
        await state.set_store_state(slice_id, "qdrant", "done")
        await state.set_last_slice("qdrant", slice_id)
    except Exception as e:
        log.error("gdelt_qdrant_write_failed", slice=slice_id, error=str(e))
        await state.set_store_state(slice_id, "qdrant", "pending_embed")
        await state.add_pending("qdrant", slice_id)

    log.info("gdelt_forward_done", slice=slice_id)


async def run_forward(state: GDELTState, neo4j_writer, qdrant_writer,
                     parquet_base: Path) -> None:
    """Entry point called by scheduler."""
    await replay_pending(state, parquet_base=parquet_base,
                         neo4j_writer=neo4j_writer, qdrant_writer=qdrant_writer)

    entries = await fetch_lastupdate()
    by_slice: dict[str, list[LastUpdateEntry]] = {}
    for e in entries:
        by_slice.setdefault(e.slice_id, []).append(e)

    latest_slice = max(by_slice.keys())
    last_done = await state.get_last_slice("parquet")
    if last_done == latest_slice:
        log.info("gdelt_no_new_slice", latest=latest_slice)
        return

    with tempfile.TemporaryDirectory() as tmp:
        await run_forward_slice(
            by_slice[latest_slice],
            state=state, parquet_base=parquet_base,
            neo4j_writer=neo4j_writer, qdrant_writer=qdrant_writer,
            tmp_dir=Path(tmp),
        )
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_forward.py -v`
Expected: 2 passed (one is a pass-through placeholder)

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/run.py \
        services/data-ingestion/tests/test_gdelt_forward.py
git commit -m "feat(gdelt): run_forward — parquet-first, neo4j/qdrant independent"
```

---

## Task 17: Backfill flow (resumable, parallel)

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/run.py` (add `run_backfill`)
- Create: `services/data-ingestion/tests/test_gdelt_backfill.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_backfill.py
from datetime import datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from gdelt_raw.run import (
    enumerate_slices_for_range, BackfillJob, initialize_backfill,
    mark_slice_done, mark_slice_failed,
)
from gdelt_raw.state import GDELTState


def test_enumerate_slices_full_day():
    slices = list(enumerate_slices_for_range(
        datetime(2026, 4, 25), datetime(2026, 4, 25, 23, 45)
    ))
    assert slices[0] == "20260425000000"
    assert slices[-1] == "20260425234500"
    assert len(slices) == 96


def test_enumerate_slices_partial():
    slices = list(enumerate_slices_for_range(
        datetime(2026, 4, 25, 0, 0), datetime(2026, 4, 25, 1, 0)
    ))
    assert slices == [
        "20260425000000", "20260425001500", "20260425003000",
        "20260425004500", "20260425010000",
    ]


def test_enumerate_slices_31_days():
    slices = list(enumerate_slices_for_range(
        datetime(2026, 3, 26), datetime(2026, 4, 25, 23, 45)
    ))
    assert len(slices) == 31 * 96


@pytest.mark.asyncio
async def test_backfill_initializes_pending_set():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    job = await initialize_backfill(
        state, job_id="job-a",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 1, 0),
    )
    assert job.job_id == "job-a"
    assert job.total == 5
    pending = await r.zrange("gdelt:backfill:job-a:pending", 0, -1)
    assert len(pending) == 5


@pytest.mark.asyncio
async def test_backfill_marks_slice_done_removes_from_pending():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await initialize_backfill(
        state, job_id="job-b",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 0, 0),
    )
    await mark_slice_done(state, "job-b", "20260425000000")
    pending = await r.zrange("gdelt:backfill:job-b:pending", 0, -1)
    done = await r.smembers("gdelt:backfill:job-b:done")
    assert pending == []
    assert done == {"20260425000000"}


@pytest.mark.asyncio
async def test_backfill_failed_slice_is_retryable():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await initialize_backfill(
        state, job_id="job-c",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 0, 0),
    )
    await mark_slice_failed(state, "job-c", "20260425000000", reason="boom")
    # Failed slices move to :failed AND remain re-enqueueable via resume
    failed = await r.smembers("gdelt:backfill:job-c:failed")
    assert "20260425000000" in failed


@pytest.mark.asyncio
async def test_resume_reenqueues_failed_slices():
    from gdelt_raw.run import resume_backfill_pending
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)
    await initialize_backfill(
        state, job_id="job-d",
        start=datetime(2026, 4, 25, 0, 0),
        end=datetime(2026, 4, 25, 0, 30),
    )
    await mark_slice_done(state, "job-d", "20260425000000")
    await mark_slice_failed(state, "job-d", "20260425001500", reason="net")
    # Pending now contains only 20260425003000
    await resume_backfill_pending(state, "job-d")
    # After resume, failed is empty and pending contains the retry
    pending = await r.zrange("gdelt:backfill:job-d:pending", 0, -1)
    assert "20260425001500" in pending
    assert await r.smembers("gdelt:backfill:job-d:failed") == set()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_backfill.py -v`
Expected: FAIL

- [ ] **Step 3: Add backfill machinery to run.py**

Append to `services/data-ingestion/gdelt_raw/run.py`:
```python
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Iterator


def enumerate_slices_for_range(start: datetime, end: datetime) -> Iterator[str]:
    """Yield slice_ids at 15-min steps, inclusive of both endpoints (aligned to :00,:15,:30,:45)."""
    start = start.replace(minute=(start.minute // 15) * 15, second=0, microsecond=0)
    cur = start
    while cur <= end:
        yield cur.strftime("%Y%m%d%H%M%S")
        cur = cur + timedelta(minutes=15)


@dataclass
class BackfillJob:
    job_id: str
    total: int


def _bf_key(job_id: str, suffix: str) -> str:
    return f"gdelt:backfill:{job_id}:{suffix}"


async def initialize_backfill(
    state: GDELTState, *, job_id: str, start: datetime, end: datetime,
) -> BackfillJob:
    """Idempotent: re-running only adds slices not already done/failed/pending."""
    slice_ids = list(enumerate_slices_for_range(start, end))
    done = await state.r.smembers(_bf_key(job_id, "done"))
    failed = await state.r.smembers(_bf_key(job_id, "failed"))
    # Pending = slice_ids − done − failed (failed stays until resume)
    to_enqueue = [s for s in slice_ids if s not in done and s not in failed]
    if to_enqueue:
        await state.r.zadd(
            _bf_key(job_id, "pending"),
            {s: int(s) for s in to_enqueue},
        )
    await state.r.set(_bf_key(job_id, "state"), "running")
    await state.r.set(_bf_key(job_id, "total"), str(len(slice_ids)))
    return BackfillJob(job_id=job_id, total=len(slice_ids))


async def pop_next_pending(state: GDELTState, job_id: str) -> str | None:
    """ZPOPMIN (single-slice atomic pop) — returns slice_id or None if empty."""
    res = await state.r.zpopmin(_bf_key(job_id, "pending"), 1)
    if not res:
        return None
    slice_id, _ = res[0]
    return slice_id


async def mark_slice_done(state: GDELTState, job_id: str, slice_id: str) -> None:
    await state.r.srem(_bf_key(job_id, "failed"), slice_id)
    await state.r.zrem(_bf_key(job_id, "pending"), slice_id)
    await state.r.sadd(_bf_key(job_id, "done"), slice_id)


async def mark_slice_failed(
    state: GDELTState, job_id: str, slice_id: str, reason: str,
) -> None:
    await state.r.zrem(_bf_key(job_id, "pending"), slice_id)
    await state.r.sadd(_bf_key(job_id, "failed"), slice_id)
    await state.r.set(_bf_key(job_id, f"failed:{slice_id}:reason"), reason)


async def resume_backfill_pending(state: GDELTState, job_id: str) -> int:
    """Move all failed slices back into pending; returns re-enqueued count."""
    failed = await state.r.smembers(_bf_key(job_id, "failed"))
    if failed:
        await state.r.zadd(
            _bf_key(job_id, "pending"),
            {s: int(s) for s in failed},
        )
        await state.r.delete(_bf_key(job_id, "failed"))
    return len(failed)


async def run_backfill(
    start: datetime, end: datetime, *,
    state: GDELTState, neo4j_writer, qdrant_writer,
    parquet_base: Path, job_id: str, parallel: int = 4,
) -> None:
    """Backfill a date range. Resumable: pending/done/failed sets in Redis."""
    job = await initialize_backfill(state, job_id=job_id, start=start, end=end)
    log.info("gdelt_backfill_start", job_id=job_id, total=job.total)

    sem = asyncio.Semaphore(parallel)
    settings = get_settings()

    async def _worker():
        while True:
            sid = await pop_next_pending(state, job_id)
            if sid is None:
                return
            # Skip if already complete (fully-done predicate covers re-runs)
            if await state.is_slice_fully_done(sid):
                await mark_slice_done(state, job_id, sid)
                continue
            async with sem:
                entries = [
                    LastUpdateEntry(0, "",
                        f"{settings.base_url}/{sid}.export.CSV.zip", "events", sid),
                    LastUpdateEntry(0, "",
                        f"{settings.base_url}/{sid}.mentions.CSV.zip", "mentions", sid),
                    LastUpdateEntry(0, "",
                        f"{settings.base_url}/{sid}.gkg.csv.zip", "gkg", sid),
                ]
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        # Historical slices: no lastupdate → no MD5 → verify_md5=False
                        # (run_forward_slice honors this via download_slice's param)
                        await run_forward_slice(
                            entries, state=state, parquet_base=parquet_base,
                            neo4j_writer=neo4j_writer, qdrant_writer=qdrant_writer,
                            tmp_dir=Path(tmp), verify_md5=False,
                        )
                        await mark_slice_done(state, job_id, sid)
                    except Exception as e:
                        log.error("backfill_slice_failed", slice=sid, error=str(e))
                        await mark_slice_failed(state, job_id, sid, reason=str(e))

    await asyncio.gather(*[_worker() for _ in range(parallel)])
    await state.r.set(_bf_key(job_id, "state"), "done")
    log.info("gdelt_backfill_done", job_id=job_id)
```

**Also update `run_forward_slice` signature and `download_slice` call** in the same file to accept `verify_md5`:

```python
# In run_forward_slice signature, add: verify_md5: bool = True
async def run_forward_slice(
    entries: list[LastUpdateEntry],
    *,
    state: GDELTState,
    parquet_base: Path,
    neo4j_writer,
    qdrant_writer,
    tmp_dir: Path,
    verify_md5: bool = True,          # NEW — passed to downloader
) -> None:
    ...

# In _extract_and_parse, update download_slice calls:
# downloads = await asyncio.gather(*[
#     download_slice(e, tmp_dir, verify_md5=verify_md5) for e in entries
# ])
# (pass verify_md5 through the call chain — simplest: thread it through
#  _extract_and_parse signature too)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_backfill.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/run.py \
        services/data-ingestion/tests/test_gdelt_backfill.py
git commit -m "feat(gdelt): backfill — resumable, parallel-N slices"
```

---

## Task 18: Constraint migration (Phase 1 + preflight)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/migrations/__init__.py` (empty)
- Create: `services/data-ingestion/gdelt_raw/migrations/phase1_constraints.cypher`
- Create: `services/data-ingestion/gdelt_raw/migrations/apply.py`
- Create: `services/data-ingestion/tests/test_gdelt_migrations.py`

- [ ] **Step 1: Write failing tests**

```python
# services/data-ingestion/tests/test_gdelt_migrations.py
from gdelt_raw.migrations.apply import (
    read_cypher_file, SOURCE_DUP_PREFLIGHT_QUERY,
)


def test_phase1_file_contains_expected_constraints():
    text = read_cypher_file("phase1_constraints.cypher")
    assert "gdelt_event_id_unique" in text
    assert "gdelt_doc_id_unique" in text
    assert "source_name_unique" in text
    assert "theme_code_unique" in text
    assert "GDELTEvent" in text
    assert "GDELTDocument" in text


def test_phase2_file_contains_indexes():
    text = read_cypher_file("phase2_indexes.cypher")
    assert "event_source_date" in text
    assert "event_cameo_root" in text
    assert "location_geo" in text


def test_source_preflight_query_is_parameterless():
    assert "name, count" in SOURCE_DUP_PREFLIGHT_QUERY or \
           "count(*)" in SOURCE_DUP_PREFLIGHT_QUERY
```

- [ ] **Step 2: Create Cypher files**

```
-- services/data-ingestion/gdelt_raw/migrations/phase1_constraints.cypher
CREATE CONSTRAINT gdelt_event_id_unique IF NOT EXISTS
  FOR (e:GDELTEvent) REQUIRE e.event_id IS UNIQUE;

CREATE CONSTRAINT gdelt_doc_id_unique IF NOT EXISTS
  FOR (d:GDELTDocument) REQUIRE d.doc_id IS UNIQUE;

CREATE CONSTRAINT source_name_unique IF NOT EXISTS
  FOR (s:Source) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT theme_code_unique IF NOT EXISTS
  FOR (t:Theme) REQUIRE t.theme_code IS UNIQUE;
```

```
-- services/data-ingestion/gdelt_raw/migrations/phase2_indexes.cypher
CREATE INDEX event_source_date IF NOT EXISTS
  FOR (e:Event) ON (e.source, e.date_added);
CREATE INDEX event_cameo_root IF NOT EXISTS
  FOR (e:Event) ON (e.cameo_root);
CREATE INDEX event_codebook_type IF NOT EXISTS
  FOR (e:Event) ON (e.codebook_type);
CREATE INDEX doc_source_gdelt_date IF NOT EXISTS
  FOR (d:Document) ON (d.source, d.gdelt_date);
CREATE INDEX doc_url IF NOT EXISTS
  FOR (d:Document) ON (d.url);
CREATE INDEX entity_name_type IF NOT EXISTS
  FOR (e:Entity) ON (e.normalized_name, e.type);
CREATE POINT INDEX location_geo IF NOT EXISTS
  FOR (l:Location) ON (l.geo);
```

- [ ] **Step 3: Implement apply.py**

```python
# services/data-ingestion/gdelt_raw/migrations/__init__.py
"""GDELT migration helpers."""
```

```python
# services/data-ingestion/gdelt_raw/migrations/apply.py
"""Apply GDELT schema migrations with Source-duplicate preflight."""

from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent

SOURCE_DUP_PREFLIGHT_QUERY = """
MATCH (s:Source)
WITH s.name AS name, count(*) AS c
WHERE name IS NOT NULL AND c > 1
RETURN name, c ORDER BY c DESC
"""


def read_cypher_file(name: str) -> str:
    return (MIGRATIONS_DIR / name).read_text()


async def check_source_duplicates(driver) -> list[tuple[str, int]]:
    async with driver.session() as session:
        result = await session.run(SOURCE_DUP_PREFLIGHT_QUERY)
        rows = [(r["name"], r["c"]) async for r in result]
    return rows


async def apply_phase1(driver) -> None:
    """Apply scoped constraints. Aborts if :Source has duplicates."""
    dups = await check_source_duplicates(driver)
    if dups:
        raise RuntimeError(
            f"Cannot apply source_name_unique — {len(dups)} duplicates found: {dups[:5]}"
        )
    statements = [
        s.strip() for s in read_cypher_file("phase1_constraints.cypher").split(";")
        if s.strip()
    ]
    async with driver.session() as session:
        for stmt in statements:
            await session.run(stmt)
            log.info("migration_applied", stmt=stmt[:60])


async def apply_phase2(driver) -> None:
    statements = [
        s.strip() for s in read_cypher_file("phase2_indexes.cypher").split(";")
        if s.strip()
    ]
    async with driver.session() as session:
        for stmt in statements:
            await session.run(stmt)
            log.info("index_applied", stmt=stmt[:60])
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_migrations.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/migrations/ \
        services/data-ingestion/tests/test_gdelt_migrations.py
git commit -m "feat(gdelt): migration files (phase1 constraints, phase2 indexes)"
```

---

## Task 19: CLI (status / forward / backfill / resume / doctor)

**Files:**
- Create: `services/data-ingestion/gdelt_raw/cli.py`
- Create: `services/data-ingestion/tests/test_gdelt_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# services/data-ingestion/tests/test_gdelt_cli.py
from click.testing import CliRunner

from gdelt_raw.cli import main


def test_cli_help():
    runner = CliRunner()
    res = runner.invoke(main, ["--help"])
    assert res.exit_code == 0
    assert "status" in res.output
    assert "forward" in res.output
    assert "backfill" in res.output
    assert "resume" in res.output
    assert "doctor" in res.output


def test_cli_backfill_requires_from_flag():
    runner = CliRunner()
    res = runner.invoke(main, ["backfill"])
    assert res.exit_code != 0
    assert "--from" in res.output or "Missing" in res.output


def test_cli_config_dumps_settings():
    runner = CliRunner()
    res = runner.invoke(main, ["config"])
    assert res.exit_code == 0
    assert "base_url" in res.output or "BASE_URL" in res.output
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CLI**

```python
# services/data-ingestion/gdelt_raw/cli.py
"""click-based CLI for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import click

from gdelt_raw.config import get_settings


def _run(coro):
    return asyncio.run(coro)


@click.group()
def main():
    """GDELT raw-files ingestion CLI."""


@main.command()
def status():
    """Show last processed slice per store, pending counts, today's totals."""
    settings = get_settings()
    click.echo(f"Config mode: {settings.filter_mode}")
    click.echo(f"CAMEO allowlist: {settings.cameo_root_allowlist}")
    click.echo("(full implementation wires Redis client via get_redis)")


@main.command()
def forward():
    """Run a single forward tick (useful for debugging)."""
    click.echo("forward tick (wires via get_clients and run_forward) — stub")


@main.command()
@click.option("--from", "from_date", required=True,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Backfill start (inclusive), format YYYY-MM-DD")
@click.option("--to", "to_date", default=None,
              type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Backfill end (inclusive), default=yesterday UTC")
def backfill(from_date: datetime, to_date: datetime | None):
    """Historical backfill for a date range."""
    to_date = to_date or (datetime.utcnow() - timedelta(days=1))
    job_id = f"backfill-{datetime.utcnow().strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:4]}"
    click.echo(f"Job: {job_id}  {from_date:%Y-%m-%d} → {to_date:%Y-%m-%d}")
    click.echo("(full implementation awaits get_clients + run_backfill wiring)")


@main.command()
@click.argument("job_id")
def resume(job_id: str):
    """Resume a backfill job."""
    click.echo(f"Resume job: {job_id}")


@main.command()
def doctor():
    """Health-check GDELT CDN, Neo4j, Qdrant, TEI, Parquet volume."""
    click.echo("doctor checks (wires via httpx/neo4j/qdrant clients) — stub")


@main.command()
def config():
    """Dump current settings."""
    settings = get_settings()
    click.echo(json.dumps(settings.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_cli.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/gdelt_raw/cli.py \
        services/data-ingestion/tests/test_gdelt_cli.py
git commit -m "feat(gdelt): click CLI skeleton (status/forward/backfill/resume/doctor/config)"
```

---

## Task 20: Wire CLI to real runtime (forward + backfill + doctor full impl)

**Files:**
- Modify: `services/data-ingestion/gdelt_raw/cli.py` — replace stubs with real wiring

- [ ] **Step 1: Implement get_clients helper**

Append to `services/data-ingestion/gdelt_raw/cli.py`:
```python
import os

import httpx
import redis.asyncio as aioredis
from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient

from gdelt_raw.recovery import replay_pending
from gdelt_raw.run import run_forward, run_backfill
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import QdrantWriter, default_tei_embed


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


async def _get_clients():
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                          decode_responses=True)
    state = GDELTState(r)
    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    qdrant_client = AsyncQdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")

    async def embed(text: str) -> list[float]:
        return await default_tei_embed(text, tei_url=tei_url)

    qdrant = QdrantWriter(
        client=qdrant_client, embed=embed,
        collection=os.getenv("QDRANT_COLLECTION", "odin_intel"),
    )
    return state, neo4j, qdrant
```

Replace `forward` stub:
```python
@main.command()
def forward():
    """Run a single forward tick."""
    async def _go():
        settings = get_settings()
        state, neo4j, qdrant = await _get_clients()
        try:
            await run_forward(state, neo4j, qdrant, Path(settings.parquet_path))
        finally:
            await neo4j.close()
    _run(_go())
    click.echo("forward tick complete")
```

Replace `backfill` stub:
```python
@main.command()
@click.option("--from", "from_date", required=True,
              type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--to", "to_date", default=None,
              type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--parallel", default=4, type=int)
def backfill(from_date: datetime, to_date: datetime | None, parallel: int):
    """Historical backfill."""
    to_date = to_date or (datetime.utcnow() - timedelta(days=1))
    job_id = f"backfill-{datetime.utcnow().strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:4]}"
    click.echo(f"Job: {job_id}  {from_date:%Y-%m-%d} → {to_date:%Y-%m-%d}")

    async def _go():
        settings = get_settings()
        state, neo4j, qdrant = await _get_clients()
        try:
            await run_backfill(
                from_date, to_date,
                state=state, neo4j_writer=neo4j, qdrant_writer=qdrant,
                parquet_base=Path(settings.parquet_path),
                job_id=job_id, parallel=parallel,
            )
        finally:
            await neo4j.close()
    _run(_go())
```

Replace `doctor`:
```python
@main.command()
def doctor():
    """Health-check all dependencies."""
    async def _check():
        settings = get_settings()
        errors = []
        state = neo4j = qdrant = None

        # GDELT CDN
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{settings.base_url}/lastupdate.txt")
                r.raise_for_status()
            click.echo("GDELT CDN:       ✓")
        except Exception as e:
            click.echo(f"GDELT CDN:       ✗ {e}"); errors.append("gdelt")

        # Parquet volume
        path = Path(settings.parquet_path)
        if path.exists() and os.access(path, os.W_OK):
            click.echo(f"Parquet volume:  ✓ {path} (writable)")
        else:
            click.echo(f"Parquet volume:  ✗ {path} missing/not-writable")
            errors.append("parquet")

        # Redis
        try:
            state, neo4j, qdrant = await _get_clients()
            await state.r.ping()
            click.echo("Redis:           ✓")
        except Exception as e:
            click.echo(f"Redis:           ✗ {e}"); errors.append("redis")

        # Neo4j
        try:
            async with neo4j._driver.session() as s:
                await s.run("RETURN 1")
            click.echo("Neo4j:           ✓")
        except Exception as e:
            click.echo(f"Neo4j:           ✗ {e}"); errors.append("neo4j")

        # Qdrant — real call, not just assume
        try:
            cols = await qdrant._client.get_collections()
            names = [c.name for c in cols.collections]
            click.echo(f"Qdrant:          ✓ collections={names}")
        except Exception as e:
            click.echo(f"Qdrant:          ✗ {e}"); errors.append("qdrant")

        # TEI — send a tiny embedding to confirm the dim
        try:
            tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{tei_url}/embed", json={"inputs": "health"})
                r.raise_for_status()
                data = r.json()
                vec = data[0] if isinstance(data[0], list) else data
                click.echo(f"TEI:             ✓ dim={len(vec)}")
        except Exception as e:
            click.echo(f"TEI:             ✗ {e}"); errors.append("tei")

        try:
            if neo4j is not None:
                await neo4j.close()
        except Exception:
            pass

        # Filter config summary (quick sanity check)
        click.echo(f"Filter mode:     {settings.filter_mode}")
        click.echo(f"CAMEO roots:     {settings.cameo_root_allowlist}")
        click.echo(f"Themes: α={len(settings.theme_allowlist)} "
                   f"nuclear={len(settings.nuclear_override_themes)}")

        if errors:
            raise SystemExit(1)

    _run(_check())
```

Replace `status`:
```python
@main.command()
def status():
    """Show last processed slice and pending counts."""
    async def _go():
        state, neo4j, _ = await _get_clients()
        try:
            for store in ("parquet", "neo4j", "qdrant"):
                last = await state.get_last_slice(store)
                click.echo(f"last_slice[{store:>7}]: {last}")
            for store in ("neo4j", "qdrant"):
                pending = await state.list_pending(store, limit=100)
                click.echo(f"pending[{store:>6}]: {len(pending)}")
        finally:
            await neo4j.close()
    _run(_go())
```

- [ ] **Step 2: Re-run CLI tests (all pass, no regressions)**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_cli.py -v`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add services/data-ingestion/gdelt_raw/cli.py
git commit -m "feat(gdelt): wire CLI to real runtime (forward, backfill, doctor, status)"
```

---

## Task 21: Scheduler wrapper + integration into existing scheduler.py

**Files:**
- Create: `services/data-ingestion/feeds/gdelt_raw_collector.py`
- Modify: `services/data-ingestion/scheduler.py`
- Modify: `odin.sh`

- [ ] **Step 1: Thin collector wrapper**

```python
# services/data-ingestion/feeds/gdelt_raw_collector.py
"""Thin scheduler wrapper — delegates to gdelt_raw.run.run_forward."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import redis.asyncio as aioredis
import structlog
from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient

from gdelt_raw.config import get_settings
from gdelt_raw.run import run_forward
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import QdrantWriter, default_tei_embed

log = structlog.get_logger(__name__)


async def run_once() -> None:
    settings = get_settings()
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                          decode_responses=True)
    state = GDELTState(r)
    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    qdrant_client = AsyncQdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    tei_url = os.getenv("TEI_EMBED_URL", "http://localhost:8001")

    async def embed(text: str) -> list[float]:
        return await default_tei_embed(text, tei_url=tei_url)

    qdrant = QdrantWriter(
        client=qdrant_client, embed=embed,
        collection=os.getenv("QDRANT_COLLECTION", "odin_intel"),
    )
    try:
        await run_forward(state, neo4j, qdrant, Path(settings.parquet_path))
    finally:
        await neo4j.close()


def collect() -> None:
    """Sync entry-point for APScheduler."""
    asyncio.run(run_once())
```

- [ ] **Step 2: Register in scheduler.py**

Modify `services/data-ingestion/scheduler.py` — add (near existing collectors):
```python
from feeds.gdelt_raw_collector import collect as gdelt_raw_collect

scheduler.add_job(
    gdelt_raw_collect,
    "interval",
    seconds=int(os.getenv("GDELT_FORWARD_INTERVAL_SECONDS", 900)),
    id="gdelt_raw_forward",
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.now() + timedelta(seconds=30),
)
```

- [ ] **Step 3: Add odin.sh subcommand**

Modify `odin.sh` — near the other subcommands add:
```bash
gdelt)
  shift
  docker exec osint-data-ingestion odin-ingest-gdelt "$@"
  ;;
```

- [ ] **Step 4: Commit**

```bash
git add services/data-ingestion/feeds/gdelt_raw_collector.py \
        services/data-ingestion/scheduler.py \
        odin.sh
git commit -m "feat(gdelt): scheduler integration + odin.sh gdelt subcommand"
```

---

## Task 22: Docker compose + volume + env

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add volume + mount + env**

Modify `docker-compose.yml`. **Rule:** only pass through env vars that we *want* to override container defaults. Don't pass `GDELT_THEME_ALLOWLIST` raw — if the outer shell doesn't have it set, Compose resolves to empty string and silently filters everything out.

```yaml
# Under data-ingestion service:
  data-ingestion:
    volumes:
      - gdelt_parquet:/data/gdelt     # ADD
      # ... existing mounts
    environment:
      # Always-set (come from .env):
      - GDELT_BASE_URL=${GDELT_BASE_URL:-http://data.gdeltproject.org/gdeltv2}
      - GDELT_FORWARD_INTERVAL_SECONDS=${GDELT_FORWARD_INTERVAL_SECONDS:-900}
      - GDELT_PARQUET_PATH=${GDELT_PARQUET_PATH:-/data/gdelt}
      - GDELT_FILTER_MODE=${GDELT_FILTER_MODE:-alpha}
      - GDELT_CAMEO_ROOT_ALLOWLIST=${GDELT_CAMEO_ROOT_ALLOWLIST:-15,18,19,20}
      - GDELT_BACKFILL_PARALLEL_SLICES=${GDELT_BACKFILL_PARALLEL_SLICES:-4}
      # NOT passed through: GDELT_THEME_ALLOWLIST, GDELT_NUCLEAR_OVERRIDE_THEMES.
      # Both have rich defaults in GDELTSettings — we only want them overridden
      # when deliberately customized. Override at run-time:
      #   GDELT_THEME_ALLOWLIST="FOO,BAR" docker compose up -d data-ingestion
      # The env block above does NOT list them, so Pydantic picks defaults.
      # ... existing env

# At bottom, under `volumes:`
volumes:
  gdelt_parquet:
    driver: local
```

- [ ] **Step 2: Verify compose syntax**

Run: `docker compose config -q`
Expected: No error output

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(gdelt): add gdelt_parquet volume + GDELT_* env passthrough"
```

---

## Task 23: Integration test — full forward tick against dev-compose

**Files:**
- Create: `services/data-ingestion/tests/test_gdelt_integration.py`

- [ ] **Step 1: Write integration test**

```python
# services/data-ingestion/tests/test_gdelt_integration.py
"""Integration test: run full forward tick against local dev-compose.

Skip if services are not running. Uses fixture slice — no live GDELT.
Bypasses download by feeding parsed DataFrames directly via
_filter_and_write_parquet + writers.write_from_parquet.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import polars as pl
import pytest


pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"


def _dev_services_up() -> bool:
    try:
        httpx.get("http://localhost:6333/", timeout=2.0).raise_for_status()
        httpx.get("http://localhost:8001/health", timeout=2.0).raise_for_status()
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _dev_services_up(), reason="dev-compose services not running")
@pytest.mark.asyncio
async def test_full_forward_tick_against_real_stores(tmp_path):
    """Run forward with fixture slice + real Neo4j/Qdrant/Redis.

    Steps:
      1. Parse fixture CSVs.
      2. Run filter + transform + atomic parquet write.
      3. Invoke Neo4j writer from parquet — asserts GDELTEvent count ≥ N.
      4. Invoke Qdrant writer from parquet — asserts collection point count grew.
      5. Assert Redis state: per-stream parquet done, neo4j done, qdrant done,
         last_slice:parquet advanced.
      6. Cleanup: delete written fixture test data to keep dev DB hygienic.
    """
    from qdrant_client import AsyncQdrantClient
    import redis.asyncio as aioredis

    from gdelt_raw.parser import parse_events, parse_mentions, parse_gkg
    from gdelt_raw.run import _filter_and_write_parquet, ParsedSlice
    from gdelt_raw.state import GDELTState
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter
    from gdelt_raw.writers.qdrant_writer import QdrantWriter, default_tei_embed

    slice_id = "99999425120000"  # test-sentinel slice_id, safe to clean up
    date = "9999-04-25"

    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                          decode_responses=True)
    state = GDELTState(r)

    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.environ["NEO4J_PASSWORD"],
    )
    qclient = AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

    async def embed(text: str):
        return await default_tei_embed(
            text, tei_url=os.getenv("TEI_EMBED_URL", "http://localhost:8001"))
    qdrant = QdrantWriter(
        client=qclient, embed=embed,
        collection=os.getenv("QDRANT_COLLECTION", "odin_intel"),
    )

    # 1. Parse
    ev_res = parse_events(FIXTURES / "slice_20260425_full.export.CSV",
                          quarantine_dir=tmp_path / "q")
    me_res = parse_mentions(FIXTURES / "slice_20260425_full.mentions.CSV",
                             quarantine_dir=tmp_path / "q")
    gk_res = parse_gkg(FIXTURES / "slice_20260425_full.gkg.csv",
                       quarantine_dir=tmp_path / "q")

    parsed = ParsedSlice(
        events_df=ev_res.df, mentions_df=me_res.df, gkg_df=gk_res.df,
        stream_states={"events": "done", "mentions": "done", "gkg": "done"},
    )

    # 2. Filter + transform + write parquet — use test slice_id + date
    # Temporarily monkey the _slice_date inside run — OR just write under tmp_path
    # with date="9999-04-25" so cleanup targets that partition.
    parquet_base = tmp_path / "gdelt"
    parquet_base.mkdir(parents=True)

    from gdelt_raw.filter import apply_filters
    from gdelt_raw.transform import (
        canonicalize_events, canonicalize_gkg, canonicalize_mentions,
    )
    from gdelt_raw.writers.parquet_writer import write_stream_parquet
    from gdelt_raw.config import get_settings

    settings = get_settings()
    fr = apply_filters(
        parsed.events_df, parsed.mentions_df, parsed.gkg_df,
        cameo_roots=settings.cameo_root_allowlist,
        theme_alpha=settings.theme_allowlist,
        theme_nuclear_override=settings.nuclear_override_themes,
    )

    # Force deterministic event_id/doc_id for cleanup
    sentinel_prefix_ev = f"gdelt:event:itest-{slice_id}-"
    sentinel_prefix_doc = f"gdelt:gkg:itest-{slice_id}-"
    ev_canon = canonicalize_events(fr.events).with_columns(
        pl.lit(sentinel_prefix_ev) + pl.col("event_id").str.split(":").list.get(-1)
        .alias("event_id")
    )
    gkg_canon = canonicalize_gkg(fr.gkg).with_columns(
        pl.lit(sentinel_prefix_doc) + pl.col("doc_id").str.split(":").list.get(-1)
        .alias("doc_id")
    )
    mentions_canon = canonicalize_mentions(fr.mentions)

    write_stream_parquet(ev_canon, base_path=parquet_base, stream="events",
                         date=date, slice_id=slice_id)
    write_stream_parquet(gkg_canon, base_path=parquet_base, stream="gkg",
                         date=date, slice_id=slice_id)
    write_stream_parquet(mentions_canon, base_path=parquet_base, stream="mentions",
                         date=date, slice_id=slice_id)

    for st in ("events", "mentions", "gkg"):
        await state.set_stream_parquet(slice_id, st, "done")

    # 3. Neo4j write from parquet
    await neo4j.write_from_parquet(parquet_base, slice_id, date)
    await state.set_store_state(slice_id, "neo4j", "done")

    # Assert at least one sentinel event exists
    async with neo4j._driver.session() as s:
        result = await s.run(
            "MATCH (e:GDELTEvent) WHERE e.event_id STARTS WITH $p RETURN count(e) AS n",
            {"p": sentinel_prefix_ev},
        )
        n = (await result.single())["n"]
    assert n >= 1, "no sentinel GDELTEvent found in Neo4j"

    # 4. Qdrant write from parquet
    n_points = await qdrant.upsert_from_parquet(parquet_base, slice_id, date)
    await state.set_store_state(slice_id, "qdrant", "done")
    assert n_points >= 1, "no sentinel gkg_doc upserted to Qdrant"

    # 5. State assertions
    await state.set_last_slice("parquet", slice_id)
    assert await state.is_slice_fully_done(slice_id) is True

    # 6. Cleanup
    async with neo4j._driver.session() as s:
        await s.run(
            "MATCH (e:GDELTEvent) WHERE e.event_id STARTS WITH $p DETACH DELETE e",
            {"p": sentinel_prefix_ev},
        )
        await s.run(
            "MATCH (d:GDELTDocument) WHERE d.doc_id STARTS WITH $p DETACH DELETE d",
            {"p": sentinel_prefix_doc},
        )
    await neo4j.close()

    # Qdrant cleanup — filter-by-prefix delete
    from qdrant_client.http.models import Filter, FieldCondition, MatchText
    await qclient.delete(
        collection_name=os.getenv("QDRANT_COLLECTION", "odin_intel"),
        points_selector=Filter(must=[
            FieldCondition(key="doc_id", match=MatchText(text=sentinel_prefix_doc)),
        ]),
    )

    # Redis cleanup
    await r.delete(
        *[f"gdelt:slice:{slice_id}:events:parquet",
          f"gdelt:slice:{slice_id}:gkg:parquet",
          f"gdelt:slice:{slice_id}:mentions:parquet",
          f"gdelt:slice:{slice_id}:neo4j",
          f"gdelt:slice:{slice_id}:qdrant"]
    )
```

- [ ] **Step 2: Run (will skip if services down)**

Run: `cd services/data-ingestion && uv run pytest -m integration -v`
Expected: SKIP or PASS — never FAIL on a box without dev-compose

- [ ] **Step 3: Commit**

```bash
git add services/data-ingestion/tests/test_gdelt_integration.py
git commit -m "test(gdelt): integration harness (skip if dev-compose down)"
```

---

## Task 24: DuckDB analytics smoke test

**Files:**
- Create: `services/data-ingestion/tests/test_gdelt_duckdb_smoke.py`

- [ ] **Step 1: Write smoke test**

```python
# services/data-ingestion/tests/test_gdelt_duckdb_smoke.py
from pathlib import Path

import duckdb
import polars as pl
import pytest


def test_duckdb_can_read_partitioned_parquet(tmp_path):
    """Guards Parquet schema drift: DuckDB must be able to SELECT from our
    date-partitioned parquet layout."""
    # Write two partitions
    for date in ("2026-04-25", "2026-04-26"):
        part = tmp_path / "events" / f"date={date}"
        part.mkdir(parents=True)
        pl.DataFrame({
            "event_id": ["gdelt:event:1", "gdelt:event:2"],
            "codebook_type": ["conflict.armed", "conflict.assault"],
            "goldstein": [-6.5, -4.2],
        }).write_parquet(part / "slice_a.parquet")

    con = duckdb.connect()
    # Hive-partitioned scan
    result = con.sql(
        f"SELECT codebook_type, count(*) AS n, avg(goldstein) AS avg_g "
        f"FROM read_parquet('{tmp_path}/events/date=*/*.parquet', "
        f"                  hive_partitioning=1) "
        f"GROUP BY codebook_type ORDER BY codebook_type"
    ).fetchall()
    assert len(result) == 2
    assert result[0][1] == 2  # 2 rows per codebook_type across 2 partitions
    assert result[1][1] == 2
```

- [ ] **Step 2: Add duckdb dev-dep**

Run:
```bash
cd services/data-ingestion && uv add --dev duckdb
```

- [ ] **Step 3: Run test — expect PASS**

Run: `cd services/data-ingestion && uv run pytest tests/test_gdelt_duckdb_smoke.py -v`
Expected: 1 passed

- [ ] **Step 4: Commit**

```bash
git add services/data-ingestion/tests/test_gdelt_duckdb_smoke.py \
        services/data-ingestion/pyproject.toml services/data-ingestion/uv.lock
git commit -m "test(gdelt): duckdb analytics smoke — guards parquet schema drift"
```

---

## Task 25: Live smoke test (marked -m live)

**Files:**
- Create: `services/data-ingestion/tests/test_gdelt_live.py`

- [ ] **Step 1: Write live test**

```python
# services/data-ingestion/tests/test_gdelt_live.py
"""Live test — touches the real GDELT CDN. Run with `pytest -m live`."""

from __future__ import annotations

import pytest

from gdelt_raw.downloader import fetch_lastupdate


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_gdelt_lastupdate_endpoint():
    entries = await fetch_lastupdate()
    assert len(entries) == 3
    streams = {e.stream for e in entries}
    assert streams == {"events", "mentions", "gkg"}
    # Slice_id is YYYYMMDDHHMMSS
    for e in entries:
        assert len(e.slice_id) == 14
        assert e.md5  # MD5 present
```

- [ ] **Step 2: Run live (manual only)**

Run: `cd services/data-ingestion && uv run pytest -m live -v`
Expected: 1 passed (network-dependent)

- [ ] **Step 3: Commit**

```bash
git add services/data-ingestion/tests/test_gdelt_live.py
git commit -m "test(gdelt): live smoke test for lastupdate.txt (opt-in via -m live)"
```

---

## Task 26: Apply migrations on dev + kick off 30-day backfill

**NOT committed code — operational task. Still follows the TDD-next-step pattern.**

- [ ] **Step 1: Pre-flight — verify constraints safe to apply**

Run:
```bash
source .env && docker exec -it osint-neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (s:Source) WITH s.name AS name, count(*) AS c WHERE c > 1 RETURN name, c"
```
Expected: No rows. If rows exist, consolidate before proceeding.

- [ ] **Step 2: Apply migrations**

Run:
```bash
docker exec osint-data-ingestion uv run python -c "
import asyncio, os
from neo4j import AsyncGraphDatabase
from gdelt_raw.migrations.apply import apply_phase1, apply_phase2

async def main():
    d = AsyncGraphDatabase.driver(
        os.environ['NEO4J_URL'], auth=('neo4j', os.environ['NEO4J_PASSWORD']))
    try:
        await apply_phase1(d)
        await apply_phase2(d)
    finally:
        await d.close()

asyncio.run(main())
"
```
Expected: `migration_applied` log for each statement. No errors.

- [ ] **Step 3: Doctor check**

Run: `./odin.sh gdelt doctor`
Expected: All rows ✓

- [ ] **Step 4: Kick off 30-day backfill**

Run:
```bash
./odin.sh gdelt backfill --from $(date -u -d '30 days ago' +%Y-%m-%d)
```
Expected: Job ID printed, parallel processing. Takes ~4-8 h.

- [ ] **Step 5: Observe 24h + smoke-check**

Run:
```bash
./odin.sh gdelt status
docker exec osint-neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (e:GDELTEvent) RETURN count(e) AS n" -p
```
Expected: Events count growing every 15 min.

- [ ] **Step 6: No commit — operational only**

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Architecture overview (Task 16 `run_forward`, Task 15 recovery)
- [x] Per-stream per-slice Redis state (Task 11)
- [x] Write-order invariant (Task 16 test `test_parquet_written_before_external_stores`)
- [x] Nuclear-Override filter UNION (Task 10)
- [x] Qdrant/Neo4j decoupling (Tasks 14, 15, 16)
- [x] Canonical `doc_id`/`event_id` everywhere (Tasks 1, 10.5, 13, 14)
- [x] Canonical Transform Layer (Task 10.5) — gap between raw GDELT and Pydantic writer contracts
- [x] Scoped constraints + preflight (Task 18)
- [x] Two-stage parser (Task 8)
- [x] Atomic Parquet writes (Task 12)
- [x] Neo4j writer covers Events + Docs + Sources + Themes + Mentions (Task 13); Entities/Locations deferred
- [x] Idempotent `:ABOUT` theme relationship (Task 13)
- [x] `last_slice:parquet` independent of Neo4j/Qdrant (Task 16)
- [x] Resumable backfill with pending/done/failed sets (Task 17)
- [x] Backfill skips MD5 verification (`verify_md5=False` threaded through) (Tasks 9, 16, 17)
- [x] CLI + scheduler integration, doctor pings Qdrant+TEI (Tasks 19, 20, 21)
- [x] Docker + env — no blank passthroughs (Task 22)
- [x] Integration test bypasses download, runs full write path with cleanup (Task 23)
- [x] DuckDB + Live smokes (Tasks 24, 25)
- [x] Migration + backfill rollout (Task 26)

**2. Placeholder scan:**
- ~~Task 16 had a pass-through test~~ → implemented in Task 16 as real behavior test.
- ~~Task 23 had a TODO~~ → implemented as real end-to-end integration test with deterministic sentinel prefix + cleanup block.
- No remaining blocking placeholders.

**3. Type consistency:**
- `build_event_id(int | str) → str` consistent in Tasks 1, 10, 10.5, 13
- `GDELTState` async methods in Tasks 11, 15, 16, 17
- `download_slice(entry, out_dir, *, verify_md5=True)` consistent across Tasks 9, 16, 17
- `QdrantWriter.upsert_from_parquet(base, slice, date)` signature matches Tasks 14, 15, 16
- `Neo4jWriter.write_from_parquet` covers Events + Docs + Mentions (Task 13)
- Canonical column names produced by transform match Pydantic writer contracts 1:1 (verified by `test_canonical_event_validates_against_pydantic_writer_contract` in Task 10.5)

**4. Review round 2 fixes applied:**
- Must-Fix 1 (canonical transform layer) → Task 10.5
- Must-Fix 2 (backfill MD5 path) → Task 9 `verify_md5` param + Tasks 16, 17 threading
- Must-Fix 3 (`last_slice:parquet` semantics) → Task 16 rewrite
- Must-Fix 4 (placeholder tests) → Task 16 real test
- Must-Fix 5 (integration test TODO) → Task 23 real test with sentinel + cleanup
- Must-Fix 6 (Neo4j mentions/themes/sources write_from_parquet) → Task 13 expanded
- Must-Fix 7 (MERGE_THEME idempotent) → Task 13 no-count version
- Must-Fix 8 (backfill truly resumable) → Task 17 pending/done/failed sets
- Should-Fix 1 (pydantic-settings dep) → Task 0
- Should-Fix 2 (CSV-list env parsing note) → Task 0 NoDecode fallback
- Should-Fix 3 (docker-compose defaults) → Task 22 no raw passthroughs
- Should-Fix 4 (doctor Qdrant+TEI checks) → Task 20
- Should-Fix 5 (absolute fixture paths) → Task 8 relative paths via `git rev-parse`

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-gdelt-raw-ingestion.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, with two-stage review between tasks (spec + quality). Best for this plan because each task is self-contained and benefits from fresh context.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
