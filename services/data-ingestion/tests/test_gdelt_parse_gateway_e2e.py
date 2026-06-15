"""T2 acceptance: one malformed key never destroys a slice's batch.

parse -> filter -> canonicalize -> (mocked) Neo4j + Qdrant writers, all in
process. No dev-compose services required (stores are mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

from gdelt_raw.filter import apply_filters
from gdelt_raw.parser import parse_gkg
from gdelt_raw.transform import canonicalize_gkg
from gdelt_raw.writers.neo4j_writer import Neo4jWriter
from gdelt_raw.writers.qdrant_writer import QdrantWriter


def _gkg_line(record_id: str, url: str, themes: str = "MILITARY",
              date: str = "20260425120000") -> str:
    f = [""] * 27
    f[0] = record_id            # gkg_record_id
    f[1] = date                 # v21_date
    f[3] = "ex.com"             # v2_source_common_name (fixed; override f[3] to vary source_name)
    f[4] = url                  # v2_document_identifier
    f[7] = themes               # v1_themes
    f[15] = "0,0,0,0,0,0,0"     # v15_tone
    return "\t".join(f)


def _empty_events_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [], "event_root_code": [], "quad_class": [],
        "goldstein_scale": [], "avg_tone": [], "num_mentions": [],
        "num_sources": [], "num_articles": [], "date_added": [],
        "fraction_date": [], "event_code": [], "actor1_code": [],
        "actor1_name": [], "actor2_code": [], "actor2_name": [], "source_url": [],
        "action_geo_lat": [], "action_geo_long": [], "action_geo_fullname": [],
        "action_geo_country_code": [], "action_geo_feature_id": [],
    }, schema={
        "global_event_id": pl.Int64, "event_root_code": pl.Int32,
        "quad_class": pl.Int8, "goldstein_scale": pl.Float64, "avg_tone": pl.Float64,
        "num_mentions": pl.Int32, "num_sources": pl.Int32, "num_articles": pl.Int32,
        "date_added": pl.Int64, "fraction_date": pl.Float64, "event_code": pl.Utf8,
        "actor1_code": pl.Utf8, "actor1_name": pl.Utf8, "actor2_code": pl.Utf8,
        "actor2_name": pl.Utf8, "source_url": pl.Utf8, "action_geo_lat": pl.Float64,
        "action_geo_long": pl.Float64, "action_geo_fullname": pl.Utf8,
        "action_geo_country_code": pl.Utf8, "action_geo_feature_id": pl.Utf8,
    })


def _empty_mentions_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [], "mention_identifier": [], "mention_doc_tone": [],
        "confidence": [], "action_char_offset": [],
    }, schema={
        "global_event_id": pl.Int64, "mention_identifier": pl.Utf8,
        "mention_doc_tone": pl.Float64, "confidence": pl.Int32,
        "action_char_offset": pl.Int32,
    })


@pytest.mark.asyncio
async def test_one_empty_gkgid_does_not_destroy_the_slice(tmp_path):
    csv = tmp_path / "s.gkg.csv"
    csv.write_text("\n".join([
        _gkg_line("", "https://ex.com/poison"),    # poison
        _gkg_line("g1", "https://ex.com/a"),
        _gkg_line("g2", "https://ex.com/b"),
    ]) + "\n")

    # 1. parse — poison quarantined, written to JSONL, error pct reflects it
    gk = parse_gkg(csv, quarantine_dir=tmp_path / "q")
    assert gk.df.height == 2
    assert gk.quarantine_count == 1
    assert 30.0 < gk.parse_error_pct < 40.0          # 1 quarantined of 3 rows
    qfile = tmp_path / "q" / "gkg.jsonl"
    assert qfile.exists() and "null_key" in qfile.read_text()

    # 2. filter + canonicalize the two survivors (no events -> empty linked aggs)
    fr = apply_filters(
        _empty_events_df(), _empty_mentions_df(), gk.df,
        cameo_roots=[15, 18, 19, 20],
        theme_alpha=["MILITARY"],
        theme_nuclear_override=["NUCLEAR", "WMD"],
    )
    assert fr.gkg.height == 2
    assert fr.gkg.get_column("doc_id").null_count() == 0
    gkg_canon = canonicalize_gkg(fr.gkg)

    # 3. write parquet
    gkg_dir = tmp_path / "gdelt" / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    gkg_canon.write_parquet(gkg_dir / "20260425120000.parquet")

    # 4. Neo4j writer (mocked driver) — both valid docs reach write_docs
    neo = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    neo.write_docs = AsyncMock()
    neo.write_events = AsyncMock()
    neo.write_mentions = AsyncMock()
    await neo.write_from_parquet(tmp_path / "gdelt", "20260425120000", "2026-04-25")
    neo.write_docs.assert_awaited_once()
    call = neo.write_docs.await_args
    docs = call.args[0] if call.args else call.kwargs["docs"]
    assert {d.doc_id for d in docs} == {"gdelt:gkg:g1", "gdelt:gkg:g2"}

    # 5. Qdrant writer (mocked client) — both valid docs upserted
    mock_client = MagicMock()
    mock_client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    mock_client.create_collection = AsyncMock()
    mock_client.upsert = AsyncMock()
    qw = QdrantWriter(client=mock_client, embed=AsyncMock(return_value=[0.1] * 1024),
                      collection="test")
    n = await qw.upsert_from_parquet(tmp_path / "gdelt", "20260425120000", "2026-04-25")
    assert n == 2
