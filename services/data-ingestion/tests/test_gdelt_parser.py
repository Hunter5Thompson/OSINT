"""Tests for the two-stage GDELT CSV parser."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from gdelt_raw.parser import parse_events

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"


def test_parser_uses_tab_separator():
    """Regression: sanity-check strict parse uses tabs."""
    res = parse_events(FIXTURES / "slice_20260425_full.export.CSV")
    assert isinstance(res.df, pl.DataFrame)
    assert res.df.height >= 1
    # Column names match EVENT_COLUMNS
    assert "global_event_id" in res.df.columns
    assert "quad_class" in res.df.columns


def test_strict_parse_fallback_quarantines_bad_rows(tmp_path):
    quarantine = tmp_path / "quarantine" / "slice"
    res = parse_events(
        FIXTURES / "slice_malformed.export.CSV",
        quarantine_dir=quarantine,
    )
    # Expect: 2 valid rows parsed, 1 line quarantined
    assert res.df.height == 2
    assert res.quarantine_count == 1
    qfile = quarantine / "events.jsonl"
    assert qfile.exists()
    content = qfile.read_text()
    assert "THIS_IS_A_BROKEN_ROW" in content


def test_parse_error_pct_computed():
    res = parse_events(FIXTURES / "slice_malformed.export.CSV")
    # 1 bad / 3 total = 33.3% — above default 5% threshold
    assert res.parse_error_pct > 30.0
    assert res.parse_error_pct < 40.0
