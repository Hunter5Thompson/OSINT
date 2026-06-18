# SUV Track 2a — Equipment / Hauptwaffensysteme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the SUV.report Hauptwaffensysteme dataset as `(:MILITARY_UNIT|:ORGANIZATION)-[:OPERATES {count, service_end, note, …}]->(:WEAPON_SYSTEM)` edges, linking existing weapon-system nodes rather than duplicating them.

**Architecture:** Deterministic crawl4ai render → Markdown-table parser → human-reviewed YAML seed → generalized match-report gate (link-first; node creation gated by `approved_new`+`evidence`) → deterministic Neo4j writer with type-guarded OPERATES + non-destructive UPSERT_WEAPON_SYSTEM. Operator level resolved via a curated `match|create` seed with an exactly-1 preflight. Read-path made OPERATES-aware. Graph-only — no Qdrant in 2a.

**Tech Stack:** Python 3.13, Pydantic v2, click, httpx, structlog, PyYAML, pytest, uv. Neo4j HTTP tx API. crawl4ai HTTP service (`:11235`). Intelligence service for the read-path (`graph/`, `agents/tools/`).

**Spec:** `docs/superpowers/specs/2026-06-18-suv-track2a-equipment-design.md`

## Global Constraints

- **Deterministic write path** — no LLM, no GPU; parsers are pure functions with raw-string fallback.
- **Two-Loop discipline** — all values `$param`-bound; relationship/label strings hardcoded; relation-endpoint nodes are MATCH-ed, never MERGE-d, within a relation template.
- **Link existing, don't duplicate** — a `new` WEAPON_SYSTEM is NOT writable by default; it requires `approved_new: true` + a non-empty `evidence` string. Alias curation is the primary resolution.
- **OPERATES type guard** — source `IN ["MILITARY_UNIT","ORGANIZATION"]`, target `type:"WEAPON_SYSTEM"`; operator matched on the seed's exact `(name, type)`.
- **No Qdrant in 2a** — the equipment build creates 0 points and instantiates no `QdrantClient` (regression-tested).
- **OPERATES vs OPERATES_IN** — OPERATES = actor operates/uses a system; OPERATES_IN = actor active in a geographic region. Documented in SUV write_templates + read-path schema; NOT in `event_codebook.yaml` or the nlm `RelationType` Literal.
- **TDD** (red→green→refactor); frequent commits; the Slice-1 companies path must stay behavior-identical (regression).
- All `cd` paths are relative to the worktree root `/home/deadpool-ultra/ODIN/OSINT/.claude/worktrees/suv-track2a-equipment`. Tests run with `uv run pytest` from `services/data-ingestion` (or `services/intelligence` for Task 8) — never bare `python`/`pytest`.

## File Structure

**data-ingestion (`services/data-ingestion/`):**
- `suv_structured/equipment_schemas.py` — NEW. `WeaponSystemRow` Pydantic + `.name` interface.
- `suv_structured/equipment_parse.py` — NEW. Markdown-table parser + `parse_count`/`parse_service_end`.
- `suv_structured/operators.py` — NEW. `OperatorEntry` seed model + loader + `match_preflight_offenders`.
- `suv_structured/match_report.py` — MODIFY. Parametrize `target_type`; add `gate_new_creation` policy.
- `suv_structured/write_templates.py` — MODIFY. Add `LINK_OPERATES`, `UPSERT_WEAPON_SYSTEM`, `UPSERT_OPERATOR`.
- `suv_structured/build_equipment.py` — NEW. Gate + statement builder (no Qdrant) + live-count helper.
- `suv_structured/cli.py` — MODIFY. Add the `equipment` subgroup (`fetch | parse | build`).
- `suv_structured/seeds/suv_operators.yaml` — NEW (committed, human-reviewed).
- `tests/fixtures/suv_equipment_heer.md` (+ a tiny synthetic edge-case fixture) — NEW.
- `tests/test_suv_equipment_parse.py`, `tests/test_suv_operators.py`, `tests/test_suv_equipment_match_report.py`, `tests/test_suv_equipment_write_templates.py`, `tests/test_suv_build_equipment.py`, `tests/test_suv_equipment_cli.py` — NEW.

**intelligence (`services/intelligence/`):**
- `graph/schema_whitelist.py` — MODIFY. Add `OPERATES` (+ `HEADQUARTERED_IN`) to `RELATIONSHIPS`.
- `agents/tools/graph_query.py` — MODIFY. Add operates-intent keywords → `one_hop`.
- `tests/test_schema_whitelist_operates.py`, `tests/test_graph_query_operates_intent.py` — NEW (or extend existing).

---

### Task 1: WeaponSystemRow schema

**Files:**
- Create: `services/data-ingestion/suv_structured/equipment_schemas.py`
- Test: `services/data-ingestion/tests/test_suv_equipment_schemas.py`

**Interfaces:**
- Produces: `WeaponSystemRow(muster: str, type_raw: str|None, count: int|None, count_raw: str|None, service_end: int|None, note: str|None, page_slug: str, suv_url: str)` with a read-only `.name` property returning `muster`.

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_suv_equipment_schemas.py
import pytest
from suv_structured.equipment_schemas import WeaponSystemRow


def test_name_property_is_muster():
    row = WeaponSystemRow(muster="Leopard 2", page_slug="hauptwaffensysteme-des-heeres",
                          suv_url="https://suv.report/hauptwaffensysteme-des-heeres/")
    assert row.name == "Leopard 2"
    assert row.count is None and row.service_end is None


