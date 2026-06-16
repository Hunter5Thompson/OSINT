import asyncio

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
    assert "I.LON IS NOT NULL" in q


def test_wire_template_is_parametrised_and_idempotent():
    assert "$loc_key" in WIRE_INCIDENT_LOCATION
    assert "MERGE (l:Location {loc_key: $loc_key})" in WIRE_INCIDENT_LOCATION
    assert "MERGE (i)-[:OCCURRED_AT]->(l)" in WIRE_INCIDENT_LOCATION


def test_build_wire_params_uses_incident_key():
    row = {"id": "inc1", "location": "Donetsk", "lat": 48.0, "lon": 37.8}
    p = build_wire_params(row)
    assert p == {
        "incident_id": "inc1", "loc_key": "incident:donetsk@48.000,37.800",
        "lat": 48.0, "lon": 37.8, "location": "Donetsk",
    }


class _FakeClient:
    """Records calls; first run() returns seeded rows, later runs return []."""
    def __init__(self, rows):
        self._rows = rows
        self.calls: list = []

    async def run(self, cypher, params=None):
        self.calls.append((cypher, params))
        # first call is the SELECT → return seeded rows; WIRE calls return []
        return self._rows if len(self.calls) == 1 else []


def test_run_dry_run_counts_without_writing():
    from graph_integrity import geo_incident
    rows = [{"id": "i1", "location": "Donetsk", "lat": 48.0, "lon": 37.8},
            {"id": "i2", "location": "Kyiv", "lat": 50.45, "lon": 30.52}]
    client = _FakeClient(rows)
    n = asyncio.run(geo_incident.run(client, dry_run=True))
    assert n == 2
    assert len(client.calls) == 1            # only the SELECT, no WIRE writes


def test_run_live_writes_one_per_row():
    from graph_integrity import geo_incident
    rows = [{"id": "i1", "location": "Donetsk", "lat": 48.0, "lon": 37.8}]
    client = _FakeClient(rows)
    n = asyncio.run(geo_incident.run(client, dry_run=False))
    assert n == 1
    # 1 SELECT + 1 WIRE
    assert len(client.calls) == 2
    wire_cypher, wire_params = client.calls[1]
    assert "OCCURRED_AT" in wire_cypher
    assert wire_params["loc_key"] == "incident:donetsk@48.000,37.800"


def test_run_empty_returns_zero():
    from graph_integrity import geo_incident
    client = _FakeClient([])
    assert asyncio.run(geo_incident.run(client, dry_run=False)) == 0
    assert len(client.calls) == 1            # SELECT only


def test_select_excludes_null_island():
    q = SELECT_UNWIRED_INCIDENTS.upper()
    assert "NOT (I.LAT = 0.0 AND I.LON = 0.0)" in q


def test_build_wire_params_null_island_is_none():
    assert build_wire_params({"id": "x", "location": None, "lat": 0.0, "lon": 0.0}) is None


def test_run_skips_null_island_row():
    from graph_integrity import geo_incident
    rows = [{"id": "i1", "location": None, "lat": 0.0, "lon": 0.0}]
    client = _FakeClient(rows)
    n = asyncio.run(geo_incident.run(client, dry_run=False))
    assert n == 0
    assert len(client.calls) == 1   # SELECT only, no WIRE for the (0,0) row
