"""Geopolitical hotspot endpoints."""
# ruff: noqa: E501 — DEFAULT_HOTSPOTS is a curated one-row-per-entry data table; keep entries on single lines.

import math
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.models.hotspot import Hotspot

router = APIRouter(prefix="/hotspots", tags=["hotspots"])

# Default hotspots - updated by data-ingestion service via Redis
DEFAULT_HOTSPOTS: list[dict[str, Any]] = [
    {"id": "ukr-001", "name": "Ukraine-Russia Conflict Zone", "latitude": 48.3, "longitude": 37.8, "region": "Eastern Europe", "threat_level": "CRITICAL", "description": "Active armed conflict between Russia and Ukraine", "sources": ["OSCE", "ISW", "Reuters"]},
    {"id": "twn-001", "name": "Taiwan Strait", "latitude": 24.0, "longitude": 121.0, "region": "East Asia", "threat_level": "HIGH", "description": "Cross-strait tensions between China and Taiwan", "sources": ["CSIS", "Reuters", "SCMP"]},
    {"id": "scs-001", "name": "South China Sea", "latitude": 12.0, "longitude": 114.0, "region": "Southeast Asia", "threat_level": "HIGH", "description": "Territorial disputes and militarization of artificial islands", "sources": ["AMTI", "Reuters", "CSIS"]},
    {"id": "kor-001", "name": "Korean DMZ", "latitude": 38.0, "longitude": 127.0, "region": "East Asia", "threat_level": "ELEVATED", "description": "Ongoing tensions between North and South Korea", "sources": ["38 North", "NKNews", "Yonhap"]},
    {"id": "gaz-001", "name": "Gaza-Israel", "latitude": 31.4, "longitude": 34.4, "region": "Middle East", "threat_level": "CRITICAL", "description": "Armed conflict in Gaza Strip", "sources": ["UNRWA", "Reuters", "Al Jazeera"]},
    {"id": "ymn-001", "name": "Yemen / Red Sea", "latitude": 15.0, "longitude": 42.0, "region": "Middle East", "threat_level": "HIGH", "description": "Houthi attacks on Red Sea shipping, Saudi-led coalition operations", "sources": ["ACLED", "Reuters", "Maritime Executive"]},
    {"id": "irn-001", "name": "Iran Nuclear Sites", "latitude": 32.7, "longitude": 51.7, "region": "Middle East", "threat_level": "HIGH", "description": "Nuclear program tensions and IAEA inspections", "sources": ["IAEA", "Arms Control Assoc", "Reuters"]},
    {"id": "syr-001", "name": "Syria", "latitude": 35.0, "longitude": 38.0, "region": "Middle East", "threat_level": "ELEVATED", "description": "Ongoing civil war, multiple foreign military operations", "sources": ["SOHR", "Reuters", "UN OCHA"]},
    {"id": "lby-001", "name": "Libya", "latitude": 32.9, "longitude": 13.1, "region": "North Africa", "threat_level": "ELEVATED", "description": "Political instability, rival governments", "sources": ["ICG", "UNSMIL", "Reuters"]},
    {"id": "som-001", "name": "Somalia / Horn of Africa", "latitude": 2.0, "longitude": 45.3, "region": "East Africa", "threat_level": "HIGH", "description": "Al-Shabaab insurgency, piracy, drought", "sources": ["AMISOM", "ICG", "Reuters"]},
    {"id": "sdn-001", "name": "Sudan", "latitude": 15.6, "longitude": 32.5, "region": "East Africa", "threat_level": "CRITICAL", "description": "Civil war between SAF and RSF", "sources": ["ACLED", "ICG", "Reuters"]},
    {"id": "mmr-001", "name": "Myanmar", "latitude": 19.8, "longitude": 96.2, "region": "Southeast Asia", "threat_level": "HIGH", "description": "Military coup, resistance movement, ethnic conflicts", "sources": ["AAPP", "ICG", "Reuters"]},
    {"id": "ksh-001", "name": "Kashmir", "latitude": 34.1, "longitude": 74.8, "region": "South Asia", "threat_level": "ELEVATED", "description": "India-Pakistan tensions over disputed territory", "sources": ["ICG", "Reuters", "The Hindu"]},
    {"id": "eth-001", "name": "Ethiopia (Tigray/Amhara)", "latitude": 13.5, "longitude": 39.5, "region": "East Africa", "threat_level": "ELEVATED", "description": "Post-conflict tensions, humanitarian crisis", "sources": ["ACLED", "ICG", "Reuters"]},
    {"id": "drc-001", "name": "DR Congo (Kivu)", "latitude": -1.7, "longitude": 29.2, "region": "Central Africa", "threat_level": "HIGH", "description": "M23 insurgency, militia violence, mineral exploitation", "sources": ["MONUSCO", "ICG", "Reuters"]},
    {"id": "shl-001", "name": "Sahel Region", "latitude": 14.5, "longitude": -1.5, "region": "West Africa", "threat_level": "HIGH", "description": "Jihadist insurgencies, military coups (Mali, Burkina Faso, Niger)", "sources": ["ACLED", "ICG", "Reuters"]},
    {"id": "arc-001", "name": "Arctic Disputes", "latitude": 75.0, "longitude": 40.0, "region": "Arctic", "threat_level": "MODERATE", "description": "Resource and territorial claims, military buildup", "sources": ["Arctic Council", "CSIS", "Reuters"]},
    {"id": "hrm-001", "name": "Strait of Hormuz", "latitude": 26.6, "longitude": 56.3, "region": "Middle East", "threat_level": "ELEVATED", "description": "Critical oil chokepoint, Iran-US naval tensions", "sources": ["IISS", "Maritime Executive", "Reuters"]},
    {"id": "blt-001", "name": "Baltic / Kaliningrad", "latitude": 55.0, "longitude": 21.0, "region": "Northern Europe", "threat_level": "ELEVATED", "description": "NATO-Russia tensions, Suwalki Gap concerns", "sources": ["NATO", "RUSI", "Reuters"]},
    {"id": "vnz-001", "name": "Venezuela-Guyana (Essequibo)", "latitude": 6.0, "longitude": -59.0, "region": "South America", "threat_level": "MODERATE", "description": "Territorial dispute over Essequibo region", "sources": ["ICJ", "Reuters", "BBC"]},
]