def test_blank_muster_rejected():
    with pytest.raises(ValueError):
        WeaponSystemRow(muster="   ", page_slug="p", suv_url="u")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_schemas.py -v`
Expected: FAIL (`ModuleNotFoundError: suv_structured.equipment_schemas`).

- [ ] **Step 3: Write minimal implementation**

```python
# services/data-ingestion/suv_structured/equipment_schemas.py
"""Pydantic model for one SUV Hauptwaffensysteme table row."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class WeaponSystemRow(BaseModel):
    muster: str                       # "Muster" column = the weapon-system name
    type_raw: str | None = None       # "Typ" column (e.g. "Kampfpanzer")
    count: int | None = None          # parsed from "Anzahl"
    count_raw: str | None = None       # original "Anzahl" string (provenance)
    service_end: int | None = None    # parsed year from "Nutzungsdauerende"
    note: str | None = None           # "Notiz"
    page_slug: str                    # which sub-page → operator
    suv_url: str                      # the sub-page URL (per-page; a valid join key)

    @field_validator("muster")
    @classmethod
    def _muster_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("weapon-system name (Muster) must be non-empty")
        return v

    @property
    def name(self) -> str:
        """Match/gate interface: the entity name is the Muster column."""
        return self.muster
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_schemas.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/equipment_schemas.py services/data-ingestion/tests/test_suv_equipment_schemas.py
git commit -m "feat(suv): WeaponSystemRow schema for equipment ingestion"
```

---

### Task 2: Equipment Markdown-table parser

**Files:**
- Create: `services/data-ingestion/suv_structured/equipment_parse.py`
- Create: `services/data-ingestion/tests/fixtures/suv_equipment_sample.md`
- Test: `services/data-ingestion/tests/test_suv_equipment_parse.py`

**Interfaces:**
- Consumes: `WeaponSystemRow` (Task 1).
- Produces: `parse_count(raw: str|None) -> int|None`, `parse_service_end(raw: str|None) -> int|None`, `parse_weapon_systems(markdown: str, *, page_slug: str, suv_url: str) -> list[WeaponSystemRow]`.

- [ ] **Step 1: Write the failing test + fixture**

Create the fixture (covers the real edge cases observed in the spike):

```markdown
<!-- services/data-ingestion/tests/fixtures/suv_equipment_sample.md -->
Letzte Aktualisierung: 7. Januar 2026
| **Muster**  | **Typ**  | **Anzahl**  | **Nutzungsdauerende**  | **Notiz**  |
| --- | --- | --- | --- | --- |
| Leopard 2   | Kampfpanzer  | 310  | 2050  | 123 weitere Leopard 2 A8 bestellt.  |
| Schwerer Waffenträger Infanterie  | Schwerer Waffenträger  | 1+  | N/A  | 122 weitere bestellt.  |
| Fuchs  | Transportpanzer  | 939 in über 30 verschiedenen Varianten  | N/A  | Ersatz durch Patria 6×6 (CAVS).  |
| Husky 3  | Überschneefahrzeug  | 1  | 2046 (20 Jahre)  | 366 weitere bestellt.  |
| BV206S/D  | Überschneefahrzeug  | 337 (189 Bv206S & 148 Bv206D)  | 2030  |  |
```

```python
# services/data-ingestion/tests/test_suv_equipment_parse.py
from pathlib import Path

from suv_structured.equipment_parse import (
    parse_count, parse_service_end, parse_weapon_systems,
)

FIXTURE = Path(__file__).parent / "fixtures" / "suv_equipment_sample.md"
PAGE = "hauptwaffensysteme-des-heeres"
URL = "https://suv.report/hauptwaffensysteme-des-heeres/"


def test_parse_count_variants():
    assert parse_count("310") == 310
    assert parse_count("1+") == 1
    assert parse_count("939 in über 30 verschiedenen Varianten") == 939
    assert parse_count("337 (189 Bv206S & 148 Bv206D)") == 337
    assert parse_count("32.000") == 32000          # German thousands-dot
    assert parse_count("N/A") is None
    assert parse_count(None) is None


def test_parse_service_end_variants():
    assert parse_service_end("2050") == 2050
    assert parse_service_end("2046 (20 Jahre)") == 2046
    assert parse_service_end("N/A") is None
    assert parse_service_end("") is None
    assert parse_service_end(None) is None


def test_parse_weapon_systems_skips_header_and_separator():
    rows = parse_weapon_systems(FIXTURE.read_text(), page_slug=PAGE, suv_url=URL)
    assert [r.muster for r in rows] == [
        "Leopard 2", "Schwerer Waffenträger Infanterie", "Fuchs", "Husky 3", "BV206S/D",
    ]


def test_parse_weapon_systems_fields():
    rows = {r.muster: r for r in parse_weapon_systems(FIXTURE.read_text(), page_slug=PAGE, suv_url=URL)}
    leo = rows["Leopard 2"]
    assert leo.type_raw == "Kampfpanzer" and leo.count == 310 and leo.service_end == 2050
    assert leo.page_slug == PAGE and leo.suv_url == URL
    fuchs = rows["Fuchs"]
    assert fuchs.count == 939 and fuchs.count_raw == "939 in über 30 verschiedenen Varianten"
    assert fuchs.service_end is None
    assert rows["Schwerer Waffenträger Infanterie"].count == 1
    assert rows["Husky 3"].service_end == 2046
    assert rows["BV206S/D"].note is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_parse.py -v`
Expected: FAIL (`ModuleNotFoundError: suv_structured.equipment_parse`).

- [ ] **Step 3: Write minimal implementation**

```python
# services/data-ingestion/suv_structured/equipment_parse.py
"""Deterministic parser: a rendered Hauptwaffensysteme sub-page (Markdown table)
-> list[WeaponSystemRow]. No LLM, no GPU. Numeric fields are best-effort
normalized with a raw-string fallback (None when no integer/year is present)."""
from __future__ import annotations

import re

import structlog

from suv_structured.equipment_schemas import WeaponSystemRow

log = structlog.get_logger(__name__)


def parse_count(raw: str | None) -> int | None:
    """'310'->310 ; '1+'->1 ; '939 in über 30 …'->939 ; '337 (189 …)'->337 ;
    '32.000'->32000 (German thousands-dot). First integer found; None if none."""
    if not raw:
        return None
    m = re.search(r"\d[\d.]*", raw)
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", ""))
    except ValueError:
        return None


def parse_service_end(raw: str | None) -> int | None:
    """'2050'->2050 ; '2046 (20 Jahre)'->2046 ; 'N/A'/empty -> None. First 4-digit year."""
    if not raw:
        return None
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", raw)
    return int(m.group(1)) if m else None


def _clean(cell: str) -> str:
    """Trim whitespace and surrounding markdown bold markers from a table cell."""
    return cell.strip().strip("*").strip()


def _split_row(line: str) -> list[str]:
    """Split a markdown table line into cells, dropping the cells the surrounding
    pipes create. Returns [] for non-table lines."""
    if "|" not in line:
        return []
    cells = [c.strip() for c in line.split("|")]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def parse_weapon_systems(
    markdown: str, *, page_slug: str, suv_url: str
) -> list[WeaponSystemRow]:
    rows: list[WeaponSystemRow] = []
    for line in markdown.splitlines():
        cells = _split_row(line)
        if len(cells) < 5:
            continue
        first = _clean(cells[0])
        # skip the header row and the '| --- | --- |' separator row
        if first.lower() == "muster" or not first:
            continue
        if set(first) <= {"-", ":"}:
            continue
        try:
            rows.append(WeaponSystemRow(
                muster=first,
                type_raw=_clean(cells[1]) or None,
                count=parse_count(_clean(cells[2]) or None),
                count_raw=_clean(cells[2]) or None,
                service_end=parse_service_end(_clean(cells[3]) or None),
                note=_clean(cells[4]) or None,
                page_slug=page_slug,
                suv_url=suv_url,
            ))
        except ValueError:
            log.warning("suv_equipment_row_skipped", cells=cells)
    log.info("suv_equipment_parsed", page=page_slug, count=len(rows))
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_parse.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/equipment_parse.py services/data-ingestion/tests/test_suv_equipment_parse.py services/data-ingestion/tests/fixtures/suv_equipment_sample.md
git commit -m "feat(suv): deterministic Markdown-table parser for Hauptwaffensysteme"
```

---

### Task 3: Operator seed model + resolver

**Files:**
- Create: `services/data-ingestion/suv_structured/operators.py`
- Create: `services/data-ingestion/suv_structured/seeds/suv_operators.yaml`
- Test: `services/data-ingestion/tests/test_suv_operators.py`

**Interfaces:**
- Produces: `OperatorEntry(page_slug, page_label, decision: "match"|"create", target_name, target_type: "MILITARY_UNIT"|"ORGANIZATION", create_properties: dict)`; `load_operators(path) -> list[OperatorEntry]`; `operators_by_slug(list) -> dict[str, OperatorEntry]`; `match_preflight_offenders(counts: dict[tuple[str,str], int]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_suv_operators.py
from pathlib import Path

import pytest

from suv_structured.operators import (
    OperatorEntry, load_operators, match_preflight_offenders, operators_by_slug,
)

SEED = Path(__file__).parent.parent / "suv_structured" / "seeds" / "suv_operators.yaml"


def test_committed_seed_loads_five_operators():
    ops = load_operators(SEED)
    assert len(ops) == 5
    slugs = {o.page_slug for o in ops}
    assert "hauptwaffensysteme-des-heeres" in slugs
    by_slug = operators_by_slug(ops)
    assert by_slug["hauptwaffensysteme-des-heeres"].target_type in ("MILITARY_UNIT", "ORGANIZATION")


def test_invalid_decision_rejected():
    with pytest.raises(ValueError):
        OperatorEntry(page_slug="p", page_label="L", decision="merge",
                      target_name="X", target_type="MILITARY_UNIT")


def test_invalid_target_type_rejected():
    with pytest.raises(ValueError):
        OperatorEntry(page_slug="p", page_label="L", decision="match",
                      target_name="X", target_type="LOCATION")


def test_preflight_flags_non_unique_match_targets():
    counts = {("Deutsches Heer", "MILITARY_UNIT"): 1, ("Luftwaffe", "MILITARY_UNIT"): 2,
              ("Marine", "MILITARY_UNIT"): 0}
    offenders = match_preflight_offenders(counts)
    assert any("Luftwaffe" in o for o in offenders)
    assert any("Marine" in o for o in offenders)
    assert not any("Deutsches Heer" in o for o in offenders)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_operators.py -v`
Expected: FAIL (`ModuleNotFoundError: suv_structured.operators`).

- [ ] **Step 3: Write minimal implementation + the committed seed**

```python
# services/data-ingestion/suv_structured/operators.py
"""Operator (Teilstreitkraft) seed: page_slug -> canonical operator node.

