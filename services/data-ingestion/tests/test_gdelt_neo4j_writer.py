import pytest
from pydantic import ValidationError

from gdelt_raw.schemas import GDELTDocumentWrite, GDELTEventWrite
from gdelt_raw.writers.neo4j_writer import (
    MERGE_DOC,
    MERGE_EVENT,
    MERGE_THEME,
    render_doc_params,
    render_event_params,
)


def test_event_template_has_secondary_label():
    assert ":Event:GDELTEvent" in MERGE_EVENT


def test_doc_template_has_secondary_label():
    assert ":Document:GDELTDocument" in MERGE_DOC


def test_writer_rejects_event_without_event_id():
    with pytest.raises(ValidationError):
        GDELTEventWrite.model_validate({
            "cameo_code": "193", "cameo_root": 19, "quad_class": 4,
            "goldstein": -6.5, "avg_tone": -4.2,
            "num_mentions": 12, "num_sources": 8, "num_articles": 11,
            "date_added": "2026-04-25T12:15:00Z", "fraction_date": 2026.3164,
            "source_url": "https://example.com/x",
            "codebook_type": "conflict.armed",
            "filter_reason": "tactical",
        })


def test_writer_rejects_doc_without_doc_id():
    with pytest.raises(ValidationError):
        GDELTDocumentWrite.model_validate({
            "url": "https://example.com/a",
            "source_name": "ex.com",
            "gdelt_date": "2026-04-25T12:15:00Z",
        })


def test_render_event_params_passes_through_fields():
    ev = GDELTEventWrite(
        event_id="gdelt:event:42",
        cameo_code="193", cameo_root=19, quad_class=4,
        goldstein=-6.5, avg_tone=-4.2,
        num_mentions=12, num_sources=8, num_articles=11,
        date_added="2026-04-25T12:15:00Z", fraction_date=2026.3164,
        source_url="https://ex.com",
        codebook_type="conflict.armed",
        filter_reason="tactical",
    )
    params = render_event_params(ev)
    assert params["event_id"] == "gdelt:event:42"
    assert params["cameo_root"] == 19
    assert params["codebook_type"] == "conflict.armed"


def test_render_doc_params_handles_optional_published_at():
    doc = GDELTDocumentWrite(
        doc_id="gdelt:gkg:r1",
        url="https://ex.com",
        source_name="ex.com",
        gdelt_date="2026-04-25T12:15:00Z",
    )
    params = render_doc_params(doc)
    assert params["doc_id"] == "gdelt:gkg:r1"
    assert params["published_at"] is None


def test_merge_theme_template_is_idempotent():
    """MERGE on the :ABOUT relationship must not carry a counter —
    otherwise replay increments it unboundedly."""
    assert "r.count = r.count + 1" not in MERGE_THEME
    # Still writes themes
    assert "UNWIND $themes" in MERGE_THEME
    assert ":ABOUT" in MERGE_THEME


def test_merge_mention_optional_match_and_returns_found_flags():
    """WP-09: OPTIONAL MATCH so a missing Document/Event is detectable (not a
    silent zero-row no-op); conditional MERGE only when both bound; RETURN the
    found-flags so write_mentions can classify drops."""
    from gdelt_raw.writers.neo4j_writer import MERGE_MENTION
    assert "OPTIONAL MATCH (d:Document {url: $doc_url})" in MERGE_MENTION
    assert "OPTIONAL MATCH (e:GDELTEvent {event_id: $event_id})" in MERGE_MENTION
    assert "FOREACH" in MERGE_MENTION
    assert "r.tone = $tone" in MERGE_MENTION  # properties still set
    assert "d_found" in MERGE_MENTION and "e_found" in MERGE_MENTION
    # No stub-Document fallback (must not defeat the theme filter):
    assert "MERGE (d:Document" not in MERGE_MENTION


# ---------------------------------------------------------------------------
# WP-02: skip-and-log invalid rows
# ---------------------------------------------------------------------------
from unittest.mock import AsyncMock  # noqa: E402

import polars as pl  # noqa: E402


