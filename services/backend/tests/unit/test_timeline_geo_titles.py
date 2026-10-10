"""U07b optional titles from query projection through the actual histogram API."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.main import app
from app.models.spatial import ScopeKind
from app.routers.timeline import _GEO_EVENTS_QUERY, _geo_events_from_rows
from app.services.spatial_filters import EventSpatialRelation, exact_event_query_templates

ROWS = json.loads(
    (Path(__file__).parents[4] / "tests/fixtures/timeline/geo-event-titles.json").read_text()
)


@pytest.mark.parametrize("kind", [ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2])
def test_exact_geo_queries_project_source_title(kind):
    templates = exact_event_query_templates(kind, EventSpatialRelation.OCCURS_IN)
    assert "ev.title AS title" in templates.geo


def test_approximate_geo_query_projects_source_title():
    assert "ev.title AS title" in _GEO_EVENTS_QUERY


@pytest.mark.parametrize("title", [None, 42, {}, "", "Original source headline"])
def test_geo_title_is_optional_and_never_invented(title):
    events, _, _ = _geo_events_from_rows([{**ROWS[0], "title": title}])
    assert events[0].model_dump()["title"] == (title if isinstance(title, str) else None)


@pytest.mark.parametrize("bbox", [None, "170,-90,-170,90"])
async def test_histogram_transports_titles_and_preserves_spatial_accounting(bbox):
    read = AsyncMock(side_effect=[ROWS, [], [], ROWS])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.routers.timeline.read_query", read):
            params = {"t_start": "2026-06-01T00:00:00Z", "t_end": "2026-06-02T00:00:00Z"}
            if bbox is not None:
                params["bbox"] = bbox
            response = await client.get("/api/timeline/histogram", params=params)
    assert response.status_code == 200
    body = response.json()
    assert body["geo_events"][0]["title"] == "Original source headline"
    assert body["geo_events"][1]["title"] is None
    assert body["geo_events"][2]["title"] is None
    assert body["geo_events"][0]["lat"] == 50.4
    assert body["geo_located_count"] == 3
    assert body["spatial_application"]["mode"] == ("global" if bbox is None else "bbox_approximate")
    assert body["bucket_ms"] == 720_000