Each row is an explicit, executable contract: match an existing node (by exact
name+type, verified by an exactly-1 preflight at build time) or create a new one."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_VALID_TYPES = ("MILITARY_UNIT", "ORGANIZATION")


class OperatorEntry(BaseModel):
    page_slug: str
    page_label: str
    decision: str                      # "match" | "create"
    target_name: str
    target_type: str                   # "MILITARY_UNIT" | "ORGANIZATION"
    create_properties: dict = Field(default_factory=dict)

    @field_validator("decision")
    @classmethod
    def _decision_valid(cls, v: str) -> str:
        if v not in ("match", "create"):
            raise ValueError(f"decision must be match|create, got {v!r}")
        return v

    @field_validator("target_type")
    @classmethod
    def _type_valid(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"target_type must be one of {_VALID_TYPES}, got {v!r}")
        return v


def load_operators(path: Path) -> list[OperatorEntry]:
    return [OperatorEntry(**row) for row in (yaml.safe_load(path.read_text()) or [])]


def operators_by_slug(entries: list[OperatorEntry]) -> dict[str, OperatorEntry]:
    return {e.page_slug: e for e in entries}


def match_preflight_offenders(counts: dict[tuple[str, str], int]) -> list[str]:
    """Given (name, type) -> live node-count for each `match` operator, return
    human-readable offenders that do not resolve to exactly one node."""
    return [f"{name} ({etype}) -> count={c}"
            for (name, etype), c in sorted(counts.items()) if c != 1]
```

```yaml
# services/data-ingestion/suv_structured/seeds/suv_operators.yaml
# Curated operator (Teilstreitkraft) resolution — one decision per row, human-reviewed.
# match: target must resolve to exactly ONE Entity{name,type} (build-time preflight).
# create: MERGE a new Entity{name,type} with create_properties.
- page_slug: hauptwaffensysteme-des-heeres
  page_label: Heer
  decision: match
  target_name: "Deutsches Heer"
  target_type: MILITARY_UNIT
- page_slug: hauptwaffensysteme-der-luftwaffe
  page_label: Luftwaffe
  decision: match
  target_name: "Deutsche Luftwaffe"
  target_type: MILITARY_UNIT
- page_slug: hauptwaffensysteme-der-marine
  page_label: Marine
  decision: match
  target_name: "Deutsche Marine"
  target_type: MILITARY_UNIT
- page_slug: hauptwaffensysteme-des-cyber-und-informationsraums
  page_label: Cyber- und Informationsraum
  decision: create
  target_name: "Cyber- und Informationsraum"
  target_type: MILITARY_UNIT
  create_properties:
    aliases: ["CIR"]
- page_slug: hauptwaffensysteme-des-unterstuetzungsbereichs
  page_label: Unterstützungsbereich
  decision: match
  target_name: "Unterstützungsbereich"
  target_type: ORGANIZATION
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_operators.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/operators.py services/data-ingestion/suv_structured/seeds/suv_operators.yaml services/data-ingestion/tests/test_suv_operators.py
git commit -m "feat(suv): operator seed model + exactly-1 preflight helper"
```

---

### Task 4: Generalize match_report for WEAPON_SYSTEM + new-creation gate

**Files:**
- Modify: `services/data-ingestion/suv_structured/match_report.py`
- Test: `services/data-ingestion/tests/test_suv_equipment_match_report.py`
- Regression: existing `services/data-ingestion/tests/test_suv_match_report.py` must still pass unchanged.

**Interfaces:**
- Consumes: any item with `.name` and `.suv_url` (Company from Slice 1; `WeaponSystemRow` from Task 1).
- Produces: `build_match_report(items, lookup, *, target_type="ORGANIZATION", gate_new_creation=False) -> list[dict]`; `load_approved(path, *, gate_new_creation=False) -> list[dict]`. `detect_drift`, `dump_report` unchanged.

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_suv_equipment_match_report.py
from pathlib import Path

import pytest

from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.match_report import build_match_report, dump_report, load_approved


def _row(muster):
    return WeaponSystemRow(muster=muster, page_slug="p", suv_url="u")


def test_weapon_system_match_new_ambiguous():
    rows = [_row("Leopard 2"), _row("Schakal"), _row("PATRIOT")]
    lookup = {
        "leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "id1")],
        "patriot": [("Patriot", "WEAPON_SYSTEM", "id2"), ("PATRIOT", "WEAPON_SYSTEM", "id3")],
    }
    report = build_match_report(rows, lookup, target_type="WEAPON_SYSTEM", gate_new_creation=True)
    by = {r["name"]: r for r in report}
    assert by["Leopard 2"]["decision"] == "match" and by["Leopard 2"]["existing_name"] == "Leopard 2"
    assert by["Schakal"]["decision"] == "new"
    assert by["PATRIOT"]["decision"] == "ambiguous"
    # new-policy fields are present for curation
    assert by["Schakal"]["approved_new"] is False and by["Schakal"]["evidence"] == ""


def test_gate_rejects_approved_new_without_evidence(tmp_path: Path):
    report = [{"name": "Schakal", "suv_url": "u", "decision": "new", "existing_name": None,
               "candidates": [], "approved": True, "approved_new": False, "evidence": ""}]
    p = tmp_path / "r.yaml"
    dump_report(report, p)
    with pytest.raises(ValueError, match="Schakal"):
        load_approved(p, gate_new_creation=True)


def test_gate_accepts_approved_new_with_evidence(tmp_path: Path):
    report = [{"name": "Schakal", "suv_url": "u", "decision": "new", "existing_name": None,
               "candidates": [], "approved": True, "approved_new": True,
               "evidence": "New 2025 IFV, no existing node"}]
    p = tmp_path / "r.yaml"
    dump_report(report, p)
    approved = load_approved(p, gate_new_creation=True)
    assert len(approved) == 1 and approved[0]["name"] == "Schakal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_match_report.py -v`
Expected: FAIL (`build_match_report() got an unexpected keyword argument 'target_type'`).

- [ ] **Step 3: Modify the implementation**

In `services/data-ingestion/suv_structured/match_report.py`, replace `build_match_report` and `load_approved`:

