# Factbook Almanac Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sparse REST-Countries almanac facts with curated-deep, CIA-World-Factbook-sourced data, produced by a deterministic `odin-infra-atlas almanac` builder that writes the committed static seed.

**Architecture:** A builder with two modes. **Refresh** (network, occasional) fetches a pinned Factbook snapshot + REST Countries and writes three committed, normalized inputs (`crosswalk.json`, `factbook_snapshot.json`, `restcountries_snapshot.json`). **Render** (offline, deterministic, no clock/network) joins those inputs + a manual `country_almanac_overrides.json` into `services/backend/data/country_almanac.json`. Render never reads its own prior output.

**Tech Stack:** Python 3.12, `click` CLI, `httpx`, `json`, stdlib `html.parser`/`html` (cleaning). Spec: `docs/superpowers/specs/2026-06-01-factbook-almanac-enrichment-design.md`.

**Baseline:** Implement on a branch off current `main` (`24798c2`, includes #29 packaging/iso3/seed-integrity + #30). No schema change; backend model `app/models/almanac.py` unchanged.

**Locked constants (from final review):**
- `MAX_CAPITAL_CENTROID_DISTANCE_KM = 5000` (flags exactly ESH + ATF on the current REST dataset).
- `FACTBOOK_REVISION = "8662a8b17a784841ab4528631b04090eb2f183eb"`, `FACTBOOK_REVISION_DATE = "2026-05-17"`, `CIA_SUNSET_DATE = "2026-02-04"`.
- `odin-infra-atlas almanac --refresh --refreshed-at YYYY-MM-DD` — `--refreshed-at` is **mandatory** for refresh (no hidden clock access).

---

## File Structure

- **Create** `services/data-ingestion/infra_atlas/almanac_constants.py` — constants + curated field mapping.
- **Create** `services/data-ingestion/infra_atlas/almanac_clean.py` — pure helpers: `clean_html`, `latest_year_value`, `format_composite`, `is_plausible_capital`.
- **Create** `services/data-ingestion/infra_atlas/build_country_almanac.py` — `refresh(...)` + `render(...)`.
- **Create** `services/data-ingestion/infra_atlas/data/iso3_gec.json` — vendored GEC↔ISO3 reference (refresh input).
- **Generated/committed** `infra_atlas/data/crosswalk.json`, `infra_atlas/data/factbook_snapshot.json`, `infra_atlas/data/restcountries_snapshot.json` (refresh outputs, committed).
- **Modify** `services/data-ingestion/infra_atlas/cli.py` — add `almanac` command.
- **Modify** `services/data-ingestion/pyproject.toml` — package-data `infra_atlas/data/*.json`.
- **Create** `services/backend/data/country_almanac_overrides.json` — manual facts/coord fixes (render input).
- **Regenerate** `services/backend/data/country_almanac.json` (render output, committed).
- **Create** `services/data-ingestion/tests/test_build_country_almanac.py` — builder unit tests.
- **Modify** `services/backend/tests/test_almanac_seed_integrity.py` — coverage classes + collision guards.

---

## Task 1: Constants + curated field mapping

**Files:** Create `services/data-ingestion/infra_atlas/almanac_constants.py`

- [ ] **Step 1: Write the file**
```python
"""Constants + curated Factbook→Almanac field mapping (single source of truth)."""
from __future__ import annotations

FACTBOOK_REVISION = "8662a8b17a784841ab4528631b04090eb2f183eb"
FACTBOOK_REVISION_DATE = "2026-05-17"
CIA_SUNSET_DATE = "2026-02-04"
FACTBOOK_TARBALL_URL = (
    f"https://codeload.github.com/factbook/factbook.json/tar.gz/{FACTBOOK_REVISION}"
)
RESTCOUNTRIES_URL = (
    "https://restcountries.com/v3.1/all"
    "?fields=cca3,ccn3,name,capital,capitalInfo,region,subregion,"
    "population,area,currencies,languages,latlng"
)
MAX_CAPITAL_CENTROID_DISTANCE_KM = 5000.0

# REST-fallback (no usable single Factbook profile) — keep economy/security optional.
REST_FALLBACK_ISO3 = {"ESH", "PSE"}
# Partial Factbook (deliberately empty economy) — security ok, economy optional.
PARTIAL_FACTBOOK_ISO3 = {"ATA"}
# Map stubs (no ISO/Factbook data) — resolvable-only.
MAP_STUB_TOPO_IDS = {"N. Cyprus", "Somaliland"}

# label -> Factbook section + key path (list = nested lookup). One entry per fact.
# Section "profile"/"people"/"government"/"economy"/"security".
FIELD_MAP: list[dict] = [
    {"section": "profile", "label": "Area", "fb": ["Geography", "Area", "total "]},
    {"section": "profile", "label": "Climate", "fb": ["Geography", "Climate"]},
    {"section": "profile", "label": "Natural resources", "fb": ["Geography", "Natural resources"]},
    {"section": "people", "label": "Population", "fb": ["People and Society", "Population", "total"]},
    {"section": "people", "label": "Median age", "fb": ["People and Society", "Median age", "total"]},
    {"section": "people", "label": "Population growth rate", "fb": ["People and Society", "Population growth rate"]},
    {"section": "people", "label": "Urbanization", "fb": ["People and Society", "Urbanization", "urban population"]},
    {"section": "people", "label": "Life expectancy", "fb": ["People and Society", "Life expectancy at birth", "total population"]},
    {"section": "people", "label": "Ethnic groups", "fb": ["People and Society", "Ethnic groups"]},
    {"section": "people", "label": "Religions", "fb": ["People and Society", "Religions"]},
    {"section": "people", "label": "Languages", "fb": ["People and Society", "Languages", "Languages"]},
    {"section": "people", "label": "Literacy", "fb": ["People and Society", "Literacy", "total population"]},
    {"section": "government", "label": "Government type", "fb": ["Government", "Government type"]},
    {"section": "government", "label": "Independence", "fb": ["Government", "Independence"]},
    {"section": "government", "label": "Chief of state", "fb": ["Government", "Executive branch", "chief of state"]},
    {"section": "government", "label": "Head of government", "fb": ["Government", "Executive branch", "head of government"]},
    {"section": "government", "label": "Suffrage", "fb": ["Government", "Suffrage"]},
    {"section": "economy", "label": "Real GDP (PPP)", "fb": ["Economy", "Real GDP (purchasing power parity)"], "multiyear": True},
    {"section": "economy", "label": "Real GDP per capita", "fb": ["Economy", "Real GDP per capita"], "multiyear": True},
    {"section": "economy", "label": "Real GDP growth rate", "fb": ["Economy", "Real GDP growth rate"], "multiyear": True},
    {"section": "economy", "label": "Inflation", "fb": ["Economy", "Inflation rate (consumer prices)"], "multiyear": True},
    {"section": "economy", "label": "GDP by sector", "fb": ["Economy", "GDP - composition, by sector of origin"], "composite": ["agriculture", "industry", "services"]},
    {"section": "economy", "label": "Industries", "fb": ["Economy", "Industries"]},
    {"section": "economy", "label": "Labor force", "fb": ["Economy", "Labor force"]},
    {"section": "economy", "label": "Unemployment rate", "fb": ["Economy", "Unemployment rate"], "multiyear": True},
    {"section": "economy", "label": "Youth unemployment", "fb": ["Economy", "Youth unemployment rate (ages 15-24)", "total"]},
    {"section": "economy", "label": "Public debt", "fb": ["Economy", "Public debt"], "multiyear": True},
    {"section": "economy", "label": "Exports", "fb": ["Economy", "Exports"], "multiyear": True},
    {"section": "economy", "label": "Exports - partners", "fb": ["Economy", "Exports - partners"]},
    {"section": "economy", "label": "Imports - partners", "fb": ["Economy", "Imports - partners"]},
    {"section": "economy", "label": "Exchange rates", "fb": ["Economy", "Exchange rates"]},
    {"section": "security", "label": "Military expenditures", "fb": ["Military and Security", "Military expenditures"], "multiyear": True},
    {"section": "security", "label": "Military and security forces", "fb": ["Military and Security", "Military and security forces"]},
    {"section": "security", "label": "Personnel strengths", "fb": ["Military and Security", "Military and security service personnel strengths"]},
    {"section": "security", "label": "Service age/obligation", "fb": ["Military and Security", "Military service age and obligation"]},
    {"section": "security", "label": "Military deployments", "fb": ["Military and Security", "Military deployments"]},
    {"section": "security", "label": "Military note", "fb": ["Military and Security", "Military - note"]},
]
```
- [ ] **Step 2: Commit** — `git add services/data-ingestion/infra_atlas/almanac_constants.py && git commit -m "feat(almanac): builder constants + curated field map"`

> NOTE: the exact `fb` key paths above are the curated targets verified against the Factbook
> structure (§5 of the spec). In Task 3 the extraction is TDD-driven against the real snapshot;
> if a key path differs at the pinned revision, fix it there (the failing test names the field).

---

## Task 2: Pure cleaning/formatting helpers (TDD)

**Files:** Create `services/data-ingestion/infra_atlas/almanac_clean.py`; Test `services/data-ingestion/tests/test_build_country_almanac.py`

- [ ] **Step 1: Write failing tests**
```python
# services/data-ingestion/tests/test_build_country_almanac.py
from infra_atlas.almanac_clean import (
    clean_html, latest_year_value, format_composite, is_plausible_capital,
)

def test_clean_html_strips_tags_and_unescapes():
    assert clean_html("<b>note:</b> a &amp; b<br>c") == "note: a & b c"
    assert clean_html("<strong>x</strong> <em>y</em>") == "x y"
    assert clean_html("2.3% (2024 est.)") == "2.3% (2024 est.)"  # year suffix kept

def test_latest_year_value_picks_newest():
    field = {
        "Inflation rate (consumer prices) 2023": {"text": "5.9% (2023 est.)"},
        "Inflation rate (consumer prices) 2024": {"text": "2.3% (2024 est.)"},
        "note": "<b>note:</b> annual",
    }
    assert latest_year_value(field) == "2.3% (2024 est.)"

def test_latest_year_value_handles_flat_text():
    assert latest_year_value({"text": "$4.6 trillion (2024 est.)"}) == "$4.6 trillion (2024 est.)"

def test_format_composite():
    field = {
        "agriculture": {"text": "0.8% (2024 est.)"},
        "industry": {"text": "25.8% (2024 est.)"},
        "services": {"text": "63.9% (2024 est.)"},
        "note": "x",
    }
    assert format_composite(field, ["agriculture", "industry", "services"]) == (
        "agriculture 0.8% (2024 est.) · industry 25.8% (2024 est.) · services 63.9% (2024 est.)"
    )

def test_is_plausible_capital():
    # Berlin near Germany centroid → plausible
    assert is_plausible_capital(52.52, 13.40, 51.0, 9.0) is True
    # out of range
    assert is_plausible_capital(-13.28, 27.14, 24.2, -12.9) is False  # swapped El Aaiún, far
    assert is_plausible_capital(95.0, 0.0, 0.0, 0.0) is False          # lat out of range
```
- [ ] **Step 2: Run, expect FAIL** — `cd services/data-ingestion && uv run pytest tests/test_build_country_almanac.py -q` → ImportError.
- [ ] **Step 3: Implement**
```python
# services/data-ingestion/infra_atlas/almanac_clean.py
from __future__ import annotations
import html
import math
import re
from html.parser import HTMLParser

class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
    def handle_data(self, data: str) -> None:
        self.parts.append(data)
    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("br", "p", "li"):
            self.parts.append(" ")

_WS = re.compile(r"\s+")

def clean_html(value: str) -> str:
    s = _Stripper()
    s.feed(html.unescape(value))
    return _WS.sub(" ", "".join(s.parts)).strip()

def latest_year_value(field: dict) -> str:
    if "text" in field:
        return clean_html(str(field["text"]))
    # nested year-keyed: pick key with the largest trailing 4-digit year
    best_key, best_year = None, -1
    for k, v in field.items():
        if k == "note" or not isinstance(v, dict) or "text" not in v:
            continue
        m = re.search(r"(\d{4})\b", k)
        year = int(m.group(1)) if m else 0
        if year >= best_year:
            best_key, best_year = k, year
    return clean_html(str(field[best_key]["text"])) if best_key else ""

def format_composite(field: dict, parts: list[str]) -> str:
    out = []
    for p in parts:
        v = field.get(p)
        if isinstance(v, dict) and "text" in v:
            out.append(f"{p} {clean_html(str(v['text']))}")
    return " · ".join(out)

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def is_plausible_capital(lat: float, lon: float, c_lat: float, c_lon: float,
                         max_km: float = 5000.0) -> bool:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return _haversine_km(lat, lon, c_lat, c_lon) <= max_km
```
- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_build_country_almanac.py -q`
- [ ] **Step 5: Commit** — `git commit -m "feat(almanac): pure html/value/coord helpers + tests"`

---

## Task 3: Refresh — produce committed snapshots + crosswalk

**Files:** `build_country_almanac.py` (`refresh`), `infra_atlas/data/iso3_gec.json` (vendored), outputs `infra_atlas/data/{crosswalk,factbook_snapshot,restcountries_snapshot}.json`

> Refresh is network-bound and run occasionally; it is NOT part of CI. It writes committed,
> normalized JSON that Render consumes offline. `topo_id`s are taken from the frontend
> TopoJSON so they match map clicks exactly.

- [ ] **Step 1: Vendor `infra_atlas/data/iso3_gec.json`** — a reviewed `{ "<iso3>": "<gec>" }` map (GEC = Factbook 2-letter code). Source it from the pinned Factbook tarball's region folders (each file is a GEC) cross-referenced with REST `cca3`; seed the known specials: `{"XKX": "kv"}` (Kosovo). Commit it. (This is data, not code — reviewed by hand.)

- [ ] **Step 2: Implement `refresh()`** in `build_country_almanac.py`:
```python
from __future__ import annotations
import io, json, tarfile
from pathlib import Path
import httpx
from infra_atlas.almanac_constants import (
    FACTBOOK_TARBALL_URL, RESTCOUNTRIES_URL, FIELD_MAP,
    REST_FALLBACK_ISO3, MAP_STUB_TOPO_IDS,
)
from infra_atlas.almanac_clean import clean_html, latest_year_value, format_composite

DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_TOPO = (
    Path(__file__).resolve().parents[3] / "services" / "frontend" / "public" / "countries-110m.json"
)

def _topo_ids() -> list[tuple[str, str]]:
    """Return (topo_id, name) for the 177 country features, mirroring
    useCountryHitTest.ts: key = str(f.id) if f.id else properties.name."""
    topo = json.loads(FRONTEND_TOPO.read_text())
    geoms = topo["objects"]["countries"]["geometries"]
    out = []
    for g in geoms:
        name = (g.get("properties") or {}).get("name", "")
        key = str(g["id"]) if g.get("id") is not None else name
        out.append((key, name))
    return out

def _extract_factbook(profile: dict) -> dict:
    facts: dict[str, list] = {s: [] for s in ["profile", "people", "government", "economy", "security"]}
    for spec in FIELD_MAP:
        node = profile
        for k in spec["fb"]:
            node = node.get(k) if isinstance(node, dict) else None
            if node is None:
                break
        if node is None:
            continue
        if spec.get("composite"):
            value = format_composite(node, spec["composite"])
        elif spec.get("multiyear"):
            value = latest_year_value(node)
        elif isinstance(node, dict) and "text" in node:
            value = clean_html(str(node["text"]))
        else:
            continue
        if value:
            facts[spec["section"]].append({"label": spec["label"], "value": value})
    return facts

def refresh(refreshed_at: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    iso3_gec = json.loads((DATA_DIR / "iso3_gec.json").read_text())

    # --- REST snapshot (normalized; latlng = country centroid) ---
    rc = httpx.get(RESTCOUNTRIES_URL, timeout=60).raise_for_status().json()
    rest = {}
    for c in rc:
        iso3 = c.get("cca3")
        if not iso3:
            continue
        cap = (c.get("capital") or [None])[0]
        cap_ll = (c.get("capitalInfo") or {}).get("latlng") or []
        rest[iso3] = {
            "m49": str(c["ccn3"]).zfill(3) if c.get("ccn3") else None,
            "region": c.get("region", ""), "subregion": c.get("subregion", ""),
            "capital": cap, "capital_latlng": cap_ll,
            "centroid": c.get("latlng") or [],
            "area": c.get("area"), "population": c.get("population"),
            "languages": sorted((c.get("languages") or {}).values()),
            "currencies": [
                f"{v.get('name', k)}" + (f" ({v['symbol']})" if v.get("symbol") else "")
                for k, v in sorted((c.get("currencies") or {}).items())
            ],
        }
    (DATA_DIR / "restcountries_snapshot.json").write_text(
        json.dumps({"_refreshed_at": refreshed_at, "countries": rest},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Factbook snapshot (tarball @ pinned SHA → gec→path index → curated extract) ---
    blob = httpx.get(FACTBOOK_TARBALL_URL, timeout=120, follow_redirects=True).raise_for_status().content
    gec_to_facts, gec_seen = {}, {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            # paths like factbook.json-<sha>/<region>/<gec>.json (skip world, comparison, meta)
            parts = m.name.split("/")
            if not (m.isfile() and m.name.endswith(".json") and len(parts) == 3):
                continue
            region, fname = parts[1], parts[2]
            if region in ("", "meta") or fname in ("world.json",):
                continue
            gec = fname[:-5]
            gec_seen[gec] = gec_seen.get(gec, 0) + 1
            gec_to_facts[gec] = _extract_factbook(json.loads(tf.extractfile(m).read()))
    dupes = {g: n for g, n in gec_seen.items() if n > 1}
    assert not dupes, f"non-unique GEC filenames at pinned revision: {dupes}"
    (DATA_DIR / "factbook_snapshot.json").write_text(
        json.dumps({"_refreshed_at": refreshed_at, "by_gec": gec_to_facts},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- Crosswalk: topo_id from frontend TopoJSON; m49/iso3 from REST; gec from iso3_gec ---
    rest_by_m49 = {v["m49"]: iso3 for iso3, v in rest.items() if v["m49"]}
    rows, seen = [], set()
    for topo_id, name in _topo_ids():
        if topo_id in MAP_STUB_TOPO_IDS:
            row = {"name": name, "topo_id": topo_id, "m49": topo_id, "iso3": None, "gec": ""}
        elif topo_id == "Kosovo":
            row = {"name": "Kosovo", "topo_id": "Kosovo", "m49": "Kosovo", "iso3": "XKX", "gec": "kv"}
        else:  # numeric M49 topo_id
            iso3 = rest_by_m49.get(topo_id.zfill(3))
            row = {"name": name, "topo_id": topo_id, "m49": topo_id,
                   "iso3": iso3, "gec": iso3_gec.get(iso3, "") if iso3 else ""}
        assert row["topo_id"] not in seen, f"duplicate topo_id {row['topo_id']}"
        seen.add(row["topo_id"])
        rows.append(row)
    (DATA_DIR / "crosswalk.json").write_text(
        json.dumps({"_refreshed_at": refreshed_at, "countries": rows},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```
- [ ] **Step 3: Run refresh once** — `cd services/data-ingestion && uv run odin-infra-atlas almanac --refresh --refreshed-at 2026-06-01` (after Task 6 wires the CLI; until then call `refresh("2026-06-01")` via `uv run python -c`).
- [ ] **Step 4: Sanity-check + commit the three snapshots** — assert `crosswalk.json` has 177 entries, unique topo_ids, and `[r["topo_id"] for r in crosswalk]` equals `[k for k,_ in _topo_ids()]`. Commit `iso3_gec.json` + the three snapshots: `git commit -m "data(almanac): vendored crosswalk + factbook/restcountries snapshots (rev 8662a8b)"`.

---

## Task 4: Render — build the seed (offline, deterministic)

**Files:** `build_country_almanac.py` (`render`); reads the snapshots + `services/backend/data/country_almanac_overrides.json`; writes `services/backend/data/country_almanac.json`.

- [ ] **Step 1: Create `services/backend/data/country_almanac_overrides.json`**
```json
{
  "ESH": { "capital": { "name": "El Aaiún", "lat": 27.15, "lon": -13.20 } }
}
```
- [ ] **Step 2: Failing test** (render is deterministic + applies coverage rules) — append to `tests/test_build_country_almanac.py`:
```python
def test_render_is_deterministic_and_covers(tmp_path, monkeypatch):
    from infra_atlas import build_country_almanac as b
    out1 = tmp_path / "a.json"; out2 = tmp_path / "b.json"
    b.render(out_path=out1, refreshed_at="2026-06-01")
    b.render(out_path=out2, refreshed_at="2026-06-01")
    assert out1.read_text() == out2.read_text()           # byte-identical
    seed = __import__("json").loads(out1.read_text())
    assert len(seed["countries"]) == 177
    ids = [c["id"] for c in seed["countries"]]
    assert len(ids) == len(set(ids))                       # no id collision
    assert seed["_meta"]["factbook_revision"]
```
- [ ] **Step 3: Run, expect FAIL** (no `render`).
- [ ] **Step 4: Implement `render()`**
```python
SEED_OUT = Path(__file__).resolve().parents[3] / "services" / "backend" / "data" / "country_almanac.json"
OVERRIDES = SEED_OUT.parent / "country_almanac_overrides.json"

def _norm(s: str) -> str:
    return s.strip().upper()

def render(out_path: Path = SEED_OUT, refreshed_at: str | None = None) -> int:
    from infra_atlas.almanac_constants import (
        FACTBOOK_REVISION, FACTBOOK_REVISION_DATE, CIA_SUNSET_DATE,
        MAX_CAPITAL_CENTROID_DISTANCE_KM,
    )
    from infra_atlas.almanac_clean import is_plausible_capital
    cross = json.loads((DATA_DIR / "crosswalk.json").read_text())
    fb = json.loads((DATA_DIR / "factbook_snapshot.json").read_text())["by_gec"]
    rest = json.loads((DATA_DIR / "restcountries_snapshot.json").read_text())["countries"]
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    refreshed = refreshed_at or fb_meta_or(cross)  # explicit; no clock

    countries = []
    for row in cross["countries"]:
        iso3, gec, topo = row["iso3"], row["gec"], row["topo_id"]
        rc = rest.get(iso3, {}) if iso3 else {}
        facts = {s: [] for s in ["profile", "people", "government", "economy", "security"]}
        for sec, items in (fb.get(gec) or {}).items():
            facts[sec] = [dict(i) for i in items]
        # REST-derived facts (only labels not already from Factbook, per section)
        _add(facts, "profile", "Area", _km2(rc.get("area")))
        _add(facts, "people", "Population", _commas(rc.get("population")))
        _add(facts, "people", "Languages", ", ".join(rc.get("languages") or []))
        _add(facts, "economy", "Currency", ", ".join(rc.get("currencies") or []))
        # capital + plausibility
        capital = None
        ll = rc.get("capital_latlng") or []
        cen = rc.get("centroid") or []
        if rc.get("capital") and len(ll) == 2 and len(cen) == 2 and is_plausible_capital(
            ll[0], ll[1], cen[0], cen[1], MAX_CAPITAL_CENTROID_DISTANCE_KM):
            capital = {"name": rc["capital"], "lat": ll[0], "lon": ll[1]}
        entry = {
            "id": topo, "iso3": iso3, "m49": row["m49"], "name": row["name"],
            "region": rc.get("region", ""), "subregion": rc.get("subregion", ""),
            "capital": capital, "facts": facts,
            "updated_at": refreshed, "source_note": _note(iso3, gec),
        }
        _apply_override(entry, overrides.get(iso3) or overrides.get(topo))
        countries.append(entry)

    seed = {
        "_meta": {"factbook_revision": FACTBOOK_REVISION,
                  "factbook_revision_date": FACTBOOK_REVISION_DATE,
                  "cia_sunset_date": CIA_SUNSET_DATE, "refreshed_at": refreshed,
                  "builder": "odin-infra-atlas almanac"},
        "countries": countries,
    }
    out_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(countries)
```
  with small helpers in the same module: `_add(facts, section, label, value)` (append `{label,value}` only if `value` truthy AND `label` not already present in ANY section — global dedup); `_apply_override(entry, ov)` (merge `region`/`subregion`/`capital`/`facts[section]`, override wins per label); `_km2(a)`→`f"{int(a):,} km²"` or `""`; `_commas(n)`→`f"{n:,}"` or `""`; `_note(iso3,gec)`→`"CIA World Factbook" if gec else "REST Countries (no Factbook profile)"`; `fb_meta_or(cross)`→`cross.get("_refreshed_at","")`.
- [ ] **Step 5: Run, expect PASS.**
- [ ] **Step 6: Commit** — `git commit -m "feat(almanac): deterministic render (snapshots+overrides → seed)"`

---

## Task 5: CLI `almanac` subcommand

**Files:** Modify `services/data-ingestion/infra_atlas/cli.py`

- [ ] **Step 1: Add the command** (after the existing imports add `from infra_atlas.build_country_almanac import refresh as almanac_refresh, render as almanac_render`):
```python
@cli.command()
@click.option("--refresh", "do_refresh", is_flag=True, help="Fetch sources + write snapshots (network).")
@click.option("--refreshed-at", "refreshed_at", default=None,
              help="YYYY-MM-DD; MANDATORY with --refresh (no clock access).")
def almanac(do_refresh: bool, refreshed_at: str | None) -> None:
    """Render services/backend/data/country_almanac.json (offline). --refresh updates snapshots."""
    if do_refresh:
        if not refreshed_at:
            raise click.UsageError("--refreshed-at YYYY-MM-DD is required with --refresh")
        almanac_refresh(refreshed_at)
        click.echo(f"Refreshed snapshots @ {refreshed_at}")
    n = almanac_render(refreshed_at=refreshed_at)
    click.echo(f"Rendered {n} countries → services/backend/data/country_almanac.json")
```
- [ ] **Step 2: Verify** — `cd services/data-ingestion && uv run odin-infra-atlas almanac --help` shows the command; `uv run odin-infra-atlas almanac --refresh` without `--refreshed-at` errors with the UsageError.
- [ ] **Step 3: Commit** — `git commit -m "feat(almanac): odin-infra-atlas almanac CLI command"`

---

## Task 6: Package-data for vendored JSON

**Files:** Modify `services/data-ingestion/pyproject.toml` (`[tool.hatch.build.targets.wheel].include`)

- [ ] **Step 1:** add `"infra_atlas/data/*.json"` to the `include` list (alongside the existing `infra_atlas/seeds/*.json`).
- [ ] **Step 2:** `cd services/data-ingestion && uv build 2>&1 | tail -3` (or `uv run python -c "import infra_atlas"`); confirm no error.
- [ ] **Step 3: Commit** — `git commit -m "build(data-ingestion): package infra_atlas/data/*.json"`

---

## Task 7: Regenerate seed + seed-integrity guardrails

**Files:** Modify `services/backend/tests/test_almanac_seed_integrity.py`; regenerate `services/backend/data/country_almanac.json`.

- [ ] **Step 1: Regenerate** — `cd services/data-ingestion && uv run odin-infra-atlas almanac --refresh --refreshed-at 2026-06-01` (writes snapshots + seed).
- [ ] **Step 2: Extend the integrity test** (replace the iso3/enrichment assertions with coverage-class logic):
```python
import json
from app.services.country_almanac import DEFAULT_ALMANAC_PATH

REST_FALLBACK = {"ESH", "PSE"}        # no usable single Factbook profile
PARTIAL = {"ATA"}                     # Factbook has no economy
MAP_STUB_NAMES = {"N. Cyprus", "Somaliland"}

def _data():
    return json.loads(DEFAULT_ALMANAC_PATH.read_text(encoding="utf-8"))

def test_exactly_177_and_unique_ids():
    cs = _data()["countries"]
    assert len(cs) == 177
    ids = [c["id"] for c in cs]
    assert len(ids) == len(set(ids)), "duplicate seed id (map collision)"

def test_factbook_countries_have_economy_and_security():
    cs = _data()["countries"]
    def has(c, sec): return len(c["facts"][sec]) > 0
    offenders = []
    for c in cs:
        if c["iso3"] in REST_FALLBACK or c["iso3"] in PARTIAL or c["name"] in MAP_STUB_NAMES:
            continue  # justified coverage classes
        if not (has(c, "economy") and has(c, "security")):
            offenders.append(c["name"])
    assert offenders == [], f"Factbook-profile countries missing economy/security: {offenders}"

def test_no_raw_html_in_values():
    bad = [c["name"] for c in _data()["countries"]
           for sec in c["facts"].values() for f in sec if "<" in f["value"]]
    assert bad == []

def test_capital_coverage_and_meta():
    cs = _data()["countries"]
    assert sum(1 for c in cs if c.get("capital")) >= 170
    assert _data()["_meta"]["factbook_revision"]
```
- [ ] **Step 3: Run** — `cd services/backend && NEO4J_PASSWORD=dummy uv run pytest tests/test_almanac_seed_integrity.py -q` → PASS.
- [ ] **Step 4: Full backend suite** — `NEO4J_PASSWORD=dummy uv run pytest -q` → green (≥269). `uvx ruff@0.15.15 check tests/test_almanac_seed_integrity.py`.
- [ ] **Step 5: data-ingestion suite + ruff** — `cd services/data-ingestion && uv run pytest -q` (incl. new builder tests) + `uvx ruff@0.15.15 check infra_atlas/`.
- [ ] **Step 6: Commit** — `git add services/backend/data/country_almanac.json services/backend/tests/test_almanac_seed_integrity.py && git commit -m "data(almanac): regenerate seed from Factbook + coverage-class guardrails"`

---

## Task 8: Live verify + finish

- [ ] **Step 1: Container** — `docker cp services/backend/data/country_almanac.json osint-backend-1:/app/data/country_almanac.json` (live; or rely on the compose `data/` mount after a restart).
- [ ] **Step 2: Spot-check via proxy** — `curl -s http://localhost:8080/api/almanac/countries/276 | python3 -m json.tool | head -40` → Germany shows rich economy + security facts. Check `840` (USA), `156` (CHN), `PSE` (REST-fallback baseline), `ESH` (overridden capital).
- [ ] **Step 3: Finish branch** — push, open PR. Use `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:** §3.1 Factbook pinned snapshot → Task 1/3. §3.2 REST snapshot → Task 3. §3.3 crosswalk + topo_id (M49/name) + 3-stub unique keys + Kosovo XKX/kv + PSE gec="" → Task 3. §4 builder refresh/render split, no-readback → Tasks 3/4. §5 field map + HTML clean + multiyear/composite + coord plausibility (5000 km) → Tasks 1/2/4. §6 overrides applied last + global dedup → Task 4. §7 baseline on main → header. §8 `_meta` → Task 4. §9 tests (builder unit + coverage-class integrity, 177, no-collision, no-HTML, ≥170 capital) → Tasks 2/4/7. CLI `odin-infra-atlas almanac` + `--refreshed-at` mandatory → Task 5. Package-data → Task 6.

**Placeholder scan:** the `fb` key paths (Task 1) are the curated targets; Task 3's extraction is TDD-driven against the real snapshot and the field test (Task 7 `test_factbook_countries_have_economy_and_security`) fails loudly if a path is wrong at the pinned revision — flagged inline, not a silent TBD. `iso3_gec.json` is vendored data sourced from the tarball file index (Task 3 Step 1). No other placeholders.

**Type consistency:** `clean_html`/`latest_year_value`/`format_composite`/`is_plausible_capital` signatures match between Task 2 (def) and Tasks 3/4 (use). Seed entry shape matches `app/models/almanac.py` (`id`,`iso3`,`m49`,`name`,`region`,`subregion`,`capital{name,lat,lon}`,`facts{5 sections}`,`updated_at`,`source_note`). `_meta` is additive (loader ignores). `topo_id` realized via `id` (no new model field).
