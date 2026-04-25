"""Writer-layer Pydantic contracts — enforce event_id/doc_id at the gateway.

Why: Neo4j Community edition does not support NOT NULL / NODE KEY constraints.
These contracts are the application-side replacement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GDELTEventWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    event_id: str = Field(pattern=r"^gdelt:event:\d+$")
    source: Literal["gdelt"] = "gdelt"
    cameo_code: str
    cameo_root: int = Field(ge=1, le=20)
    quad_class: int = Field(ge=1, le=4)
    goldstein: float
    avg_tone: float
    num_mentions: int
    num_sources: int
    num_articles: int
    date_added: datetime
    fraction_date: float
    actor1_code: str | None = None
    actor1_name: str | None = None
    actor2_code: str | None = None
    actor2_name: str | None = None
    source_url: str
    codebook_type: str
    filter_reason: Literal["tactical", "nuclear_override"]


class GDELTDocumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    doc_id: str = Field(pattern=r"^gdelt:gkg:\S+$")
    source: Literal["gdelt_gkg"] = "gdelt_gkg"
    url: str
    source_name: str
    gdelt_date: datetime
    published_at: datetime | None = None
    themes: list[str] = Field(default_factory=list)
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    tone_positive: float = 0.0
    tone_negative: float = 0.0
    tone_polarity: float = 0.0
    tone_activity: float = 0.0
    tone_self_group: float = 0.0
    word_count: int = 0
    sharp_image_url: str | None = None
    quotations: list[str] = Field(default_factory=list)
    # Materialized join fields (may be empty if doc had no Mentions)
    linked_event_ids: list[str] = Field(default_factory=list)
    goldstein_min: float | None = None
    goldstein_avg: float | None = None
    cameo_roots_linked: list[int] = Field(default_factory=list)
    codebook_types_linked: list[str] = Field(default_factory=list)