```python
def build_match_report(
    items: list,
    lookup: dict[str, list[tuple[str, str, str]]],
    *,
    target_type: str = "ORGANIZATION",
    gate_new_creation: bool = False,
) -> list[dict]:
    """Classify each item against existing graph entities of ``target_type``.

    ``items`` is any object exposing ``.name`` and ``.suv_url`` (Company or
    WeaponSystemRow). ``lookup`` maps lowercased name -> [(existing_name, type, id), ...].
    When ``gate_new_creation`` is set, each entry also carries ``approved_new``/
    ``evidence`` fields for the curator (used by the WEAPON_SYSTEM new-creation gate)."""
    report: list[dict] = []
    for c in items:
        key = c.name.strip().lower()
        rows = lookup.get(key, [])
        if not rows:
            canon = canonicalize_entity(c.name, target_type).name.strip().lower()
            if canon != key:
                rows = lookup.get(canon, [])
        targets = [r for r in rows if r[1] == target_type]
        if not rows:
            decision, existing = MatchDecision.NEW, None
        elif len(rows) == 1 and len(targets) == 1:
            decision, existing = MatchDecision.MATCH, targets[0][0]
        else:
            decision, existing = MatchDecision.AMBIGUOUS, None
        entry = {
            "name": c.name,
            "suv_url": c.suv_url,
            "decision": str(decision),
            "existing_name": existing,
            "candidates": [{"name": n, "type": t, "id": i} for n, t, i in rows],
            "approved": False,
        }
        if gate_new_creation:
            entry["approved_new"] = False
            entry["evidence"] = ""
        report.append(entry)
    return report
```

```python
def load_approved(path: Path, *, gate_new_creation: bool = False) -> list[dict]:
    """Load report; return only entries with ``approved is True``.

    Validates each approved entry defensively (see below) and raises ValueError
    listing every offender. With ``gate_new_creation`` set, an approved ``new``
    entry additionally requires ``approved_new is True`` + a non-empty ``evidence``
    string — link-existing is the default; node creation is the deliberate exception."""
    entries = yaml.safe_load(path.read_text()) or []
    approved = [e for e in entries if e.get("approved") is True]
    valid = {str(d) for d in MatchDecision}
    errors: list[str] = []
    for e in approved:
        name = e.get("name", "<unnamed>")
        decision = e.get("decision")
        norm = decision.lower() if isinstance(decision, str) else None
        if "name" not in e or decision is None:
            errors.append(f"{name}: missing 'name'/'decision' key")
            continue
        if norm not in valid:
            errors.append(f"{name}: unrecognized decision {decision!r}")
            continue
        e["decision"] = norm
        if norm == str(MatchDecision.AMBIGUOUS):
            errors.append(f"{name}: approved but still ambiguous (resolve first)")
        elif norm == str(MatchDecision.MATCH) and not e.get("existing_name"):
            errors.append(f"{name}: approved match missing existing_name")
        elif norm == str(MatchDecision.NEW) and gate_new_creation:
            if e.get("approved_new") is not True or not (e.get("evidence") or "").strip():
                errors.append(
                    f"{name}: approved 'new' WEAPON_SYSTEM requires approved_new: true "
                    "+ non-empty evidence (prefer alias curation to creating a node)")
    if errors:
        raise ValueError("unsafe approved entries: " + "; ".join(errors))
    return approved
```

(Companies callers pass neither new kwarg, so their behavior is byte-identical.)

- [ ] **Step 4: Run tests to verify pass + no regression**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_match_report.py tests/test_suv_match_report.py -v`
Expected: PASS (new file 3 passed; existing companies match-report tests unchanged & green).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/match_report.py services/data-ingestion/tests/test_suv_equipment_match_report.py
git commit -m "feat(suv): generalize match_report (target_type + WEAPON_SYSTEM new-creation gate)"
```

---

### Task 5: OPERATES + UPSERT_WEAPON_SYSTEM + UPSERT_OPERATOR templates

**Files:**
- Modify: `services/data-ingestion/suv_structured/write_templates.py`
- Test: `services/data-ingestion/tests/test_suv_equipment_write_templates.py`

**Interfaces:**
- Produces: module constants `LINK_OPERATES`, `UPSERT_WEAPON_SYSTEM`, `UPSERT_OPERATOR` (Cypher strings).

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_suv_equipment_write_templates.py
import re

from suv_structured import write_templates as wt


def test_operates_is_type_guarded_and_match_only():
    t = wt.LINK_OPERATES
    # operator matched on exact (name, type) bound from the seed
    assert "MATCH (op:Entity {name: $op_name, type: $op_type})" in t
    # allowed-source-type invariant
    assert 'op.type IN ["MILITARY_UNIT", "ORGANIZATION"]' in t
    # target is WEAPON_SYSTEM, matched (never merged)
    assert 'MATCH (ws:Entity {name: $ws_name, type: "WEAPON_SYSTEM"})' in t
    # the relationship is merged; the endpoint NODES are not
    assert "MERGE (op)-[r:OPERATES]->(ws)" in t
    assert not re.search(r"MERGE \(op:Entity", t)
    assert not re.search(r"MERGE \(ws:Entity", t)
    # edge properties
    for p in ("$count", "$count_raw", "$service_end", "$note", "$suv_url"):
        assert p in t
    assert 'r.data_source = "suv.report"' in t


def test_upsert_weapon_system_is_non_destructive():
    t = wt.UPSERT_WEAPON_SYSTEM
    assert 'MERGE (w:Entity {name: $name, type: "WEAPON_SYSTEM"})' in t
    assert "coalesce(w.aliases, [])" in t          # alias append-dedup
    assert "coalesce(w.weapon_type, $weapon_type)" in t   # enrich-if-absent, never clobber
    assert "ON CREATE SET w.first_seen" in t


def test_upsert_operator_creates_typed_node():
    t = wt.UPSERT_OPERATOR
    assert "MERGE (o:Entity {name: $name, type: $type})" in t
    assert "coalesce(o.aliases, [])" in t
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_write_templates.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'LINK_OPERATES'`).

- [ ] **Step 3: Append the templates**

Append to `services/data-ingestion/suv_structured/write_templates.py`:

```python
# --- Track 2a: equipment / Hauptwaffensysteme ---
#
# OPERATES links an operator (MILITARY_UNIT|ORGANIZATION) to a WEAPON_SYSTEM it
# operates/uses. Distinct from the geographic OPERATES_IN (actor active in a
# region). The operator is matched on the seed's exact (name, type); the WHERE
# enforces the allowed-source-type invariant so a malformed seed cannot link from
# a non-actor (e.g. a LOCATION). Both endpoints are MATCH-ed, never MERGE-d.

UPSERT_OPERATOR = """
MERGE (o:Entity {name: $name, type: $type})
ON CREATE SET o.first_seen = datetime(), o.data_source = "suv.report"
SET o.aliases = coalesce(o.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(o.aliases, [])],
    o.last_seen = datetime()
"""

UPSERT_WEAPON_SYSTEM = """
MERGE (w:Entity {name: $name, type: "WEAPON_SYSTEM"})
ON CREATE SET w.first_seen = datetime()
SET w.aliases = coalesce(w.aliases, []) +
        [a IN $aliases WHERE NOT a IN coalesce(w.aliases, [])],
    w.weapon_type = coalesce(w.weapon_type, $weapon_type),
    w.data_source = coalesce(w.data_source, $data_source),
    w.suv_url = coalesce(w.suv_url, $suv_url),
    w.last_seen = datetime()
"""

