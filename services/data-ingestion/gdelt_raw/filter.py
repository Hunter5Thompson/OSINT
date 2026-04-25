"""Multi-stage filter with Nuclear-Override UNION semantics.

1. tactical_event_ids  := events where event_root_code ∈ allowlist
2. gkg_alpha           := gkg where themes match alpha-set
3. gkg_nuclear         := gkg where themes match nuclear-override set
4. nuclear_event_ids   := mentions where url ∈ gkg_nuclear.urls
5. final_event_ids     := tactical ∪ nuclear
6. events_filtered     := events ∩ final, with filter_reason column
7. gkg_filtered        := alpha ∪ nuclear (deduped on gkg_record_id)
                          with materialized linked-event aggregates
8. mentions_filtered   := mentions where event_id ∈ final
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from gdelt_raw.cameo_mapping import map_cameo_root
from gdelt_raw.ids import build_event_id, build_doc_id
from gdelt_raw.theme_matching import any_match_in_themes, compile_patterns


@dataclass
class FilterResult:
    events: pl.DataFrame
    mentions: pl.DataFrame
    gkg: pl.DataFrame


def _themes_list(col: pl.Expr) -> pl.Expr:
    return col.fill_null("").str.split(";")


def _gkg_theme_match(df: pl.DataFrame, matcher) -> pl.Series:
    themes = df.get_column("v1_themes").fill_null("").str.split(";").to_list()
    return pl.Series([any_match_in_themes(t, matcher) for t in themes])


def apply_filters(
    events_df: pl.DataFrame,
    mentions_df: pl.DataFrame,
    gkg_df: pl.DataFrame,
    *,
    cameo_roots: list[int],
    theme_alpha: list[str],
    theme_nuclear_override: list[str],
) -> FilterResult:
    # 1. tactical events
    tactical_ids = set(
        events_df.filter(pl.col("event_root_code").is_in(cameo_roots))
        .get_column("global_event_id").to_list()
    )

    # 2. gkg alpha
    alpha_matcher = compile_patterns(theme_alpha)
    gkg_alpha_mask = _gkg_theme_match(gkg_df, alpha_matcher)
    gkg_alpha = gkg_df.filter(gkg_alpha_mask)

    # 3. gkg nuclear
    nuclear_matcher = compile_patterns(theme_nuclear_override)
    gkg_nuclear_mask = _gkg_theme_match(gkg_df, nuclear_matcher)
    gkg_nuclear = gkg_df.filter(gkg_nuclear_mask)

    # 4. nuclear event ids via mentions → gkg_nuclear.urls
    nuclear_urls = set(gkg_nuclear.get_column("v2_document_identifier").to_list())
    nuclear_ids = set(
        mentions_df.filter(pl.col("mention_identifier").is_in(nuclear_urls))
        .get_column("global_event_id").to_list()
    )

    # 5. union
    final_ids = tactical_ids | nuclear_ids

    # 6. filter events and annotate
    events_filtered = (
        events_df.filter(pl.col("global_event_id").is_in(final_ids))
        .with_columns([
            pl.when(pl.col("global_event_id").is_in(tactical_ids))
              .then(pl.lit("tactical"))
              .otherwise(pl.lit("nuclear_override"))
              .alias("filter_reason"),
            pl.col("event_root_code")
              .map_elements(lambda r: map_cameo_root(int(r)) or "", return_dtype=pl.Utf8)
              .alias("codebook_type"),
            pl.col("global_event_id")
              .map_elements(lambda i: build_event_id(int(i)), return_dtype=pl.Utf8)
              .alias("event_id"),
        ])
    )

    # 7. gkg union and materialized join
    gkg_union = pl.concat([gkg_alpha, gkg_nuclear]).unique(subset=["gkg_record_id"])

    # Aggregate mentions+events per mention_url to avoid N:N duplicate explosion
    events_for_join = events_filtered.select([
        "global_event_id", "event_id", "event_root_code",
        "goldstein_scale", "codebook_type",
    ])
    mentions_scoped = mentions_df.filter(pl.col("global_event_id").is_in(final_ids))
    linked_agg = (
        mentions_scoped.join(events_for_join, on="global_event_id")
        .group_by("mention_identifier")
        .agg([
            pl.col("event_id").unique().alias("linked_event_ids"),
            pl.col("goldstein_scale").min().alias("goldstein_min"),
            pl.col("goldstein_scale").mean().alias("goldstein_avg"),
            pl.col("event_root_code").unique().alias("cameo_roots_linked"),
            pl.col("codebook_type").unique().alias("codebook_types_linked"),
        ])
    )

    gkg_with_join = gkg_union.join(
        linked_agg,
        left_on="v2_document_identifier", right_on="mention_identifier",
        how="left",
    ).with_columns([
        pl.col("gkg_record_id")
          .map_elements(build_doc_id, return_dtype=pl.Utf8)
          .alias("doc_id"),
    ])

    # Invariant: doc_id unique
    assert gkg_with_join.n_unique("gkg_record_id") == gkg_with_join.height

    # 8. mentions
    mentions_filtered = mentions_scoped

    return FilterResult(
        events=events_filtered,
        mentions=mentions_filtered,
        gkg=gkg_with_join,
    )
