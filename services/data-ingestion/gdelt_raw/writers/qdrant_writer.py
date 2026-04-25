"""Qdrant writer — embeds GKG docs and upserts points.

Reads ONLY from GKG parquet. Independent of Neo4j state.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import structlog
from qdrant_client.models import PointStruct

from gdelt_raw.ids import qdrant_point_id_for_doc

log = structlog.get_logger(__name__)


def build_embed_text(row: dict[str, Any]) -> str:
    title = row.get("title") or row.get("doc_id", "")
    themes = ", ".join(row.get("themes") or [])
    persons = ", ".join(row.get("persons") or [])
    orgs = ", ".join(row.get("organizations") or [])
    actors = (persons + (", " if persons and orgs else "") + orgs).strip(", ")
    return f"{title}\nThemes: {themes}\nActors: {actors}"[:1500]


def build_payload(row: dict[str, Any]) -> dict[str, Any]:
    gdelt_date = row.get("gdelt_date") or row.get("v21_date")
    if isinstance(gdelt_date, datetime):
        gdelt_date_iso = gdelt_date.isoformat()
    elif isinstance(gdelt_date, str):
        gdelt_date_iso = gdelt_date
    elif gdelt_date:
        gdelt_date_iso = datetime.strptime(str(gdelt_date), "%Y%m%d%H%M%S") \
            .replace(tzinfo=UTC).isoformat()
    else:
        gdelt_date_iso = None

    return {
        "source": "gdelt_gkg",
        "doc_id": row["doc_id"],
        "url": row.get("url"),
        "source_name": row.get("source_name") or row.get("v2_source_common_name"),
        "title": row.get("title") or row["doc_id"],
        "themes": row.get("themes") or [],
        "persons": row.get("persons") or [],
        "organizations": row.get("organizations") or [],
        "tone_polarity": row.get("tone_polarity") or 0.0,
        "linked_event_ids": row.get("linked_event_ids") or [],
        "goldstein_min": row.get("goldstein_min"),
        "goldstein_avg": row.get("goldstein_avg"),
        "cameo_roots_linked": row.get("cameo_roots_linked") or [],
        "codebook_types_linked": row.get("codebook_types_linked") or [],
        "gdelt_date": gdelt_date_iso,
        "published_at": row.get("published_at"),
        "ingested_at": datetime.now(UTC).isoformat(),
    }


async def default_tei_embed(text: str, tei_url: str, http_timeout: float = 30.0) -> list[float]:
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        resp = await client.post(f"{tei_url}/embed", json={"inputs": text})
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data[0], list) else data


class QdrantWriter:
    def __init__(self, client, embed: Callable[[str], Awaitable[list[float]]], collection: str):
        self._client = client
        self._embed = embed
        self._collection = collection

    async def upsert_from_parquet(
        self, parquet_base: Path, slice_id: str, date: str,
    ) -> int:
        path = Path(parquet_base) / "gkg" / f"date={date}" / f"{slice_id}.parquet"
        if not path.exists():
            return 0
        df = pl.read_parquet(path)
        points: list[PointStruct] = []
        for row in df.to_dicts():
            text = build_embed_text(row)
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            vector = await self._embed(text)
            payload = build_payload(row)
            payload["content_hash"] = content_hash
            points.append(PointStruct(
                id=qdrant_point_id_for_doc(row["doc_id"]),
                vector=vector,
                payload=payload,
            ))
        if points:
            await self._client.upsert(collection_name=self._collection, points=points)
        log.info("qdrant_written", slice=slice_id, count=len(points))
        return len(points)