LINK_OPERATES = """
MATCH (op:Entity {name: $op_name, type: $op_type}) WHERE op.type IN ["MILITARY_UNIT", "ORGANIZATION"]
MATCH (ws:Entity {name: $ws_name, type: "WEAPON_SYSTEM"})
WITH op, ws LIMIT 1
MERGE (op)-[r:OPERATES]->(ws)
ON CREATE SET r.first_seen = datetime(), r.data_source = "suv.report"
SET r.count = $count, r.count_raw = $count_raw, r.service_end = $service_end,
    r.note = $note, r.suv_url = $suv_url, r.last_seen = datetime()
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_write_templates.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/write_templates.py services/data-ingestion/tests/test_suv_equipment_write_templates.py
git commit -m "feat(suv): OPERATES + UPSERT_WEAPON_SYSTEM/OPERATOR write templates (type-guarded, MATCH-only)"
```

---

### Task 6: build_equipment — gate + statement builder (no Qdrant)

**Files:**
- Create: `services/data-ingestion/suv_structured/build_equipment.py`
- Test: `services/data-ingestion/tests/test_suv_build_equipment.py`

**Interfaces:**
- Consumes: `WeaponSystemRow` (T1), `OperatorEntry`/`operators_by_slug` (T3), `load_approved`/`detect_drift` (T4), `LINK_OPERATES`/`UPSERT_WEAPON_SYSTEM`/`UPSERT_OPERATOR` (T5), `canonicalize_entity` and `write_neo4j` (Slice 1).
- Produces: `dedup_systems(rows) -> list[WeaponSystemRow]`; `ws_write_name(row, entry) -> str`; `build_equipment_statements(rows, approved, operators, *, extracted_at) -> list[dict]`; `resolve_equipment_build_inputs(*, rows, operators, approved: list[dict]) -> list[dict]`; `match_target_counts(...)` live helper.

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_suv_build_equipment.py
from pathlib import Path

import pytest

from suv_structured.build_equipment import (
    EquipmentBuildGateError, build_equipment_statements, dedup_systems, ws_write_name,
)
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.operators import OperatorEntry, operators_by_slug

HEER = "hauptwaffensysteme-des-heeres"
URL = "https://suv.report/hauptwaffensysteme-des-heeres/"
OPS = operators_by_slug([OperatorEntry(
    page_slug=HEER, page_label="Heer", decision="match",
    target_name="Deutsches Heer", target_type="MILITARY_UNIT")])


def _row(muster, count=None, service_end=None):
    return WeaponSystemRow(muster=muster, type_raw="Kampfpanzer", count=count,
                           count_raw=str(count) if count else None,
                           service_end=service_end, page_slug=HEER, suv_url=URL)


def test_dedup_systems_by_muster():
    rows = [_row("Leopard 2"), _row("Leopard 2"), _row("Puma")]
    assert sorted(r.muster for r in dedup_systems(rows)) == ["Leopard 2", "Puma"]


def test_ws_write_name_match_vs_new():
    matched = {"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}
    new = {"name": "Schakal", "decision": "new", "approved_new": True, "evidence": "x"}
    assert ws_write_name(_row("Leopard 2"), matched) == "Leopard 2"
    assert ws_write_name(_row("Schakal"), new) == "Schakal"


def test_build_statements_orders_endpoints_before_link():
    rows = [_row("Leopard 2", count=310, service_end=2050)]
    approved = [{"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}]
    stmts = build_equipment_statements(rows, approved, OPS, extracted_at="2026-06-18T00:00:00Z")
    # the WEAPON_SYSTEM upsert (MERGE w) precedes the OPERATES link (MATCH op)
    ws_idx = next(i for i, s in enumerate(stmts) if "MERGE (w:Entity" in s["statement"])
    op_idx = next(i for i, s in enumerate(stmts) if "MERGE (op)-[r:OPERATES]" in s["statement"])
    assert ws_idx < op_idx
    link = stmts[op_idx]["parameters"]
    assert link == {"op_name": "Deutsches Heer", "op_type": "MILITARY_UNIT",
                    "ws_name": "Leopard 2", "count": 310, "count_raw": "310",
                    "service_end": 2050, "note": None, "suv_url": URL}


def test_build_equipment_module_has_no_qdrant_dependency():
    """Track 2a is graph-only: the build module must not import or touch Qdrant."""
    import suv_structured.build_equipment as be
    assert "qdrant" not in Path(be.__file__).read_text().lower()


def test_build_raises_on_missing_operator():
    """Fail-closed: an approved holding whose page has no operator seed must raise,
    never be silently skipped (defense-in-depth alongside the gate)."""
    rows = [_row("Leopard 2")]  # page_slug = HEER
    approved = [{"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}]
    with pytest.raises(EquipmentBuildGateError):
        build_equipment_statements(rows, approved, {}, extracted_at="t")  # empty operator map


def test_build_skips_unapproved_rows():
    rows = [_row("Leopard 2"), _row("UnapprovedThing")]
    approved = [{"name": "Leopard 2", "decision": "match", "existing_name": "Leopard 2"}]
    stmts = build_equipment_statements(rows, approved, OPS, extracted_at="t")
    assert not any("UnapprovedThing" in str(s["parameters"]) for s in stmts)


def test_build_creates_operator_for_create_decision():
    ops = operators_by_slug([OperatorEntry(
        page_slug=HEER, page_label="CIR", decision="create",
        target_name="Cyber- und Informationsraum", target_type="MILITARY_UNIT",
        create_properties={"aliases": ["CIR"]})])
    rows = [_row("Tool X")]
    approved = [{"name": "Tool X", "decision": "match", "existing_name": "Tool X"}]
    stmts = build_equipment_statements(rows, approved, ops, extracted_at="t")
    assert any("MERGE (o:Entity {name: $name, type: $type})" in s["statement"] for s in stmts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_build_equipment.py -v`
Expected: FAIL (`ModuleNotFoundError: suv_structured.build_equipment`).

- [ ] **Step 3: Write minimal implementation**

```python
# services/data-ingestion/suv_structured/build_equipment.py
"""Deterministic builder: approved weapon systems + operator seed -> Neo4j statements.

No LLM, no GPU, NO Qdrant (Track 2a is graph-only). Endpoint upserts (operator +
weapon-system) are emitted before the OPERATES link in the same transaction so the
relationship template's MATCH-ed endpoints exist."""
from __future__ import annotations

import base64
from pathlib import Path

import httpx
import structlog

from canonicalize import canonicalize_entity
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.operators import OperatorEntry
from suv_structured.write_templates import (
    LINK_OPERATES, UPSERT_OPERATOR, UPSERT_WEAPON_SYSTEM,
)

log = structlog.get_logger(__name__)


class EquipmentBuildGateError(RuntimeError):
    """Raised when the equipment --approved-matches merge gate is not satisfied."""


def dedup_systems(rows: list[WeaponSystemRow]) -> list[WeaponSystemRow]:
    """Unique weapon systems by muster (entity resolution is per system, not per
    operator-holding row). First occurrence wins."""
    seen: dict[str, WeaponSystemRow] = {}
    for r in rows:
        seen.setdefault(r.muster, r)
    return list(seen.values())


def ws_write_name(row: WeaponSystemRow, entry: dict) -> str:
    """Match -> approved existing canonical name; new -> canonicalized SUV muster."""
    if (entry.get("decision") or "").lower() == "match" and entry.get("existing_name"):
        return entry["existing_name"]
    return canonicalize_entity(row.muster, "WEAPON_SYSTEM").name