def test_validate_rows_skips_invalid_keeps_valid():
    from gdelt_raw.writers.neo4j_writer import _validate_rows

    rows = [
        {  # valid
            "event_id": "gdelt:event:1", "cameo_code": "193", "cameo_root": 19,
            "quad_class": 4, "goldstein": -6.5, "avg_tone": -4.2,
            "num_mentions": 1, "num_sources": 1, "num_articles": 1,
            "date_added": "2026-04-25T12:15:00Z", "fraction_date": 2026.3164,
            "source_url": "https://ex.com", "codebook_type": "conflict.armed",
            "filter_reason": "tactical",
        },
        {  # invalid: missing event_id
            "cameo_code": "193", "cameo_root": 19, "quad_class": 4,
            "goldstein": -6.5, "avg_tone": -4.2, "num_mentions": 1,
            "num_sources": 1, "num_articles": 1, "date_added": "2026-04-25T12:15:00Z",
            "fraction_date": 2026.3164, "source_url": "https://ex.com",
            "codebook_type": "conflict.armed", "filter_reason": "tactical",
        },
    ]
    valid = _validate_rows(rows, GDELTEventWrite, "events")
    assert len(valid) == 1
    assert valid[0].event_id == "gdelt:event:1"


def test_validate_rows_skips_null_doc_id():
    from gdelt_raw.writers.neo4j_writer import _validate_rows

    rows = [
        {"doc_id": "gdelt:gkg:r1", "url": "https://ex.com", "source_name": "ex.com",
         "gdelt_date": "2026-04-25T12:15:00Z"},
        {"doc_id": None, "url": "https://ex.com", "source_name": "ex.com",
         "gdelt_date": "2026-04-25T12:15:00Z"},
    ]
    valid = _validate_rows(rows, GDELTDocumentWrite, "gkg")
    assert len(valid) == 1
    assert valid[0].doc_id == "gdelt:gkg:r1"


@pytest.mark.asyncio
async def test_write_from_parquet_skips_bad_gkg_row(tmp_path):
    """One null-doc_id row in the gkg parquet must not block the valid docs."""
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter

    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    pl.DataFrame({
        "doc_id": ["gdelt:gkg:g1", None],
        "source": ["gdelt_gkg", "gdelt_gkg"],
        "url": ["https://ex.com/1", "https://ex.com/2"],
        "source_name": ["ex.com", "ex.com"],
        "gdelt_date": ["2026-04-25T12:00:00", "2026-04-25T12:00:00"],
        "themes": [["MILITARY"], ["MILITARY"]],
        "persons": [[], []], "organizations": [[], []],
        "tone_positive": [0.0, 0.0], "tone_negative": [0.0, 0.0],
        "tone_polarity": [0.0, 0.0], "tone_activity": [0.0, 0.0],
        "tone_self_group": [0.0, 0.0], "word_count": [0, 0],
        "sharp_image_url": [None, None], "quotations": [[], []],
        "linked_event_ids": [[], []], "goldstein_min": [None, None],
        "goldstein_avg": [None, None], "cameo_roots_linked": [[], []],
        "codebook_types_linked": [[], []],
    }).write_parquet(gkg_dir / "20260425120000.parquet")

    writer = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    writer.write_docs = AsyncMock()           # capture validated docs; no real Neo4j
    writer.write_events = AsyncMock()
    writer.write_mentions = AsyncMock()

    await writer.write_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    writer.write_docs.assert_awaited_once()
    (docs,) = writer.write_docs.await_args.args
    assert len(docs) == 1
    assert docs[0].doc_id == "gdelt:gkg:g1"


