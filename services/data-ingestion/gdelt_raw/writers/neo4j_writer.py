"""Neo4j writer — deterministic Cypher MERGE templates.

Writers validate via Pydantic contracts before any Neo4j call.
No LLM-generated Cypher on the write-path (CLAUDE.md rule).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import structlog
from neo4j import AsyncGraphDatabase

from gdelt_raw.schemas import GDELTDocumentWrite, GDELTEventWrite

log = structlog.get_logger(__name__)


MERGE_EVENT = """
MERGE (e:Event:GDELTEvent {event_id: $event_id})
  ON CREATE SET
    e.source = 'gdelt',
    e.cameo_code = $cameo_code,
    e.cameo_root = $cameo_root,
    e.quad_class = $quad_class,
    e.goldstein = $goldstein,
    e.avg_tone = $avg_tone,
    e.num_mentions = $num_mentions,
    e.num_sources = $num_sources,
    e.num_articles = $num_articles,
    e.date_added = datetime($date_added),
    e.fraction_date = $fraction_date,
    e.actor1_code = $actor1_code,
    e.actor1_name = $actor1_name,
    e.actor2_code = $actor2_code,
    e.actor2_name = $actor2_name,
    e.source_url = $source_url,
    e.codebook_type = $codebook_type,
    e.filter_reason = $filter_reason
  ON MATCH SET
    e.num_mentions = $num_mentions,
    e.num_sources = $num_sources,
    e.num_articles = $num_articles
"""

MERGE_DOC = """
MERGE (d:Document:GDELTDocument {doc_id: $doc_id})
  ON CREATE SET
    d.source = 'gdelt_gkg',
    d.url = $url,
    d.source_name = $source_name,
    d.gdelt_date = datetime($gdelt_date),
    d.published_at = CASE WHEN $published_at IS NULL THEN NULL ELSE datetime($published_at) END,
    d.themes = $themes,
    d.tone_polarity = $tone_polarity,
    d.word_count = $word_count,
    d.sharp_image_url = $sharp_image_url,
    d.quotations = $quotations
"""

MERGE_SOURCE = """
MERGE (s:Source {name: $name})
  ON CREATE SET s.quality_tier = 'unverified', s.updated_at = datetime()
  ON MATCH SET  s.updated_at = datetime()
WITH s
MATCH (d:GDELTDocument {doc_id: $doc_id})
MERGE (d)-[:FROM_SOURCE]->(s)
"""

MERGE_THEME = """
MATCH (d:GDELTDocument {doc_id: $doc_id})
UNWIND $themes AS tcode
MERGE (t:Theme {theme_code: tcode})
MERGE (d)-[:ABOUT]->(t)
"""
# Idempotency: MERGE on the relationship is set-semantic — no count
# increment on replay. If theme-frequency is ever needed, store it in
# d.themes (list) and query with list functions.

MERGE_MENTION = """
// Intentional: :Document (unscoped) so GDELT mentions can bridge
// to docs from other ingestion paths.
MATCH (d:Document {url: $doc_url})
MATCH (e:GDELTEvent {event_id: $event_id})
MERGE (d)-[r:MENTIONS]->(e)
  ON CREATE SET r.tone = $tone, r.confidence = $confidence, r.char_offset = $char_offset
  ON MATCH  SET r.tone = $tone, r.confidence = $confidence, r.char_offset = $char_offset
"""
# ON MATCH also SETs — last-write-wins on properties, but edge count stays 1.


def render_event_params(ev: GDELTEventWrite) -> dict[str, Any]:
    d = ev.model_dump(mode="json")  # datetime → iso
    return d


def render_doc_params(doc: GDELTDocumentWrite) -> dict[str, Any]:
    d = doc.model_dump(mode="json")
    return d


class Neo4jWriter:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self):
        await self._driver.close()

    async def write_events(self, events: list[GDELTEventWrite]):
        # noqa rationale: outer `with` binds `session`, which is required by
        # `await session.begin_transaction()` in the inner `with` — cannot be
        # combined into a single `async with X, Y` form.
        async with self._driver.session() as session:  # noqa: SIM117
            async with await session.begin_transaction() as tx:
                for ev in events:
                    await tx.run(MERGE_EVENT, render_event_params(ev))
                await tx.commit()

    async def write_docs(self, docs: list[GDELTDocumentWrite]):
        async with self._driver.session() as session:  # noqa: SIM117
            async with await session.begin_transaction() as tx:
                for d in docs:
                    params = render_doc_params(d)
                    await tx.run(MERGE_DOC, params)
                    await tx.run(MERGE_SOURCE, {"name": d.source_name, "doc_id": d.doc_id})
                    if d.themes:
                        await tx.run(MERGE_THEME, {"themes": d.themes, "doc_id": d.doc_id})
                await tx.commit()

    async def write_mentions(self, mentions: list[dict]):
        """mentions: list of canonical dicts with event_id, mention_url, tone,
        confidence, char_offset. Requires corresponding Documents + GDELTEvents
        to already exist in the graph."""
        async with self._driver.session() as session:  # noqa: SIM117
            async with await session.begin_transaction() as tx:
                for m in mentions:
                    await tx.run(MERGE_MENTION, {
                        "doc_url": m["mention_url"],
                        "event_id": m["event_id"],
                        "tone": m.get("tone"),
                        "confidence": m.get("confidence"),
                        "char_offset": m.get("char_offset"),
                    })
                await tx.commit()

    async def write_from_parquet(self, parquet_base: str | Path, slice_id: str, date: str):
        """Read the three canonical parquet streams and write in dependency order:
        Events → Documents (+ Sources, + Themes) → Mentions (Doc→Event edges).

        Phase 1 scope: Events, Documents, Sources, Themes, Mentions.
        Deferred to Phase 2 (separate spec): Entities (from V2Persons/V2Orgs),
        Locations (from V2Locations), INVOLVES edges, OCCURRED_AT edges.

        Atomicity is per-stream, not per-slice — if a downstream stream
        fails, idempotent MERGE on retry recovers the missing edges."""
        ev_path = Path(parquet_base) / "events" / f"date={date}" / f"{slice_id}.parquet"
        gkg_path = Path(parquet_base) / "gkg" / f"date={date}" / f"{slice_id}.parquet"
        mentions_path = Path(parquet_base) / "mentions" / f"date={date}" / f"{slice_id}.parquet"

        if ev_path.exists():
            ev_df = pl.read_parquet(ev_path)
            events = [GDELTEventWrite.model_validate(r) for r in ev_df.to_dicts()]
            await self.write_events(events)

        if gkg_path.exists():
            gkg_df = pl.read_parquet(gkg_path)
            docs = [GDELTDocumentWrite.model_validate(r) for r in gkg_df.to_dicts()]
            await self.write_docs(docs)

        # Mentions require both Events and Docs to already exist — only write
        # if both parquet streams were present.
        if mentions_path.exists() and ev_path.exists() and gkg_path.exists():
            m_df = pl.read_parquet(mentions_path)
            await self.write_mentions(m_df.to_dicts())