def build_equipment_statements(
    rows: list[WeaponSystemRow],
    approved: list[dict],
    operators: dict[str, OperatorEntry],
    *,
    extracted_at: str,
) -> list[dict]:
    """Build Neo4j HTTP-API statements for approved systems only. Joined by NAME
    (muster). One OPERATES edge per operator-holding row; operator + weapon-system
    upserts emitted once each, before the first link that references them."""
    approved_by_name = {e["name"]: e for e in approved}
    statements: list[dict] = []
    created_ops: set[tuple[str, str]] = set()
    upserted_ws: set[str] = set()
    for row in rows:
        entry = approved_by_name.get(row.muster)
        if entry is None:
            continue
        op = operators.get(row.page_slug)
        if op is None:
            # fail-closed: never silently drop an approved holding (the gate already
            # checks this, but the builder must not depend on the gate having run)
            raise EquipmentBuildGateError(
                f"no operator seed row for page {row.page_slug!r} (system {row.muster!r})")
        if op.decision == "create" and (op.target_name, op.target_type) not in created_ops:
            created_ops.add((op.target_name, op.target_type))
            statements.append({"statement": UPSERT_OPERATOR, "parameters": {
                "name": op.target_name, "type": op.target_type,
                "aliases": sorted(set(op.create_properties.get("aliases", []))),
            }})
        ws_name = ws_write_name(row, entry)
        if ws_name not in upserted_ws:
            upserted_ws.add(ws_name)
            statements.append({"statement": UPSERT_WEAPON_SYSTEM, "parameters": {
                "name": ws_name,
                "aliases": sorted({row.muster, ws_name}),
                "weapon_type": row.type_raw,
                "data_source": "suv.report",
                "suv_url": row.suv_url,
            }})
        statements.append({"statement": LINK_OPERATES, "parameters": {
            "op_name": op.target_name, "op_type": op.target_type,
            "ws_name": ws_name,
            "count": row.count, "count_raw": row.count_raw,
            "service_end": row.service_end, "note": row.note,
            "suv_url": row.suv_url,
        }})
    log.info("suv_equipment_statements_built", statements=len(statements))
    return statements


def resolve_equipment_build_inputs(
    *, rows: list[WeaponSystemRow], operators: dict[str, OperatorEntry],
    approved: list[dict],
) -> list[dict]:
    """Enforce the gate: approved names must exist in the parsed rows, every
    referenced page must have an operator, and no two approved entries may resolve
    to the same canonical weapon-system write-name (silent merge)."""
    musters = {r.muster for r in rows}
    unknown = [e["name"] for e in approved if e["name"] not in musters]
    if unknown:
        raise EquipmentBuildGateError(f"approved report diverges from seed (unknown: {unknown})")
    # check EVERY approved-row occurrence: a system can appear on multiple pages, so a
    # one-page-per-muster map could hide a page that lacks an operator seed row.
    approved_names = {e["name"] for e in approved}
    missing_ops = sorted({r.page_slug for r in rows
                          if r.muster in approved_names and r.page_slug not in operators})
    if missing_ops:
        raise EquipmentBuildGateError(f"no operator seed row for page(s): {missing_ops}")
    by_name = {r.muster: r for r in rows}
    seen: dict[str, str] = {}
    collisions: list[str] = []
    for e in approved:
        row = by_name.get(e["name"])
        if row is None:
            continue
        wn = ws_write_name(row, e)
        if wn in seen:
            collisions.append(f"{seen[wn]!r} + {e['name']!r} -> {wn!r}")
        else:
            seen[wn] = e["name"]
    if collisions:
        raise EquipmentBuildGateError(
            f"multiple approved entries resolve to the same canonical system: {collisions}")
    return approved


async def match_target_counts(
    operators: dict[str, OperatorEntry], client: httpx.AsyncClient,
    *, neo4j_http_url: str, neo4j_user: str, neo4j_password: str,
) -> dict[tuple[str, str], int]:
    """Live node-count per (name, type) for each `match` operator (exactly-1 preflight input)."""
    targets = sorted({(o.target_name, o.target_type)
                      for o in operators.values() if o.decision == "match"})
    if not targets:
        return {}
    cypher = ("UNWIND $pairs AS p "
              "MATCH (e:Entity {name: p.name, type: p.type}) "
              "RETURN p.name AS name, p.type AS type, count(e) AS c")
    pairs = [{"name": n, "type": t} for n, t in targets]
    auth = base64.b64encode(f"{neo4j_user}:{neo4j_password}".encode()).decode()
    resp = await client.post(
        f"{neo4j_http_url}/db/neo4j/tx/commit",
        json={"statements": [{"statement": cypher, "parameters": {"pairs": pairs}}]},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"Neo4j preflight error: {data['errors'][0].get('message', data['errors'])}")
    counts = {(n, t): 0 for n, t in targets}
    for row in (data["results"][0]["data"] if data.get("results") else []):
        name, etype, c = row["row"]
        counts[(name, etype)] = c
    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_build_equipment.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/build_equipment.py services/data-ingestion/tests/test_suv_build_equipment.py
git commit -m "feat(suv): build_equipment — gate + statement builder + match preflight (no Qdrant)"
```

---

### Task 7: CLI `equipment` subgroup (fetch | parse | build) + Qdrant regression

**Files:**
- Modify: `services/data-ingestion/suv_structured/cli.py`
- Test: `services/data-ingestion/tests/test_suv_equipment_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6, plus Slice-1 `fetch_directory_markdown`, `_lookup_existing`, `write_neo4j`, `build_match_report`, `detect_drift`, `dump_report`.
- Produces: `equipment` click group with `fetch`, `parse`, `build` commands; module constants `EQUIPMENT_PAGES`, `EQUIPMENT_SEED`, `OPERATORS_SEED`.

- [ ] **Step 1: Write the failing test**

```python
# services/data-ingestion/tests/test_suv_equipment_cli.py
from pathlib import Path
from unittest.mock import AsyncMock

from click.testing import CliRunner

from suv_structured.cli import cli


def test_equipment_build_refuses_without_approved_matches(tmp_path: Path, monkeypatch):
    # point the seed at a tmp file so the command reaches the gate, not the missing-seed error
    seed = tmp_path / "suv_equipment.yaml"
    seed.write_text("- {muster: Leopard 2, page_slug: hauptwaffensysteme-des-heeres, suv_url: u}\n")
    monkeypatch.setattr("suv_structured.cli.EQUIPMENT_SEED", seed)
    res = CliRunner().invoke(cli, ["equipment", "build"])
    assert res.exit_code != 0
    # EquipmentBuildGateError is raised (not echoed) → check output AND exception
    assert "approved-matches" in (res.output + str(res.exception)).lower()


def test_equipment_group_registered():
    res = CliRunner().invoke(cli, ["equipment", "--help"])
    assert res.exit_code == 0
    for sub in ("fetch", "parse", "build"):
        assert sub in res.output


def test_equipment_build_happy_path_writes_no_qdrant(tmp_path: Path, monkeypatch):
    """AC6 regression: a full real build traverses the write path WITHOUT instantiating
    a QdrantClient. QdrantClient is patched to explode if touched."""
    import suv_structured.cli as cli_mod

    seed = tmp_path / "suv_equipment.yaml"
    seed.write_text("- {muster: Leopard 2, page_slug: hauptwaffensysteme-des-heeres, suv_url: u}\n")
    approved = tmp_path / "approved.yaml"
    approved.write_text(
        '- {name: "Leopard 2", decision: match, existing_name: "Leopard 2", '
        "approved: true, approved_new: false, evidence: \"\"}\n")
    monkeypatch.setattr("suv_structured.cli.EQUIPMENT_SEED", seed)

    def _boom(*a, **k):
        raise AssertionError("QdrantClient must not be instantiated in the equipment path")
    monkeypatch.setattr(cli_mod, "QdrantClient", _boom, raising=False)

    # stub the live-graph calls so the test needs no Neo4j
    monkeypatch.setattr(cli_mod, "_lookup_existing", AsyncMock(
        return_value={"leopard 2": [("Leopard 2", "WEAPON_SYSTEM", "id1")]}))
    monkeypatch.setattr(cli_mod, "match_target_counts", AsyncMock(
        return_value={("Deutsches Heer", "MILITARY_UNIT"): 1}))
    captured = {}
    async def _fake_write_neo4j(statements, **kw):
        captured["stmts"] = statements
    monkeypatch.setattr(cli_mod, "write_neo4j", _fake_write_neo4j)

    res = CliRunner().invoke(cli, ["equipment", "build", "--approved-matches", str(approved)])
    assert res.exit_code == 0, (res.output, res.exception)
    assert "qdrant=0" in res.output
    # the write path produced an OPERATES link statement
    assert any("MERGE (op)-[r:OPERATES]" in s["statement"] for s in captured["stmts"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_cli.py -v`
