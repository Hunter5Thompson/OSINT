from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

from gdelt_raw.writers.qdrant_writer import (
    QdrantWriter,
    build_embed_text,
    build_payload,
)


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
        "v2_source_common_name": "ex.com",
        "v1_themes": "ARMEDCONFLICT;KILL",
        "themes": ["ARMEDCONFLICT", "KILL"],
        "persons": [],
        "organizations": [],
        "linked_event_ids": ["gdelt:event:1", "gdelt:event:2"],
        "goldstein_min": -6.0,
        "goldstein_avg": -4.0,
        "cameo_roots_linked": [18, 19],
        "codebook_types_linked": ["conflict.assault", "conflict.armed"],
        "v21_date": 20260425120000,
        "tone_polarity": 8.4,
        "word_count": 599,
    }
    p = build_payload(row)
    assert p["doc_id"] == "gdelt:gkg:r1"
    assert p["source"] == "gdelt_gkg"
    assert isinstance(p["linked_event_ids"], list)
    assert isinstance(p["cameo_roots_linked"], list)


def test_payload_linked_fields_are_lists():
    row = {
        "doc_id": "gdelt:gkg:r2", "url": "https://ex.com",
        "v2_source_common_name": "ex.com", "v1_themes": "",
        "themes": [], "persons": [], "organizations": [],
        "linked_event_ids": None, "goldstein_min": None, "goldstein_avg": None,
        "cameo_roots_linked": None, "codebook_types_linked": None,
        "v21_date": 20260425120000, "tone_polarity": 0.0, "word_count": 0,
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
        "v2_source_common_name": ["ex.com"],
        "v1_themes": ["ARMEDCONFLICT;KILL"],
        "themes": [["ARMEDCONFLICT", "KILL"]],
        "persons": [["A"]],
        "organizations": [[]],
        "linked_event_ids": [["gdelt:event:1"]],
        "goldstein_min": [-6.0],
        "goldstein_avg": [-6.0],
        "cameo_roots_linked": [[19]],
        "codebook_types_linked": [["conflict.armed"]],
        "v21_date": [20260425120000],
        "tone_polarity": [8.4],
        "word_count": [599],
    })
    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    df.write_parquet(gkg_dir / "20260425120000.parquet")

    mock_client = MagicMock()
    mock_client.upsert = AsyncMock()
    embedder = AsyncMock(return_value=[0.1] * 1024)

    w = QdrantWriter(client=mock_client, embed=embedder, collection="test")
    n = await w.upsert_from_parquet(tmp_path, "20260425120000", "2026-04-25")
    assert n == 1
    mock_client.upsert.assert_called_once()
