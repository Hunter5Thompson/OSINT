"""Declarative role matrix for relation validation (Relation v2).

Each RelationType maps to one RoleRule. The validator (relation_validator.py) uses
these to split extracted relations into canonical vs candidate. CONCEPT/POLICY appear
in no rule, so any relation touching them becomes a candidate.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleRule:
    source_types: frozenset[str]
    target_types: frozenset[str]
    symmetric: bool
    mode: str  # "canonical" | "candidate_only"


ACTOR = frozenset({"COUNTRY", "ORGANIZATION", "MILITARY_UNIT"})
PLACE = frozenset({"COUNTRY", "REGION", "LOCATION"})
PLATFORM = frozenset({"WEAPON_SYSTEM", "VESSEL", "AIRCRAFT", "SATELLITE"})
_PERSON = frozenset({"PERSON"})

RELATION_ROLE_RULES: dict[str, RoleRule] = {
    "OPERATES": RoleRule(ACTOR, PLATFORM, False, "canonical"),
    "OPERATES_IN": RoleRule(ACTOR | _PERSON, PLACE, False, "canonical"),
    "COMMANDS": RoleRule(
        frozenset({"PERSON", "MILITARY_UNIT", "ORGANIZATION"}),
        frozenset({"MILITARY_UNIT", "ORGANIZATION"}), False, "canonical",
    ),
    "SANCTIONS": RoleRule(
        frozenset({"COUNTRY", "ORGANIZATION"}),
        frozenset({"COUNTRY", "ORGANIZATION", "PERSON"}), False, "canonical",
    ),
    "SUPPLIES_TO": RoleRule(frozenset({"COUNTRY", "ORGANIZATION"}), ACTOR, False, "canonical"),
    "MEMBER_OF": RoleRule(
        ACTOR | _PERSON, frozenset({"ORGANIZATION", "TREATY"}), False, "canonical",
    ),
    "ALLIED_WITH": RoleRule(
        frozenset({"COUNTRY", "ORGANIZATION"}),
        frozenset({"COUNTRY", "ORGANIZATION"}), True, "canonical",
    ),
    "COMPETES_WITH": RoleRule(
        frozenset({"COUNTRY", "ORGANIZATION"}),
        frozenset({"COUNTRY", "ORGANIZATION"}), True, "canonical",
    ),
    "NEGOTIATES_WITH": RoleRule(ACTOR | _PERSON, ACTOR | _PERSON, True, "canonical"),
    "TARGETS": RoleRule(ACTOR | PLATFORM, ACTOR | PLACE | PLATFORM, False, "candidate_only"),
}