Expected: FAIL (`No such command 'equipment'`).

- [ ] **Step 3: Add the `equipment` subgroup to cli.py**

Add these imports near the top of `services/data-ingestion/suv_structured/cli.py` (after the existing imports):

```python
from suv_structured.build_equipment import (
    EquipmentBuildGateError,
    build_equipment_statements,
    dedup_systems,
    match_target_counts,
    resolve_equipment_build_inputs,
)
from suv_structured.equipment_parse import parse_weapon_systems
from suv_structured.equipment_schemas import WeaponSystemRow
from suv_structured.operators import (
    load_operators, match_preflight_offenders, operators_by_slug,
)
```

Add the module constants (after `SEED_PATH`):

```python
EQUIPMENT_PAGES = {
    "hauptwaffensysteme-des-heeres": "https://suv.report/hauptwaffensysteme-des-heeres/",
    "hauptwaffensysteme-der-luftwaffe": "https://suv.report/hauptwaffensysteme-der-luftwaffe/",
    "hauptwaffensysteme-der-marine": "https://suv.report/hauptwaffensysteme-der-marine/",
    "hauptwaffensysteme-des-cyber-und-informationsraums":
        "https://suv.report/hauptwaffensysteme-des-cyber-und-informationsraums/",
    "hauptwaffensysteme-des-unterstuetzungsbereichs":
        "https://suv.report/hauptwaffensysteme-des-unterstuetzungsbereichs/",
}
EQUIPMENT_SEED = Path(__file__).parent / "seeds" / "suv_equipment.yaml"
OPERATORS_SEED = Path(__file__).parent / "seeds" / "suv_operators.yaml"


def _load_equipment_seed(path: Path) -> list[WeaponSystemRow]:
    return [WeaponSystemRow(**row) for row in (yaml.safe_load(path.read_text()) or [])]
```

Add the subgroup (anywhere after the `cli` group is defined, e.g. before `_lookup_existing`):

```python
@cli.group()
def equipment() -> None:
    """SUV Hauptwaffensysteme structured ingestion (Track 2a)."""


@equipment.command("fetch")
def equipment_fetch() -> None:
    """Render all 5 Hauptwaffensysteme sub-pages and print their markdown."""
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            for slug, url in EQUIPMENT_PAGES.items():
                md = await fetch_directory_markdown(
                    url, crawl4ai_url=settings.crawl4ai_url, client=client)
                click.echo(f"===== {slug} ({len(md)} chars) =====")
                click.echo(md)
    asyncio.run(_run())


@equipment.command("parse")
def equipment_parse_cmd() -> None:
    """Render + parse all 5 sub-pages; write the seed snapshot for human review."""
    async def _run() -> None:
        rows: list[WeaponSystemRow] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for slug, url in EQUIPMENT_PAGES.items():
                md = await fetch_directory_markdown(
                    url, crawl4ai_url=settings.crawl4ai_url, client=client)
                rows.extend(parse_weapon_systems(md, page_slug=slug, suv_url=url))
        if len(rows) < 30:
            raise click.ClickException(
                f"parse yielded only {len(rows)} systems — likely a shell/error page; seed NOT written")
        EQUIPMENT_SEED.parent.mkdir(parents=True, exist_ok=True)
        EQUIPMENT_SEED.write_text(
            yaml.safe_dump([r.model_dump() for r in rows], allow_unicode=True, sort_keys=False))
        click.echo(f"wrote {len(rows)} weapon systems -> {EQUIPMENT_SEED}")
    asyncio.run(_run())


@equipment.command("build")
@click.option("--dry-run", is_flag=True, help="Write match_report.yaml; no graph writes.")
@click.option("--approved-matches", "approved_path", type=click.Path(path_type=Path),
              default=None, help="Curated, approved match report (required for real build).")
@click.option("--report-out", type=click.Path(path_type=Path),
              default=Path("equipment_match_report.yaml"), help="Where --dry-run writes the report.")
def equipment_build(dry_run: bool, approved_path: Path | None, report_out: Path) -> None:
    """Dry-run produces the weapon-system match report; real run requires --approved-matches."""
    async def _run() -> None:
        if not EQUIPMENT_SEED.exists():
            raise click.ClickException(
                f"no seed at {EQUIPMENT_SEED} — run `odin-suv-structured equipment parse` first")
        rows = _load_equipment_seed(EQUIPMENT_SEED)
        operators = operators_by_slug(load_operators(OPERATORS_SEED))
        unique = dedup_systems(rows)
        u, pw = settings.neo4j_user, settings.neo4j_password
        async with httpx.AsyncClient(timeout=60.0) as client:
            if dry_run:
                lookup = await _lookup_existing(unique, client, settings.neo4j_http_url, u, pw,
                                                entity_type="WEAPON_SYSTEM")
                dump_report(build_match_report(
                    unique, lookup, target_type="WEAPON_SYSTEM", gate_new_creation=True), report_out)
                click.echo(f"dry-run: wrote match report -> {report_out}")
                return
            if approved_path is None:
                raise EquipmentBuildGateError(
                    "refusing to build without --approved-matches <report.yaml> "
                    "(run `equipment build --dry-run` first, curate + set approved: true)")
            approved = load_approved(approved_path, gate_new_creation=True)
            resolve_equipment_build_inputs(rows=rows, operators=operators, approved=approved)
            # re-derive against the live graph; abort on drift
            lookup = await _lookup_existing(unique, client, settings.neo4j_http_url, u, pw,
                                            entity_type="WEAPON_SYSTEM")
            fresh = build_match_report(unique, lookup, target_type="WEAPON_SYSTEM", gate_new_creation=True)
            drift = detect_drift(approved, fresh)
            if drift:
                raise EquipmentBuildGateError(
                    f"graph changed since dry-run — re-run `equipment build --dry-run` + re-curate: {drift}")
            # operator exactly-1 preflight (match rows only)
            counts = await match_target_counts(
                operators, client, neo4j_http_url=settings.neo4j_http_url,
                neo4j_user=u, neo4j_password=pw)
            offenders = match_preflight_offenders(counts)
            if offenders:
                raise EquipmentBuildGateError(
                    f"operator match preflight failed (not exactly-1): {offenders}")
            from datetime import UTC, datetime
            ts = datetime.now(UTC).isoformat()
            stmts = build_equipment_statements(rows, approved, operators, extracted_at=ts)
            await write_neo4j(stmts, client=client, neo4j_http_url=settings.neo4j_http_url,
                              neo4j_user=u, neo4j_password=pw)
            click.echo(f"built {len(approved)} systems (neo4j stmts={len(stmts)}, qdrant=0)")
    asyncio.run(_run())
```

**Required signature change to the existing `_lookup_existing` (cli.py:217)** so the
`entity_type="WEAPON_SYSTEM"` kwarg used in the code block above is accepted. It already reads only
`c.name`, so it works for `WeaponSystemRow`; only its hardcoded canonicalize type must be parametrized:

```python
# cli.py: add the keyword-only param and use it in the canonicalize call(s)
async def _lookup_existing(
    companies, client, neo4j_http_url: str, user: str, password: str,
    *, entity_type: str = "ORGANIZATION",
):
    ...
        canon = canonicalize_entity(c.name, entity_type).name   # was hardcoded "ORGANIZATION"
    ...
```
The companies `build` caller passes no `entity_type`, so it keeps the `"ORGANIZATION"` default and is
behavior-identical (regression: `tests/test_suv_cli.py` must stay green).

