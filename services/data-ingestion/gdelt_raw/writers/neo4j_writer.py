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
from pydantic import BaseModel, ValidationError

from gdelt_raw.ids import build_location_id
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
    e.timeline_at = datetime($date_added),
    e.time_basis = 'indexed',
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
    e.num_articles = $num_articles,
    e.timeline_at = datetime($date_added),
    e.time_basis = 'indexed'
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
// Intentional: :Document (unscoped) so GDELT mentions can bridge to docs from
// other ingestion paths. OPTIONAL MATCH (not MATCH) so a mention whose article
// was not theme-matched is a DETECTABLE drop, not a silent zero-row no-op
// (WP-09). The FOREACH performs the MERGE only when both nodes resolved.
OPTIONAL MATCH (d:Document {url: $doc_url})
OPTIONAL MATCH (e:GDELTEvent {event_id: $event_id})
FOREACH (_ IN CASE WHEN d IS NOT NULL AND e IS NOT NULL THEN [1] ELSE [] END |
  MERGE (d)-[r:MENTIONS]->(e)
    SET r.tone = $tone, r.confidence = $confidence, r.char_offset = $char_offset
)
RETURN d IS NOT NULL AS d_found, e IS NOT NULL AS e_found
"""
# SET (not ON CREATE/ON MATCH) is unconditional last-write-wins — equivalent to
# the prior template's identical ON CREATE/ON MATCH SET, but FOREACH-legal.

MERGE_LOCATION = """
MATCH (ev:GDELTEvent {event_id: $event_id})
MERGE (l:Location {loc_key: $loc_key})
  ON CREATE SET l.name = $name, l.country = $country,
                l.lat = $lat, l.lon = $lon, l.geo_basis = 'gdelt_actiongeo'
MERGE (ev)-[:OCCURRED_AT]->(l)
"""


def location_params_for(ev: GDELTEventWrite) -> dict[str, Any] | None:
    if ev.action_geo_lat is None or ev.action_geo_long is None:
        return None
    return {
        "event_id": ev.event_id,
        "loc_key": build_location_id(
            ev.action_geo_feature_id or "",
            ev.action_geo_country_code or "",
            ev.action_geo_fullname or "",
        ),
        "name": ev.action_geo_fullname,
        "country": ev.action_geo_country_code,
        "lat": ev.action_geo_lat,
        "lon": ev.action_geo_long,
    }


def render_event_params(ev: GDELTEventWrite) -> dict[str, Any]:
    d = ev.model_dump(mode="json")  # datetime → iso
    return d


def render_doc_params(doc: GDELTDocumentWrite) -> dict[str, Any]:
    d = doc.model_dump(mode="json")
    return d


def _classify_mention(*, d_found: bool, e_found: bool, rels_created: int) -> str:
    """Classify one MERGE_MENTION outcome. A drop is a MATCH binding nothing —
    NOT rels_created == 0 (that is also 0 on replay / existing edge)."""
    if not d_found:
        return "dropped_no_document"
    if not e_found:
        return "dropped_no_event"
    return "written" if rels_created > 0 else "existing"


def _validate_rows(rows: list[dict], model: type[BaseModel], stream: str) -> list:
    """Validate each row against ``model``; skip-and-log rejects instead of
    fail-fast. One malformed row (e.g. a null doc_id that slipped past the
    parser gate) must not block the whole slice's batch write (WP-02)."""
    valid = []
    rejected = 0
    for r in rows:
        try:
            valid.append(model.model_validate(r))
        except ValidationError as e:
            rejected += 1
            log.warning(
                "gdelt_writer_row_rejected",
                stream=stream,
                doc_id=r.get("doc_id"),
                event_id=r.get("event_id"),
                error=str(e).splitlines()[0],
            )
    if rejected:
        log.warning(
            "gdelt_writer_rows_rejected",
            stream=stream, rejected=rejected, accepted=len(valid),
        )
    return valid


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
                    loc = location_params_for(ev)
                    if loc is not None:
                        await tx.run(MERGE_LOCATION, loc)
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

    async def write_mentions(self, mentions: list[dict], slice_id: str) -> dict[str, int]:
        """mentions: canonical dicts with event_id, mention_url, tone, confidence,
        char_offset. A mention whose article was not theme-matched has no
        Document and is counted as dropped_no_document (by-design filtering — see
        WP-09), never silently lost. Returns per-slice outcome counts."""
        counts = {"written": 0, "existing": 0,
                  "dropped_no_document": 0, "dropped_no_event": 0}
        async with self._driver.session() as session:  # noqa: SIM117
            async with await session.begin_transaction() as tx:
                for m in mentions:
                    result = await tx.run(MERGE_MENTION, {
                        "doc_url": m["mention_url"],
                        "event_id": m["event_id"],
                        "tone": m.get("tone"),
                        "confidence": m.get("confidence"),
                        "char_offset": m.get("char_offset"),
                    })
                    # MERGE_MENTION always RETURNs exactly one row (OPTIONAL MATCH
                    # never reduces cardinality to zero), so single() is safe; it
                    # drains the stream, after which consume() returns the buffered
                    # summary (relationships_created). The @pytest.mark.integration
                    # test runs this query + single()/consume() against a live Neo4j
                    # (CI has no Neo4j); it does not yet assert the edge-creation
                    # arm — see follow-up to remap the mentions sentinel event_id.
                    record = await result.single()
                    summary = await result.consume()
                    outcome = _classify_mention(
                        d_found=bool(record["d_found"]),
                        e_found=bool(record["e_found"]),
                        rels_created=summary.counters.relationships_created,
                    )
                    counts[outcome] += 1
                await tx.commit()

        log.info("gdelt_mentions_written_total", slice=slice_id, **counts)
        if counts["dropped_no_document"] or counts["dropped_no_event"]:
            # Event name is the spec-mandated metric (dominant cause is a
            # non-theme-matched article → no Document); the payload carries BOTH
            # dropped_no_document and dropped_no_event so neither kind is lost.
            log.warning(
                "gdelt_mentions_dropped_no_document_total",
                slice=slice_id,
                dropped_no_document=counts["dropped_no_document"],
                dropped_no_event=counts["dropped_no_event"],
            )
        return counts

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
            events = _validate_rows(ev_df.to_dicts(), GDELTEventWrite, "events")
            if events:
                await self.write_events(events)

        if gkg_path.exists():
            gkg_df = pl.read_parquet(gkg_path)
            docs = _validate_rows(gkg_df.to_dicts(), GDELTDocumentWrite, "gkg")
            if docs:
                await self.write_docs(docs)

        # Mentions require both Events and Docs to already exist — only write
        # if both parquet streams were present.
        if mentions_path.exists() and ev_path.exists() and gkg_path.exists():
            m_df = pl.read_parquet(mentions_path)
            await self.write_mentions(m_df.to_dicts(), slice_id)
