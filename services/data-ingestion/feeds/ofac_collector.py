"""OFAC Sanctions collector — SDN + Consolidated lists via XML."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import structlog
from lxml import etree
from qdrant_client.models import PointStruct

from config import Settings
from feeds.base import BaseCollector

log = structlog.get_logger(__name__)

OFAC_FEEDS = {
    "sdn": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/sdn_advanced.xml",
    "consolidated": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/cons_advanced.xml",
}

_NS = {"ns": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML"}

# 120s timeout for large XML downloads
_DOWNLOAD_TIMEOUT = 120.0


def _txt(el: etree._Element | None, tag: str) -> str:
    """Return text of a direct child element, or empty string."""
    if el is None:
        return ""
    child = el.find(f"ns:{tag}", _NS)
    return (child.text or "").strip() if child is not None else ""


def parse_sdn_xml(xml_text: str) -> list[dict]:
    """Parse OFAC SDN/Consolidated XML and return a list of normalised entry dicts.

    Each dict contains:
        ofac_id, entity_type, full_name, programs, aliases, identifiers, addresses
    """
    root = etree.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    entries: list[dict] = []

    for entry_el in root.findall("ns:sdnEntry", _NS):
        ofac_id = _txt(entry_el, "uid")
        entity_type = _txt(entry_el, "sdnType")
        last_name = _txt(entry_el, "lastName")
        first_name = _txt(entry_el, "firstName")

        if entity_type == "Individual" and first_name:
            full_name = f"{first_name} {last_name}"
        else:
            full_name = last_name

        # Programs
        programs: list[str] = []
        prog_list = entry_el.find("ns:programList", _NS)
        if prog_list is not None:
            for prog in prog_list.findall("ns:program", _NS):
                if prog.text:
                    programs.append(prog.text.strip())

        # Aliases (akaList)
        aliases: list[str] = []
        aka_list = entry_el.find("ns:akaList", _NS)
        if aka_list is not None:
            for aka in aka_list.findall("ns:aka", _NS):
                aka_name = _txt(aka, "lastName")
                if aka_name:
                    aliases.append(aka_name)

        # Identifiers (idList)
        identifiers: list[dict] = []
        id_list = entry_el.find("ns:idList", _NS)
        if id_list is not None:
            for id_el in id_list.findall("ns:id", _NS):
                id_type = _txt(id_el, "idType")
                id_value = _txt(id_el, "idNumber")
                id_country = _txt(id_el, "idCountry")
                if id_type or id_value:
                    rec: dict = {"type": id_type, "value": id_value}
                    if id_country:
                        rec["country"] = id_country
                    identifiers.append(rec)

        # Addresses
        addresses: list[dict] = []
        addr_list = entry_el.find("ns:addressList", _NS)
        if addr_list is not None:
            for addr_el in addr_list.findall("ns:address", _NS):
                addr: dict = {}
                country = _txt(addr_el, "country")
                city = _txt(addr_el, "city")
                state = _txt(addr_el, "stateOrProvince")
                if country:
                    addr["country"] = country
                if city:
                    addr["city"] = city
                if state:
                    addr["state"] = state
                if addr:
                    addresses.append(addr)

        entries.append(
            {
                "ofac_id": ofac_id,
                "entity_type": entity_type,
                "full_name": full_name,
                "programs": programs,
                "aliases": aliases,
                "identifiers": identifiers,
                "addresses": addresses,
            }
        )

    return entries


class OFACCollector(BaseCollector):
    """Fetch OFAC SDN + Consolidated XML lists and ingest into Qdrant + Neo4j."""

    def __init__(self, settings: Settings, redis_client: Any | None = None) -> None:
        super().__init__(settings, redis_client)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_embed_text(self, entry: dict) -> str:
        """Build embedding text: name | AKA: aliases | Programs: programs"""
        name = entry.get("full_name", "")
        aliases = entry.get("aliases", [])
        programs = entry.get("programs", [])
        parts = [name]
        if aliases:
            parts.append(f"AKA: {', '.join(aliases)}")
        if programs:
            parts.append(f"Programs: {', '.join(programs)}")
        return " | ".join(parts)

    async def _fetch_xml(self, feed_name: str, url: str) -> str | None:
        """Download XML feed with extended timeout."""
        try:
            resp = await self.http.get(url, timeout=_DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            log.info("ofac_feed_downloaded", feed=feed_name, bytes=len(resp.content))
            return resp.text
        except Exception as exc:
            log.error("ofac_fetch_failed", feed=feed_name, error=str(exc))
            return None

    async def _write_neo4j(self, entry: dict) -> None:
        """Write SanctionedEntity + relationships to Neo4j using deterministic Cypher templates."""
        neo4j_tx_url = f"{self.settings.neo4j_url}/db/neo4j/tx/commit"
        auth = (self.settings.neo4j_user, self.settings.neo4j_password)
        now = datetime.now(UTC).isoformat()

        statements = []

        # 1. MERGE SanctionedEntity
        statements.append(
            {
                "statement": """