@pytest.mark.asyncio
async def test_write_from_parquet_all_invalid_gkg_is_noop(tmp_path):
    """A gkg parquet where every row is invalid (all null doc_id) must leave
    write_docs uncalled (the `if docs:` guard) — not an empty-list write."""
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter

    gkg_dir = tmp_path / "gkg" / "date=2026-04-25"
    gkg_dir.mkdir(parents=True)
    pl.DataFrame({
        "doc_id": [None, None],
        "source": ["gdelt_gkg", "gdelt_gkg"],
        "url": ["https://ex.com/1", "https://ex.com/2"],
        "source_name": ["ex.com", "ex.com"],
        "gdelt_date": ["2026-04-25T12:00:00", "2026-04-25T12:00:00"],
        "themes": [["MILITARY"], ["MILITARY"]],
        "persons": [[], []], "organizations": [[], []],
        "tone_positive": [0.0, 0.0], "tone_negative": [0.0, 0.0],
        "tone_polarity": [0.0, 0.0], "tone_activity": [0.0, 0.0],
        "tone_self_group": [0.0, 0.0], "word_count": [0, 0],
        "sharp_image_url": [None, None], "quotations": [[], []],
        "linked_event_ids": [[], []], "goldstein_min": [None, None],
        "goldstein_avg": [None, None], "cameo_roots_linked": [[], []],
        "codebook_types_linked": [[], []],
    }).write_parquet(gkg_dir / "20260425120000.parquet")

    writer = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    writer.write_docs = AsyncMock()
    writer.write_events = AsyncMock()
    writer.write_mentions = AsyncMock()

    await writer.write_from_parquet(tmp_path, "20260425120000", "2026-04-25")

    writer.write_docs.assert_not_awaited()


# ---------------------------------------------------------------------------
# WP-09: observable MENTIONS writes — _classify_mention + write_mentions
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock  # noqa: E402

import structlog  # noqa: E402


def test_classify_mention_outcomes():
    from gdelt_raw.writers.neo4j_writer import _classify_mention
    assert _classify_mention(d_found=False, e_found=True, rels_created=0) == "dropped_no_document"
    assert _classify_mention(d_found=True, e_found=False, rels_created=0) == "dropped_no_event"
    assert _classify_mention(d_found=True, e_found=True, rels_created=1) == "written"
    assert _classify_mention(d_found=True, e_found=True, rels_created=0) == "existing"
    assert _classify_mention(d_found=False, e_found=False, rels_created=0) == "dropped_no_document"


def _mention_result(d_found: bool, e_found: bool, rels_created: int):
    result = MagicMock()
    result.single = AsyncMock(return_value={"d_found": d_found, "e_found": e_found})
    summary = MagicMock()
    summary.counters.relationships_created = rels_created
    result.consume = AsyncMock(return_value=summary)
    return result


def _writer_with_tx(results: list):
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter
    tx = MagicMock()
    tx.run = AsyncMock(side_effect=results)
    tx.commit = AsyncMock()
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=tx)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_transaction = AsyncMock(return_value=tx_cm)
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    w = Neo4jWriter("bolt://localhost:7687", "neo4j", "x")
    w._driver = MagicMock()
    w._driver.session = MagicMock(return_value=session_cm)
    return w


@pytest.mark.asyncio
async def test_write_mentions_counts_and_warns_on_drops():
    w = _writer_with_tx([
        _mention_result(True, True, 1),    # written
        _mention_result(True, True, 0),    # existing
        _mention_result(False, True, 0),   # dropped_no_document
        _mention_result(True, False, 0),   # dropped_no_event
    ])
    mentions = [
        {"mention_url": f"https://ex.com/{i}", "event_id": f"gdelt:event:{i}",
         "tone": 0.0, "confidence": 100, "char_offset": 0}
        for i in range(4)
    ]
    with structlog.testing.capture_logs() as logs:
        counts = await w.write_mentions(mentions, "20260425120000")

    assert counts == {"written": 1, "existing": 1,
                      "dropped_no_document": 1, "dropped_no_event": 1}
    metric = [e for e in logs if e["event"] == "gdelt_mentions_written_total"]
    assert metric and metric[0]["written"] == 1 and metric[0]["dropped_no_document"] == 1
    assert any(e["event"] == "gdelt_mentions_dropped_no_document_total"
               and e["log_level"] == "warning" for e in logs)


@pytest.mark.asyncio
async def test_write_mentions_empty_is_noop():
    """A slice with zero mentions returns all-zero counts and does not raise."""
    w = _writer_with_tx([])
    counts = await w.write_mentions([], "20260425120000")
    assert counts == {"written": 0, "existing": 0,
                      "dropped_no_document": 0, "dropped_no_event": 0}
