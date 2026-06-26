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

# Smoke-run A: manufacturer/contractor ORG-source OPERATES (Lockheed→MK41, Raytheon→AN/SPY-6)
# is not gate-reliable; restrict to state/military operators only.
_OPERATES_SOURCE = frozenset({"COUNTRY", "MILITARY_UNIT"})

RELATION_ROLE_RULES: dict[str, RoleRule] = {
    # Smoke A: drop ORGANIZATION from source — ORG OPERATES platform is a recurring
    # manufacturer-as-operator error the type gate cannot catch.
    "OPERATES": RoleRule(_OPERATES_SOURCE, PLATFORM, False, "canonical"),
    "OPERATES_IN": RoleRule(ACTOR | _PERSON, PLACE, False, "canonical"),
    # Smoke A: drop ORGANIZATION from target — COMMANDS→ORG was fired for civilian/academic
    # leadership (Terman→Stanford, Perry→ISL); military command chain only.
    "COMMANDS": RoleRule(
        frozenset({"PERSON", "MILITARY_UNIT", "ORGANIZATION"}),
        frozenset({"MILITARY_UNIT"}), False, "canonical",
    ),
    "SANCTIONS": RoleRule(
        frozenset({"COUNTRY", "ORGANIZATION"}),
        frozenset({"COUNTRY", "ORGANIZATION", "PERSON"}), False, "canonical",
    ),
    # Smoke A: supplier↔recipient DIRECTION is not type-gate-catchable (LLNL↔IBM reversals);
    # demote to candidate_only like TARGETS.
    "SUPPLIES_TO": RoleRule(frozenset({"COUNTRY", "ORGANIZATION"}), ACTOR, False, "candidate_only"),
    "MEMBER_OF": RoleRule(
        ACTOR | _PERSON, frozenset({"ORGANIZATION", "TREATY"}), False, "canonical",
    ),
    "ALLIED_WITH": RoleRule(
        frozenset({"COUNTRY", "ORGANIZATION"}),
        frozenset({"COUNTRY", "ORGANIZATION"}), True, "canonical",
    ),
    # Smoke A: ally-vs-rival direction (Germany↔USA) is not type-gate-catchable;
    # demote to candidate_only like TARGETS.
    "COMPETES_WITH": RoleRule(
        frozenset({"COUNTRY", "ORGANIZATION"}),
        frozenset({"COUNTRY", "ORGANIZATION"}), True, "candidate_only",
    ),
    "NEGOTIATES_WITH": RoleRule(ACTOR | _PERSON, ACTOR | _PERSON, True, "canonical"),
    "TARGETS": RoleRule(ACTOR | PLATFORM, ACTOR | PLACE | PLATFORM, False, "candidate_only"),
}
