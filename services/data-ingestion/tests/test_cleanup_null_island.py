"""WP-11 repair: detach + delete shared (0,0) null-island :Location nodes."""
import asyncio

from graph_integrity.cleanup_null_island import (
    COUNT_NULL_ISLAND,
    DELETE_NULL_ISLAND,
    run,
)


class _FakeClient:
    def __init__(self, locations=2, attached=5, deleted=2):
        self._count = {"null_island_locations": locations, "attached_nodes": attached}
        self._deleted = {"deleted": deleted}
        self.calls = []

    async def run(self, cypher, params=None):
        self.calls.append((cypher, params))
        if cypher == COUNT_NULL_ISLAND:
            return [self._count]
        return [self._deleted]


def test_dry_run_counts_without_deleting():
    client = _FakeClient(locations=2, attached=5)
    n = asyncio.run(run(client, dry_run=True))
    assert n == 2
    assert [c[0] for c in client.calls] == [COUNT_NULL_ISLAND]


def test_apply_detach_deletes_null_island_nodes():
    client = _FakeClient(locations=2, deleted=2)
    n = asyncio.run(run(client, dry_run=False))
    assert n == 2
    cyphers = [c[0] for c in client.calls]
    assert COUNT_NULL_ISLAND in cyphers
    assert DELETE_NULL_ISLAND in cyphers
    assert "DETACH DELETE" in DELETE_NULL_ISLAND


def test_delete_query_is_scoped_to_zero_zero():
    assert "l.lat = 0.0 AND l.lon = 0.0" in DELETE_NULL_ISLAND
