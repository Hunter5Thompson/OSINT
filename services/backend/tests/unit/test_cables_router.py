"""Contract tests for /api/v1/cables endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.cable import CableDataset, LandingPoint, SubmarineCable


@pytest.fixture
def mock_cable_dataset() -> CableDataset:
    return CableDataset(
        cables=[
            SubmarineCable(
                id="1",
                name="Test Cable",
                color="#ff6600",
                coordinates=[[[0.0, 1.0], [2.0, 3.0]]],
                landing_point_ids=["lp1"],
            )
        ],
        landing_points=[
            LandingPoint(id="lp1", name="Marseille", country="France", latitude=43.3, longitude=5.4)
        ],
        source="live",
    )


class TestCablesRouter:
    @pytest.mark.asyncio
    async def test_get_cables_returns_200(self, mock_cable_dataset: CableDataset) -> None:
        with patch("app.services.cable_service.get_cable_dataset", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = mock_cable_dataset
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/cables")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_cables_response_shape(self, mock_cable_dataset: CableDataset) -> None:
        with patch("app.services.cable_service.get_cable_dataset", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = mock_cable_dataset
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/cables")
            body = resp.json()
            assert "cables" in body
            assert "landing_points" in body
            assert "source" in body
            assert isinstance(body["cables"], list)
            assert body["cables"][0]["name"] == "Test Cable"
            assert body["source"] == "live"

    @pytest.mark.asyncio
    async def test_get_cables_502_on_error(self) -> None:
        with patch("app.services.cable_service.get_cable_dataset", new_callable=AsyncMock) as mock_fn:
            mock_fn.side_effect = Exception("boom")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/cables")
            assert resp.status_code == 502
