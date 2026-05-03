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
