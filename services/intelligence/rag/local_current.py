"""Read-only, time-filtered access to the existing curated RSS corpus."""

import hashlib
from datetime import UTC, datetime

from qdrant_client import models

from rag.corpus_policy import analysis_filter, validate_lane
from rag.evidence import EvidenceItem, RetrievalProvenance, to_evidence_item
from rag.retriever import enhanced_search
from spatial import (
    RetrievalSpatialRelation,
    SpatialScopeTokenV1,
    combine_filters,
    compile_qdrant_scope_filter,
)


async def search_current_corpus(
    question: str,
    since: datetime,
    as_of: datetime,
    *,
    scope: SpatialScopeTokenV1 | None = None,
    relation: RetrievalSpatialRelation = RetrievalSpatialRelation.EITHER,
) -> list[EvidenceItem]:
    temporal = models.Filter(
        must=[
            models.FieldCondition(
                key="published_at",
                range=models.DatetimeRange(gte=since, lte=as_of),
            )
        ]
    )
    scoped = compile_qdrant_scope_filter(scope, relation) if scope else None
    hits = await enhanced_search(
        question,
        limit=4,
        pool=12,
        score_threshold=0.45,
        query_filter=combine_filters(combine_filters(analysis_filter(), temporal), scoped),
        enable_graph_context=False,
        raise_on_failure=True,
    )
    items = []
    for hit in validate_lane(hits, "analysis"):
        item = to_evidence_item(hit)
        published = item.source.published_at
        if published is None or not since <= published <= as_of:
            continue
        text = hit.get("content", "")
        if not isinstance(text, str) or not text.strip():
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()
        item.retrieval = RetrievalProvenance(
            retrieved_at=datetime.now(UTC),
            content_kind="fulltext_chunk" if hit.get("source") == "rss_fulltext" else "snippet",
            content_sha256=digest,
            source_chars=len(text),
            excerpt_truncated=len(text) > 700,
            original_lineage=item.source.url or item.source.source_ref_id,
            temporal_basis="source_publication",
        )
        items.append(item)
    return items
