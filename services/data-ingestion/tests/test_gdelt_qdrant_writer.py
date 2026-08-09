from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from gdelt_raw.writers.qdrant_writer import (
    QdrantWriter,
    build_embed_text,
    build_payload,
)
from graph_integrity.spatial_normalizer import load_normalization_index

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIRECTORY = (
    REPOSITORY_ROOT
    / "services/backend/data/spatial/catalogs/spatial-v1-e76a16bff799"
)
CROSSWALK_PATH = (
    REPOSITORY_ROOT
    / "services/data-ingestion/spatial_catalog/data/country_crosswalk.json"
)


@pytest.fixture(scope="module")
def spatial_index():
    return load_normalization_index(
        CATALOG_DIRECTORY,
        crosswalk_path=CROSSWALK_PATH,
    )


def _event_row(**overrides):
    row = {
        "event_id": "gdelt:event:1",
        "source": "gdelt",
        "cameo_code": "193",
        "cameo_root": 19,
        "quad_class": 4,
        "goldstein": -6.5,
        "avg_tone": -4.0,
        "num_mentions": 3,
        "num_sources": 2,
        "num_articles": 3,
        "date_added": "2026-06-13T22:15:00Z",
        "fraction_date": 2026.4,
        "actor1_code": None,
        "actor1_name": None,
        "actor2_code": None,
        "actor2_name": None,
        "source_url": "https://example.test/event",
        "codebook_type": "conflict.armed",
        "filter_reason": "tactical",
        "action_geo_lat": 48.0,
        "action_geo_long": 37.8,
        "action_geo_fullname": "Donetsk, Ukraine",
        "action_geo_country_code": "UP",
        "action_geo_feature_id": "-1044367",
    }
    row.update(overrides)
    return row


def test_embed_text_is_deterministic():
    row = {
        "doc_id": "gdelt:gkg:r1",
        "title": "Strike in Donbas",
        "themes": ["ARMEDCONFLICT", "KILL"],
        "persons": ["Foo"],
        "organizations": ["NATO"],
    }
    a = build_embed_text(row)
    b = build_embed_text(row)
    assert a == b
    assert len(a) <= 1500


def test_payload_uses_canonical_doc_id():
    row = {
        "doc_id": "gdelt:gkg:r1",
        "url": "https://ex.com",
        "source_name": "ex.com",
        "gdelt_date": "2026-04-25T12:00:00",
        "themes": ["ARMEDCONFLICT", "KILL"],
        "persons": [],
        "organizations": [],
        "linked_event_ids": ["gdelt:event:1", "gdelt:event:2"],
        "goldstein_min": -6.0,
        "goldstein_avg": -4.0,
        "cameo_roots_linked": [18, 19],
        "codebook_types_linked": ["conflict.assault", "conflict.armed"],
        "tone_polarity": 8.4,
        "word_count": 599,
    }
    p = build_payload(row)
    assert p["doc_id"] == "gdelt:gkg:r1"
    assert p["source"] == "gdelt_gkg"
    assert p["source_name"] == "ex.com"
    assert p["gdelt_date"] == "2026-04-25T12:00:00"
    assert isinstance(p["linked_event_ids"], list)
    assert isinstance(p["cameo_roots_linked"], list)


def test_payload_linked_fields_are_lists():
    row = {
        "doc_id": "gdelt:gkg:r2", "url": "https://ex.com",
        "source_name": "ex.com", "gdelt_date": "2026-04-25T12:00:00",
        "themes": [], "persons": [], "organizations": [],
        "linked_event_ids": None, "goldstein_min": None, "goldstein_avg": None,
        "cameo_roots_linked": None, "codebook_types_linked": None,
        "tone_polarity": 0.0, "word_count": 0,
    }
    p = build_payload(row)
    assert p["linked_event_ids"] == []
    assert p["cameo_roots_linked"] == []


@pytest.mark.asyncio
async def test_qdrant_can_upsert_when_neo4j_failed_but_parquet_exists(tmp_path):
    """Qdrant reads only from GKG parquet — it must NOT require Neo4j state."""
    df = pl.DataFrame({
        "doc_id": ["gdelt:gkg:r1"],
        "url": ["https://ex.com"],
        "source_name": ["ex.com"],
        "gdelt_date": ["2026-04-25T12:00:00"],
        "themes": [["ARMEDCONFLICT", "KILL"]],
        "persons": [["A"]],
        "organizations": [[]],
        "linked_event_ids": [["gdelt:event:1"]],
        "goldstein_min": [-6.0],
        "goldstein_avg": [-6.0],
        "cameo_roots_linked": [[19]],
        "codebook_types_linked": [["conflict.armed"]],
        "tone_polarity": [8.4],
        "word_count": [599],
    })
    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    df.write_parquet(gkg_dir / "20260425120000.parquet")

    mock_client = MagicMock()
    mock_client.get_collections = AsyncMock(
        return_value=MagicMock(collections=[]),
    )
    mock_client.create_collection = AsyncMock()
    mock_client.upsert = AsyncMock()
    embedder = AsyncMock(return_value=[0.1] * 1024)

    w = QdrantWriter(client=mock_client, embed=embedder, collection="test")
    n = await w.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")
    assert n == 1
    mock_client.create_collection.assert_awaited_once()
    mock_client.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_qdrant_occurrence_comes_from_exact_linked_event_action_geo(
    tmp_path,
    spatial_index,
):
    gkg = pl.DataFrame({
        "doc_id": ["gdelt:gkg:r1"],
        "url": ["https://ex.com"],
        "source_name": ["ex.com"],
        "title": ["No location inference from this title"],
        "gdelt_date": ["2026-04-25T12:00:00"],
        "themes": [["ARMEDCONFLICT"]],
        "persons": [[]],
        "organizations": [[]],
        "linked_event_ids": [["gdelt:event:1"]],
        "goldstein_min": [-6.0],
        "goldstein_avg": [-6.0],
        "cameo_roots_linked": [[19]],
        "codebook_types_linked": [["conflict.armed"]],
        "tone_polarity": [8.4],
        "word_count": [599],
    })
    events = pl.DataFrame([_event_row()])
    for stream, frame in (("gkg", gkg), ("events", events)):
        stream_dir = tmp_path / stream / "date=2026-04-25"
        stream_dir.mkdir(parents=True)
        frame.write_parquet(stream_dir / "20260425120000.parquet")

    client = MagicMock()
    client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    writer = QdrantWriter(
        client=client,
        embed=AsyncMock(return_value=[0.1] * 1024),
        collection="test",
        spatial_index=spatial_index,
    )

    await writer.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    point = client.upsert.await_args.kwargs["points"][0]
    assert point.payload["spatial_occurrence_scope_revision_tokens"] == [
        "sr1|country:UKR|spatial-derive-v1-d30efa07e141",
        "sr1|admin1:iso3166-2:UA-14|spatial-derive-v1-4d1de888e0c7",
    ]
    assert point.payload["spatial_about_scope_revision_tokens"] == []
    assert point.payload["geo"] == {"lon": 37.8, "lat": 48.0}
    assert point.payload["spatial_derivations"][0]["evidence_id"] == (
        "gdelt:event:1"
    )


