"""GP HTTP-to-cache producer contract with isolated Redis and source fixtures."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fakeredis.aioredis
import pytest

from feeds.gp_updater import GPUpdater

GP = json.loads(
    (
        Path(__file__).resolve().parents[3] / "tests/fixtures/satellites/celestrak-100651.json"
    ).read_text()
)
URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=JSON"


@pytest.mark.asyncio
async def test_six_digit_gp_http_is_written_to_independent_cache(httpx_mock):
    httpx_mock.add_response(url=URL, json=[GP])
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater._redis.set("tle:group:active", "legacy untouched")
    await updater.update()
    cached = await updater._redis.get("orbits:v1:group:active")
    assert cached is not None
    body = json.loads(cached)
    assert body["schema_version"] == 1
    assert body["satellites"][0]["norad_id"] == 100651
    assert body["satellites"][0]["orbit"]["elements"]["NORAD_CAT_ID"] == 100651
    assert body["fetched_at"].endswith("Z")
    assert body["satellites"][0]["orbit"]["elements"]["EPOCH"] == GP["EPOCH"] + "Z"
    assert await updater._redis.get("orbits:v1:norad:100651") is not None
    assert await updater._redis.get("tle:group:active") == "legacy untouched"


@pytest.mark.asyncio
async def test_poison_row_keeps_healthy_neighbors_and_diagnostics(httpx_mock):
    httpx_mock.add_response(
        url=URL, json=[GP, {**GP, "NORAD_CAT_ID": True}, {**GP, "NORAD_CAT_ID": 100652}]
    )
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater.update()
    body = json.loads(await updater._redis.get("orbits:v1:group:active"))
    assert [row["norad_id"] for row in body["satellites"]] == [100651, 100652]
    assert body["status"] == "partial"
    assert body["rejections"][0]["code"] == "invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, None, "error", [{}]])
async def test_invalid_group_never_overwrites_retained_cache(payload, httpx_mock):
    httpx_mock.add_response(url=URL, json=payload)
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater._redis.set("orbits:v1:group:active", "retained old snapshot")
    with pytest.raises(ValueError):
        await updater.update()
    assert await updater._redis.get("orbits:v1:group:active") == "retained old snapshot"


@pytest.mark.asyncio
async def test_failed_group_does_not_block_next_healthy_group(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=500)
    httpx_mock.add_response(url=URL.replace("GROUP=active", "GROUP=stations"), json=[GP])
    updater = GPUpdater(["active", "stations"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater.update()
    assert await updater._redis.get("orbits:v1:group:active") is None
    assert (
        json.loads(await updater._redis.get("orbits:v1:group:stations"))["satellites"][0][
            "norad_id"
        ]
        == 100651
    )


@pytest.mark.asyncio
async def test_valid_empty_group_is_explicit_success(httpx_mock):
    httpx_mock.add_response(url=URL, json=[])
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater.update()
    body = json.loads(await updater._redis.get("orbits:v1:group:active"))
    assert body["satellites"] == []
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_restart_does_not_redownload_within_celestrak_cycle(httpx_mock):
    httpx_mock.add_response(url=URL, json=[GP])
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater.update()
    before = await updater._redis.get("orbits:v1:group:active")
    await updater.update()
    assert await updater._redis.get("orbits:v1:group:active") == before
    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_unchanged_response_keeps_original_fetch_time(httpx_mock):
    httpx_mock.add_response(url=URL, json=[GP])
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater.update()
    old = json.loads(await updater._redis.get("orbits:v1:group:active"))
    old["fetched_at"] = (datetime.now(UTC) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    await updater._redis.set("orbits:v1:group:active", json.dumps(old))
    httpx_mock.add_response(
        url=URL, status_code=403, text="GP data has not updated since your last successful download"
    )
    await updater.update()
    assert json.loads(await updater._redis.get("orbits:v1:group:active")) == old


@pytest.mark.asyncio
async def test_unchanged_without_any_cache_is_unavailable(httpx_mock):
    httpx_mock.add_response(
        url=URL, status_code=403, text="GP data has not updated since your last successful download"
    )
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with pytest.raises(ValueError):
        await updater.update()


@pytest.mark.asyncio
async def test_overlapping_group_cannot_replace_a_newer_individual_epoch(httpx_mock):
    httpx_mock.add_response(url=URL, json=[{**GP, "EPOCH": "2026-10-09T08:00:00.000000"}])
    httpx_mock.add_response(url=URL.replace("GROUP=active", "GROUP=stations"), json=[GP])
    updater = GPUpdater(["active", "stations"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater.update()
    individual = json.loads(await updater._redis.get("orbits:v1:norad:100651"))
    assert individual["orbit"]["elements"]["EPOCH"] == "2026-10-09T08:00:00.000000Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["version", "catalog", "fetched", "accepted", "status"])
async def test_corrupt_cache_refetches_and_does_not_delete_legacy(damage, httpx_mock):
    from feeds.gp_updater import decode_gp_group

    body = decode_gp_group([GP], "active", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    if damage == "version":
        body["schema_version"] = True
    elif damage == "catalog":
        body["satellites"][0]["norad_id"] = 1
    elif damage == "fetched":
        body["fetched_at"] = "not-a-time"
    elif damage == "accepted":
        body["accepted_records"] = 0
    else:
        body["status"] = "partial"
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await updater._redis.set("orbits:v1:group:active", json.dumps(body))
    await updater._redis.set("tle:group:active", "legacy untouched")
    httpx_mock.add_response(url=URL, json=[GP])
    await updater.update()
    assert len(httpx_mock.get_requests()) == 1
    assert (
        json.loads(await updater._redis.get("orbits:v1:group:active"))["satellites"][0]["norad_id"]
        == 100651
    )
    assert await updater._redis.get("tle:group:active") == "legacy untouched"


@pytest.mark.asyncio
async def test_concurrent_newer_epoch_survives_transaction_conflict(httpx_mock, monkeypatch):
    from feeds.gp_updater import decode_gp_group

    httpx_mock.add_response(url=URL, json=[GP])
    updater = GPUpdater(["active"])
    updater._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    newer = decode_gp_group(
        [{**GP, "EPOCH": "2026-10-09T08:00:00.000000"}], "other", "2026-10-10T00:00:00Z"
    )["satellites"][0]
    pipeline_type = type(updater._redis.pipeline())
    original = pipeline_type.execute
    injected = False

    async def concurrent_write(pipe, *args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            await updater._redis.set("orbits:v1:norad:100651", json.dumps(newer))
        return await original(pipe, *args, **kwargs)

    monkeypatch.setattr(pipeline_type, "execute", concurrent_write)
    await updater.update()
    actual = json.loads(await updater._redis.get("orbits:v1:norad:100651"))
    assert actual["orbit"]["elements"]["EPOCH"] == "2026-10-09T08:00:00.000000Z"
