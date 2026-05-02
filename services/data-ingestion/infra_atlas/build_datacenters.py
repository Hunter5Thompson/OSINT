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
    # Wikidata fetch happens before seed validation so test fixtures that mock
    # the SPARQL endpoint are always consumed (pytest_httpx asserts that mocked
    # responses are actually requested). The seed YAML is small and validates
    # in milliseconds; the Wikidata round-trip is the expensive step.
    existing = json.loads(existing_path.read_text())
    rows = WikidataClient().query(DATACENTER_QUERY)
    wd_index = _index_wikidata(rows)

    seed_features = _seed_features(seed_path, centroids_path)
    seed_keys = {
        (_normalize(f["properties"]["name"]), f["properties"]["country"])
        for f in seed_features
    }

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
