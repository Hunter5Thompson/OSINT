from graph_integrity.country_centroids import _CENTROIDS, _NAME_TO_ISO2, centroid_for, resolve_iso2
from graph_integrity.loc_key import centroid_key, incident_key, slug


def test_slug_is_deterministic_and_lowercase():
    assert slug("Donetsk Oblast") == "donetsk-oblast"
    assert slug("  São Paulo ") == "sao-paulo"


def test_centroid_key_uses_lowercase_iso2():
    assert centroid_key("UA") == "centroid:ua"
    assert centroid_key("us") == "centroid:us"


def test_incident_key_prefers_name_else_rounded_coords():
    assert incident_key("Donetsk", 48.0159, 37.8028) == "incident:donetsk"
    assert incident_key("", 48.0159, 37.8028) == "geo:48.016,37.803"
    assert incident_key(None, 48.0159, 37.8028) == "geo:48.016,37.803"


def test_centroid_for_known_country():
    lat, lon = centroid_for("UA")
    assert 40 < lat < 55 and 20 < lon < 45  # Ukraine centroid plausibility
    assert centroid_for("ZZ") is None  # unknown ISO2


def test_resolve_iso2_accepts_code_and_name():
    assert resolve_iso2("UA") == "UA"
    assert resolve_iso2("ua") == "UA"
    assert resolve_iso2("Ukraine") == "UA"
    assert resolve_iso2("ukraine") == "UA"
    assert resolve_iso2("United States") == "US"
    assert resolve_iso2("USA") == "US"
    assert resolve_iso2("U.S.") == "US"
    assert resolve_iso2("Russian Federation") == "RU"
    assert resolve_iso2("Zorgon") is None
    assert resolve_iso2(None) is None


def test_name_to_iso2_values_all_have_centroids():
    # invariant: every mapped ISO2 must be a real centroid key
    for iso2 in _NAME_TO_ISO2.values():
        assert iso2 in _CENTROIDS, f"{iso2} missing from _CENTROIDS"
