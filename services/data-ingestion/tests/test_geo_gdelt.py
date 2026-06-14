import asyncio

from graph_integrity import geo_gdelt
from graph_integrity.geo_gdelt import (
    BACKFILL_OCCURRED_AT,
    COUNT_EXISTING_GEOLESS,
    build_geo_row,
    export_url_for,
    slice_ids_from_parquet,
)


class _FakeClient:
    def __init__(self, count: int = 1):
        self.count = count
        self.calls: list = []

    async def run(self, cypher, params=None):
        self.calls.append((cypher, params))
        return [{"count": self.count}]


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
    assert "UNWIND $rows AS row" in q
    assert "MATCH (ev:GDELTEvent {event_id: row.event_id})" in q
    # idempotency guard: only backfill events that lack the edge
    assert "WHERE NOT (ev)-[:OCCURRED_AT]->(:Location)" in q
    assert "MERGE (l:Location {loc_key: row.loc_key})" in q
    assert "MERGE (ev)-[:OCCURRED_AT]->(l)" in q
    assert "gdelt_actiongeo" in q


def test_dry_run_count_template_scoped_to_existing_geoless_events():
    q = COUNT_EXISTING_GEOLESS
    assert "UNWIND $rows AS row" in q
    assert "MATCH (ev:GDELTEvent {event_id: row.event_id})" in q
    assert "WHERE NOT (ev)-[:OCCURRED_AT]->(:Location)" in q
    assert "RETURN count(ev) AS count" in q


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


def test_run_dry_run_counts_existing_geoless_events_without_writing(tmp_path):
    _seed_one_slice(tmp_path)
    rows = [
        {"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
         "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
         "action_geo_feature_id": "-1"},
        {"global_event_id": 2, "action_geo_lat": None, "action_geo_long": None},
    ]
    client = _FakeClient(count=1)
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=True, fetch=lambda _slice: rows,
    ))
    assert n == 1
    assert client.calls[0][0] == COUNT_EXISTING_GEOLESS
    assert client.calls[0][1]["rows"][0]["event_id"] == "gdelt:event:1"


def test_run_live_writes_existing_geoless_events_in_batch(tmp_path):
    _seed_one_slice(tmp_path)
    rows = [{"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
             "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
             "action_geo_feature_id": "-1"}]
    client = _FakeClient(count=1)
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=False, fetch=lambda _slice: rows,
    ))
    assert n == 1
    assert client.calls[0][0] == BACKFILL_OCCURRED_AT
    assert client.calls[0][1]["rows"][0]["event_id"] == "gdelt:event:1"


def test_run_skips_missing_slice_without_aborting(tmp_path):
    _seed_one_slice(tmp_path)

    def boom(_slice):
        raise FileNotFoundError("410 gone")

    client = _FakeClient()
    n = asyncio.run(geo_gdelt.run(
        client, parquet_base=tmp_path, dry_run=False, fetch=boom, skip_missing=True,
    ))
    assert n == 0
    assert client.calls == []


def test_fetch_and_parse_orchestrates_download_and_parse(tmp_path, monkeypatch):
    from graph_integrity import geo_gdelt

    fake_rows = [{"global_event_id": 1, "action_geo_lat": 48.0, "action_geo_long": 37.8,
                  "action_geo_fullname": "Donetsk", "action_geo_country_code": "UP",
                  "action_geo_feature_id": "-1"}]

    class _DF:
        def to_dicts(self):
            return fake_rows

    class _Res:
        df = _DF()

    monkeypatch.setattr(geo_gdelt, "_download_export",
                        lambda slice_id, dest: tmp_path / "x.csv")
    monkeypatch.setattr(geo_gdelt, "parse_events", lambda path, quarantine_dir: _Res())

    rows = geo_gdelt._fetch_and_parse("20260613221500")
    assert rows == fake_rows
