"""WP-05: a document is geo-stamped only when it resolves to exactly ONE distinct
country. Multi-country docs stay geoless (honest located:0) instead of plotting
every event onto the first location's country centroid."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline import _write_to_neo4j
from tests.test_pipeline import _make_settings


async def _geo_statements(events, locations):
    """Run _write_to_neo4j with the given locations; return posted Cypher statements."""
    captured = {}

    async def _post(url, json, auth):  # noqa: A002 — mirror httpx kwarg name
        captured["statements"] = json["statements"]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"results": [], "errors": []}
        return resp

    client = AsyncMock()
    client.post = _post
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("pipeline.httpx.AsyncClient", return_value=cm):
        await _write_to_neo4j(
            events, [], "http://u", "doc title", "rss", _make_settings(),
            locations=locations,
        )
    return captured["statements"]


def _has_occurred_at(stmts):
    return any("OCCURRED_AT" in s["statement"] for s in stmts)


def _occurred_loc_key(stmts):
    for s in stmts:
        if "OCCURRED_AT" in s["statement"]:
            return s["parameters"].get("loc_key")
    return None


@pytest.mark.asyncio
async def test_single_country_single_location_stamps_centroid():
    stmts = await _geo_statements(
        [{"title": "Strike on Kyiv", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}],
    )
    assert _has_occurred_at(stmts)
    assert _occurred_loc_key(stmts) == "centroid:ua"


@pytest.mark.asyncio
async def test_single_country_multiple_locations_still_stamps():
    stmts = await _geo_statements(
        [{"title": "Strikes across Ukraine", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}, {"name": "Odessa", "country": "Ukraine"}],
    )
    assert _has_occurred_at(stmts)
    assert _occurred_loc_key(stmts) == "centroid:ua"


@pytest.mark.asyncio
async def test_multi_country_document_is_geoless():
    stmts = await _geo_statements(
        [{"title": "Russia strikes Kyiv; US sanctions Iran",
          "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}, {"name": "Tehran", "country": "Iran"}],
    )
    assert not _has_occurred_at(stmts)


@pytest.mark.asyncio
async def test_known_plus_unresolvable_country_is_geoless():
    stmts = await _geo_statements(
        [{"title": "x", "codebook_type": "conflict.armed_clash"}],
        [{"name": "Kyiv", "country": "Ukraine"}, {"name": "Nowhere", "country": "Atlantis"}],
    )
    assert not _has_occurred_at(stmts)


@pytest.mark.asyncio
async def test_empty_locations_is_geoless():
    stmts = await _geo_statements(
        [{"title": "x", "codebook_type": "conflict.armed_clash"}], [],
    )
    assert not _has_occurred_at(stmts)
