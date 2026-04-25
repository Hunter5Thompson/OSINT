"""Atomic Parquet writer — .tmp + fsync + rename."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import structlog

log = structlog.get_logger(__name__)


def write_stream_parquet(
    df: pl.DataFrame,
    *,
    base_path: Path,
    stream: str,          # "events" | "mentions" | "gkg"
    date: str,            # "2026-04-25"
    slice_id: str,        # "20260425120000"
) -> Path:
    partition = Path(base_path) / stream / f"date={date}"
    partition.mkdir(parents=True, exist_ok=True)
    final = partition / f"{slice_id}.parquet"
    tmp = partition / f"{slice_id}.parquet.tmp"

    # Write into .tmp first
    df.write_parquet(tmp, compression="snappy")

    # fsync the file and the directory for durability on crash
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    dir_fd = os.open(str(partition), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    # Atomic rename — either fully visible or not at all
    tmp.replace(final)
    log.info("parquet_written",
             stream=stream, slice=slice_id, rows=df.height, path=str(final))
    return final
