from pathlib import Path

from suv_structured.equipment_parse import (
    parse_count, parse_service_end, parse_weapon_systems,
)

FIXTURE = Path(__file__).parent / "fixtures" / "suv_equipment_sample.md"
PAGE = "hauptwaffensysteme-des-heeres"
URL = "https://suv.report/hauptwaffensysteme-des-heeres/"


def test_parse_count_variants():
    assert parse_count("310") == 310
    assert parse_count("1+") == 1
    assert parse_count("939 in über 30 verschiedenen Varianten") == 939
    assert parse_count("337 (189 Bv206S & 148 Bv206D)") == 337
    assert parse_count("32.000") == 32000          # German thousands-dot
    assert parse_count("N/A") is None
    assert parse_count(None) is None


def test_parse_service_end_variants():
    assert parse_service_end("2050") == 2050
    assert parse_service_end("2046 (20 Jahre)") == 2046
    assert parse_service_end("N/A") is None
    assert parse_service_end("") is None
    assert parse_service_end(None) is None


def test_parse_weapon_systems_skips_header_and_separator():
    rows = parse_weapon_systems(FIXTURE.read_text(), page_slug=PAGE, suv_url=URL)
    assert [r.muster for r in rows] == [
        "Leopard 2", "Schwerer Waffenträger Infanterie", "Fuchs", "Husky 3", "BV206S/D",
    ]


def test_parse_weapon_systems_fields():
    rows = {r.muster: r for r in parse_weapon_systems(FIXTURE.read_text(), page_slug=PAGE, suv_url=URL)}
    leo = rows["Leopard 2"]
    assert leo.type_raw == "Kampfpanzer" and leo.count == 310 and leo.service_end == 2050
    assert leo.page_slug == PAGE and leo.suv_url == URL
    fuchs = rows["Fuchs"]
    assert fuchs.count == 939 and fuchs.count_raw == "939 in über 30 verschiedenen Varianten"
    assert fuchs.service_end is None
    assert rows["Schwerer Waffenträger Infanterie"].count == 1
    assert rows["Husky 3"].service_end == 2046
    assert rows["BV206S/D"].note is None
