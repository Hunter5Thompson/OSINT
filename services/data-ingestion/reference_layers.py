"""Reproducible offline reference-layer export; never labels snapshots as live.

Run from this service: uv run python reference_layers.py INPUT_DIRECTORY OUTPUT_DIRECTORY
The three inputs are pinned by SHA-256 below. No network access occurs here.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sys
from pathlib import Path

from shapely.geometry import Point, shape

NE_SOURCE = "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/"
WRI_SOURCE = "https://github.com/wri/global-power-plant-database/tree/7a91cfbb2a4e272597acbc00506d61fc1ec73b3d"
INPUT_HASHES = {
    "cities.geojson": "9b8e3de09048ef00dfc70357dbb9fa324493f214b5e0ae4daf1aa79a8d10116b",
    "admin1.geojson": "22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5",
    "powerplants.csv": "4b1f93e0fd93664f18684d9b05d0a52ed9658c6a8cf0d21ff2520791379ba7fc",
}


def nuclear_sites(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        if row["primary_fuel"] != "Nuclear":
            continue
        lat, lon = float(row["latitude"]), float(row["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid nuclear reference coordinate")
        capacity = float(row["capacity_mw"]) if row.get("capacity_mw") else None
        if capacity is not None and (not math.isfinite(capacity) or capacity < 0):
            raise ValueError("Invalid capacity")
        result.append(
            dict(
                id=row["gppd_idnr"],
                name=row["name"],
                country=row["country"],
                kind="nuclearPlants",
                latitude=lat,
                longitude=lon,
                capacityMw=capacity,
                source=WRI_SOURCE,
                sourceLabel="WRI Global Power Plant Database · CC BY 4.0",
                note=(
                    "Historical WRI snapshot (2021 release); not live. "
                    "Operating status not verified."
                ),
            )
        )
    return sorted(result, key=lambda site: site["id"])


def region_profiles(regions: dict, cities: dict) -> list[dict]:
    capitals: dict[str, list[dict]] = {}
    for city in cities["features"]:
        props = city["properties"]
        if props["FEATURECLA"] not in {
            "Admin-0 capital",
            "Admin-0 region capital",
            "Admin-1 capital",
            "Admin-1 region capital",
        }:
            continue
        capitals.setdefault(props["ADM0_A3"], []).append(city)
    result = []
    for region in regions["features"]:
        props = region["properties"]
        code = props.get("iso_3166_2")
        if not code or not re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", code) or not props.get("name"):
            continue
        # Do not import a de-facto country assignment that contradicts the
        # source's own ISO subdivision identity (e.g. disputed territories).
        if props.get("iso_a2") != code.split("-")[0]:
            continue
        country = props["adm0_a3"]
        geometry = shape(region["geometry"])
        candidates = [
            city
            for city in capitals.get(country, [])
            if geometry.covers(Point(city["geometry"]["coordinates"]))
        ]
        # Ambiguous matches are not guessed or promoted into a capital claim.
        capital = None
        if len(candidates) == 1:
            city = candidates[0]
            cp = city["properties"]
            lon, lat = city["geometry"]["coordinates"]
            capital = dict(
                name=cp.get("NAME_DE") or cp["NAME"],
                latitude=lat,
                longitude=lon,
                population=cp.get("POP_MAX"),
                timezone=cp.get("TIMEZONE"),
            )
        result.append(
            dict(
                key=f"admin1:iso3166-2:{code}",
                country=country,
                name=props["name"],
                division=props.get("type_en") or "Administrative region",
                capital=capital,
                source=NE_SOURCE,
                sourceLabel="Natural Earth 5.1.2 · public domain",
            )
        )
    # ISO keys duplicated by source geometry cannot serve as unambiguous UI identities.
    counts: dict[str, int] = {}
    for item in result:
        counts[item["key"]] = counts.get(item["key"], 0) + 1
    return sorted(
        [item for item in result if counts[item["key"]] == 1], key=lambda item: item["key"]
    )


def main() -> None:
    source_dir, output_dir = map(Path, sys.argv[1:])
    inputs = {}
    for name, digest in INPUT_HASHES.items():
        payload = (source_dir / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError(f"Source hash mismatch: {name}")
        inputs[name] = payload.decode("utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "nuclear-sites.json": nuclear_sites(
            list(csv.DictReader(io.StringIO(inputs["powerplants.csv"])))
        ),
        "region-profiles.json": region_profiles(
            json.loads(inputs["admin1.geojson"]), json.loads(inputs["cities.geojson"])
        ),
    }
    for name, data in artifacts.items():
        (output_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        print(f"{name}: {len(data)} records")


if __name__ == "__main__":
    main()