- [ ] **Step 4: Run tests + the companies CLI regression**

Run: `cd services/data-ingestion && uv run pytest tests/test_suv_equipment_cli.py tests/test_suv_cli.py -v`
Expected: PASS (equipment CLI 3 passed; companies CLI tests unchanged & green).

- [ ] **Step 5: Commit**

```bash
git add services/data-ingestion/suv_structured/cli.py services/data-ingestion/tests/test_suv_equipment_cli.py
git commit -m "feat(suv): equipment CLI subgroup (fetch|parse|build) with gate + operator preflight; no Qdrant"
```

---

### Task 8: Read-path — make OPERATES discoverable

**Files:**
- Modify: `services/intelligence/graph/schema_whitelist.py:9`
- Modify: `services/intelligence/agents/tools/graph_query.py` (intent matcher, ~line 226)
- Test: `services/intelligence/tests/test_schema_whitelist_operates.py`, `services/intelligence/tests/test_graph_query_operates_intent.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (read-path is independent; can be done in parallel).
- Produces: `OPERATES` (and `HEADQUARTERED_IN`) in `schema_whitelist.RELATIONSHIPS`; an operates-intent branch returning the `one_hop` template.

- [ ] **Step 1: Write the failing test**

```python
# services/intelligence/tests/test_schema_whitelist_operates.py
from graph.schema_whitelist import RELATIONSHIPS, schema_prompt_block


def test_operates_in_whitelist():
    assert "OPERATES" in RELATIONSHIPS
    assert "HEADQUARTERED_IN" in RELATIONSHIPS  # Slice-1 edge, previously missing
    assert "OPERATES" in schema_prompt_block()
```

```python
# services/intelligence/tests/test_graph_query_operates_intent.py
from agents.tools.graph_query import _match_intent


def test_betreibt_question_routes_to_relationship_template():
    # Quoted CANONICAL operator name. Two reasons it must be quoted+canonical:
    # (1) the proper-noun heuristic on unquoted text is brittle (it would extract
    #     "Systeme Heer?" from "Welche Systeme betreibt das Heer?"), and
    # (2) OPERATES edges attach to "Deutsches Heer" (the seed's canonical operator),
    #     NOT "Heer" — so only the canonical name actually retrieves the edges.
    tmpl, params = _match_intent('Welche Systeme betreibt "Deutsches Heer"?')
    assert tmpl == "one_hop" and params == {"name": "Deutsches Heer"}


def test_operates_keyword_routes_to_relationship_template():
    tmpl, params = _match_intent('what does "Deutsche Luftwaffe" operate')
    assert tmpl == "one_hop" and params == {"name": "Deutsche Luftwaffe"}
```

Verified signature: `_match_intent(question: str) -> tuple[str | None, dict]` (graph_query.py:184);
the entity is extracted INSIDE via quoted-string then proper-noun heuristics, and the existing
`one_hop` branch returns `("one_hop", {"name": entity})`.

**Honest scope limit (do NOT overclaim):** this task makes OPERATES *discoverable* — a query naming
the canonical operator in quotes routes to a relationship template that surfaces OPERATES edges. It
does NOT make free-text German natural-language querying ("das Heer", alias→canonical resolution
`Heer`→`Deutsches Heer`) reliable; that depends on the brittle entity-extraction heuristic and is a
separate, pre-existing read-path concern, explicitly out of 2a scope.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/intelligence && uv run pytest tests/test_schema_whitelist_operates.py tests/test_graph_query_operates_intent.py -v`
Expected: FAIL (`AssertionError: OPERATES not in RELATIONSHIPS` / intent returns `entity_lookup` or `None`).

- [ ] **Step 3: Modify the read-path**

In `services/intelligence/graph/schema_whitelist.py`, line 9:

```python
RELATIONSHIPS = (
    "INVOLVES", "REPORTED_BY", "OCCURRED_AT", "MENTIONS",
    "OPERATES", "HEADQUARTERED_IN",
)
```

In `services/intelligence/agents/tools/graph_query.py`, inside `_match_intent`, add an operates-intent
branch immediately BEFORE the existing `one_hop` branch (the `"connected to"/"related to"/"neighbors
of"/"linked to"` one, ~line 221). No earlier branch matches these keywords (verified: top_connected,
event_timeline, co_occurring, source_backed, events_by_entity, two_hop_network, entity_lookup keywords
don't overlap `operate`/`betreibt`). Match the surrounding code's exact style:

```python
    if entity and any(kw in q for kw in (
        "operates", "operate", "betreibt", "in dienst", "im bestand",
        "fielded", "in service",
    )):
        return "one_hop", {"name": entity}
```

(`one_hop` already traverses `-[r]-(n)` and returns `type(r)`, so OPERATES edges surface
without free-Cypher. Keep the OPERATES↔OPERATES_IN distinction in the tool description text if
that file documents relationship semantics — coordinate wording with `intel-codebook-curator`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/intelligence && uv run pytest tests/test_schema_whitelist_operates.py tests/test_graph_query_operates_intent.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/intelligence/graph/schema_whitelist.py services/intelligence/agents/tools/graph_query.py services/intelligence/tests/test_schema_whitelist_operates.py services/intelligence/tests/test_graph_query_operates_intent.py
git commit -m "feat(intel): read-path discovers OPERATES (whitelist + betreibt/operates intent)"
```

---

## Final verification (after all tasks)

- [ ] **Full data-ingestion suite green (no regression):**
  Run: `cd services/data-ingestion && uv run pytest -q`
  Expected: all pass except the 1 known pre-existing GDELT-integration skip (~965+ passed).
- [ ] **Intelligence read-path suite green:**
  Run: `cd services/intelligence && uv run pytest -q`
- [ ] **Lint:**
  Run: `cd services/data-ingestion && uv run ruff check suv_structured/ tests/` and
  `cd services/intelligence && uv run ruff check graph/ agents/tools/graph_query.py`
- [ ] **Reviews (per task + holistic):** two-stage review (spec-review + quality-review) per task,
  never skipped; **plus an explicit adversarial gate-bypass review** of Task 4 (the new-creation
  gate) + Task 6 (`resolve_equipment_build_inputs`) + Task 5 (OPERATES type-guard) — try to construct
  an approved report or seed that writes a node/edge the gate should reject. Final holistic opus review.

## Operational run (separate from implementation — gated, dry-run default)

Not part of the TDD tasks; performed once the PR is merged, by the operator:
1. `odin-suv-structured equipment parse` → review `seeds/suv_equipment.yaml` (commit the snapshot).
2. `odin-suv-structured equipment build --dry-run` → `equipment_match_report.yaml`. Curate: resolve
   `ambiguous`, add canonicalize aliases for surface variants (re-run dry-run), mark deliberate
   creations `approved_new: true` + `evidence`, set `approved: true`. Confirm the operator seed.
3. **Neo4j backup** (dump) before any write.
4. `odin-suv-structured equipment build --approved-matches <curated.yaml>` → verify via Cypher:
   `MATCH (:Entity{type:"MILITARY_UNIT"})-[r:OPERATES]->(w:Entity{type:"WEAPON_SYSTEM"}) RETURN count(r)`.
5. Rebuild/recreate the intelligence image from this worktree (`docker compose -p osint … --no-build`);
   no GPU swap. Verify a read-path query naming the canonical operator in quotes —
   `Welche Systeme betreibt "Deutsches Heer"?` — surfaces OPERATES edges (unquoted/alias forms are a
   known read-path limitation, see Task 8's scope note).
