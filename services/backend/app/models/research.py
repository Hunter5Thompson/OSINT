"""Public current-research receipts; retrieval is never a truth certification."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RetrievalProvenance(BaseModel):
    retrieved_at: datetime
    content_kind: Literal["snippet", "fulltext", "fulltext_chunk"]
    content_sha256: str
    source_chars: int = 0
    excerpt_truncated: bool = False
    original_lineage: str
    lineage_basis: Literal["url", "attribution", "identical_content"] = "url"
    temporal_basis: Literal["provider_publication", "source_publication", "unknown"] = "unknown"
    spatial_basis: Literal["topic_only", "scoped"] = "topic_only"


class ResearchAttempt(BaseModel):
    action: Literal["search", "extract", "local_search"]
    status: Literal["succeeded", "empty", "partial", "failed", "blocked"]
    code: str | None = None
    reserved_credits: int = 0
    reported_credits: float | None = None


class ResearchCoverage(BaseModel):
    as_of: datetime
    published_since: datetime
    status: Literal["complete", "partial", "unavailable", "not_requested"]
    situation: Literal["evidence_available", "insufficient_evidence", "research_failed"]
    forecast: Literal["not_requested", "not_assessed"] = "not_assessed"
    current_evidence_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    attempts: list[ResearchAttempt] = Field(default_factory=list)
    scope_key: str = "world"
    spatial_basis: Literal["topic_only"] = "topic_only"
