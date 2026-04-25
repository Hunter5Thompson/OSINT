from gdelt_raw.geo import build_location_payload


def test_full_fields_produces_point_dict():
    p = build_location_payload(
        feature_id="-3365797", name="Kyiv", country_code="UA",
        lat=50.4501, lon=30.5234,
    )
    assert p["feature_id"] == "-3365797"
    assert p["name"] == "Kyiv"
    assert p["country_code"] == "UA"
    assert p["lat"] == 50.4501
    assert p["lon"] == 30.5234
    assert p["geo"] == {"latitude": 50.4501, "longitude": 30.5234, "crs": "wgs-84"}


def test_missing_feature_id_falls_back_to_slug():
    p = build_location_payload(
        feature_id="", name="Kyiv", country_code="UA",
        lat=50.45, lon=30.52,
    )
    assert p["feature_id"].startswith("gdelt:loc:ua:"), p["feature_id"]


def test_missing_coords_returns_none():
    p = build_location_payload(
        feature_id="-3365797", name="Kyiv", country_code="UA",
        lat=None, lon=None,
    )
    assert p is None


def test_zero_zero_coords_treated_as_missing():
    # GDELT uses 0/0 for "unknown" in some places — skip these.
    p = build_location_payload(
        feature_id="XYZ", name="Null Island", country_code="",
        lat=0.0, lon=0.0,
    )
    assert p is None
