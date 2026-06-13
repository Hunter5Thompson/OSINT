import asyncio

from graph_integrity import geo_gdelt
from graph_integrity.geo_gdelt import (
    BACKFILL_OCCURRED_AT,
    build_geo_row,
    export_url_for,
    slice_ids_from_parquet,
)


class _FakeClient:
    def __init__(self):
        self.writes: list = []

    async def run(self, cypher, params=None):
        self.writes.append(params)
        return []


def _seed_one_slice(tmp_path):
    d = tmp_path / "events" / "date=20260613"
    d.mkdir(parents=True)
    (d / "20260613221500.parquet").touch()


def test_slice_ids_from_parquet(tmp_path):
    d = tmp_path / "events" / "date=20260613"
    d.mkdir(parents=True)
    (d / "20260613221500.parquet").touch()
    (d / "20260613224500.parquet").touch()
    ids = slice_ids_from_parquet(tmp_path)
    assert ids == ["20260613221500", "20260613224500"]


def test_export_url_for():
    assert export_url_for("20260613221500") == (
        "http://data.gdeltproject.org/gdeltv2/20260613221500.export.CSV.zip"
    )


def test_backfill_template_scoped_to_existing_geoless_events():
    q = BACKFILL_OCCURRED_AT
    assert "MATCH (ev:GDELTEvent {event_id: $event_id})" in q
    assert "MERGE (l:Location {loc_key: $loc_key})" in q
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in q
    assert "gdelt_actiongeo" in q


def test_build_geo_row_from_raw():
    raw = {
        "global_event_id": 12345, "action_geo_lat": 48.0, "action_geo_long": 37.8,
        "action_geo_fullname": "Donetsk, Ukraine", "action_geo_country_code": "UP",
        "action_geo_feature_id": "-1044367",
    }
    row = build_geo_row(raw)
    assert row["event_id"] == "gdelt:event:12345"
    assert row["loc_key"] == "gdelt:loc:-1044367"
    assert row["lat"] == 48.0
    assert build_geo_row({"global_event_id": 9, "action_geo_lat": None}) is None


def test_run_dry_run_counts_geo_rows_without_writing(tmp_path):
    _seed_one_slice(tmp_path)
    rows = [
        {"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
         "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
         "action_geo_feature_id": "-1"},
        {"global_event_id": 2, "action_geo_lat": None, "action_geo_long": None},
    ]
    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=True, fetch=lambda _slice: rows,
    ))
    assert n == 1
    assert client.writes == []


def test_run_live_writes_each_geo_row(tmp_path):
    _seed_one_slice(tmp_path)
    rows = [{"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
             "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
             "action_geo_feature_id": "-1"}]
    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=False, fetch=lambda _slice: rows,
    ))
    assert n == 1
    assert client.writes[0]["event_id"] == "gdelt:event:1"


def test_run_skips_missing_slice_without_aborting(tmp_path):
    _seed_one_slice(tmp_path)

    def boom(_slice):
        raise FileNotFoundError("410 gone")

    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=False, fetch=boom, skip_missing=True,
    ))
    assert n == 0
    assert client.writes == []
