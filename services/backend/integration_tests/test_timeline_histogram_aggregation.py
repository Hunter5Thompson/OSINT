"""Real Neo4j equivalence and bounded-transfer gate on a disposable marked DB."""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

os.environ.setdefault("NEO4J_PASSWORD", "histogram-test-only")

from app.routers import timeline  # noqa: E402
from app.services import spatial_filters  # noqa: E402
from app.services.severity import (  # noqa: E402
    category_of,
    dominant_category,
    normalize_severity,
)


@pytest.fixture
async def database():
    uri = os.environ.get("HN_TEST_NEO4J_URI")
    password = os.environ.get("HN_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.fail("Explicit isolated HN Neo4j credentials are required")
    driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
    async with driver.session() as session:
        result = await session.run(
            "MATCH (:HNTestInstance {id: 'hn-g06-isolated-20261010'}) RETURN true"
        )
        assert await result.single() is not None, "Isolated test marker missing"
    token = uuid4().hex
    try:
        yield driver, token
    finally:
        async with driver.session() as session:
            while True:
                result = await session.run(
                    "MATCH (n {histogram_test: $token}) WITH n LIMIT 1000 "
                    "DETACH DELETE n RETURN count(*) AS removed", token=token,
                )
                if (await result.single())["removed"] == 0:
                    break
        await driver.close()


async def read(driver, query, params):
    async with driver.session() as session:
        result = await session.run(query, params)
        return await result.data()


@pytest.mark.parametrize("start", ["1969-12-31T23:59:58Z", "2091-06-01T00:00:00Z"])
@pytest.mark.parametrize("scope", ["global", "bbox", "dateline", "country", "admin1", "admin2"])
async def test_histogram_preserves_all_events_with_bounded_database_rows(database, start, scope):
    driver, token = database
    size = int(os.environ.get("HN_HISTOGRAM_EVENT_COUNT", "2000"))
    start_ms = int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() * 1000)
    end = datetime.fromtimestamp((start_ms + 4000) / 1000, UTC).isoformat()
    dates = [
        start, end,
        datetime.fromtimestamp((start_ms + 1000) / 1000, UTC).isoformat(),
        datetime.fromtimestamp((start_ms + 999.999) / 1000, UTC).isoformat(),
        datetime.fromtimestamp((start_ms + 1999.001) / 1000, UTC).isoformat(),
        datetime.fromtimestamp((start_ms + 2500) / 1000, UTC).astimezone().isoformat(),
        datetime.fromtimestamp((start_ms - 1) / 1000, UTC).isoformat(),
        datetime.fromtimestamp((start_ms + 4001) / 1000, UTC).isoformat(),
    ]
    for offset in range(0, size, 1000):
        await read(driver, """
            UNWIND range($offset, $end - 1) AS i
            CREATE (ev:Event {histogram_test: $token,
              timeline_at: datetime($dates[i % size($dates)]),
              codebook_type: $categories[i % size($categories)],
              severity: $severities[i % size($severities)]})
            CREATE (l:Location {histogram_test: $token,
              lat: 0.0, lon: CASE WHEN i % 2 = 0 THEN 175.0 ELSE 25.0 END,
              country_scope_key: 'country:UKR', admin1_scope_key: 'admin1:UKR.1',
              admin2_scope_key: 'admin2:UKR.1.1',
              spatial_conflict: i % 13 = 0,
              spatial_derivation_revision: CASE WHEN i % 11 = 0 THEN 'old' ELSE 'current' END})
            CREATE (ev)-[:OCCURRED_AT]->(l)
            CREATE (ev)-[:OCCURRED_AT]->(l)
            """, {"offset": offset, "end": min(offset + 1000, size), "token": token, "dates": dates,
                  "categories": ["civil.demo", "military.strike", None, " custom .x", 12,
                                 ".bad", "conflict.armed", "zeta", "alpha"],
                  "severities": [None, " WARNING ", "moderate", "elevated", "extreme", 5,
                                 "invalid", "low", "medium", "critical"]})
    params = {"t_start": start, "t_end": end, "start_ms": start_ms,
              "bucket_ms": 1000, "buckets": 4, "bbox_off": scope == "global",
              "west": 170 if scope == "dateline" else 20,
              "east": -170 if scope == "dateline" else 30, "south": -10, "north": 10,
              "scope_key": {"country": "country:UKR", "admin1": "admin1:UKR.1",
                            "admin2": "admin2:UKR.1.1"}.get(scope),
              "compatible_revisions": ["current"]}
    if scope in ("global", "bbox", "dateline"):
        query = timeline._HISTOGRAM_QUERY
        legacy = """
          MATCH (ev:Event)
          WHERE ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
          OPTIONAL MATCH (ev)-[:OCCURRED_AT]->(l:Location)
          WITH ev, l WHERE $bbox_off OR
            (l.lat IS NOT NULL AND l.lon IS NOT NULL AND l.lat >= $south AND l.lat <= $north
             AND (($west <= $east AND l.lon >= $west AND l.lon <= $east)
               OR ($west > $east AND (l.lon >= $west OR l.lon <= $east))))
          WITH DISTINCT ev
        """
    else:
        query = getattr(spatial_filters, f"_EVENTS_{scope.upper()}_SCOPE_HISTOGRAM_QUERY")
        # Test-owned identifier comes only from the closed parametrization above.
        legacy = f"""
          MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
          WHERE l.{scope}_scope_key = $scope_key
            AND l.spatial_derivation_revision IN $compatible_revisions
            AND l.spatial_conflict = false
            AND ev.timeline_at >= datetime($t_start) AND ev.timeline_at <= datetime($t_end)
          WITH DISTINCT ev
        """
    legacy += (" RETURN toString(ev.timeline_at) AS time, "
               "ev.codebook_type AS codebook_type, ev.severity AS severity")
    before = perf_counter()
    raw = await read(driver, legacy, params)
    raw_seconds = perf_counter() - before
    before = perf_counter()
    grouped = await read(driver, query, params)
    seconds = perf_counter() - before
    assert len(raw) > 100
    assert len(grouped) <= params["buckets"]
    # Independent legacy Python binning oracle, including negative/sub-ms times.
    expected = {}
    for row in raw:
        ms = int(datetime.fromisoformat(row["time"].replace("Z", "+00:00")).timestamp() * 1000)
        bucket = max(0, min((ms - start_ms) // 1000, 3))
        expected.setdefault(bucket, []).append(row)
    actual = timeline._histogram_buckets(grouped, start_ms, 1000)
    for bucket in actual:
        index = (int(datetime.fromisoformat(bucket.ts).timestamp() * 1000) - start_ms) // 1000
        rows = expected.pop(index)
        assert bucket.count == len(rows)
        assert bucket.by_category == dict(Counter(category_of(r["codebook_type"]) for r in rows))
        assert bucket.by_severity == dict(Counter(normalize_severity(r["severity"]) for r in rows))
        assert bucket.dominant_category == dominant_category([r["codebook_type"] for r in rows])
    assert not expected
    assert sum(b.count for b in actual) == len(raw)
    if path := os.environ.get("HN_HISTOGRAM_EVIDENCE"):
        with Path(path).open("a") as output:
            output.write(json.dumps({"scope": scope, "start": start, "seeded": size,
                "raw_rows": len(raw), "grouped_rows": len(grouped),
                "raw_bytes": len(json.dumps(raw)), "grouped_bytes": len(json.dumps(grouped)),
                "raw_seconds": raw_seconds, "grouped_seconds": seconds,
                "equivalent": True}) + "\n")
