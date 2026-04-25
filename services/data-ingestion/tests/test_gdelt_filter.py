import polars as pl

from gdelt_raw.filter import apply_filters, FilterResult


def _events_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [1, 2, 3, 4],
        "event_root_code": [19, 3, 18, 1],  # only 19,18 tactical
        "quad_class": [4, 1, 4, 1],
        "goldstein_scale": [-6.5, 1.0, -4.2, 0.5],
        "avg_tone": [-4.0, 2.0, -3.5, 1.0],
        "num_mentions": [10, 5, 3, 2],
        "num_sources": [8, 3, 2, 1],
        "num_articles": [9, 4, 2, 1],
        "date_added": [20260425120000] * 4,
        "fraction_date": [2026.3164] * 4,
        "event_code": ["193", "030", "180", "010"],
        "source_url": [f"https://ex.com/{i}" for i in range(4)],
    })


def _mentions_df() -> pl.DataFrame:
    return pl.DataFrame({
        "global_event_id": [3, 4, 4],
        "mention_identifier": ["https://nuc.com/a", "https://nuc.com/a", "https://other.com"],
        "mention_doc_tone": [-5.0, -3.0, 0.0],
        "confidence": [100, 100, 90],
        "action_char_offset": [10, 20, 30],
    })


def _gkg_df() -> pl.DataFrame:
    return pl.DataFrame({
        "gkg_record_id": ["r1", "r2"],
        "v21_date": [20260425120000, 20260425120000],
        "v2_document_identifier": ["https://nuc.com/a", "https://ex.com/2"],
        "v1_themes": ["NUCLEAR;WMD", "ARMEDCONFLICT;KILL"],
        "v2_source_common_name": ["nuc.com", "ex.com"],
    })


def test_tactical_filter_keeps_roots_18_19():
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    assert set(res.events.get_column("global_event_id").to_list()) >= {1, 3}


def test_nuclear_theme_override_keeps_event_outside_cameo_allowlist():
    """Event 4 has event_root_code=1 (not in allowlist) but is referenced
    by GKG doc r1 which has NUCLEAR theme → must be kept."""
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    kept = set(res.events.get_column("global_event_id").to_list())
    assert 4 in kept, f"nuclear-override failed, kept={kept}"
    # And filter_reason distinguishes
    rows = res.events.filter(pl.col("global_event_id") == 4).to_dicts()
    assert rows[0]["filter_reason"] == "nuclear_override"


def test_gkg_join_does_not_duplicate_docs_with_multiple_events():
    """GKG doc r1 is referenced by multiple events (via mentions fixture).
    After materialized-join we MUST still have doc_id unique."""
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    doc_ids = res.gkg.get_column("gkg_record_id").to_list()
    assert len(doc_ids) == len(set(doc_ids))


def test_gkg_linked_fields_are_lists():
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    # doc r1 links to events 3+4
    row = res.gkg.filter(pl.col("gkg_record_id") == "r1").to_dicts()[0]
    assert isinstance(row["linked_event_ids"], list)
    assert isinstance(row["cameo_roots_linked"], list)
    assert set(row["linked_event_ids"]) == {"gdelt:event:3", "gdelt:event:4"}


def test_gkg_alpha_doc_without_mentions_yields_empty_lists():
    """A gkg_alpha doc whose v2_document_identifier does not appear in any mention
    must still survive the left join, with empty list aggregates (not None)."""
    # gkg doc r2 has v2_document_identifier="https://ex.com/2"; no mention references it.
    res = apply_filters(_events_df(), _mentions_df(), _gkg_df(),
                        cameo_roots=[15, 18, 19, 20],
                        theme_alpha=["ARMEDCONFLICT", "KILL"],
                        theme_nuclear_override=["NUCLEAR", "WMD"])
    rows = res.gkg.filter(pl.col("gkg_record_id") == "r2").to_dicts()
    assert len(rows) == 1
    row = rows[0]
    assert row["linked_event_ids"] == []
    assert row["cameo_roots_linked"] == []
    assert row["codebook_types_linked"] == []
    # goldstein_min / goldstein_avg may legitimately be None
