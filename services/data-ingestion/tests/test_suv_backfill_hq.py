import httpx
import pytest

from suv_structured.backfill_hq import (
    build_hq_link_statements,
    count_location_targets,
    fetch_suv_orgs,
    unmapped_or_ambiguous_targets,
)


def test_build_hq_link_statements_maps_and_skips():
    rows = [("Rheinmetall", "Deutschland"), ("KNDS", "Niederlande"), ("Skyfall", "Atlantis")]
    statements, skipped = build_hq_link_statements(rows)
    params = [s["parameters"] for s in statements]
    assert {"name": "Rheinmetall", "country": "Germany"} in params
    assert {"name": "KNDS", "country": "Netherlands"} in params
    assert len(statements) == 2
    assert skipped == [("Skyfall", "Atlantis")]
    assert all("HEADQUARTERED_IN" in s["statement"] for s in statements)


def test_unmapped_or_ambiguous_targets_flags_non_singletons():
    assert unmapped_or_ambiguous_targets({"Germany": 1, "Netherlands": 1}) == []
    assert unmapped_or_ambiguous_targets({"Germany": 0, "Netherlands": 1}) == ["Germany"]
    assert unmapped_or_ambiguous_targets({"Germany": 2}) == ["Germany"]


@pytest.mark.asyncio
async def test_fetch_suv_orgs_parses_rows():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"data": [
            {"row": ["Rheinmetall", "Deutschland"]},
            {"row": ["KNDS", "Niederlande"]},
        ]}], "errors": []})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        rows = await fetch_suv_orgs(client, neo4j_http_url="http://neo",
                                    neo4j_user="neo4j", neo4j_password="pw")
    assert rows == [("Rheinmetall", "Deutschland"), ("KNDS", "Niederlande")]


@pytest.mark.asyncio
async def test_count_location_targets_zero_fills_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"data": [
            {"row": ["Germany", 1]},
            {"row": ["Atlantis", 0]},
        ]}], "errors": []})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        counts = await count_location_targets(client, ["Germany", "Atlantis"],
                                              neo4j_http_url="http://neo",
                                              neo4j_user="neo4j", neo4j_password="pw")
    assert counts == {"Germany": 1, "Atlantis": 0}


@pytest.mark.asyncio
async def test_read_raises_on_neo4j_error_body():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"results": [], "errors": [{"message": "boom"}]}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="boom"):
            await fetch_suv_orgs(client, neo4j_http_url="http://neo",
                                 neo4j_user="neo4j", neo4j_password="pw")


@pytest.mark.asyncio
async def test_count_location_targets_empty_list_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"data": []}], "errors": []})
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        counts = await count_location_targets(client, [], neo4j_http_url="http://neo",
                                              neo4j_user="neo4j", neo4j_password="pw")
    assert counts == {}


@pytest.mark.asyncio
async def test_run_read_raises_on_http_error_status():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, text="unavailable"))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_suv_orgs(client, neo4j_http_url="http://neo",
                                 neo4j_user="neo4j", neo4j_password="pw")
