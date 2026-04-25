"""Forward and backfill orchestration for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import structlog

from gdelt_raw.config import get_settings
from gdelt_raw.downloader import (
    LastUpdateEntry, download_slice, fetch_lastupdate,
)
from gdelt_raw.filter import apply_filters, FilterResult
from gdelt_raw.parser import parse_events, parse_mentions, parse_gkg
from gdelt_raw.recovery import replay_pending
from gdelt_raw.state import GDELTState
from gdelt_raw.writers.parquet_writer import write_stream_parquet

log = structlog.get_logger(__name__)


@dataclass
class ParsedSlice:
    events_df: pl.DataFrame
    mentions_df: pl.DataFrame
    gkg_df: pl.DataFrame
    stream_states: dict[str, str]   # "done" | "failed"


def _slice_date(slice_id: str) -> str:
    return f"{slice_id[0:4]}-{slice_id[4:6]}-{slice_id[6:8]}"


async def _extract_and_parse(
    entries: list[LastUpdateEntry], tmp_dir: Path,
    *, verify_md5: bool = True,
) -> ParsedSlice:
    settings = get_settings()
    downloads = await asyncio.gather(*[
        download_slice(e, tmp_dir, verify_md5=verify_md5) for e in entries
    ])
    extracted: dict[str, Path] = {}
    for entry, zpath in zip(entries, downloads):
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp_dir)
            names = z.namelist()
            extracted[entry.stream] = tmp_dir / names[0]

    stream_states = {}
    quarantine = tmp_dir / "quarantine"
    ev_res = parse_events(extracted["events"], quarantine_dir=quarantine)
    me_res = parse_mentions(extracted["mentions"], quarantine_dir=quarantine)
    gk_res = parse_gkg(extracted["gkg"], quarantine_dir=quarantine)
    for name, res in [("events", ev_res), ("mentions", me_res), ("gkg", gk_res)]:
        stream_states[name] = (
            "failed" if res.parse_error_pct > settings.max_parse_error_pct else "done"
        )

    return ParsedSlice(
        events_df=ev_res.df, mentions_df=me_res.df, gkg_df=gk_res.df,
        stream_states=stream_states,
    )


async def _filter_and_write_parquet(
    parsed: ParsedSlice, slice_id: str, *,
    state: GDELTState, parquet_base: Path,
) -> FilterResult | None:
    from gdelt_raw.transform import (
        canonicalize_events, canonicalize_gkg, canonicalize_mentions,
    )
    settings = get_settings()
    fr = apply_filters(
        parsed.events_df, parsed.mentions_df, parsed.gkg_df,
        cameo_roots=settings.cameo_root_allowlist,
        theme_alpha=settings.theme_allowlist,
        theme_nuclear_override=settings.nuclear_override_themes,
    )
    # Canonicalize BEFORE persisting — parquet holds writer-schema directly.
    canonical = {
        "events": canonicalize_events(fr.events) if parsed.stream_states["events"] == "done"
                  else None,
        "gkg": canonicalize_gkg(fr.gkg) if parsed.stream_states["gkg"] == "done"
               else None,
        "mentions": canonicalize_mentions(fr.mentions) if parsed.stream_states["mentions"] == "done"
                    else None,
    }
    date = _slice_date(slice_id)
    for stream, df in canonical.items():
        if df is None:
            await state.set_stream_parquet(slice_id, stream, "failed")
            continue
        write_stream_parquet(df, base_path=parquet_base, stream=stream,
                             date=date, slice_id=slice_id)
        await state.set_stream_parquet(slice_id, stream, "done")
    return fr


async def run_forward_slice(
    entries: list[LastUpdateEntry],
    *,
    state: GDELTState,
    parquet_base: Path,
    neo4j_writer,
    qdrant_writer,
    tmp_dir: Path,
    verify_md5: bool = True,
) -> None:
    slice_id = entries[0].slice_id
    date = _slice_date(slice_id)
    log.info("gdelt_forward_start", slice=slice_id, verify_md5=verify_md5)

    work = tmp_dir / slice_id
    work.mkdir(parents=True, exist_ok=True)

    # Default forward path uses MD5 verify (default of _extract_and_parse);
    # backfill callers explicitly opt out via verify_md5=False.
    if verify_md5:
        parsed = await _extract_and_parse(entries, work)
    else:
        parsed = await _extract_and_parse(entries, work, verify_md5=False)
    await _filter_and_write_parquet(parsed, slice_id, state=state,
                                    parquet_base=parquet_base)

    # Advance parquet last_slice as soon as ALL 3 streams are persisted.
    # Truth-layer progress is INDEPENDENT of Neo4j/Qdrant outcomes — otherwise
    # a down Qdrant would cause forward() to re-download the same slice forever.
    parquet_states = [
        await state.get_stream_parquet(slice_id, s)
        for s in ("events", "mentions", "gkg")
    ]
    if all(s == "done" for s in parquet_states):
        await state.set_last_slice("parquet", slice_id)

    # Neo4j
    try:
        await neo4j_writer.write_from_parquet(parquet_base, slice_id, date)
        await state.set_store_state(slice_id, "neo4j", "done")
        await state.set_last_slice("neo4j", slice_id)
    except Exception as e:
        log.error("gdelt_neo4j_write_failed", slice=slice_id, error=str(e))
        await state.set_store_state(slice_id, "neo4j", f"failed:{e}")
        await state.add_pending("neo4j", slice_id)

    # Qdrant — INDEPENDENT of Neo4j outcome
    try:
        await qdrant_writer.upsert_from_parquet(parquet_base, slice_id, date)
        await state.set_store_state(slice_id, "qdrant", "done")
        await state.set_last_slice("qdrant", slice_id)
    except Exception as e:
        log.error("gdelt_qdrant_write_failed", slice=slice_id, error=str(e))
        await state.set_store_state(slice_id, "qdrant", "pending_embed")
        await state.add_pending("qdrant", slice_id)

    log.info("gdelt_forward_done", slice=slice_id)


async def run_forward(state: GDELTState, neo4j_writer, qdrant_writer,
                     parquet_base: Path) -> None:
    """Entry point called by scheduler."""
    await replay_pending(state, parquet_base=parquet_base,
                         neo4j_writer=neo4j_writer, qdrant_writer=qdrant_writer)

    entries = await fetch_lastupdate()
    by_slice: dict[str, list[LastUpdateEntry]] = {}
    for e in entries:
        by_slice.setdefault(e.slice_id, []).append(e)

    latest_slice = max(by_slice.keys())
    last_done = await state.get_last_slice("parquet")
    if last_done == latest_slice:
        log.info("gdelt_no_new_slice", latest=latest_slice)
        return

    with tempfile.TemporaryDirectory() as tmp:
        await run_forward_slice(
            by_slice[latest_slice],
            state=state, parquet_base=parquet_base,
            neo4j_writer=neo4j_writer, qdrant_writer=qdrant_writer,
            tmp_dir=Path(tmp),
        )
