"""Refresh pinned CIA Factbook + REST Countries snapshots and the topo crosswalk.

Network-bound build step. Fetches:
  * GeoNames countryInfo.txt -> ISO3<->GEC (FIPS 10-4) candidate map
  * the pinned Factbook .json tarball  -> per-GEC normalized fact snapshot
  * REST Countries v3.1               -> per-ISO3 normalized snapshot

and writes committed JSON artifacts under ``infra_atlas/data/``.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import httpx

from infra_atlas.almanac_clean import (
    clean_html,
    format_composite,
    is_plausible_capital,
    latest_year_value,
)
from infra_atlas.almanac_constants import (
    CIA_SUNSET_DATE,
    FACTBOOK_REVISION,
    FACTBOOK_REVISION_DATE,
    FACTBOOK_TARBALL_URL,
    FIELD_MAP,
    MAP_STUB_TOPO_IDS,
    MAX_CAPITAL_CENTROID_DISTANCE_KM,
    REST_FALLBACK_ISO3,
    RESTCOUNTRIES_URL,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_TOPO = (
    Path(__file__).resolve().parents[3]
    / "services"
    / "frontend"
    / "public"
    / "countries-110m.json"
)
SEED_OUT = (
    Path(__file__).resolve().parents[3] / "services" / "backend" / "data" / "country_almanac.json"
)
OVERRIDES = SEED_OUT.parent / "country_almanac_overrides.json"
_SECTIONS = ["profile", "people", "government", "economy", "security"]
GEONAMES_COUNTRYINFO_URL = "https://download.geonames.org/export/dump/countryInfo.txt"
# Kosovo: no FIPS 10-4 code in GeoNames; CIA Factbook uses GEC "kv".
KOSOVO_ISO3 = "XKX"
KOSOVO_GEC = "kv"


def _topo_ids() -> list[tuple[str, str]]:
    topo = json.loads(FRONTEND_TOPO.read_text())
    geoms = topo["objects"]["countries"]["geometries"]
    out = []
    for g in geoms:
        name = (g.get("properties") or {}).get("name", "")
        key = str(g["id"]) if g.get("id") is not None else name
        out.append((key, name))
    return out


def _write_json(path: Path, obj: object) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fetch_factbook_tar(client: httpx.Client) -> bytes:
    resp = client.get(FACTBOOK_TARBALL_URL, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _factbook_gec_set(tar_bytes: bytes) -> set[str]:
    """Valid GEC codes = the ``<gec>.json`` profile filenames in the tarball."""
    gecs: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/")
            if len(parts) != 3 or not parts[2].endswith(".json"):
                continue
            region, filename = parts[1], parts[2]
            if region in ("", "meta") or filename == "world.json":
                continue
            gecs.add(filename[:-5])
    return gecs


def _build_iso3_gec(client: httpx.Client, valid_gec: set[str]) -> dict[str, str]:
    """Fetch GeoNames ISO3<->FIPS, validate against the Factbook, vendor the map."""
    resp = client.get(GEONAMES_COUNTRYINFO_URL)
    resp.raise_for_status()
    text = resp.text
    candidates: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 4:
            continue
        iso3, fips = cols[1].strip(), cols[3].strip()
        if iso3 and fips:
            candidates[iso3] = fips.lower()

    iso3_gec: dict[str, str] = {}
    dropped: list[tuple[str, str]] = []
    for iso3, gec in candidates.items():
        if gec in valid_gec:
            iso3_gec[iso3] = gec
        else:
            dropped.append((iso3, gec))

    # Known special case absent from GeoNames FIPS column.
    iso3_gec[KOSOVO_ISO3] = KOSOVO_GEC

    if dropped:
        print(
            f"[iso3_gec] dropped {len(dropped)} candidate(s) with no Factbook "
            f"profile: {sorted(dropped)}"
        )
    iso3_gec = dict(sorted(iso3_gec.items()))
    _write_json(DATA_DIR / "iso3_gec.json", iso3_gec)
    print(f"[iso3_gec] wrote {len(iso3_gec)} ISO3->GEC entries")
    return iso3_gec


def _fetch_restcountries(client: httpx.Client) -> list[dict]:
    """GET the pinned REST URL; fall back to a two-batch merge if the API
    rejects >10 fields (HTTP 400 on /all). Same 12 fields either way."""
    resp = client.get(RESTCOUNTRIES_URL)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code != 400:
        resp.raise_for_status()

    base, _, query = RESTCOUNTRIES_URL.partition("?fields=")
    fields = query.split(",")
    half = (len(fields) + 1) // 2
    batch1 = ["cca3", *fields[:half]]
    batch2 = ["cca3", *fields[half:]]
    merged: dict[str, dict] = {}
    for batch in (batch1, batch2):
        rows = client.get(f"{base}?fields={','.join(dict.fromkeys(batch))}").json()
        for row in rows:
            iso3 = row.get("cca3")
            if iso3:
                merged.setdefault(iso3, {}).update(row)
    print(f"[rest] pinned URL returned 400; merged two field-batches -> {len(merged)}")
    return list(merged.values())


def _build_rest_snapshot(rows: list[dict]) -> dict[str, dict]:
    countries: dict[str, dict] = {}
    for row in rows:
        iso3 = row.get("cca3")
        if not iso3:
            continue
        ccn3 = row.get("ccn3")
        capital_list = row.get("capital") or []
        capital_info = row.get("capitalInfo") or {}
        currencies = row.get("currencies") or {}
        languages = row.get("languages") or {}
        currency_strs = []
        for code in sorted(currencies):
            cur = currencies[code] or {}
            name = cur.get("name", "")
            symbol = cur.get("symbol")
            currency_strs.append(f"{name} ({symbol})" if symbol else name)
        countries[iso3] = {
            "m49": str(ccn3).zfill(3) if ccn3 else None,
            "region": row.get("region"),
            "subregion": row.get("subregion"),
            "capital": capital_list[0] if capital_list else None,
            "capital_latlng": capital_info.get("latlng"),
            "centroid": row.get("latlng"),
            "area": row.get("area"),
            "population": row.get("population"),
            "languages": sorted(languages.values()),
            "currencies": currency_strs,
        }
    return countries


def _extract_factbook(profile: dict) -> dict:
    facts = {s: [] for s in ["profile", "people", "government", "economy", "security"]}
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


def _build_factbook_snapshot(tar_bytes: bytes) -> dict[str, dict]:
    by_gec: dict[str, dict] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/")
            if len(parts) != 3 or not parts[2].endswith(".json"):
                continue
            region, filename = parts[1], parts[2]
            if region in ("", "meta") or filename == "world.json":
                continue
            gec = filename[:-5]
            assert gec not in by_gec, f"duplicate GEC filename: {gec}"
            data = json.loads(tf.extractfile(m).read())
            by_gec[gec] = _extract_factbook(data)
    return by_gec


def _km2(a: float | None) -> str:
    return f"{round(a):,} km²" if a else ""


def _commas(n: int | None) -> str:
    return f"{n:,}" if n else ""


def _note(gec: str) -> str:
    return "CIA World Factbook" if gec else "REST Countries (no Factbook profile)"


def _add(facts: dict, section: str, label: str, value: str) -> None:
    """Append {label,value} to section only if value truthy.

    Also skips if label already present in ANY section (global dedup).
    """
    if not value:
        return
    for sec in facts.values():
        if any(f["label"] == label for f in sec):
            return
    facts[section].append({"label": label, "value": value})


def _apply_override(entry: dict, ov: dict | None) -> None:
    if not ov:
        return
    for key in ("region", "subregion", "capital"):
        if key in ov:
            entry[key] = ov[key]
    for section, items in (ov.get("facts") or {}).items():
        if section not in _SECTIONS:
            continue
        existing = entry["facts"].setdefault(section, [])
        for item in items:  # override wins per label
            existing[:] = [f for f in existing if f["label"] != item["label"]]
            existing.append(item)


def render(out_path: Path = SEED_OUT, refreshed_at: str | None = None) -> int:
    cross = json.loads((DATA_DIR / "crosswalk.json").read_text())
    fb = json.loads((DATA_DIR / "factbook_snapshot.json").read_text())["by_gec"]
    rest = json.loads((DATA_DIR / "restcountries_snapshot.json").read_text())["countries"]
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    refreshed = refreshed_at or cross.get("_refreshed_at", "")

    countries = []
    for row in cross["countries"]:
        iso3, gec, topo = row["iso3"], row["gec"], row["topo_id"]
        rc = rest.get(iso3, {}) if iso3 else {}
        facts: dict[str, list] = {s: [] for s in _SECTIONS}
        for sec, items in (fb.get(gec) or {}).items():
            if sec in facts:
                facts[sec] = [dict(i) for i in items]
        _add(facts, "profile", "Area", _km2(rc.get("area")))
        _add(facts, "people", "Population", _commas(rc.get("population")))
        _add(facts, "people", "Languages", ", ".join(rc.get("languages") or []))
        _add(facts, "economy", "Currency", ", ".join(rc.get("currencies") or []))
        capital = None
        ll = rc.get("capital_latlng") or []
        cen = rc.get("centroid") or []
        if (
            rc.get("capital")
            and len(ll) == 2
            and len(cen) == 2
            and is_plausible_capital(ll[0], ll[1], cen[0], cen[1], MAX_CAPITAL_CENTROID_DISTANCE_KM)
        ):
            capital = {"name": rc["capital"], "lat": ll[0], "lon": ll[1]}
        entry: dict = {
            "id": topo,
            "iso3": iso3,
            "m49": row["m49"],
            "name": row["name"],
            "region": rc.get("region", ""),
            "subregion": rc.get("subregion", ""),
            "capital": capital,
            "facts": facts,
            "updated_at": refreshed,
            "source_note": _note(gec),
        }
        _apply_override(entry, overrides.get(iso3) or overrides.get(topo))
        countries.append(entry)

    seed = {
        "_meta": {
            "factbook_revision": FACTBOOK_REVISION,
            "factbook_revision_date": FACTBOOK_REVISION_DATE,
            "cia_sunset_date": CIA_SUNSET_DATE,
            "refreshed_at": refreshed,
            "builder": "odin-infra-atlas almanac",
        },
        "countries": countries,
    }
    out_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(countries)


def refresh(refreshed_at: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0) as client:
        tar_bytes = _fetch_factbook_tar(client)
        valid_gec = _factbook_gec_set(tar_bytes)
        iso3_gec = _build_iso3_gec(client, valid_gec)

        rest_rows = _fetch_restcountries(client)

    rest_countries = _build_rest_snapshot(rest_rows)
    _write_json(
        DATA_DIR / "restcountries_snapshot.json",
        {"_refreshed_at": refreshed_at, "countries": rest_countries},
    )

    by_gec = _build_factbook_snapshot(tar_bytes)
    _write_json(
        DATA_DIR / "factbook_snapshot.json",
        {"_refreshed_at": refreshed_at, "by_gec": by_gec},
    )

    rest_by_m49 = {
        v["m49"]: iso3 for iso3, v in rest_countries.items() if v.get("m49")
    }
    countries = []
    seen: set[str] = set()
    for topo_id, name in _topo_ids():
        assert topo_id not in seen, f"duplicate topo_id: {topo_id}"
        seen.add(topo_id)
        if topo_id in MAP_STUB_TOPO_IDS:
            entry = {
                "name": name,
                "topo_id": topo_id,
                "m49": topo_id,
                "iso3": None,
                "gec": "",
            }
        elif topo_id == "Kosovo":
            entry = {
                "name": "Kosovo",
                "topo_id": "Kosovo",
                "m49": "Kosovo",
                "iso3": KOSOVO_ISO3,
                "gec": KOSOVO_GEC,
            }
        else:
            iso3 = rest_by_m49.get(topo_id.zfill(3))
            entry = {
                "name": name,
                "topo_id": topo_id,
                "m49": topo_id,
                "iso3": iso3,
                "gec": "" if iso3 in REST_FALLBACK_ISO3 else iso3_gec.get(iso3, ""),
            }
        countries.append(entry)

    _write_json(
        DATA_DIR / "crosswalk.json",
        {"_refreshed_at": refreshed_at, "countries": countries},
    )
    print(f"[crosswalk] wrote {len(countries)} entries")
