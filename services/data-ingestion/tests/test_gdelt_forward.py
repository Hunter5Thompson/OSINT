from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from gdelt_raw.run import run_forward_slice
from gdelt_raw.state import GDELTState
from gdelt_raw.downloader import LastUpdateEntry


@pytest.mark.asyncio
async def test_parquet_written_before_external_stores(tmp_path, monkeypatch):
    """Order invariant: parquet-state done before neo4j/qdrant are even called."""
    call_log: list[str] = []

    # Mocks
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)

    async def fake_download(entry, out_dir):
        f = out_dir / entry.url.rsplit("/", 1)[-1]
        f.write_bytes(b"x")
        return f

    # Stub the pipeline pieces
    neo4j = MagicMock(); neo4j.write_from_parquet = AsyncMock(
        side_effect=lambda *a, **k: call_log.append("neo4j"))
    qdrant = MagicMock(); qdrant.upsert_from_parquet = AsyncMock(
        side_effect=lambda *a, **k: call_log.append("qdrant") or 0)

    with patch("gdelt_raw.run.download_slice", side_effect=fake_download), \
         patch("gdelt_raw.run._extract_and_parse", new=AsyncMock(return_value=MagicMock(
            events_df=MagicMock(), mentions_df=MagicMock(), gkg_df=MagicMock(),
            stream_states={"events":"done","mentions":"done","gkg":"done"},
         ))), \
         patch("gdelt_raw.run._filter_and_write_parquet", new=AsyncMock(
            side_effect=lambda *a, **k: call_log.append("parquet"))):

        entries = [
            LastUpdateEntry(0, "m", "http://x/y.export.CSV.zip", "events", "20260425120000"),
            LastUpdateEntry(0, "m", "http://x/y.mentions.CSV.zip", "mentions", "20260425120000"),
            LastUpdateEntry(0, "m", "http://x/y.gkg.csv.zip", "gkg", "20260425120000"),
        ]
        await run_forward_slice(
            entries, state=state, parquet_base=tmp_path,
            neo4j_writer=neo4j, qdrant_writer=qdrant, tmp_dir=tmp_path / "work",
        )

    assert call_log.index("parquet") < call_log.index("neo4j")
    assert call_log.index("parquet") < call_log.index("qdrant")


@pytest.mark.asyncio
async def test_store_state_not_advanced_on_failure(tmp_path, monkeypatch):
    """If Neo4j raises, neo4j state must stay 'failed:*' and NOT advance
    last_slice:neo4j. Parquet last_slice must still advance (truth-layer)."""
    import fakeredis.aioredis
    from gdelt_raw.run import run_forward_slice
    from gdelt_raw.state import GDELTState
    from gdelt_raw.downloader import LastUpdateEntry

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    state = GDELTState(r)

    # Stub download + parse + filter — mark parquet streams as done
    async def fake_download(entry, out_dir, **kwargs):
        f = out_dir / entry.url.rsplit("/", 1)[-1]
        f.write_bytes(b"z")
        return f

    async def fake_extract(entries, work, *, verify_md5=True):
        from gdelt_raw.run import ParsedSlice
        import polars as pl
        return ParsedSlice(
            events_df=pl.DataFrame({"global_event_id": []}),
            mentions_df=pl.DataFrame({"global_event_id": []}),
            gkg_df=pl.DataFrame({"gkg_record_id": []}),
            stream_states={"events": "done", "mentions": "done", "gkg": "done"},
        )

    async def fake_filter_write(parsed, slice_id, *, state, parquet_base):
        for st in ("events", "mentions", "gkg"):
            await state.set_stream_parquet(slice_id, st, "done")
        return None

    monkeypatch.setattr("gdelt_raw.run.download_slice", fake_download)
    monkeypatch.setattr("gdelt_raw.run._extract_and_parse", fake_extract)
    monkeypatch.setattr("gdelt_raw.run._filter_and_write_parquet", fake_filter_write)

    # Neo4j writer that raises, Qdrant writer that succeeds
    from unittest.mock import MagicMock, AsyncMock
    neo4j = MagicMock()
    neo4j.write_from_parquet = AsyncMock(side_effect=RuntimeError("boom"))
    qdrant = MagicMock()
    qdrant.upsert_from_parquet = AsyncMock(return_value=0)

    entries = [
        LastUpdateEntry(0, "m", "http://x/y.export.CSV.zip", "events", "20260425120000"),
        LastUpdateEntry(0, "m", "http://x/y.mentions.CSV.zip", "mentions", "20260425120000"),
        LastUpdateEntry(0, "m", "http://x/y.gkg.csv.zip", "gkg", "20260425120000"),
    ]
    await run_forward_slice(
        entries, state=state, parquet_base=tmp_path,
        neo4j_writer=neo4j, qdrant_writer=qdrant, tmp_dir=tmp_path / "work",
    )

    # Neo4j failed — state reflects it, last_slice:neo4j NOT advanced
    n_state = await state.get_store_state("20260425120000", "neo4j")
    assert n_state and n_state.startswith("failed")
    assert "20260425120000" in await state.list_pending("neo4j")
    assert await state.get_last_slice("neo4j") is None

    # Qdrant succeeded — independent of Neo4j
    assert await state.get_store_state("20260425120000", "qdrant") == "done"
    assert await state.get_last_slice("qdrant") == "20260425120000"

    # Parquet last_slice DID advance — truth layer moves forward
    assert await state.get_last_slice("parquet") == "20260425120000"
