"""Canonical transform: raw-filtered GDELT DataFrames → Pydantic-writer schema.

Without this layer, Parquet would hold raw GDELT column names while
Neo4j/Qdrant writers expect canonical field names. This is the single place
where that translation happens. Everything downstream speaks canonical.
"""

from __future__ import annotations

import polars as pl

from gdelt_raw.ids import build_event_id


def _parse_gdelt_datetime(col: str) -> pl.Expr:
    """GDELT date_added / v21_date is int YYYYMMDDHHMMSS → parse to datetime."""
    return (
        pl.col(col).cast(pl.Utf8)
        .str.strptime(pl.Datetime, format="%Y%m%d%H%M%S", strict=False)
    )


def _split_semicolon_list(col: str) -> pl.Expr:
    """GDELT semicolon-delimited strings (e.g. V1Themes) → list[str], empties dropped."""
    return (
        pl.col(col).fill_null("")
        .str.split(";")
        .list.eval(pl.element().filter(pl.element().str.len_chars() > 0))
    )


def canonicalize_events(df: pl.DataFrame) -> pl.DataFrame:
    """Raw-filtered events DataFrame → canonical events DataFrame.

    Input columns (from filter.apply_filters): global_event_id, event_id,
    event_code, event_root_code, quad_class, goldstein_scale, avg_tone,
    num_mentions, num_sources, num_articles, date_added (int), fraction_date,
    actor1_*, actor2_*, source_url, codebook_type, filter_reason.

    Output schema matches GDELTEventWrite exactly.
    """
    return df.select([
        pl.col("event_id"),
        pl.lit("gdelt").alias("source"),
        pl.col("event_code").alias("cameo_code"),
        pl.col("event_root_code").alias("cameo_root"),
        pl.col("quad_class"),
        pl.col("goldstein_scale").alias("goldstein"),
        pl.col("avg_tone"),
        pl.col("num_mentions"),
        pl.col("num_sources"),
        pl.col("num_articles"),
        _parse_gdelt_datetime("date_added").alias("date_added"),
        pl.col("fraction_date"),
        pl.col("actor1_code"),
        pl.col("actor1_name"),
        pl.col("actor2_code"),
        pl.col("actor2_name"),
        pl.col("source_url"),
        pl.col("codebook_type"),
        pl.col("filter_reason"),
    ])


def canonicalize_gkg(df: pl.DataFrame) -> pl.DataFrame:
    """Raw-filtered GKG → canonical GKG. Output matches GDELTDocumentWrite.

    v15_tone is 7-field comma-separated: avgTone, posTone, negTone, polarity,
    activityRef, selfGroupRef, wordCount.
    """
    # Split v15_tone once, then extract by position
    tone_parts = pl.col("v15_tone").fill_null("0,0,0,0,0,0,0").str.split(",")

    return df.select([
        pl.col("doc_id"),
        pl.lit("gdelt_gkg").alias("source"),
        pl.col("v2_document_identifier").alias("url"),
        pl.col("v2_source_common_name").alias("source_name"),
        _parse_gdelt_datetime("v21_date").alias("gdelt_date"),
        pl.lit(None, dtype=pl.Datetime).alias("published_at"),
        _split_semicolon_list("v1_themes").alias("themes"),
        _split_semicolon_list("v1_persons").alias("persons"),
        _split_semicolon_list("v1_organizations").alias("organizations"),
        tone_parts.list.get(1).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_positive"),
        tone_parts.list.get(2).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_negative"),
        tone_parts.list.get(3).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_polarity"),
        tone_parts.list.get(4).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_activity"),
        tone_parts.list.get(5).cast(pl.Float64, strict=False).fill_null(0.0)
            .alias("tone_self_group"),
        tone_parts.list.get(6).cast(pl.Int64, strict=False).fill_null(0)
            .alias("word_count"),
        pl.col("v21_sharp_image").alias("sharp_image_url"),
        _split_semicolon_list("v21_quotations").alias("quotations"),
        pl.col("linked_event_ids").fill_null([]),
        pl.col("goldstein_min"),
        pl.col("goldstein_avg"),
        pl.col("cameo_roots_linked").fill_null([]),
        pl.col("codebook_types_linked").fill_null([]),
    ])


def canonicalize_mentions(df: pl.DataFrame) -> pl.DataFrame:
    """Raw mentions → canonical (event_id, mention_url, tone, confidence, char_offset)."""
    return df.select([
        pl.col("global_event_id")
          .map_elements(lambda i: build_event_id(int(i)), return_dtype=pl.Utf8)
          .alias("event_id"),
        pl.col("mention_identifier").alias("mention_url"),
        pl.col("mention_doc_tone").alias("tone"),
        pl.col("confidence"),
        pl.col("action_char_offset").alias("char_offset"),
    ])
