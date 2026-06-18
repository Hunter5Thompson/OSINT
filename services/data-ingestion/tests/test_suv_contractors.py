from suv_structured.contractors import split_contractors


def test_single_with_internal_ampersand_splits():
    # deterministic rule: '&' always splits. "PSM … & Management GmbH" → two fragments.
    # Neither fragment matches an existing ORG, so the gate emits NO wrong edge, and the
    # program's contractor_raw retains the full original string. This is the accepted tradeoff.
    assert split_contractors("PSM Projekt System & Management GmbH") == [
        "PSM Projekt System", "Management GmbH"]


def test_consortium_ampersand():
    assert split_contractors("KNDS Deutschland & Hensoldt") == ["KNDS Deutschland", "Hensoldt"]


def test_consortium_comma():
    assert split_contractors("Saab AB, ESG Elektroniksystem- und Logistik-GmbH") == [
        "Saab AB", "ESG Elektroniksystem- und Logistik-GmbH"]


def test_paren_konsortium():
    result = split_contractors(
        "Konsortium KOFA GIADS (Airbus Defence und Space & Frequentis Deutschland)"
    )
    assert result == ["Airbus Defence und Space", "Frequentis Deutschland"]


def test_etc_dropped():
    assert split_contractors("Hensoldt Sensors GmbH, Rohde & Schwarz, etc.") == [
        "Hensoldt Sensors GmbH", "Rohde & Schwarz"]


def test_empty():
    assert split_contractors("/") == []
    assert split_contractors("N/A") == []
    assert split_contractors(None) == []
    assert split_contractors("") == []
