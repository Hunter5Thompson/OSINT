"""Forward and backfill orchestration for GDELT raw ingestion."""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import structlog

from gdelt_raw.config import get_settings
from gdelt_raw.downloader import (
    LastUpdateEntry,
    download_slice,
    fetch_lastupdate,
)
from gdelt_raw.filter import FilterResult, apply_filters
from gdelt_raw.parser import parse_events, parse_gkg, parse_mentions
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
        canonicalize_events,
        canonicalize_gkg,
        canonicalize_mentions,
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

    parsed = await _extract_and_parse(entries, work, verify_md5=verify_md5)
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


# ---------------------------------------------------------------------------
# Backfill — resumable, parallel slice processing over a date range.
# ---------------------------------------------------------------------------


def enumerate_slices_for_range(start: datetime, end: datetime) -> Iterator[str]:
    """Yield slice_ids at 15-min steps, inclusive of both endpoints (aligned to :00,:15,:30,:45)."""
    start = start.replace(minute=(start.minute // 15) * 15, second=0, microsecond=0)
    cur = start
    while cur <= end:
        yield cur.strftime("%Y%m%d%H%M%S")
        cur = cur + timedelta(minutes=15)


@dataclass
class BackfillJob:
    job_id: str
    total: int


def _bf_key(job_id: str, suffix: str) -> str:
    return f"gdelt:backfill:{job_id}:{suffix}"


async def initialize_backfill(
    state: GDELTState, *, job_id: str, start: datetime, end: datetime,
) -> BackfillJob:
    """Idempotent: re-running only adds slices not already done/failed/pending."""
    slice_ids = list(enumerate_slices_for_range(start, end))
    done = await state.r.smembers(_bf_key(job_id, "done"))
    failed = await state.r.smembers(_bf_key(job_id, "failed"))
    # Pending = slice_ids - done - failed (failed stays until resume)
    to_enqueue = [s for s in slice_ids if s not in done and s not in failed]
    if to_enqueue:
        await state.r.zadd(
            _bf_key(job_id, "pending"),
            {s: int(s) for s in to_enqueue},
        )
    await state.r.set(_bf_key(job_id, "state"), "running")
    await state.r.set(_bf_key(job_id, "total"), str(len(slice_ids)))
    return BackfillJob(job_id=job_id, total=len(slice_ids))


async def pop_next_pending(state: GDELTState, job_id: str) -> str | None:
    """ZPOPMIN (single-slice atomic pop) — returns slice_id or None if empty."""
    res = await state.r.zpopmin(_bf_key(job_id, "pending"), 1)
    if not res:
        return None
    slice_id, _ = res[0]
    return slice_id


async def mark_slice_done(state: GDELTState, job_id: str, slice_id: str) -> None:
    await state.r.srem(_bf_key(job_id, "failed"), slice_id)
    await state.r.zrem(_bf_key(job_id, "pending"), slice_id)
    await state.r.sadd(_bf_key(job_id, "done"), slice_id)


async def mark_slice_failed(
    state: GDELTState, job_id: str, slice_id: str, reason: str,
) -> None:
    await state.r.zrem(_bf_key(job_id, "pending"), slice_id)
    await state.r.sadd(_bf_key(job_id, "failed"), slice_id)
    await state.r.set(_bf_key(job_id, f"failed:{slice_id}:reason"), reason)


async def resume_backfill_pending(state: GDELTState, job_id: str) -> int:
    """Move all failed slices back into pending; returns re-enqueued count."""
    failed = await state.r.smembers(_bf_key(job_id, "failed"))
    if failed:
        await state.r.zadd(
            _bf_key(job_id, "pending"),
            {s: int(s) for s in failed},
        )
        await state.r.delete(_bf_key(job_id, "failed"))
    return len(failed)


async def run_backfill(
    start: datetime, end: datetime, *,
    state: GDELTState, neo4j_writer, qdrant_writer,
    parquet_base: Path, job_id: str, parallel: int = 4,
) -> None:
    """Backfill a date range. Resumable: pending/done/failed sets in Redis."""
    job = await initialize_backfill(state, job_id=job_id, start=start, end=end)
    log.info("gdelt_backfill_start", job_id=job_id, total=job.total)

    sem = asyncio.Semaphore(parallel)
    settings = get_settings()

    async def _worker():
        while True:
            sid = await pop_next_pending(state, job_id)
            if sid is None:
                return
            # Skip if already complete (fully-done predicate covers re-runs)
            if await state.is_slice_fully_done(sid):
                await mark_slice_done(state, job_id, sid)
                continue
            async with sem:
                entries = [
                    LastUpdateEntry(0, "",
                        f"{settings.base_url}/{sid}.export.CSV.zip", "events", sid),
                    LastUpdateEntry(0, "",
                        f"{settings.base_url}/{sid}.mentions.CSV.zip", "mentions", sid),
                    LastUpdateEntry(0, "",
                        f"{settings.base_url}/{sid}.gkg.csv.zip", "gkg", sid),
                ]
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        # Historical slices: no lastupdate -> no MD5 -> verify_md5=False
                        await run_forward_slice(
                            entries, state=state, parquet_base=parquet_base,
                            neo4j_writer=neo4j_writer, qdrant_writer=qdrant_writer,
                            tmp_dir=Path(tmp), verify_md5=False,
                        )
                        await mark_slice_done(state, job_id, sid)
                    except Exception as e:
                        log.error("backfill_slice_failed", slice=sid, error=str(e))
                        await mark_slice_failed(state, job_id, sid, reason=str(e))

    await asyncio.gather(*[_worker() for _ in range(parallel)])
    await state.r.set(_bf_key(job_id, "state"), "done")
    log.info("gdelt_backfill_done", job_id=job_id)
