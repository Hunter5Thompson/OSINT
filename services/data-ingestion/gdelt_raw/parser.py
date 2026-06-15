"""Two-stage CSV parser for GDELT streams.

Stage 1: Strict Polars parse (fast path, ~95%).
Stage 2: Fallback — line-level pre-validation, bad rows → quarantine,
         then re-parse only valid lines.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import structlog

from gdelt_raw.polars_schemas import (
    EVENT_COLUMNS,
    EVENT_POLARS_SCHEMA,
    GKG_COLUMNS,
    GKG_POLARS_SCHEMA,
    MENTION_COLUMNS,
    MENTION_POLARS_SCHEMA,
)

log = structlog.get_logger(__name__)


def _quarantine_null_keys(
    df: pl.DataFrame,
    id_column: str,
    stream_name: str,
    quarantine_dir: Path | None,
) -> tuple[pl.DataFrame, int]:
    """Divert rows whose primary-key column is null to the quarantine JSONL and
    drop them from the frame. Runs on BOTH the strict and fallback paths — an
    empty leading key is silently null-coerced by ``null_values=[""]`` on the
    strict path (no error), so this gate, not the tab-count check, is what
    catches it. Returns (clean_df, dropped_count)."""
    if df.height == 0 or id_column not in df.columns:
        return df, 0
    bad = df.filter(pl.col(id_column).is_null())
    if bad.height == 0:
        return df, 0
    if quarantine_dir is not None:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        qfile = quarantine_dir / f"{stream_name}.jsonl"
        with qfile.open("a", encoding="utf-8") as fh:  # append: tab-count path may have written
            for row in bad.to_dicts():
                fh.write(json.dumps(
                    {"reason": "null_key", "id_column": id_column, "row": row},
                    default=str,
                ) + "\n")
    log.warning(
        "gdelt_null_key_quarantined",
        stream=stream_name, id_column=id_column, count=bad.height,
    )
    return df.filter(pl.col(id_column).is_not_null()), bad.height


# Non-id typed columns whose null on the fallback path means a silently coerced
# cell (WP-12). The id columns are handled by the null-key gate, not here.
_TYPE_COERCE_WATCH: dict[str, list[str]] = {"events": ["event_root_code"]}


def _count_type_coerced(df: pl.DataFrame, stream_name: str) -> int:
    """Count rows where any watched non-id typed column is null after a
    fallback re-parse. Only called when the fallback path ran — on the strict
    path an empty cell is genuinely-missing data parsed cleanly as null, not a
    coercion. Run AFTER the null-key gate so dropped null-id rows aren't
    double-counted."""
    cols = [c for c in _TYPE_COERCE_WATCH.get(stream_name, []) if c in df.columns]
    if not cols or df.height == 0:
        return 0
    mask = pl.any_horizontal([pl.col(c).is_null() for c in cols])
    return df.filter(mask).height


@dataclass
class ParseResult:
    """Outcome of parsing a single GDELT slice file.

    Fields:
        df: parsed DataFrame (empty if no valid rows).
        total_lines: count of non-empty source lines (denominator for error pct).
        quarantine_count: rows diverted to quarantine — wrong-tab-count lines
            (fallback path) plus null/empty primary-key rows (null-key gate, WP-02).
        type_coerced_count: number of rows with a null-coerced non-id typed cell
            (counted, not dropped) — WP-12.
    """

    df: pl.DataFrame
    total_lines: int
    quarantine_count: int
    type_coerced_count: int = 0

    @property
    def parse_error_pct(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return 100.0 * (self.quarantine_count + self.type_coerced_count) / self.total_lines


def _parse_strict(path: Path, cols: list[str], schema: dict) -> pl.DataFrame:
    return pl.read_csv(
        str(path),
        separator="\t",
        has_header=False,
        new_columns=cols,
        schema_overrides=schema,
        ignore_errors=False,
        null_values=[""],
    )


def _parse_with_fallback(
    path: Path,
    cols: list[str],
    schema: dict,
    stream_name: str,
    quarantine_dir: Path | None,
) -> ParseResult:
    raw_lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    # Drop trailing blank lines but keep them counted as "total" only if non-empty.
    non_empty = [ln for ln in raw_lines if ln.strip()]
    total = len(non_empty)
    expected_cols = len(cols)

    valid: list[str] = []
    bad: list[tuple[int, str]] = []
    for idx, ln in enumerate(non_empty, start=1):
        if ln.count("\t") + 1 == expected_cols:
            valid.append(ln)
        else:
            bad.append((idx, ln))

    if bad and quarantine_dir is not None:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        qfile = quarantine_dir / f"{stream_name}.jsonl"
        with qfile.open("w", encoding="utf-8") as fh:
            for line_no, content in bad:
                fh.write(json.dumps({"line": line_no, "content": content}) + "\n")

    if not valid:
        empty = pl.DataFrame(schema={c: pl.Utf8 for c in cols})
        return ParseResult(
            df=empty,
            total_lines=total,
            quarantine_count=len(bad),
        )

    df = pl.read_csv(
        io.StringIO("\n".join(valid)),
        separator="\t",
        has_header=False,
        new_columns=cols,
        schema_overrides=schema,
        ignore_errors=True,  # we already filtered — be forgiving now
        null_values=[""],
    )
    return ParseResult(df=df, total_lines=total, quarantine_count=len(bad))


def _parse_stream(
    path: Path,
    cols: list[str],
    schema: dict,
    stream_name: str,
    id_column: str,
    quarantine_dir: Path | None,
) -> ParseResult:
    if not path.is_file():
        raise FileNotFoundError(f"GDELT slice not found: {path}")
    # Count non-empty source lines once; both strict and fallback paths use this
    # denominator so parse_error_pct is meaningful and comparable across paths.
    # Re-reading on the strict-path success is intentional: ~80 MB / 100K lines
    # is a fraction of a second on local disk and ops visibility is worth it.
    non_empty_count = sum(
        1
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.strip()
    )
    try:
        df = _parse_strict(path, cols, schema)
        tab_quarantine = 0
        took_fallback = False
    except (
        pl.exceptions.ComputeError,
        pl.exceptions.SchemaFieldNotFoundError,
        pl.exceptions.NoDataError,
    ) as e:
        log.warning("gdelt_parser_fallback", stream=stream_name, error=str(e))
        fb = _parse_with_fallback(path, cols, schema, stream_name, quarantine_dir)
        df = fb.df
        tab_quarantine = fb.quarantine_count
        took_fallback = True

    # WP-02: divert null/empty primary-key rows on both paths.
    df, null_quarantine = _quarantine_null_keys(df, id_column, stream_name, quarantine_dir)

    # WP-12: only the fallback path silently null-coerces type-corrupt cells
    # (ignore_errors=True). An empty cell on the strict path is genuinely-missing
    # data parsed cleanly as null, not a coercion — so we don't count it here.
    type_coerced = _count_type_coerced(df, stream_name) if took_fallback else 0

    return ParseResult(
        df=df,
        total_lines=non_empty_count,
        quarantine_count=tab_quarantine + null_quarantine,
        type_coerced_count=type_coerced,
    )


def parse_events(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    """Parse a GDELT events.CSV slice (tab-separated, no header).

    Args:
        quarantine_dir: optional directory; malformed lines written as JSONL.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    return _parse_stream(
        path, EVENT_COLUMNS, EVENT_POLARS_SCHEMA, "events",
        "global_event_id", quarantine_dir,
    )


def parse_mentions(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    """Parse a GDELT mentions.CSV slice (tab-separated, no header).

    Args:
        quarantine_dir: optional directory; malformed lines written as JSONL.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    return _parse_stream(
        path, MENTION_COLUMNS, MENTION_POLARS_SCHEMA, "mentions",
        "global_event_id", quarantine_dir,
    )


def parse_gkg(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    """Parse a GDELT gkg.csv slice (tab-separated, no header).

    Args:
        quarantine_dir: optional directory; malformed lines written as JSONL.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    return _parse_stream(
        path, GKG_COLUMNS, GKG_POLARS_SCHEMA, "gkg",
        "gkg_record_id", quarantine_dir,
    )
