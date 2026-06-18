"""Operator (Teilstreitkraft) seed: page_slug -> canonical operator node.

Each row is an explicit, executable contract: match an existing node (by exact
name+type, verified by an exactly-1 preflight at build time) or create a new one."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_VALID_TYPES = ("MILITARY_UNIT", "ORGANIZATION")


class OperatorEntry(BaseModel):
    page_slug: str
    page_label: str
    decision: str                      # "match" | "create"
    target_name: str
    target_type: str                   # "MILITARY_UNIT" | "ORGANIZATION"
    create_properties: dict = Field(default_factory=dict)

    @field_validator("decision")
    @classmethod
    def _decision_valid(cls, v: str) -> str:
        if v not in ("match", "create"):
            raise ValueError(f"decision must be match|create, got {v!r}")
        return v

    @field_validator("target_type")
    @classmethod
    def _type_valid(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"target_type must be one of {_VALID_TYPES}, got {v!r}")
        return v


def load_operators(path: Path) -> list[OperatorEntry]:
    return [OperatorEntry(**row) for row in (yaml.safe_load(path.read_text()) or [])]


def operators_by_slug(entries: list[OperatorEntry]) -> dict[str, OperatorEntry]:
    return {e.page_slug: e for e in entries}


def match_preflight_offenders(counts: dict[tuple[str, str], int]) -> list[str]:
    """Given (name, type) -> live node-count for each `match` operator, return
    human-readable offenders that do not resolve to exactly one node."""
    return [f"{name} ({etype}) -> count={c}"
            for (name, etype), c in sorted(counts.items()) if c != 1]
