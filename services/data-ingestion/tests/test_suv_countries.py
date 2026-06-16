# tests/test_suv_countries.py
from suv_structured.countries import to_graph_country


def test_maps_common_german_country_names():
    assert to_graph_country("Deutschland") == "Germany"
    assert to_graph_country("Frankreich") == "France"
    assert to_graph_country("USA") == "United States"
    assert to_graph_country("Vereinigte Staaten") == "United States"


def test_unknown_country_returns_none():
    assert to_graph_country("Atlantis") is None
    assert to_graph_country(None) is None
