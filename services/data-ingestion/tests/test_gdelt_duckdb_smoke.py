from pathlib import Path

import duckdb
import polars as pl
import pytest


def test_duckdb_can_read_partitioned_parquet(tmp_path):
    """Guards Parquet schema drift: DuckDB must be able to SELECT from our
    date-partitioned parquet layout."""
    # Write two partitions
    for date in ("2026-04-25", "2026-04-26"):
        part = tmp_path / "events" / f"date={date}"
        part.mkdir(parents=True)
        pl.DataFrame({
            "event_id": ["gdelt:event:1", "gdelt:event:2"],
            "codebook_type": ["conflict.armed", "conflict.assault"],
            "goldstein": [-6.5, -4.2],
        }).write_parquet(part / "slice_a.parquet")

    con = duckdb.connect()
    # Hive-partitioned scan
    result = con.sql(
        f"SELECT codebook_type, count(*) AS n, avg(goldstein) AS avg_g "
        f"FROM read_parquet('{tmp_path}/events/date=*/*.parquet', "
        f"                  hive_partitioning=1) "
        f"GROUP BY codebook_type ORDER BY codebook_type"
    ).fetchall()
    assert len(result) == 2
    assert result[0][1] == 2  # 2 rows per codebook_type across 2 partitions
    assert result[1][1] == 2
