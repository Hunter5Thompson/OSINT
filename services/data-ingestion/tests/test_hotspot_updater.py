"""A03: source measurement failure must not become a zero-count de-escalation."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from feeds import hotspot_updater


@pytest.fixture
def updater(monkeypatch):
    monkeypatch.setattr(
        hotspot_updater,
        "QdrantClient",
        lambda **_kwargs: SimpleNamespace(scroll=lambda **_args: ([], None)),
    )
    instance = hotspot_updater.HotspotUpdater()
    instance._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return instance


def curated(identifier):
    return {
        "id": identifier,
        "name": identifier,
        "lat": 10,
        "lon": 20,
        "region": "Fixture",
        "description": "Fixture",
        "sources": ["fixture"],
        "threat_level": "high",
    }


@pytest.mark.asyncio
async def test_query_failure_is_not_a_zero_measurement(updater, monkeypatch):
    # Only this unit's thread-call boundary is mocked; no thread/runtime patch.
    monkeypatch.setattr(hotspot_updater.asyncio, "to_thread", AsyncMock(side_effect=TimeoutError))
    with pytest.raises(TimeoutError):
        await updater._count_recent_mentions("Fixture")


@pytest.mark.asyncio
async def test_partial_query_failure_retains_prior_record_and_other_hotspots(updater, monkeypatch):
    hotspots = [curated(identifier) for identifier in ["failed", "zero", "sixteen", "thirtyone"]]
    monkeypatch.setattr(hotspot_updater, "HOTSPOTS", hotspots)
    old = {
        **hotspots[0],
        "threat_level": "critical",
        "base_threat_level": "high",
        "recent_mentions": 40,
        "updated_at": "2026-10-09T00:00:00+00:00",
    }
    old_json = json.dumps(old)
    await updater._redis.set("hotspot:failed", old_json)
    updater._count_recent_mentions = AsyncMock(side_effect=[TimeoutError(), 0, 16, 31])
    await updater.update()
    assert await updater._redis.get("hotspot:failed") == old_json
    snapshot = json.loads(await updater._redis.get("hotspots:all"))
    assert [item["id"] for item in snapshot] == ["failed", "zero", "sixteen", "thirtyone"]
    assert [item["threat_level"] for item in snapshot] == [
        "CRITICAL",
        "ELEVATED",
        "CRITICAL",
        "CRITICAL",
    ]
    assert snapshot[0]["last_updated"] == old["updated_at"]
    assert json.loads(await updater._redis.get("hotspot:index")) == [
        item["id"] for item in snapshot
    ]


@pytest.mark.asyncio
async def test_failed_query_without_prior_uses_curated_base_with_unknown_count(
    updater, monkeypatch
):
    monkeypatch.setattr(hotspot_updater, "HOTSPOTS", [curated("failed")])
    updater._count_recent_mentions = AsyncMock(side_effect=TimeoutError)
    await updater.update()
    individual = json.loads(await updater._redis.get("hotspot:failed"))
    snapshot = json.loads(await updater._redis.get("hotspots:all"))
    assert individual["recent_mentions"] is None
    assert individual["threat_level"] == "high"
    assert individual["measurement_status"] == "unavailable"
    assert snapshot[0]["threat_level"] == "HIGH"
    assert snapshot[0]["last_updated"] == individual["updated_at"]
    assert individual["measurement_at"] is None


@pytest.mark.asyncio
async def test_failed_query_preserves_valid_aggregate_when_individual_expired(updater, monkeypatch):
    monkeypatch.setattr(hotspot_updater, "HOTSPOTS", [curated("failed")])
    prior = {
        "id": "failed",
        "name": "Original fixture",
        "latitude": 11,
        "longitude": 21,
        "region": "Fixture",
        "description": "Older valid record",
        "sources": ["fixture"],
        "threat_level": "CRITICAL",
        "last_updated": "2026-10-09T00:00:00+00:00",
    }
    await updater._redis.set("hotspots:all", json.dumps([prior]))
    updater._count_recent_mentions = AsyncMock(side_effect=TimeoutError)
    await updater.update()
    assert json.loads(await updater._redis.get("hotspots:all")) == [prior]
    assert await updater._redis.get("hotspot:failed") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["invalid JSON", "null", "[]", '{"id":"failed"}'])
async def test_corrupt_prior_record_uses_curated_base_without_invented_measurement(
    updater, monkeypatch, invalid
):
    monkeypatch.setattr(hotspot_updater, "HOTSPOTS", [curated("failed")])
    await updater._redis.set("hotspot:failed", invalid)
    updater._count_recent_mentions = AsyncMock(side_effect=TimeoutError)
    await updater.update()
    snapshot = json.loads(await updater._redis.get("hotspots:all"))
    assert snapshot[0]["threat_level"] == "HIGH"
    assert json.loads(await updater._redis.get("hotspot:failed"))["recent_mentions"] is None


@pytest.mark.asyncio
async def test_removed_curated_id_is_not_restored_from_old_snapshot(updater, monkeypatch):
    monkeypatch.setattr(hotspot_updater, "HOTSPOTS", [])
    prior = {
        "id": "removed",
        "name": "Removed",
        "latitude": 10,
        "longitude": 20,
        "region": "Fixture",
        "description": "Fixture",
        "sources": [],
        "threat_level": "CRITICAL",
        "last_updated": "2026-10-09T00:00:00Z",
    }
    await updater._redis.set("hotspots:all", json.dumps([prior]))
    await updater.update()
    assert json.loads(await updater._redis.get("hotspots:all")) == []


@pytest.mark.asyncio
async def test_redis_write_failure_is_not_a_successful_partial_snapshot(updater, monkeypatch):
    monkeypatch.setattr(hotspot_updater, "HOTSPOTS", [curated("failed")])
    old_json = '[{"id":"old snapshot sentinel"}]'
    await updater._redis.set("hotspots:all", old_json)
    updater._count_recent_mentions = AsyncMock(return_value=16)
    monkeypatch.setattr(updater._redis, "set", AsyncMock(side_effect=ConnectionError))
    with pytest.raises(ConnectionError):
        await updater.update()
    assert await updater._redis.get("hotspots:all") == old_json


@pytest.mark.asyncio
async def test_successful_empty_query_is_zero(updater, monkeypatch):
    monkeypatch.setattr(hotspot_updater.asyncio, "to_thread", AsyncMock(return_value=([], None)))
    assert await updater._count_recent_mentions("Fixture") == 0


def test_extreme_cached_coordinate_is_invalid_not_a_validation_crash(updater):
    old = {
        **curated("failed"),
        "lat": 10**1000,
        "recent_mentions": 40,
        "updated_at": "2026-10-09T00:00:00Z",
    }
    assert updater._retained_record(json.dumps(old), "failed") is None
