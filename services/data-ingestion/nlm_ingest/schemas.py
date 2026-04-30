from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal, get_args

from pydantic import BaseModel

EntityType = Literal[
    "ORGANIZATION", "COUNTRY", "LOCATION", "PERSON", "REGION",
    "WEAPON_SYSTEM", "MILITARY_UNIT", "POLICY",
    "TREATY", "CONCEPT", "VESSEL", "AIRCRAFT", "SATELLITE",
]

# Canonical EntityType set, derived programmatically from the Literal so adding
# a new EntityType value automatically updates this set without manual sync.
CANONICAL_ENTITY_TYPES: frozenset[str] = frozenset(get_args(EntityType))

# Map legacy lowercase entity-type emissions (the strings the current vLLM
# extraction prompt produces, see pipeline.py _RESPONSE_SCHEMA and the
# intelligence service's ExtractedEntityRaw.type Literal) onto the canonical
# uppercase values used by the nlm_ingest pipeline.
#
# Drift guard: tests/test_nlm_schemas.py asserts the keys here equal the
# Literal values in services/intelligence/codebook/extractor.py.
LEGACY_ENTITY_TYPE_MAP: dict[str, str] = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
    "military_unit": "MILITARY_UNIT",
    "weapon_system": "WEAPON_SYSTEM",
    "vessel": "VESSEL",
    "aircraft": "AIRCRAFT",
    "satellite": "SATELLITE",
}


def normalize_entity_type(value: str) -> str:
    """Map legacy lowercase entity-type values to canonical uppercase.

    Idempotent on already-canonical input. Raises ValueError on unknown values
    so callers can decide on fail-closed vs documented-fallback handling.
    """
    if value in CANONICAL_ENTITY_TYPES:
        return value
    if value in LEGACY_ENTITY_TYPE_MAP:
        return LEGACY_ENTITY_TYPE_MAP[value]
    raise ValueError(f"unknown entity type: {value!r}")

RelationType = Literal[
    "ALLIED_WITH", "COMPETES_WITH", "SANCTIONS",
    "SUPPLIES_TO", "OPERATES_IN", "MEMBER_OF",
    "COMMANDS", "TARGETS", "NEGOTIATES_WITH",
]

ClaimType = Literal["factual", "assessment", "prediction"]
ClaimPolarity = Literal["positive", "negative", "neutral"]


class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker: str | None = None
    text: str


class Transcript(BaseModel):
    notebook_id: str
    duration_seconds: float
    language: str
    segments: list[TranscriptSegment]
    full_text: str


class Entity(BaseModel):
    name: str
    type: EntityType
    aliases: list[str] = []
    confidence: float


class Relation(BaseModel):
    source: str
    target: str
    type: RelationType
    evidence: str
    confidence: float


class Claim(BaseModel):
    statement: str
    type: ClaimType
    polarity: ClaimPolarity
    entities_involved: list[str]
    confidence: float
    temporal_scope: str


class Extraction(BaseModel):
    notebook_id: str
    entities: list[Entity]
    relations: list[Relation]
    claims: list[Claim]
    extraction_model: str
    prompt_version: str


def claim_hash(statement: str) -> str:
    """Return a 24-char hex SHA-256 digest of a normalised claim statement.

    Normalisation steps (order matters):
    1. NFKC unicode normalisation  — deﬁnition → definition
    2. Lowercase
    3. Strip leading/trailing whitespace
    4. Collapse internal whitespace runs to a single space
    5. Strip all non-word, non-space characters (punctuation)
    """
    normalized = unicodedata.normalize("NFKC", statement)
    normalized = normalized.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:24]
