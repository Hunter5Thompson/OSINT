"""Tests for OFAC sanctions collector with XML parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feeds.ofac_collector import OFACCollector, parse_sdn_xml


SAMPLE_SDN_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML">
  <publshInformation>
    <Publish_Date>04/01/2026</Publish_Date>
  </publshInformation>
  <sdnEntry>
    <uid>12345</uid>
    <sdnType>Entity</sdnType>
    <lastName>MEGA SHIPPING LLC</lastName>
    <programList>
      <program>IRAN</program>
      <program>SDGT</program>
    </programList>
    <akaList>
      <aka>
        <uid>1001</uid>
        <type>a.k.a.</type>
        <lastName>MEGA MARINE</lastName>
      </aka>
    </akaList>
    <idList>
      <id>
        <uid>2001</uid>
        <idType>IMO Number</idType>
        <idNumber>9123456</idNumber>
        <idCountry>IR</idCountry>
      </id>
      <id>
        <uid>2002</uid>
        <idType>Registration Number</idType>
        <idNumber>REG-99</idNumber>
      </id>
    </idList>
    <addressList>
      <address>
        <uid>3001</uid>
        <country>Iran</country>
        <city>Tehran</city>
      </address>
    </addressList>
  </sdnEntry>
  <sdnEntry>
    <uid>67890</uid>
    <sdnType>Individual</sdnType>
    <lastName>DOE</lastName>
    <firstName>John</firstName>
    <programList>
      <program>UKRAINE-EO13661</program>
    </programList>
  </sdnEntry>
</sdnList>
"""

SAMPLE_CONS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML">
  <sdnEntry>
    <uid>12345</uid>
    <sdnType>Entity</sdnType>
    <lastName>MEGA SHIPPING LLC</lastName>
    <programList><program>IRAN</program></programList>
  </sdnEntry>
  <sdnEntry>
    <uid>99999</uid>
    <sdnType>Individual</sdnType>
    <lastName>PETROV</lastName>
    <firstName>Ivan</firstName>
    <programList><program>RUSSIA-EO14024</program></programList>
  </sdnEntry>
</sdnList>
"""


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.qdrant_url = "http://localhost:6333"
    s.qdrant_collection = "odin_intel"
    s.tei_embed_url = "http://localhost:8001"
    s.http_timeout = 30.0
    s.embedding_dimensions = 1024
    s.neo4j_url = "http://localhost:7474"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "test"
    s.redis_stream_events = "events:new"
    return s


@pytest.fixture
def collector(mock_settings):
    with patch("feeds.base.QdrantClient") as mock_qdrant:
        mock_qdrant.return_value = MagicMock()
        c = OFACCollector(settings=mock_settings)
    c.qdrant.retrieve.return_value = []
    return c


def test_parse_sdn_xml_entity_count():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    assert len(entries) == 2


def test_parse_sdn_xml_entity_fields():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert entity["ofac_id"] == "12345"
    assert entity["entity_type"] == "Entity"
    assert entity["full_name"] == "MEGA SHIPPING LLC"
    assert entity["programs"] == ["IRAN", "SDGT"]


def test_parse_sdn_xml_aliases():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert "MEGA MARINE" in entity["aliases"]


def test_parse_sdn_xml_identifiers():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert len(entity["identifiers"]) == 2
    imo = next(i for i in entity["identifiers"] if i["type"] == "IMO Number")
    assert imo["value"] == "9123456"
    assert imo["country"] == "IR"


def test_parse_sdn_xml_addresses():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    entity = entries[0]
    assert len(entity["addresses"]) == 1
    assert entity["addresses"][0]["country"] == "Iran"
    assert entity["addresses"][0]["city"] == "Tehran"


def test_parse_sdn_xml_individual():
    entries = parse_sdn_xml(SAMPLE_SDN_XML)
    person = entries[1]
    assert person["entity_type"] == "Individual"
    assert person["full_name"] == "John DOE"
    assert person["programs"] == ["UKRAINE-EO13661"]
    assert person["aliases"] == []
    assert person["identifiers"] == []


def test_cross_feed_dedup():
    """SDN and Consolidated may share entries — deduplicate by ofac_id."""
    sdn_entries = parse_sdn_xml(SAMPLE_SDN_XML)
    cons_entries = parse_sdn_xml(SAMPLE_CONS_XML)

    all_entries = sdn_entries + cons_entries
    assert len(all_entries) == 4

    seen_ids: set[str] = set()
    unique: list[dict] = []
    for entry in all_entries:
        if entry["ofac_id"] not in seen_ids:
            seen_ids.add(entry["ofac_id"])
            unique.append(entry)

    assert len(unique) == 3
    unique_ids = {e["ofac_id"] for e in unique}
    assert unique_ids == {"12345", "67890", "99999"}


def test_build_embed_text(collector):
    entry = {
        "full_name": "MEGA SHIPPING LLC",
        "aliases": ["MEGA MARINE"],
        "programs": ["IRAN", "SDGT"],
    }
    text = collector._build_embed_text(entry)
    assert "MEGA SHIPPING LLC" in text
    assert "MEGA MARINE" in text
    assert "IRAN" in text
