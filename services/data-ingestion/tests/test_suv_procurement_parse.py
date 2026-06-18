from pathlib import Path

from suv_structured.procurement_parse import (
    parse_cost_eur,
    parse_delivery,
    parse_procurements,
    parse_quantity,
)

FIXTURE = Path(__file__).parent / "fixtures" / "suv_procurements_sample.md"
URL = "https://suv.report/modernisierungsvorhaben/"


def test_parse_cost_eur():
    assert parse_cost_eur("1,85 Mrd. Euro") == 1.85e9
    assert parse_cost_eur("5,4 Mrd. Euro") == 5.4e9
    assert parse_cost_eur("35,3 Millionen Euro") == 35.3e6
    assert parse_cost_eur("N/A") is None
    assert parse_cost_eur(None) is None


def test_parse_delivery():
    assert parse_delivery("2024 – 2029") == (2024, 2029)
    assert parse_delivery("2025") == (2025, 2025)
    assert parse_delivery("N/A") == (None, None)
    assert parse_delivery(None) == (None, None)


def test_parse_quantity():
    assert parse_quantity("297") == 297
    assert parse_quantity("1.200") == 1200
    assert parse_quantity("N/A") is None


def test_parse_procurements_branch_tracking_and_fields():
    progs = parse_procurements(FIXTURE.read_text(), suv_url=URL)
    assert [p.title for p in progs] == [
        "Konsolidierte Nachrüstung Puma 1. Los", "Eurofighter"]
    puma = progs[0]
    assert puma.branch == "Heer" and puma.typ == "Schützenpanzer"
    assert puma.status == "Auslieferung" and puma.quantity == 297
    assert puma.cost_eur == 1.85e9 and puma.delivery_start == 2024 and puma.delivery_end == 2029
    assert puma.contractor_raw == "PSM Projekt System & Management GmbH"
    assert "Rahmenvertrag" in puma.description
    assert progs[1].branch == "Luftwaffe"   # branch tracking switched
