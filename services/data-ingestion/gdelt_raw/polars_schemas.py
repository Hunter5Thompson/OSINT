"""Polars column definitions for GDELT 2.0 CSVs.

Columns are tab-separated, no header. Order matches GDELT codebook.
"""

from __future__ import annotations

import polars as pl

# ── Events (export.CSV) — 61 columns ────────────────────────────────────────
EVENT_COLUMNS: list[str] = [
    "global_event_id", "day", "month_year", "year", "fraction_date",
    "actor1_code", "actor1_name", "actor1_country_code",
    "actor1_known_group_code", "actor1_ethnic_code",
    "actor1_religion1_code", "actor1_religion2_code",
    "actor1_type1_code", "actor1_type2_code", "actor1_type3_code",
    "actor2_code", "actor2_name", "actor2_country_code",
    "actor2_known_group_code", "actor2_ethnic_code",
    "actor2_religion1_code", "actor2_religion2_code",
    "actor2_type1_code", "actor2_type2_code", "actor2_type3_code",
    "is_root_event", "event_code", "event_base_code", "event_root_code",
    "quad_class", "goldstein_scale",
    "num_mentions", "num_sources", "num_articles", "avg_tone",
    "actor1_geo_type", "actor1_geo_fullname", "actor1_geo_country_code",
    "actor1_geo_adm1_code", "actor1_geo_adm2_code",
    "actor1_geo_lat", "actor1_geo_long", "actor1_geo_feature_id",
    "actor2_geo_type", "actor2_geo_fullname", "actor2_geo_country_code",
    "actor2_geo_adm1_code", "actor2_geo_adm2_code",
    "actor2_geo_lat", "actor2_geo_long", "actor2_geo_feature_id",
    "action_geo_type", "action_geo_fullname", "action_geo_country_code",
    "action_geo_adm1_code", "action_geo_adm2_code",
    "action_geo_lat", "action_geo_long", "action_geo_feature_id",
    "date_added", "source_url",
]

EVENT_POLARS_SCHEMA: dict[str, pl.DataType] = {
    "global_event_id": pl.Int64,
    "day": pl.Int32, "month_year": pl.Int32, "year": pl.Int32,
    "fraction_date": pl.Float64,
    "is_root_event": pl.Int8,
    "event_code": pl.Utf8, "event_base_code": pl.Utf8, "event_root_code": pl.Int32,
    "quad_class": pl.Int8, "goldstein_scale": pl.Float64,
    "num_mentions": pl.Int32, "num_sources": pl.Int32,
    "num_articles": pl.Int32, "avg_tone": pl.Float64,
    "actor1_geo_lat": pl.Float64, "actor1_geo_long": pl.Float64,
    "actor2_geo_lat": pl.Float64, "actor2_geo_long": pl.Float64,
    "action_geo_lat": pl.Float64, "action_geo_long": pl.Float64,
    "date_added": pl.Int64,  # YYYYMMDDHHMMSS
}


# ── Mentions (mentions.CSV) — 16 columns ────────────────────────────────────
MENTION_COLUMNS: list[str] = [
    "global_event_id", "event_time_date", "mention_time_date",
    "mention_type", "mention_source_name", "mention_identifier",
    "sentence_id", "actor1_char_offset", "actor2_char_offset",
    "action_char_offset", "in_raw_text", "confidence",
    "mention_doc_len", "mention_doc_tone",
    "mention_doc_translation_info", "extras",
]

MENTION_POLARS_SCHEMA: dict[str, pl.DataType] = {
    "global_event_id": pl.Int64,
    "event_time_date": pl.Int64,
    "mention_time_date": pl.Int64,
    "mention_type": pl.Int8,
    "sentence_id": pl.Int32,
    "actor1_char_offset": pl.Int32,
    "actor2_char_offset": pl.Int32,
    "action_char_offset": pl.Int32,
    "in_raw_text": pl.Int8,
    "confidence": pl.Int32,
    "mention_doc_len": pl.Int32,
    "mention_doc_tone": pl.Float64,
}


# ── GKG (gkg.csv) — 27 columns ──────────────────────────────────────────────
GKG_COLUMNS: list[str] = [
    "gkg_record_id", "v21_date", "v2_source_collection_identifier",
    "v2_source_common_name", "v2_document_identifier",
    "v1_counts", "v21_counts",
    "v1_themes", "v2_enhanced_themes",
    "v1_locations", "v2_enhanced_locations",
    "v1_persons", "v2_enhanced_persons",
    "v1_organizations", "v2_enhanced_organizations",
    "v15_tone", "v21_enhanced_dates",
    "v2_gcam",
    "v21_sharp_image", "v21_related_images",
    "v21_social_image_embeds", "v21_social_video_embeds",
    "v21_quotations", "v21_all_names", "v21_amounts",
    "v21_translation_info", "v2_extras_xml",
]

GKG_POLARS_SCHEMA: dict[str, pl.DataType] = {
    "gkg_record_id": pl.Utf8,
    "v21_date": pl.Int64,
    "v2_document_identifier": pl.Utf8,
}
