from pathlib import Path

import polars as pl
import pytest

from gdelt_raw.writers.parquet_writer import write_stream_parquet


def test_atomic_rename_produces_final_file(tmp_path):
    df = pl.DataFrame({"a": [1, 2, 3]})
    final = write_stream_parquet(
        df, base_path=tmp_path, stream="events",
        date="2026-04-25", slice_id="20260425120000",
    )
    assert final.exists()
    assert final.name == "20260425120000.parquet"
    assert not (final.parent / "20260425120000.parquet.tmp").exists()
    loaded = pl.read_parquet(final)
    assert loaded.height == 3


def test_incomplete_tmp_parquet_is_not_marked_done(tmp_path, monkeypatch):
    """If rename fails we must NOT leave a final file behind."""
    df = pl.DataFrame({"a": [1]})

    # Force a rename failure
    original_replace = Path.replace
    def _fail(self, target):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(Path, "replace", _fail)

    with pytest.raises(OSError):
        write_stream_parquet(
            df, base_path=tmp_path, stream="events",
            date="2026-04-25", slice_id="20260425120000",
        )

    monkeypatch.setattr(Path, "replace", original_replace)
    # The final file must NOT exist
    assert not (tmp_path / "events" / "date=2026-04-25" / "20260425120000.parquet").exists()


def test_partitioned_layout(tmp_path):
    df = pl.DataFrame({"a": [1]})
    out = write_stream_parquet(
        df, base_path=tmp_path, stream="gkg",
        date="2026-04-25", slice_id="20260425120000",
    )
    assert out.parent.name == "date=2026-04-25"
    assert out.parent.parent.name == "gkg"
