"""WP-07 repair: re-key collided incident Locations onto coordinate-bearing keys."""
import asyncio

from graph_integrity.rekey_incident_locations import (
    FETCH_INCIDENT_LOCATIONS,
    IncidentLoc,
    plan_rekey,
    run,
    verify_no_duplicate_loc_keys,
)


def _row(incident_id, location, lat, lon, current_loc_key):
    return IncidentLoc(incident_id, location, lat, lon, current_loc_key)


def test_plan_rekey_splits_same_name_different_coords():
    rows = [
        _row("a", "Donetsk", 48.0, 37.8, "incident:donetsk"),
        _row("b", "Donetsk", 49.0, 38.0, "incident:donetsk"),
    ]
    plan = plan_rekey(rows)
    assert plan.rewire_count == 2
    new_keys = {new for (_id, _old, new) in plan.rewires}
    assert new_keys == {"incident:donetsk@48.000,37.800", "incident:donetsk@49.000,38.000"}


def test_plan_rekey_noop_when_already_coordinate_bearing():
    rows = [_row("a", "Donetsk", 48.0, 37.8, "incident:donetsk@48.000,37.800")]
    assert plan_rekey(rows).rewire_count == 0


class _FakeClient:
    def __init__(self, fetch_rows):
        self._fetch_rows = fetch_rows
        self.calls = []

    async def run(self, cypher, params=None):
        self.calls.append((cypher, params))
        if cypher == FETCH_INCIDENT_LOCATIONS:
            return self._fetch_rows
        return []


_RAW = [
    {"incident_id": "a", "location": "Donetsk", "lat": 48.0, "lon": 37.8,
     "current_loc_key": "incident:donetsk"},
    {"incident_id": "b", "location": "Donetsk", "lat": 49.0, "lon": 38.0,
     "current_loc_key": "incident:donetsk"},
]


def test_dry_run_counts_without_writing():
    client = _FakeClient(_RAW)
    n = asyncio.run(run(client, dry_run=True))
    assert n == 2
    assert [c[0] for c in client.calls] == [FETCH_INCIDENT_LOCATIONS]


def test_apply_rewires_and_cleans_orphans():
    client = _FakeClient(_RAW)
    n = asyncio.run(run(client, dry_run=False))
    assert n == 2
    cyphers = [c[0] for c in client.calls]
    assert cyphers[0] == FETCH_INCIDENT_LOCATIONS
    assert sum("MERGE (i)-[:OCCURRED_AT]->(l)" in c for c in cyphers) == 2
    assert any("NOT ()-[:OCCURRED_AT]->(l)" in c for c in cyphers)


def test_verify_no_duplicate_loc_keys_returns_pairs():
    class _C:
        async def run(self, cypher, params=None):
            return [{"key": "incident:x@1.000,2.000", "c": 2}]
    assert asyncio.run(verify_no_duplicate_loc_keys(_C())) == [("incident:x@1.000,2.000", 2)]


def test_verify_no_duplicate_loc_keys_empty_when_clean():
    class _C:
        async def run(self, cypher, params=None):
            return []
    assert asyncio.run(verify_no_duplicate_loc_keys(_C())) == []


def test_plan_rekey_handles_transient_double_edge():
    # Task-3 transient: an incident temporarily has BOTH the stale old-key row
    # and the correct new-key row. Only the stale row should trigger a rewire.
    rows = [
        _row("a", "Donetsk", 48.0, 37.8, "incident:donetsk"),
        _row("a", "Donetsk", 48.0, 37.8, "incident:donetsk@48.000,37.800"),
    ]
    plan = plan_rekey(rows)
    assert plan.rewire_count == 1


def test_plan_rekey_skips_null_island_incidents():
    rows = [_row("a", "Unknown", 0.0, 0.0, "incident:unknown")]
    assert plan_rekey(rows).rewire_count == 0
