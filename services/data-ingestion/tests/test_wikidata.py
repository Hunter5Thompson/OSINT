"""Tests for the shared Wikidata SPARQL client."""

import pytest
from pytest_httpx import HTTPXMock

from infra_atlas.wikidata import WikidataClient, WikidataRow

WIKIDATA_RESPONSE = {
    "head": {"vars": ["item", "itemLabel", "coord"]},
    "results": {
        "bindings": [
            {
                "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q42"},
                "itemLabel": {"type": "literal", "value": "Test Site"},
                "coord": {
                    "type": "literal",
                    "datatype": "http://www.opengis.net/ont/geosparql#wktLiteral",
                    "value": "Point(13.4 52.5)",
                },
            }
        ]
    },
}


def test_query_returns_parsed_rows(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=WIKIDATA_RESPONSE)
    client = WikidataClient()
    rows = client.query("SELECT ?item ?itemLabel ?coord WHERE { ?item wdt:P31 wd:Q42 }")
    assert len(rows) == 1
    assert rows[0]["itemLabel"] == "Test Site"
    assert rows[0]["item"] == "http://www.wikidata.org/entity/Q42"


def test_parse_wkt_point_extracts_lon_lat() -> None:
    lon, lat = WikidataRow.parse_wkt_point("Point(13.4 52.5)")
    assert lon == pytest.approx(13.4)
    assert lat == pytest.approx(52.5)


def test_parse_wkt_point_rejects_non_point() -> None:
    with pytest.raises(ValueError):
        WikidataRow.parse_wkt_point("LineString(0 0, 1 1)")


def test_qid_from_uri_extracts_qid() -> None:
    qid = WikidataRow.qid_from_uri("http://www.wikidata.org/entity/Q3417395")
    assert qid == "Q3417395"


def test_query_handles_empty_results(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json={"head": {"vars": []}, "results": {"bindings": []}})
    client = WikidataClient()
    rows = client.query("SELECT ?x WHERE { ?x wdt:P31 wd:Qnonexistent }")
    assert rows == []
