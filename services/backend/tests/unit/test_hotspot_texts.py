"""D06: invalid identities are isolated and missing optional text stays empty."""

import httpx
import pytest

from app.main import app
from app.routers.hotspots import _hotspots_from_rows

GOOD = {
    "id": "good",
    "name": "Good",
    "latitude": 10,
    "longitude": 20,
    "region": "Fixture",
    "description": "A fixture",
    "threat_level": "HIGH",
    "sources": ["fixture"],
}


@pytest.mark.parametrize("field", ["id", "name"])
@pytest.mark.parametrize("value", [None, "", "   ", 0, False, {}])
def test_invalid_identity_only_removes_its_own_row(field, value):
    rows = _hotspots_from_rows([{**GOOD, field: value}, GOOD])
    assert [row.id for row in rows] == ["good"]


@pytest.mark.parametrize("value", [None, 0, False, {}, []])
def test_invalid_optional_text_is_empty(value):
    result = _hotspots_from_rows([{**GOOD, "region": value, "description": value}])
    assert len(result) == 1
    assert result[0].region == ""
    assert result[0].description == ""


def test_real_text_and_existing_sources_and_coordinates_are_preserved():
    result = _hotspots_from_rows([{**GOOD, "id": " good ", "name": " Good "}])
    assert result[0].id == "good"
    assert result[0].name == "Good"
    assert result[0].region == GOOD["region"]
    assert result[0].description == GOOD["description"]
    assert result[0].latitude == 10 and result[0].longitude == 20
    assert result[0].sources == ["fixture"]


async def test_http_cache_neighbor_with_null_identity_is_not_stringified():
    app.state.cache.get.return_value = [
        {**GOOD, "id": None},
        {**GOOD, "region": None, "description": None},
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/hotspots")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["good"]
    assert response.json()[0]["region"] == response.json()[0]["description"] == ""
