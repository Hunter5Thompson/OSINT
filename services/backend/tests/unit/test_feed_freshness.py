"""Tests for the data-based feed freshness watchdog."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.feed_freshness import compute_feed_freshness

NOW = 1_800_000_000.0


def _point(epoch: float) -> object:
    class P:
        payload = {"ingested_epoch": epoch}

    return P()


def _client_by_source(latest: dict[str, float | None | Exception]) -> AsyncMock:
    """Fake Qdrant whose scroll answers per `source` filter value."""

    async def scroll(**kwargs: object) -> tuple[list[object], None]:
        flt = kwargs["scroll_filter"]
        source = flt.must[0].match.value  # type: ignore[attr-defined]
        value = latest[source]
        if isinstance(value, Exception):
            raise value
        return ([_point(value)] if value is not None else [], None)

    client = AsyncMock()
    client.scroll.side_effect = scroll
    return client


@pytest.mark.asyncio
async def test_fresh_stale_and_missing_sources_are_classified() -> None:
    client = _client_by_source({"rss": NOW - 600, "firms": NOW - 50_000, "ucdp": None})
    report = await compute_feed_freshness(
        client,
        collection="odin_intel",
        max_age_s={"rss": 7200, "firms": 43_200, "ucdp": 3_888_000},
        now=NOW,
    )

    by = {s.source: s for s in report.sources}
    assert by["rss"].status == "fresh" and by["rss"].age_s == 600
    assert by["firms"].status == "stale" and by["firms"].age_s == 50_000
    assert by["ucdp"].status == "missing" and by["ucdp"].last_ingested_at is None
    assert report.status == "degraded"


@pytest.mark.asyncio
async def test_all_fresh_is_ok_and_latest_point_is_requested_by_epoch_desc() -> None:
    client = _client_by_source({"rss": NOW - 60})
    report = await compute_feed_freshness(
        client, collection="odin_intel", max_age_s={"rss": 7200}, now=NOW
    )

    assert report.status == "ok"
    assert report.sources[0].last_ingested_at is not None
    kwargs = client.scroll.call_args.kwargs
    assert kwargs["limit"] == 1
    assert kwargs["order_by"].key == "ingested_epoch"
    assert kwargs["order_by"].direction == "desc"


@pytest.mark.asyncio
async def test_query_failure_is_unknown_not_fresh() -> None:
    # e.g. missing ingested_epoch range index -> order_by is rejected by Qdrant
    client = _client_by_source({"rss": RuntimeError("no range index for ingested_epoch")})
    report = await compute_feed_freshness(
        client, collection="odin_intel", max_age_s={"rss": 7200}, now=NOW
    )

    assert report.sources[0].status == "unknown"
    assert "range index" in (report.sources[0].error or "")
    assert report.status == "degraded"


@pytest.mark.asyncio
async def test_non_numeric_epoch_payload_is_unknown() -> None:
    client = _client_by_source({"rss": "garbage"})  # type: ignore[dict-item]
    report = await compute_feed_freshness(
        client, collection="odin_intel", max_age_s={"rss": 7200}, now=NOW
    )
    assert report.sources[0].status == "unknown"


def test_feeds_health_endpoint_serves_report() -> None:
    client = _client_by_source(dict.fromkeys(
        ("gdelt_gkg", "rss", "rss_fulltext", "telegram", "firms", "usgs",
         "eonet", "gdacs", "ucdp", "portwatch"),
        None,
    ))
    client.scroll.side_effect = None
    client.scroll.return_value = ([], None)
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    app.state.cache = mock_cache

    with patch(
        "app.routers.feed_health.get_qdrant_client", AsyncMock(return_value=client)
    ):
        resp = TestClient(app).get("/api/health/feeds")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert {s["status"] for s in body["sources"]} == {"missing"}
    assert "rss" in {s["source"] for s in body["sources"]}
