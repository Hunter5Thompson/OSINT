import pytest

from suv_structured.procurement_schemas import ProcurementProgram, profile_text


def test_program_minimal():
    p = ProcurementProgram(title="Konsolidierte Nachrüstung Puma 1. Los", branch="Heer",
                           suv_url="https://suv.report/modernisierungsvorhaben/")
    assert p.title.startswith("Konsolidierte") and p.branch == "Heer"
    assert p.quantity is None and p.cost_eur is None


def test_blank_title_rejected():
    with pytest.raises(ValueError):
        ProcurementProgram(title="  ", branch="Heer", suv_url="u")


def test_profile_text_includes_key_fields():
    p = ProcurementProgram(
        title="Puma 1. Los",
        branch="Heer",
        typ="Schützenpanzer",
        status="Auslieferung",
        contractor_raw="PSM Projekt System & Management GmbH",
        quantity=297,
        cost_eur=1.85e9,
        delivery_raw="2024 – 2029",
        description="Rahmenvertrag zur Nachrüstung.",
        suv_url="u")
    t = profile_text(p)
    assert "Puma 1. Los" in t and "Schützenpanzer" in t and "Auslieferung" in t
    assert "297" in t and "PSM" in t and "Nachrüstung" in t
