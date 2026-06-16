# tests/test_suv_countries.py
import unicodedata

from suv_structured.countries import to_graph_country


def test_maps_common_german_country_names():
    assert to_graph_country("Deutschland") == "Germany"
    assert to_graph_country("Frankreich") == "France"
    assert to_graph_country("USA") == "United States"
    assert to_graph_country("Vereinigte Staaten") == "United States"


def test_unknown_country_returns_none():
    assert to_graph_country("Atlantis") is None
    assert to_graph_country(None) is None


def test_normalizes_umlaut_country_names():
    assert to_graph_country("Türkei") == "Türkiye"
    assert to_graph_country("Österreich") == "Austria"


def test_handles_nfd_decomposed_umlaut():
    # "Tu" + combining diaeresis (NFD) must normalize to NFC and match the dict key
    nfd_tuerkei = unicodedata.normalize("NFD", "Türkei")
    assert to_graph_country(nfd_tuerkei) == "Türkiye"


def test_empty_and_whitespace_return_none():
    assert to_graph_country("") is None
    assert to_graph_country("   ") is None
