"""Intelligence analysis models."""

from datetime import UTC, datetime
from functools import partial
from typing import Any

from pydantic import BaseModel, Field

_utc_now = partial(datetime.now, UTC)


class IntelQuery(BaseModel):
    query: str = Field(..., max_length=2000)
    region: str | None = None
    hotspot_id: str | None = None
    image_url: str | None = None
    use_legacy: bool = False
    report_id: str | None = None
    report_message: str | None = Field(default=None, max_length=8000)


class IntelDocument(BaseModel):
    doc_id: str
    source: str
    title: str
    content: str
    region: str | None = None
    hotspot_ids: list[str] = Field(default_factory=list)
    published_at: datetime
    ingested_at: datetime = Field(default_factory=_utc_now)


class IntelAnalysis(BaseModel):
    query: str
    agent_chain: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    analysis: str
    confidence: float = 0.0
    threat_assessment: str | None = None
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = "react"
    timestamp: datetime = Field(default_factory=_utc_now)


class APIError(BaseModel):
    error: str
    detail: str | None = None
    code: str
    timestamp: datetime = Field(default_factory=_utc_now)
