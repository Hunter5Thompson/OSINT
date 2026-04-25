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


@dataclass
class ParseResult:
    """Outcome of parsing a single GDELT slice file.

    Fields:
        df: parsed DataFrame (empty if no valid rows).
        total_lines: count of non-empty source lines (denominator for error pct).
        quarantine_count: number of malformed lines diverted to quarantine.
    """

    df: pl.DataFrame
    total_lines: int
    quarantine_count: int

    @property
    def parse_error_pct(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return 100.0 * self.quarantine_count / self.total_lines


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
        return ParseResult(
            df=df, total_lines=non_empty_count, quarantine_count=0
        )
    except (
        pl.exceptions.ComputeError,
        pl.exceptions.SchemaFieldNotFoundError,
        pl.exceptions.NoDataError,
    ) as e:
        log.warning("gdelt_parser_fallback", stream=stream_name, error=str(e))
        return _parse_with_fallback(path, cols, schema, stream_name, quarantine_dir)


def parse_events(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    """Parse a GDELT events.CSV slice (tab-separated, no header).

    Args:
        quarantine_dir: optional directory; malformed lines written as JSONL.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    return _parse_stream(
        path, EVENT_COLUMNS, EVENT_POLARS_SCHEMA, "events", quarantine_dir
    )


def parse_mentions(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    """Parse a GDELT mentions.CSV slice (tab-separated, no header).

    Args:
        quarantine_dir: optional directory; malformed lines written as JSONL.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    return _parse_stream(
        path, MENTION_COLUMNS, MENTION_POLARS_SCHEMA, "mentions", quarantine_dir
    )


def parse_gkg(path: Path, quarantine_dir: Path | None = None) -> ParseResult:
    """Parse a GDELT gkg.csv slice (tab-separated, no header).

    Args:
        quarantine_dir: optional directory; malformed lines written as JSONL.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    return _parse_stream(
        path, GKG_COLUMNS, GKG_POLARS_SCHEMA, "gkg", quarantine_dir
    )
