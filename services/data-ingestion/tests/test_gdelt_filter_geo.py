"""Test that action_geo_* columns survive the apply_filters pipeline.

Task 6: geo columns must pass through filter.py unchanged so a later task
can write Location nodes from them.
"""

from __future__ import annotations

import polars as pl
import pytest

from gdelt_raw.filter import apply_filters

# ── minimal fixtures ────────────────────────────────────────────────────────

def _events_df_with_geo() -> pl.DataFrame:
    """Minimal events DataFrame that includes all five action_geo_* columns.

    event_root_code=19 is in the tactical allowlist used below, so this event
    will survive the tactical filter and appear in out.events.
    """
    return pl.DataFrame({
        "global_event_id":            [1],
        "event_root_code":            [19],
        "quad_class":                 [4],
        "goldstein_scale":            [-6.5],
        "avg_tone":                   [-4.0],
        "num_mentions":               [10],
        "num_sources":                [8],
        "num_articles":               [9],
        "date_added":                 [20260425120000],
        "fraction_date":              [2026.3164],
        "event_code":                 ["193"],
        "source_url":                 ["https://ex.com/1"],
        # ── the five geo columns this task guards ──
        "action_geo_lat":             [48.8566],
        "action_geo_long":            [2.3522],
        "action_geo_fullname":        ["Paris, France"],
        "action_geo_country_code":    ["FR"],
        "action_geo_feature_id":      ["-2427361"],
    }, schema_overrides={
        "action_geo_lat":  pl.Float64,
        "action_geo_long": pl.Float64,
    })


def _mentions_df() -> pl.DataFrame:
    """Minimal mentions frame — no rows needed because event 1 is tactical."""
    return pl.DataFrame(schema={
        "global_event_id":    pl.Int64,
        "mention_identifier": pl.Utf8,
        "mention_doc_tone":   pl.Float64,
        "confidence":         pl.Int32,
        "action_char_offset": pl.Int32,
    })


def _gkg_df() -> pl.DataFrame:
    """Minimal GKG frame — one doc for alpha theme completeness."""
    return pl.DataFrame({
        "gkg_record_id":            ["r1"],
        "v21_date":                 [20260425120000],
        "v2_document_identifier":   ["https://ex.com/1"],
        "v1_themes":                ["ARMEDCONFLICT"],
        "v2_source_common_name":    ["ex.com"],
    })


# ── the test ────────────────────────────────────────────────────────────────

def test_filtered_events_retain_action_geo_columns():
    """action_geo_* columns must survive apply_filters unchanged."""
    out = apply_filters(
        _events_df_with_geo(),
        _mentions_df(),
        _gkg_df(),
        cameo_roots=[15, 18, 19, 20],
        theme_alpha=["ARMEDCONFLICT"],
        theme_nuclear_override=["NUCLEAR"],
    )

    assert out.events.height >= 1, "fixture event did not pass tactical filter"

    cols = out.events.columns
    for c in (
        "action_geo_lat",
        "action_geo_long",
        "action_geo_fullname",
        "action_geo_country_code",
        "action_geo_feature_id",
    ):
        assert c in cols, f"{c} dropped by filter"

    # Also verify the values round-trip correctly
    row = out.events.filter(pl.col("global_event_id") == 1).to_dicts()[0]
    assert row["action_geo_lat"] == pytest.approx(48.8566)
    assert row["action_geo_long"] == pytest.approx(2.3522)
    assert row["action_geo_fullname"] == "Paris, France"
    assert row["action_geo_country_code"] == "FR"
    assert row["action_geo_feature_id"] == "-2427361"
