from graph_integrity.country_centroids import centroid_for
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