@pytest.mark.asyncio
async def test_gkg_title_and_themes_never_infer_occurrence(
    tmp_path,
    spatial_index,
):
    gkg = pl.DataFrame({
        "doc_id": ["gdelt:gkg:r2"],
        "url": ["https://ex.com/ukraine"],
        "source_name": ["ex.com"],
        "title": ["Ukraine Donetsk conflict"],
        "gdelt_date": ["2026-04-25T12:00:00"],
        "themes": [["UKRAINE", "DONETSK"]],
        "persons": [[]],
        "organizations": [[]],
        "linked_event_ids": [[]],
        "goldstein_min": [None],
        "goldstein_avg": [None],
        "cameo_roots_linked": [[]],
        "codebook_types_linked": [[]],
        "tone_polarity": [0.0],
        "word_count": [100],
    })
    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    gkg.write_parquet(gkg_dir / "20260425120000.parquet")

    client = MagicMock()
    client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    writer = QdrantWriter(
        client=client,
        embed=AsyncMock(return_value=[0.1] * 1024),
        collection="test",
        spatial_index=spatial_index,
    )

    await writer.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    point = client.upsert.await_args.kwargs["points"][0]
    assert point.payload["spatial_occurrence_scope_revision_tokens"] == []
    assert point.payload["spatial_derivations"] == []


@pytest.mark.asyncio
async def test_qdrant_writer_validates_existing_collection_only_once():
    collection = MagicMock(name="odin_intel")
    collection.name = "odin_intel"
    info = MagicMock()
    client = MagicMock()
    client.get_collections = AsyncMock(
        return_value=MagicMock(collections=[collection]),
    )
    client.get_collection = AsyncMock(return_value=info)

    writer = QdrantWriter(client=client, embed=AsyncMock(), collection="odin_intel")
    with patch("gdelt_raw.writers.qdrant_writer.validate_collection_schema") as validate:
        await writer._ensure_collection()
        await writer._ensure_collection()

    validate.assert_called_once_with(info, enable_hybrid=False)
    client.get_collections.assert_awaited_once()
    client.create_payload_index.assert_not_called()


@pytest.mark.asyncio
async def test_qdrant_writer_close_releases_client():
    client = MagicMock(close=AsyncMock())
    writer = QdrantWriter(client=client, embed=AsyncMock(), collection="odin_intel")

    await writer.close()

    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_qdrant_skips_row_with_null_doc_id(tmp_path):
    """A null doc_id must be skipped+logged, not crash uuid5(NAMESPACE_URL, None)."""
    df = pl.DataFrame({
        "doc_id": ["gdelt:gkg:g1", None],
        "url": ["https://ex.com/1", "https://ex.com/2"],
        "source_name": ["ex.com", "ex.com"],
        "gdelt_date": ["2026-04-25T12:00:00", "2026-04-25T12:00:00"],
        "themes": [["MILITARY"], ["MILITARY"]],
        "persons": [[], []], "organizations": [[], []],
        "linked_event_ids": [[], []], "goldstein_min": [None, None],
        "goldstein_avg": [None, None], "cameo_roots_linked": [[], []],
        "codebook_types_linked": [[], []],
        "tone_polarity": [0.0, 0.0], "word_count": [0, 0],
    })
    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    df.write_parquet(gkg_dir / "20260425120000.parquet")

    mock_client = MagicMock()
    mock_client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    mock_client.create_collection = AsyncMock()
    mock_client.upsert = AsyncMock()
    embedder = AsyncMock(return_value=[0.1] * 1024)

    w = QdrantWriter(client=mock_client, embed=embedder, collection="test")
    n = await w.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    assert n == 1                                  # only the valid row upserted
    mock_client.upsert.assert_called_once()
    (_, kwargs) = mock_client.upsert.call_args
    assert len(kwargs["points"]) == 1
    assert embedder.call_count == 1  # skipped row must not burn a TEI call
