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
from dataclasses import dataclass
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
