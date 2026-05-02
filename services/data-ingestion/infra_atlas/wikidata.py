"""Wikidata SPARQL client.

Synchronous wrapper around https://query.wikidata.org/sparql. Always returns
JSON; flattens each binding into a {var: value} dict.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = (
    "ODIN-Worldview/0.1 "
    "(https://github.com/Hunter5Thompson/ODIN; ai.zero.shot@gmail.com)"
)
DEFAULT_TIMEOUT = 60.0


class WikidataRow:
    """Parsers for the value shapes Wikidata returns."""

    _WKT_POINT_RE = re.compile(r"^Point\(([-\d.]+)\s+([-\d.]+)\)$")
    _QID_RE = re.compile(r"/entity/(Q\d+)$")

    @classmethod
    def parse_wkt_point(cls, wkt: str) -> tuple[float, float]:
        """Return (lon, lat) from a Wikidata P625 WKT point string."""
        match = cls._WKT_POINT_RE.match(wkt.strip())
        if not match:
            raise ValueError(f"not a WKT Point: {wkt!r}")
        return float(match.group(1)), float(match.group(2))

    @classmethod
    def qid_from_uri(cls, uri: str) -> str:
        match = cls._QID_RE.search(uri)
        if not match:
            raise ValueError(f"not a Wikidata entity URI: {uri!r}")
        return match.group(1)


class WikidataClient:
    """Synchronous Wikidata SPARQL client."""

    def __init__(self, endpoint: str = WIKIDATA_SPARQL, timeout: float = DEFAULT_TIMEOUT):
        self._endpoint = endpoint
        self._timeout = timeout

    def query(self, sparql: str) -> list[dict[str, Any]]:
        resp = httpx.get(
            self._endpoint,
            params={"query": sparql, "format": "json"},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        return [
            {var: binding[var]["value"] for var in binding}
            for binding in payload["results"]["bindings"]
        ]
