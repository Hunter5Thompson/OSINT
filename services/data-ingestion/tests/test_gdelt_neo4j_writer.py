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


def test_merge_mention_sets_properties_on_match_too():
    """Replay must not leave stale tone/confidence; ON MATCH re-sets them."""
    from gdelt_raw.writers.neo4j_writer import MERGE_MENTION
    assert "ON MATCH" in MERGE_MENTION
    assert "r.tone = $tone" in MERGE_MENTION
