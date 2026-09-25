import json

import pytest

from spatial_catalog.compiler import _parse_natural_earth_admin1


def feature(code="DE-BE"):
    return {
        "type": "Feature",
        "properties": {"adm0_a3": "DEU", "iso_3166_2": code, "name": "Berlin"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[13, 52], [14, 52], [14, 53], [13, 53], [13, 52]]],
        },
    }


def test_natural_earth_admin1_uses_declared_iso_identity():
    payload = json.dumps({"type": "FeatureCollection", "features": [feature()]}).encode()
    result = _parse_natural_earth_admin1(payload, "country:DEU")
    assert [(f.scope_key, f.label) for f in result] == [("admin1:iso3166-2:DE-BE", "Berlin")]


def test_natural_earth_admin1_rejects_missing_identity_instead_of_guessing():
    payload = json.dumps({"type": "FeatureCollection", "features": [feature("")]}).encode()
    with pytest.raises(ValueError, match="ADMIN1_IDENTITY"):
        _parse_natural_earth_admin1(payload, "country:DEU")
