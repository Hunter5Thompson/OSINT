"""Intelligence analysis models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.spatial import SpatialQueryRef

_utc_now = partial(datetime.now, UTC)


class RetrievalSpatialRelation(StrEnum):
    ABOUT = "about"
    OCCURRENCE = "occurrence"
    EITHER = "either"


class _FrozenContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpatialRunScopeV1(_FrozenContractModel):
    schema_version: Literal[1] = 1
    scope_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:._-]+$")
    catalog_revision: str = Field(
        min_length=23,
        max_length=79,
        pattern=r"^spatial-v[0-9]+-[a-f0-9]{12,64}$",
    )
    derivation_revision: str = Field(
        min_length=30,
        max_length=96,
        pattern=r"^spatial-derive-v[0-9]+-[a-f0-9]{12,64}$",
    )
    boundary_policy: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[A-Za-z0-9._-]+$",
    )


class SpatialRunConsumerApplication(_FrozenContractModel):
    status: Literal["applied", "not-called", "unsupported", "failed"]
    mode: Literal["global", "semantic-key"]
    completeness: Literal["complete", "partial", "unknown"]
    detail_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=96,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )


class SpatialRunApplicationV1(_FrozenContractModel):
    schema_version: Literal[1] = 1
    scope: SpatialRunScopeV1
    relation: RetrievalSpatialRelation
    qdrant: SpatialRunConsumerApplication
    neo4j: SpatialRunConsumerApplication
    blocked_tools: tuple[str, ...] = Field(default=(), max_length=16)
    coverage_revision: str | None = Field(
        default=None,
        min_length=34,
        max_length=90,
        pattern=r"^spatial-projection-v[0-9]+-[a-f0-9]{12,64}$",
    )

    @field_validator("blocked_tools")
    @classmethod
    def validate_blocked_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("blocked tools must be unique")
        if any(
            not tool
            or not tool.isascii()
            or not tool[0].islower()
            or len(tool) > 96
            or not all(char.islower() or char.isdigit() or char == "_" for char in tool)
            for tool in value
        ):
            raise ValueError("invalid blocked tool name")
        return value


class IntelQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., max_length=2000)
    region: str | None = None
    spatial_scope: SpatialQueryRef | None = None
    spatial_relation: RetrievalSpatialRelation = RetrievalSpatialRelation.EITHER
    hotspot_id: str | None = None
    image_url: str | None = None
    use_legacy: bool = False
    report_id: str | None = None
    report_message: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def reject_legacy_spatial_combinations(self) -> IntelQuery:
        if self.spatial_scope is None:
            return self
        if self.region is not None:
            raise ValueError("region and spatial_scope are mutually exclusive")
        if self.use_legacy:
            raise ValueError("SPATIAL_SCOPE_UNSUPPORTED_LEGACY")
        return self

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("image_url must be an absolute http(s) URL")

        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise ValueError("image_url host must be public")

        try:
            addr = ip_address(host)
        except ValueError:
            return value

        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            raise ValueError("image_url host must be public")

        return value


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
    spatial_application: SpatialRunApplicationV1 | None = None


class APIError(BaseModel):
    error: str
    detail: str | None = None
    code: str
    timestamp: datetime = Field(default_factory=_utc_now)
