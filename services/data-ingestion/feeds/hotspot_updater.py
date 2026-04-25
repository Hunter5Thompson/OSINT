"""Geopolitical Hotspot Updater — maintains curated hotspot data and updates threat levels."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchText

from config import settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Curated Geopolitical Hotspots (50+)
# ---------------------------------------------------------------------------
HOTSPOTS: list[dict[str, Any]] = [
    # Eastern Europe & Post-Soviet
    {"id": "ua-ru-conflict", "name": "Ukraine/Russia Conflict Zone", "lat": 48.3, "lon": 37.8, "region": "Eastern Europe", "threat_level": "critical", "description": "Active armed conflict between Russia and Ukraine since 2022 full-scale invasion.", "sources": ["liveuamap", "ISW", "FIRMS"]},
    {"id": "transnistria", "name": "Transnistria (Moldova)", "lat": 47.0, "lon": 29.5, "region": "Eastern Europe", "threat_level": "elevated", "description": "Breakaway region of Moldova with Russian military presence.", "sources": ["OSCE", "Crisis Group"]},
    {"id": "nagorno-karabakh", "name": "Nagorno-Karabakh", "lat": 39.8, "lon": 46.8, "region": "Caucasus", "threat_level": "high", "description": "Disputed territory between Armenia and Azerbaijan. 2023 military operation displaced ethnic Armenian population.", "sources": ["Crisis Group", "ACLED"]},
    {"id": "georgia-abkhazia", "name": "Georgia-Abkhazia/South Ossetia", "lat": 42.2, "lon": 43.5, "region": "Caucasus", "threat_level": "elevated", "description": "Russian-occupied breakaway regions of Georgia.", "sources": ["OSCE", "EU Monitoring Mission"]},
    {"id": "baltic-kaliningrad", "name": "Baltic States / Kaliningrad", "lat": 55.0, "lon": 21.0, "region": "Northern Europe", "threat_level": "elevated", "description": "NATO-Russia tension zone around Baltic states and Kaliningrad exclave.", "sources": ["NATO", "RAND"]},
    {"id": "belarus-border", "name": "Belarus-NATO Border", "lat": 53.5, "lon": 25.0, "region": "Eastern Europe", "threat_level": "elevated", "description": "Hybrid warfare and migrant weaponization on Belarus-Poland/Lithuania borders.", "sources": ["Frontex", "NATO"]},

    # Middle East
    {"id": "gaza-israel", "name": "Gaza / Israel", "lat": 31.4, "lon": 34.4, "region": "Middle East", "threat_level": "critical", "description": "Active armed conflict since October 2023 Hamas attack and subsequent Israeli military operations.", "sources": ["OCHA", "UNRWA", "ACLED"]},
    {"id": "west-bank", "name": "West Bank", "lat": 31.9, "lon": 35.2, "region": "Middle East", "threat_level": "high", "description": "Rising settler violence and IDF operations in occupied West Bank.", "sources": ["OCHA", "B'Tselem"]},
    {"id": "lebanon-hezbollah", "name": "Lebanon / Hezbollah", "lat": 33.3, "lon": 35.5, "region": "Middle East", "threat_level": "high", "description": "Cross-border exchange of fire between Hezbollah and Israel along Blue Line.", "sources": ["UNIFIL", "ACLED"]},
    {"id": "syria", "name": "Syria", "lat": 35.0, "lon": 38.0, "region": "Middle East", "threat_level": "high", "description": "Ongoing civil war, ISIS remnants, Turkish operations in north, Israeli strikes.", "sources": ["SOHR", "ACLED", "Crisis Group"]},
    {"id": "yemen-red-sea", "name": "Yemen / Red Sea", "lat": 15.0, "lon": 42.0, "region": "Middle East", "threat_level": "critical", "description": "Houthi attacks on Red Sea shipping; US/UK military strikes on Houthi positions.", "sources": ["UKMTO", "ACLED", "Crisis Group"]},
    {"id": "iran-nuclear", "name": "Iran Nuclear Sites", "lat": 32.7, "lon": 51.7, "region": "Middle East", "threat_level": "high", "description": "Uranium enrichment approaching weapons-grade; IAEA monitoring challenges.", "sources": ["IAEA", "ISIS (nuclear)", "Arms Control Association"]},
    {"id": "iraq-instability", "name": "Iraq (PMF/ISIS)", "lat": 33.3, "lon": 44.4, "region": "Middle East", "threat_level": "elevated", "description": "Iran-backed PMF militias; ISIS remnant attacks; US base targeting.", "sources": ["ACLED", "Crisis Group"]},
    {"id": "strait-of-hormuz", "name": "Strait of Hormuz", "lat": 26.6, "lon": 56.3, "region": "Middle East", "threat_level": "high", "description": "Critical oil chokepoint; Iran seizure of tankers; US naval presence.", "sources": ["UKMTO", "EIA"]},

    # Asia-Pacific
    {"id": "taiwan-strait", "name": "Taiwan Strait", "lat": 24.0, "lon": 121.0, "region": "Asia-Pacific", "threat_level": "high", "description": "PLA military pressure on Taiwan; frequent ADIZ incursions and naval exercises.", "sources": ["Taiwan MND", "CSIS", "IISS"]},
    {"id": "south-china-sea", "name": "South China Sea", "lat": 12.0, "lon": 114.0, "region": "Asia-Pacific", "threat_level": "high", "description": "Territorial disputes involving China, Philippines, Vietnam. Militarized artificial islands.", "sources": ["AMTI/CSIS", "UNCLOS", "Philippine Coast Guard"]},
    {"id": "korean-dmz", "name": "Korean DMZ", "lat": 38.0, "lon": 127.0, "region": "Asia-Pacific", "threat_level": "high", "description": "DPRK nuclear/missile programs; heavily militarized border; periodic provocations.", "sources": ["38 North", "NTI", "ROK JCS"]},
    {"id": "kashmir", "name": "Kashmir", "lat": 34.1, "lon": 74.8, "region": "South Asia", "threat_level": "elevated", "description": "Disputed territory between India and Pakistan with periodic flare-ups.", "sources": ["Crisis Group", "ACLED"]},
    {"id": "myanmar", "name": "Myanmar Civil War", "lat": 19.8, "lon": 96.2, "region": "Southeast Asia", "threat_level": "critical", "description": "Full-scale civil war following 2021 coup; ethnic armed organizations gaining ground against junta.", "sources": ["ACLED", "Crisis Group", "ISP Myanmar"]},
    {"id": "east-china-sea", "name": "East China Sea (Senkaku/Diaoyu)", "lat": 25.7, "lon": 123.5, "region": "Asia-Pacific", "threat_level": "elevated", "description": "China-Japan territorial dispute over Senkaku/Diaoyu islands.", "sources": ["Japan MOD", "CSIS"]},
    {"id": "india-china-lac", "name": "India-China LAC", "lat": 34.5, "lon": 78.0, "region": "South Asia", "threat_level": "elevated", "description": "Line of Actual Control standoff in Ladakh/Aksai Chin. Galwan clash 2020.", "sources": ["Indian MOD", "Crisis Group"]},
    {"id": "afghanistan", "name": "Afghanistan", "lat": 34.5, "lon": 69.2, "region": "South Asia", "threat_level": "high", "description": "Taliban governance; ISIS-K insurgency; humanitarian crisis.", "sources": ["UNAMA", "Crisis Group", "ACLED"]},
    {"id": "philippines-insurgency", "name": "Philippines (Mindanao)", "lat": 7.5, "lon": 124.0, "region": "Southeast Asia", "threat_level": "elevated", "description": "NPA and Islamist militant activity in Mindanao.", "sources": ["ACLED", "Philippine military"]},

    # Africa
    {"id": "sudan-civil-war", "name": "Sudan Civil War", "lat": 15.6, "lon": 32.5, "region": "East Africa", "threat_level": "critical", "description": "Full-scale civil war between SAF and RSF since April 2023; massive displacement.", "sources": ["ACLED", "OCHA", "Crisis Group"]},
    {"id": "ethiopia-tigray", "name": "Ethiopia / Tigray", "lat": 13.5, "lon": 39.5, "region": "East Africa", "threat_level": "elevated", "description": "Post-ceasefire tensions; Amhara insurgency; ENDF operations.", "sources": ["ACLED", "Crisis Group"]},
    {"id": "somalia-horn", "name": "Somalia / Horn of Africa", "lat": 2.0, "lon": 45.3, "region": "East Africa", "threat_level": "high", "description": "Al-Shabaab insurgency; drought and famine; piracy risks.", "sources": ["AMISOM", "ACLED", "IMB"]},
    {"id": "drc-kivu", "name": "DR Congo (Kivu)", "lat": -1.7, "lon": 29.2, "region": "Central Africa", "threat_level": "critical", "description": "M23 offensive backed by Rwanda; dozens of armed groups in eastern DRC.", "sources": ["MONUSCO", "ACLED", "Crisis Group"]},
    {"id": "sahel-region", "name": "Sahel Region (Mali/Burkina/Niger)", "lat": 14.5, "lon": -1.5, "region": "West Africa", "threat_level": "critical", "description": "Jihadist insurgency; military coups; Wagner/Africa Corps presence.", "sources": ["ACLED", "Crisis Group", "ISS Africa"]},
    {"id": "libya", "name": "Libya", "lat": 32.9, "lon": 13.1, "region": "North Africa", "threat_level": "high", "description": "Divided government; rival militias; foreign military presence.", "sources": ["UNSMIL", "ACLED", "Crisis Group"]},
    {"id": "mozambique-cabo", "name": "Mozambique (Cabo Delgado)", "lat": -12.5, "lon": 40.5, "region": "Southern Africa", "threat_level": "elevated", "description": "ASWJ/ISIS-linked insurgency threatening LNG projects.", "sources": ["ACLED", "Crisis Group"]},
    {"id": "cameroon-anglophone", "name": "Cameroon (Anglophone Crisis)", "lat": 5.9, "lon": 10.1, "region": "Central Africa", "threat_level": "elevated", "description": "Separatist conflict in English-speaking regions since 2017.", "sources": ["ACLED", "Crisis Group"]},
    {"id": "nigeria-northeast", "name": "Nigeria (Northeast/Boko Haram)", "lat": 11.8, "lon": 13.2, "region": "West Africa", "threat_level": "high", "description": "Boko Haram/ISWAP insurgency in Borno; banditry in northwest.", "sources": ["ACLED", "Crisis Group"]},
    {"id": "central-african-republic", "name": "Central African Republic", "lat": 4.4, "lon": 18.6, "region": "Central Africa", "threat_level": "high", "description": "Armed groups control large territory; Wagner/Africa Corps presence.", "sources": ["MINUSCA", "ACLED"]},
    {"id": "south-sudan", "name": "South Sudan", "lat": 6.9, "lon": 31.6, "region": "East Africa", "threat_level": "high", "description": "Fragile peace agreement; subnational violence; humanitarian crisis.", "sources": ["UNMISS", "ACLED", "Crisis Group"]},

    # Americas
    {"id": "haiti", "name": "Haiti", "lat": 18.5, "lon": -72.3, "region": "Caribbean", "threat_level": "critical", "description": "Gang control of Port-au-Prince; state collapse; multinational security mission.", "sources": ["ACLED", "Crisis Group", "OCHA"]},
    {"id": "venezuela-guyana", "name": "Venezuela-Guyana (Essequibo)", "lat": 6.0, "lon": -59.0, "region": "South America", "threat_level": "elevated", "description": "Venezuelan territorial claim on Essequibo region; military posturing.", "sources": ["Crisis Group", "ICJ"]},
    {"id": "colombia-armed-groups", "name": "Colombia (Armed Groups)", "lat": 4.6, "lon": -74.1, "region": "South America", "threat_level": "elevated", "description": "ELN, FARC dissidents, narco groups; peace process challenges.", "sources": ["ACLED", "Crisis Group"]},
    {"id": "mexico-cartel", "name": "Mexico (Cartel Violence)", "lat": 23.6, "lon": -102.5, "region": "North America", "threat_level": "high", "description": "Cartel warfare; record homicide rates; fentanyl trafficking.", "sources": ["ACLED", "InSight Crime"]},
    {"id": "western-sahara", "name": "Western Sahara", "lat": 24.5, "lon": -13.0, "region": "North Africa", "threat_level": "moderate", "description": "Frozen territorial dispute between Morocco and the Polisario Front with periodic flare-ups.", "sources": ["UN MINURSO", "Crisis Group"]},

    # Chokepoints & Strategic Waterways
    {"id": "bab-el-mandeb", "name": "Bab el-Mandeb Strait", "lat": 12.6, "lon": 43.3, "region": "Red Sea", "threat_level": "critical", "description": "Critical shipping chokepoint under Houthi missile/drone threat.", "sources": ["UKMTO", "IMB"]},
    {"id": "suez-canal", "name": "Suez Canal", "lat": 30.5, "lon": 32.3, "region": "Middle East", "threat_level": "elevated", "description": "Major global trade artery; traffic disrupted by Red Sea crisis rerouting.", "sources": ["Suez Canal Authority", "EIA"]},
    {"id": "malacca-strait", "name": "Strait of Malacca", "lat": 2.5, "lon": 101.5, "region": "Southeast Asia", "threat_level": "elevated", "description": "Busiest shipping lane; piracy risk; strategic naval chokepoint.", "sources": ["IMB", "ReCAAP"]},
    {"id": "turkish-straits", "name": "Turkish Straits (Bosphorus/Dardanelles)", "lat": 41.1, "lon": 29.0, "region": "Middle East", "threat_level": "moderate", "description": "Montreux Convention; Russian Black Sea Fleet transit; grain corridor.", "sources": ["Turkish Navy", "Montreux Convention"]},
    {"id": "panama-canal", "name": "Panama Canal", "lat": 9.1, "lon": -79.7, "region": "Central America", "threat_level": "moderate", "description": "Drought-induced transit restrictions affecting global shipping.", "sources": ["Panama Canal Authority"]},

    # Arctic & Other
    {"id": "arctic-disputes", "name": "Arctic Disputes", "lat": 75.0, "lon": 40.0, "region": "Arctic", "threat_level": "elevated", "description": "Russia, NATO nations competing for Arctic resources and sea routes.", "sources": ["Arctic Council", "CSIS", "RAND"]},
    {"id": "svalbard", "name": "Svalbard", "lat": 78.2, "lon": 15.6, "region": "Arctic", "threat_level": "moderate", "description": "Strategic Arctic archipelago; Russian presence; undersea cable concerns.", "sources": ["Norwegian Intelligence", "RUSI"]},
    {"id": "greenland", "name": "Greenland", "lat": 72.0, "lon": -40.0, "region": "Arctic", "threat_level": "moderate", "description": "Strategic location; rare earth minerals; US military interest.", "sources": ["Danish MOD", "CSIS"]},
    {"id": "falklands", "name": "Falkland Islands", "lat": -51.8, "lon": -59.0, "region": "South Atlantic", "threat_level": "low", "description": "UK-Argentina territorial dispute; periodic diplomatic tensions.", "sources": ["UK MOD"]},

    # Cyber / Hybrid Threat Zones
    {"id": "undersea-cables-north-sea", "name": "North Sea Undersea Cables", "lat": 56.0, "lon": 3.0, "region": "Northern Europe", "threat_level": "elevated", "description": "Critical internet/energy infrastructure; Russian submarine activity.", "sources": ["NATO", "RUSI", "Policy Exchange"]},
    {"id": "space-domain", "name": "Space Domain (LEO)", "lat": 0.0, "lon": 0.0, "region": "Global", "threat_level": "elevated", "description": "ASAT weapons tests; orbital debris; satellite jamming and spoofing.", "sources": ["Space Force", "Secure World Foundation"]},
]


class HotspotUpdater:
    """Update geopolitical hotspot data in Redis with dynamic threat level adjustments."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self.qdrant = QdrantClient(url=settings.qdrant_url)

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    async def _count_recent_mentions(self, hotspot_name: str) -> int:
        """Query Qdrant for recent articles mentioning this hotspot.

        Uses a simple scroll with payload filter rather than vector search,
        because we want a count of recently ingested items matching the name.
        """
        try:
            query_text = hotspot_name.replace("/", " ").replace("-", " ")
            results, _ = self.qdrant.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=Filter(
                    should=[
                        FieldCondition(key="title", match=MatchText(text=query_text)),
                    ]
                ),
                limit=100,
            )
            return len(results)
        except Exception:
            return 0

    @staticmethod
    def _normalize_backend_threat(level: str) -> str:
        mapping = {
            "critical": "CRITICAL",
            "high": "HIGH",
            "elevated": "ELEVATED",
            "moderate": "MODERATE",
            "low": "MODERATE",
        }
        return mapping.get(level.lower(), "MODERATE")

    def _adjust_threat_level(self, base_level: str, mention_count: int) -> str:
        """Adjust threat level based on recent media coverage volume."""
        level_order = ["low", "moderate", "elevated", "high", "critical"]
        try:
            idx = level_order.index(base_level)
        except ValueError:
            idx = 2  # default to elevated

        if mention_count > 30:
            idx = min(idx + 2, 4)
        elif mention_count > 15:
            idx = min(idx + 1, 4)
        elif mention_count < 2:
            idx = max(idx - 1, 0)

        return level_order[idx]

    async def update(self) -> None:
        """Update all hotspots in Redis."""
        log.info("hotspot_update_started", hotspot_count=len(HOTSPOTS))
        start = time.monotonic()
        r = await self._get_redis()
        backend_hotspots: list[dict[str, Any]] = []

        for hotspot in HOTSPOTS:
            try:
                # Attempt to adjust threat level based on recent articles
                mention_count = await self._count_recent_mentions(hotspot["name"])
                adjusted_level = self._adjust_threat_level(
                    hotspot["threat_level"], mention_count
                )
                now_iso = datetime.now(UTC).isoformat()

                record = {
                    **hotspot,
                    "threat_level": adjusted_level,
                    "base_threat_level": hotspot["threat_level"],
                    "recent_mentions": mention_count,
                    "updated_at": now_iso,
                }
                backend_record = {
                    "id": hotspot["id"],
                    "name": hotspot["name"],
                    "latitude": hotspot["lat"],
                    "longitude": hotspot["lon"],
                    "region": hotspot["region"],
                    "threat_level": self._normalize_backend_threat(adjusted_level),
                    "description": hotspot["description"],
                    "sources": hotspot["sources"],
                    "last_updated": now_iso,
                }
                backend_hotspots.append(backend_record)

                # Store individual hotspot
                await r.set(
                    f"hotspot:{hotspot['id']}",
                    json.dumps(record),
                    ex=settings.hotspot_cache_ttl,
                )
            except Exception:
                log.exception("hotspot_update_error", hotspot=hotspot["id"])

        # Store full list of hotspot IDs for enumeration
        hotspot_ids = [h["id"] for h in HOTSPOTS]
        await r.set("hotspot:index", json.dumps(hotspot_ids), ex=settings.hotspot_cache_ttl)
        await r.set("hotspots:all", json.dumps(backend_hotspots), ex=settings.hotspot_cache_ttl)

        elapsed = round(time.monotonic() - start, 2)
        log.info("hotspot_update_finished", hotspot_count=len(HOTSPOTS), elapsed_seconds=elapsed)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
