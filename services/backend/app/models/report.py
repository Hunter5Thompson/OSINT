"""Pydantic models for Briefing reports and report-scoped chat messages."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Literal

from pydantic import BaseModel, Field

_utc_now = partial(datetime.now, UTC)

ReportStatus = Literal["Draft", "Published", "Archived"]
MessageRole = Literal["user", "munin", "system"]
AccentTone = Literal["sentinel", "amber", "sage"]


class DossierMetric(BaseModel):
    label: str
    value: str
    sub: str
    tone: AccentTone = "sentinel"


class MarginEntry(BaseModel):
    label: str
    value: str


class ReportRecord(BaseModel):
    id: str
    paragraph_num: int
    stamp: str
    title: str
    status: ReportStatus = "Draft"
    confidence: float = Field(default=0.62, ge=0.0, le=1.0)
    location: str = "unspecified theatre"
    coords: str = "--"
    findings: list[str] = Field(default_factory=list)
    metrics: list[DossierMetric] = Field(default_factory=list)
    context: str = ""
    body_title: str = ""
    body_paragraphs: list[str] = Field(default_factory=list)
    margin: list[MarginEntry] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class ReportCreateRequest(BaseModel):
    title: str = "Untitled Dossier"
    status: ReportStatus = "Draft"
    confidence: float = Field(default=0.62, ge=0.0, le=1.0)
    location: str = "unspecified theatre"
    coords: str = "--"
    findings: list[str] = Field(default_factory=list)
    metrics: list[DossierMetric] = Field(default_factory=list)
    context: str = ""
    body_title: str = "Initial Editorial Draft"
    body_paragraphs: list[str] = Field(default_factory=list)
    margin: list[MarginEntry] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ReportUpdateRequest(BaseModel):
    title: str | None = None
    status: ReportStatus | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    location: str | None = None
    coords: str | None = None
    findings: list[str] | None = None
    metrics: list[DossierMetric] | None = None
    context: str | None = None
    body_title: str | None = None
    body_paragraphs: list[str] | None = None
    margin: list[MarginEntry] | None = None
    sources: list[str] | None = None


class ReportMessage(BaseModel):
    id: str
    role: MessageRole
    text: str
    ts: datetime = Field(default_factory=_utc_now)
    refs: list[str] = Field(default_factory=list)


class ReportMessageCreate(BaseModel):
    role: MessageRole
    text: str = Field(..., min_length=1, max_length=8000)
    ts: datetime | None = None
    refs: list[str] = Field(default_factory=list)
