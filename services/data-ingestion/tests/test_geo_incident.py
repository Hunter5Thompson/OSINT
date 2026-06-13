from graph_integrity.geo_incident import (
    SELECT_UNWIRED_INCIDENTS,
    WIRE_INCIDENT_LOCATION,
    build_wire_params,
)


def test_select_only_unwired_with_coords():
    q = SELECT_UNWIRED_INCIDENTS.upper()
    assert "OCCURRED_AT" in q
    assert "NOT" in q                 # only incidents lacking the edge
    assert "I.LAT IS NOT NULL" in q


def test_wire_template_is_parametrised_and_idempotent():
    assert "$loc_key" in WIRE_INCIDENT_LOCATION
    assert "MERGE (l:Location {loc_key: $loc_key})" in WIRE_INCIDENT_LOCATION
    assert "MERGE (i)-[:OCCURRED_AT]->(l)" in WIRE_INCIDENT_LOCATION


def test_build_wire_params_uses_incident_key():
    row = {"id": "inc1", "location": "Donetsk", "lat": 48.0, "lon": 37.8}
    p = build_wire_params(row)
    assert p == {
        "incident_id": "inc1", "loc_key": "incident:donetsk",
        "lat": 48.0, "lon": 37.8, "location": "Donetsk",
    }
