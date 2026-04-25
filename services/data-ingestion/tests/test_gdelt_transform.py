from datetime import datetime

import polars as pl

from gdelt_raw.transform import (
    canonicalize_events,
    canonicalize_gkg,
    canonicalize_mentions,
)


def _raw_filtered_events() -> pl.DataFrame:
    """Minimal raw-filtered events DataFrame as produced by filter.apply_filters."""
    return pl.DataFrame({
        "global_event_id": [1300904663],
        "event_id": ["gdelt:event:1300904663"],
        "event_code": ["193"],
        "event_root_code": [19],
        "quad_class": [4],
        "goldstein_scale": [-6.5],
        "avg_tone": [-4.2],
        "num_mentions": [12],
        "num_sources": [8],
        "num_articles": [11],
        "date_added": [20260425121500],
        "fraction_date": [2026.3164],
        "actor1_code": ["MIL"], "actor1_name": ["MILITARY"],
        "actor2_code": ["REB"], "actor2_name": ["REBELS"],
        "source_url": ["https://ex.com/a"],
        "codebook_type": ["conflict.armed"],
        "filter_reason": ["tactical"],
    })


def _raw_filtered_gkg() -> pl.DataFrame:
    return pl.DataFrame({
        "gkg_record_id": ["20260425121500-42"],
        "doc_id": ["gdelt:gkg:20260425121500-42"],
        "v21_date": [20260425121500],
        "v2_document_identifier": ["https://ex.com/a"],
        "v2_source_common_name": ["ex.com"],
        "v1_themes": ["ARMEDCONFLICT;KILL;MILITARY"],
        "v1_persons": ["Vladimir Putin;Joe Biden"],
        "v1_organizations": ["NATO;UN"],
        "v15_tone": ["2.1,5.0,-3.0,8.0,3.5,1.1,599"],
        "v21_sharp_image": ["https://ex.com/img.jpg"],
        "v21_quotations": [""],
        "linked_event_ids": [["gdelt:event:1", "gdelt:event:2"]],
        "goldstein_min": [-6.5],
        "goldstein_avg": [-6.0],
        "cameo_roots_linked": [[18, 19]],
        "codebook_types_linked": [["conflict.assault", "conflict.armed"]],
    })


def _raw_filtered_mentions() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [1300904663],
        "mention_identifier": ["https://ex.com/a"],
        "mention_doc_tone": [-6.1],
        "confidence": [100],
        "action_char_offset": [1664],
    })


def test_canonicalize_events_renames_and_adds_source():
    out = canonicalize_events(_raw_filtered_events())
    row = out.to_dicts()[0]
    assert row["event_id"] == "gdelt:event:1300904663"
    assert row["source"] == "gdelt"
    assert row["cameo_code"] == "193"
    assert row["cameo_root"] == 19
    assert row["goldstein"] == -6.5
    assert isinstance(row["date_added"], datetime)
    assert row["date_added"].year == 2026
    assert row["date_added"].month == 4
    assert row["codebook_type"] == "conflict.armed"
    assert row["filter_reason"] == "tactical"


def test_canonicalize_events_drops_raw_columns():
    out = canonicalize_events(_raw_filtered_events())
    assert "global_event_id" not in out.columns
    assert "event_code" not in out.columns
    assert "event_root_code" not in out.columns
    assert "goldstein_scale" not in out.columns


def test_canonicalize_gkg_parses_themes_into_list():
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    assert row["themes"] == ["ARMEDCONFLICT", "KILL", "MILITARY"]
    assert row["persons"] == ["Vladimir Putin", "Joe Biden"]
    assert row["organizations"] == ["NATO", "UN"]


def test_canonicalize_gkg_renames_url_and_dates():
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    assert row["doc_id"] == "gdelt:gkg:20260425121500-42"
    assert row["url"] == "https://ex.com/a"
    assert row["source_name"] == "ex.com"
    assert row["source"] == "gdelt_gkg"
    assert isinstance(row["gdelt_date"], datetime)
    assert row["published_at"] is None


def test_canonicalize_gkg_parses_v15_tone_seven_fields():
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    # V1.5 tone format: avgTone,posTone,negTone,polarity,actRef,selfGrpRef,wordCount
    assert row["tone_positive"] == 5.0
    assert row["tone_negative"] == -3.0
    assert row["tone_polarity"] == 8.0
    assert row["word_count"] == 599


def test_canonicalize_gkg_handles_empty_list_fields():
    df = _raw_filtered_gkg().with_columns([
        pl.lit("").alias("v1_persons"),
        pl.lit("").alias("v1_organizations"),
    ])
    out = canonicalize_gkg(df)
    row = out.to_dicts()[0]
    assert row["persons"] == []
    assert row["organizations"] == []


def test_canonicalize_mentions_renames_and_builds_canonical_event_id():
    out = canonicalize_mentions(_raw_filtered_mentions())
    row = out.to_dicts()[0]
    assert row["event_id"] == "gdelt:event:1300904663"
    assert row["mention_url"] == "https://ex.com/a"
    assert row["tone"] == -6.1
    assert row["confidence"] == 100
    assert row["char_offset"] == 1664


def test_canonical_event_validates_against_pydantic_writer_contract():
    """Integration check: canonical output must pass GDELTEventWrite."""
    from gdelt_raw.schemas import GDELTEventWrite
    out = canonicalize_events(_raw_filtered_events())
    row = out.to_dicts()[0]
    GDELTEventWrite.model_validate(row)  # raises if schema mismatch


def test_canonical_doc_validates_against_pydantic_writer_contract():
    from gdelt_raw.schemas import GDELTDocumentWrite
    out = canonicalize_gkg(_raw_filtered_gkg())
    row = out.to_dicts()[0]
    GDELTDocumentWrite.model_validate(row)
