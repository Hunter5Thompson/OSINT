# services/backend/tests/test_briefing_endpoint.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_briefing_streams_for_known_country(monkeypatch):
    async def fake_stream(**kwargs):
        assert "grounding_evidence" in kwargs and kwargs["grounding_evidence"]
        yield {"event": "status", "data": "{}"}
        yield {"event": "result", "data": '{"analysis":"ok"}'}
        yield {"event": "done", "data": ""}
    monkeypatch.setattr("app.routers.almanac.stream_intel_query", fake_stream)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/almanac/countries/276/briefing")
        assert r.status_code == 200
        assert "result" in r.text


@pytest.mark.asyncio
async def test_briefing_404_for_unknown_country(monkeypatch):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/almanac/countries/zzz/briefing")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_briefing_works_for_rest_fallback_countries(monkeypatch):
    async def fake_stream(**kwargs):
        # sparse-facts countries still produce an almanac evidence item
        assert kwargs["grounding_evidence"][0]["provider"] == "odin-country-almanac"
        yield {"event": "result", "data": '{"analysis":"ok"}'}
        yield {"event": "done", "data": ""}
    monkeypatch.setattr("app.routers.almanac.stream_intel_query", fake_stream)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        for cid in ("732", "275"):  # ESH (W. Sahara) + PSE (Palestine), REST-fallback profiles
            r = await ac.post(f"/api/almanac/countries/{cid}/briefing")
            assert r.status_code == 200