MERGE (e:SanctionedEntity {ofac_id: $ofac_id})
SET e.name = $name,
    e.entity_type = $entity_type,
    e.updated_at = $updated_at
""",
                "parameters": {
                    "ofac_id": entry["ofac_id"],
                    "name": entry["full_name"],
                    "entity_type": entry["entity_type"],
                    "updated_at": now,
                },
            }
        )

        # 2. MERGE SanctionsProgram + SANCTIONED_UNDER
        for program in entry["programs"]:
            statements.append(
                {
                    "statement": """
MERGE (p:SanctionsProgram {name: $program})
WITH p
MATCH (e:SanctionedEntity {ofac_id: $ofac_id})
MERGE (e)-[:SANCTIONED_UNDER]->(p)
""",
                    "parameters": {"program": program, "ofac_id": entry["ofac_id"]},
                }
            )

        # 3. MERGE Alias + HAS_ALIAS
        for alias in entry["aliases"]:
            statements.append(
                {
                    "statement": """
MERGE (a:Alias {name: $alias})
WITH a
MATCH (e:SanctionedEntity {ofac_id: $ofac_id})
MERGE (e)-[:HAS_ALIAS]->(a)
""",
                    "parameters": {"alias": alias, "ofac_id": entry["ofac_id"]},
                }
            )

        # 4. MERGE Identifier + HAS_ID
        for ident in entry["identifiers"]:
            statements.append(
                {
                    "statement": """
MERGE (i:Identifier {type: $id_type, value: $id_value})
SET i.country = $id_country
WITH i
MATCH (e:SanctionedEntity {ofac_id: $ofac_id})
MERGE (e)-[:HAS_ID]->(i)
""",
                    "parameters": {
                        "id_type": ident["type"],
                        "id_value": ident["value"],
                        "id_country": ident.get("country", ""),
                        "ofac_id": entry["ofac_id"],
                    },
                }
            )

        payload = {"statements": statements}
        try:
            resp = await self.http.post(neo4j_tx_url, json=payload, auth=auth)
            resp.raise_for_status()
            errors = resp.json().get("errors", [])
            if errors:
                log.warning("ofac_neo4j_errors", ofac_id=entry["ofac_id"], errors=errors)
            else:
                log.debug("ofac_neo4j_written", ofac_id=entry["ofac_id"])
        except Exception as exc:
            log.warning("ofac_neo4j_failed", ofac_id=entry["ofac_id"], error=str(exc))

    # ------------------------------------------------------------------
    # Main collect loop
    # ------------------------------------------------------------------

    async def collect(self) -> None:
        log.info("ofac_collection_started")
        start = time.monotonic()

        await self._ensure_collection()

        # Phase 1: Download and parse both feeds
        all_entries: list[dict] = []
        for feed_name, url in OFAC_FEEDS.items():
            xml_text = await self._fetch_xml(feed_name, url)
            if not xml_text:
                continue
            try:
                entries = parse_sdn_xml(xml_text)
                log.info("ofac_feed_parsed", feed=feed_name, count=len(entries))
                all_entries.extend(entries)
            except Exception as exc:
                log.error("ofac_parse_failed", feed=feed_name, error=str(exc))

        # Phase 2: Cross-feed dedup by ofac_id
        seen_ids: set[str] = set()
        unique_entries: list[dict] = []
        for entry in all_entries:
            if entry["ofac_id"] not in seen_ids:
                seen_ids.add(entry["ofac_id"])
                unique_entries.append(entry)

        log.info(
            "ofac_dedup_complete",
            total_fetched=len(all_entries),
            unique=len(unique_entries),
        )

        # Phase 3: Neo4j write (always — MERGE updates existing) + Qdrant dedup
        total_new = 0
        points: list[PointStruct] = []

        for entry in unique_entries:
            # Always write/update Neo4j graph
            await self._write_neo4j(entry)

            # Qdrant: skip duplicates
            chash = self._content_hash(entry["ofac_id"])
            pid = self._point_id(chash)
            if await self._dedup_check(pid):
                continue

            embed_text = self._build_embed_text(entry)
            payload = {
                "source": "ofac",
                "ofac_id": entry["ofac_id"],
                "full_name": entry["full_name"],
                "entity_type": entry["entity_type"],
                "programs": entry["programs"],
                "aliases": entry["aliases"],
            }

            try:
                point = await self._build_point(embed_text, payload, chash)
                points.append(point)
                total_new += 1
            except Exception as exc:
                log.warning("ofac_embed_failed", ofac_id=entry["ofac_id"], error=str(exc))

        await self._batch_upsert(points)

        elapsed = round(time.monotonic() - start, 2)
        log.info(
            "ofac_collection_finished",
            total_new=total_new,
            total_unique=len(unique_entries),
            elapsed_seconds=elapsed,
        )
