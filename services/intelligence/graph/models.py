"""Pydantic models for the Neo4j knowledge graph."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    type: Literal[
        "person", "organization", "location", "weapon_system",
        "satellite", "vessel", "aircraft", "military_unit",
    ]
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    summary: str = ""
    timestamp: datetime
    codebook_type: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1, default=0.5)


class Source(BaseModel):
    url: str
    name: str
    credibility_score: float = Field(ge=0, le=1, default=0.5)


class Location(BaseModel):
    name: str
    country: str
    lat: float | None = None
    lon: float | None = None