def _normalize_threat_level(value: Any) -> str:
    raw = str(value or "").strip().upper()
    mapping = {
        "CRITICAL": "CRITICAL",
        "HIGH": "HIGH",
        "ELEVATED": "ELEVATED",
        "MODERATE": "MODERATE",
        "LOW": "MODERATE",
    }
    return mapping.get(raw, "MODERATE")


def _required_coord(raw: dict[str, Any], keys: tuple[str, ...], *, limit: float) -> float:
    for key in keys:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"invalid {key}")
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"invalid {key}") from exc
        if not math.isfinite(number) or not -limit <= number <= limit:
            raise ValueError(f"{key} out of range")
        return number
    raise ValueError("missing coordinate")


def _sources(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _normalize_hotspot(raw: dict[str, Any]) -> Hotspot:
    hotspot_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    if not hotspot_id or not name:
        raise ValueError("hotspot identity is incomplete")
    normalized: dict[str, Any] = {
        "id": hotspot_id,
        "name": name,
        "latitude": _required_coord(raw, ("latitude", "lat"), limit=90),
        "longitude": _required_coord(raw, ("longitude", "lon"), limit=180),
        "region": str(raw.get("region", "")),
        "threat_level": _normalize_threat_level(raw.get("threat_level")),
        "description": str(raw.get("description", "")),
        "sources": _sources(raw.get("sources", [])),
    }
    updated = raw.get("last_updated", raw.get("updated_at"))
    if updated is not None:
        normalized["last_updated"] = updated
    return Hotspot(**normalized)


def _hotspots_from_rows(rows: object) -> list[Hotspot]:
    if not isinstance(rows, list):
        return []
    items: list[Hotspot] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            items.append(_normalize_hotspot(raw))
        except (ValidationError, ValueError, TypeError):
            continue
    return items


@router.get("", response_model=list[Hotspot])
async def get_hotspots(request: Request) -> list[Hotspot]:
    cached = _hotspots_from_rows(await request.app.state.cache.get("hotspots:all"))
    if cached:
        return cached

    # Backward-compatible fallback for per-hotspot cache keys.
    hotspot_ids = await request.app.state.cache.get("hotspot:index")
    if isinstance(hotspot_ids, list) and hotspot_ids:
        items: list[Hotspot] = []
        for hotspot_id in hotspot_ids:
            raw = await request.app.state.cache.get(f"hotspot:{hotspot_id}")
            if isinstance(raw, dict):
                try:
                    items.append(_normalize_hotspot(raw))
                except Exception:
                    continue
        if items:
            return items

    return [_normalize_hotspot(h) for h in DEFAULT_HOTSPOTS]


@router.get("/{hotspot_id}", response_model=Hotspot)
async def get_hotspot(hotspot_id: str, request: Request) -> Hotspot:
    hotspots = await get_hotspots(request)
    for h in hotspots:
        if h.id == hotspot_id:
            return h
    raise HTTPException(status_code=404, detail=f"Hotspot {hotspot_id} not found")
