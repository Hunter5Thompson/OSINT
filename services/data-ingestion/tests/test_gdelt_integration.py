"""Integration test: run full forward tick against local dev-compose.

Skip if services are not running. Uses fixture slice — no live GDELT.
Bypasses download by feeding parsed DataFrames directly via
_filter_and_write_parquet + writers.write_from_parquet.

Required environment when services are up:
    NEO4J_PASSWORD     password for the local Neo4j (required to actually run)
    REDIS_URL          default: redis://localhost:6379/0
    NEO4J_URL          default: bolt://localhost:7687
    NEO4J_USER         default: neo4j
    QDRANT_URL         default: http://localhost:6333
    QDRANT_COLLECTION  default: odin_intel
    TEI_EMBED_URL      default: http://localhost:8001

If NEO4J_PASSWORD is not set we still want pytest *collection* to succeed —
hence ``os.getenv("NEO4J_PASSWORD", "")``. The test only runs when the
``_dev_services_up()`` health-check passes; otherwise it is skipped cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import polars as pl
import pytest

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"


def _dev_services_up() -> bool:
    """True only when Qdrant + TEI are reachable AND a Neo4j password is set.

    Neo4j auth errors (missing credentials) would surface as a hard failure
    inside the test, but Task 23 mandates the test must *never* fail when the
    dev environment isn't fully wired up — only skip cleanly. So we also
    require ``NEO4J_PASSWORD`` to be present before declaring services up.
    """
    if not os.getenv("NEO4J_PASSWORD"):
        return False
    try:
        httpx.get("http://localhost:6333/", timeout=2.0).raise_for_status()
        httpx.get("http://localhost:8001/health", timeout=2.0).raise_for_status()
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _dev_services_up(), reason="dev-compose services not running")
@pytest.mark.asyncio
async def test_full_forward_tick_against_real_stores(tmp_path):
    """Run forward with fixture slice + real Neo4j/Qdrant/Redis."""
    import redis.asyncio as aioredis
    from qdrant_client import AsyncQdrantClient

    from gdelt_raw.parser import parse_events, parse_gkg, parse_mentions
    from gdelt_raw.run import ParsedSlice
    from gdelt_raw.state import GDELTState
    from gdelt_raw.writers.neo4j_writer import Neo4jWriter
    from gdelt_raw.writers.qdrant_writer import QdrantWriter, default_tei_embed

    slice_id = "99999425120000"  # test-sentinel slice_id, safe to clean up
    date = "9999-04-25"

    r = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    state = GDELTState(r)

    neo4j = Neo4jWriter(
        uri=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", ""),
    )
    qclient = AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

    async def embed(text: str):
        return await default_tei_embed(
            text, tei_url=os.getenv("TEI_EMBED_URL", "http://localhost:8001")
        )

    qdrant = QdrantWriter(
        client=qclient,
        embed=embed,
        collection=os.getenv("QDRANT_COLLECTION", "odin_intel"),
    )

    # 1. Parse
    ev_res = parse_events(
        FIXTURES / "slice_20260425_full.export.CSV", quarantine_dir=tmp_path / "q"
    )
    me_res = parse_mentions(
        FIXTURES / "slice_20260425_full.mentions.CSV", quarantine_dir=tmp_path / "q"
    )
    gk_res = parse_gkg(
        FIXTURES / "slice_20260425_full.gkg.csv", quarantine_dir=tmp_path / "q"
    )

    parsed = ParsedSlice(
        events_df=ev_res.df,
        mentions_df=me_res.df,
        gkg_df=gk_res.df,
        stream_states={"events": "done", "mentions": "done", "gkg": "done"},
    )

    parquet_base = tmp_path / "gdelt"
    parquet_base.mkdir(parents=True)

    from gdelt_raw.config import get_settings
    from gdelt_raw.filter import apply_filters
    from gdelt_raw.transform import (
        canonicalize_events,
        canonicalize_gkg,
        canonicalize_mentions,
    )
    from gdelt_raw.writers.parquet_writer import write_stream_parquet

    settings = get_settings()
    fr = apply_filters(
        parsed.events_df,
        parsed.mentions_df,
        parsed.gkg_df,
        cameo_roots=settings.cameo_root_allowlist,
        theme_alpha=settings.theme_allowlist,
        theme_nuclear_override=settings.nuclear_override_themes,
    )

    # Force deterministic event_id/doc_id for cleanup.
    # GDELTEventWrite.event_id pattern is ``^gdelt:event:\d+$`` so the sentinel
    # has to stay digit-pure — we reuse the slice_id (``99999425120000``) as a
    # numeric prefix that no real GDELT event will ever have.
    # GDELTDocumentWrite.doc_id pattern is ``^gdelt:gkg:\S+$`` so we can use a
    # readable string sentinel there.
    sentinel_ev_numeric_prefix = slice_id  # all-digits, unmistakably synthetic
    sentinel_prefix_ev = f"gdelt:event:{sentinel_ev_numeric_prefix}"
    sentinel_prefix_doc = f"gdelt:gkg:itest-{slice_id}-"
    ev_canon = canonicalize_events(fr.events).with_columns(
        (
            pl.lit(sentinel_prefix_ev)
            + pl.col("event_id").str.split(":").list.get(-1)
        ).alias("event_id")
    )
    gkg_canon = canonicalize_gkg(fr.gkg).with_columns(
        (
            pl.lit(sentinel_prefix_doc)
            + pl.col("doc_id").str.split(":").list.get(-1)
        ).alias("doc_id")
    )
    mentions_canon = canonicalize_mentions(fr.mentions)

    write_stream_parquet(
        ev_canon,
        base_path=parquet_base,
        stream="events",
        date=date,
        slice_id=slice_id,
    )
    write_stream_parquet(
        gkg_canon,
        base_path=parquet_base,
        stream="gkg",
        date=date,
        slice_id=slice_id,
    )
    write_stream_parquet(
        mentions_canon,
        base_path=parquet_base,
        stream="mentions",
        date=date,
        slice_id=slice_id,
    )

    for st in ("events", "mentions", "gkg"):
        await state.set_stream_parquet(slice_id, st, "done")

    # 3. Neo4j write from parquet
    await neo4j.write_from_parquet(parquet_base, slice_id, date)
    await state.set_store_state(slice_id, "neo4j", "done")

    # Assert at least one sentinel event exists
    async with neo4j._driver.session() as s:
        result = await s.run(
            "MATCH (e:GDELTEvent) WHERE e.event_id STARTS WITH $p RETURN count(e) AS n",
            {"p": sentinel_prefix_ev},
        )
        n = (await result.single())["n"]
    assert n >= 1, "no sentinel GDELTEvent found in Neo4j"

    # 4. Qdrant write from parquet
    n_points = await qdrant.upsert_from_parquet(parquet_base, slice_id, date)
    await state.set_store_state(slice_id, "qdrant", "done")
    assert n_points >= 1, "no sentinel gkg_doc upserted to Qdrant"

    # 5. State assertions
    await state.set_last_slice("parquet", slice_id)
    assert await state.is_slice_fully_done(slice_id) is True

    # 6. Cleanup
    async with neo4j._driver.session() as s:
        await s.run(
            "MATCH (e:GDELTEvent) WHERE e.event_id STARTS WITH $p DETACH DELETE e",
            {"p": sentinel_prefix_ev},
        )
        await s.run(
            "MATCH (d:GDELTDocument) WHERE d.doc_id STARTS WITH $p DETACH DELETE d",
            {"p": sentinel_prefix_doc},
        )
    await neo4j.close()

    # Qdrant cleanup — filter-by-prefix delete
    from qdrant_client.http.models import FieldCondition, Filter, MatchText

    await qclient.delete(
        collection_name=os.getenv("QDRANT_COLLECTION", "odin_intel"),
        points_selector=Filter(
            must=[
                FieldCondition(key="doc_id", match=MatchText(text=sentinel_prefix_doc)),
            ]
        ),
    )

    # Redis cleanup
    await r.delete(
        *[
            f"gdelt:slice:{slice_id}:events:parquet",
            f"gdelt:slice:{slice_id}:gkg:parquet",
            f"gdelt:slice:{slice_id}:mentions:parquet",
            f"gdelt:slice:{slice_id}:neo4j",
            f"gdelt:slice:{slice_id}:qdrant",
        ]
    )
