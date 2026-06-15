"""Tests for the two-stage GDELT CSV parser."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from gdelt_raw.parser import parse_events, parse_gkg, parse_mentions

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


def test_parser_raises_filenotfound_on_missing_slice(tmp_path):
    missing = tmp_path / "does-not-exist.export.CSV"
    with pytest.raises(FileNotFoundError):
        parse_events(missing)


def _gkg_line(record_id: str, *, url: str = "https://ex.com/a",
              themes: str = "MILITARY", date: str = "20260425120000") -> str:
    """Build a 27-column GKG line (tab-separated). Empty record_id => null key."""
    f = [""] * 27
    f[0] = record_id                 # gkg_record_id
    f[1] = date                      # v21_date
    f[3] = "ex.com"                  # v2_source_common_name
    f[4] = url                       # v2_document_identifier
    f[7] = themes                    # v1_themes
    f[15] = "0,0,0,0,0,0,0"          # v15_tone
    return "\t".join(f)


def test_gkg_empty_record_id_is_quarantined_valid_rows_survive(tmp_path):
    csv = tmp_path / "s.gkg.csv"
    csv.write_text("\n".join([
        _gkg_line(""),                       # poison: empty leading GKGRecordID
        _gkg_line("g1", url="https://ex.com/1"),
        _gkg_line("g2", url="https://ex.com/2"),
    ]) + "\n")
    q = tmp_path / "q"
    res = parse_gkg(csv, quarantine_dir=q)

    assert res.df.height == 2                                  # only valid rows remain
    assert res.df.get_column("gkg_record_id").null_count() == 0
    assert set(res.df.get_column("gkg_record_id").to_list()) == {"g1", "g2"}
    assert res.quarantine_count == 1                           # poison counted
    assert res.parse_error_pct > 30.0                          # 1 of 3
    qfile = q / "gkg.jsonl"
    assert qfile.exists()
    assert "null_key" in qfile.read_text()


def test_events_null_global_event_id_is_quarantined(tmp_path):
    """Reuse a real valid events line; blank its global_event_id on one copy."""
    good = (FIXTURES / "slice_20260425_full.export.CSV").read_text().splitlines()[0]
    parts = good.split("\t")
    parts[0] = ""                            # blank global_event_id => null key
    bad = "\t".join(parts)
    csv = tmp_path / "s.export.CSV"
    csv.write_text(good + "\n" + bad + "\n")
    q = tmp_path / "q"
    res = parse_events(csv, quarantine_dir=q)

    assert res.df.height == 1                                  # poison dropped
    assert res.df.get_column("global_event_id").null_count() == 0
    assert res.quarantine_count == 1
    assert (q / "events.jsonl").read_text().count("null_key") == 1


def test_mentions_null_global_event_id_is_quarantined(tmp_path):
    good = (FIXTURES / "slice_20260425_full.mentions.CSV").read_text().splitlines()[0]
    parts = good.split("\t")
    parts[0] = ""                            # blank global_event_id => null key
    bad = "\t".join(parts)
    csv = tmp_path / "s.mentions.CSV"
    csv.write_text(good + "\n" + bad + "\n")
    q = tmp_path / "q"
    res = parse_mentions(csv, quarantine_dir=q)

    assert res.df.height == 1
    assert res.df.get_column("global_event_id").null_count() == 0
    assert res.quarantine_count == 1
    assert (q / "mentions.jsonl").read_text().count("null_key") == 1
