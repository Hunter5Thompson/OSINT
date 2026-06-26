from typing import get_args

from nlm_ingest.relation_rules import _OPERATES_SOURCE, PLATFORM, RELATION_ROLE_RULES
from nlm_ingest.schemas import CANONICAL_ENTITY_TYPES, RelationType


def test_every_relation_type_has_exactly_one_rule():
    assert set(RELATION_ROLE_RULES) == set(get_args(RelationType))

def test_rules_reference_only_known_entity_types():
    for name, rule in RELATION_ROLE_RULES.items():
        assert rule.source_types <= CANONICAL_ENTITY_TYPES, name
        assert rule.target_types <= CANONICAL_ENTITY_TYPES, name

def test_targets_is_candidate_only():
    assert RELATION_ROLE_RULES["TARGETS"].mode == "candidate_only"

def test_allied_with_is_country_org_only_and_symmetric():
    r = RELATION_ROLE_RULES["ALLIED_WITH"]
    assert r.source_types == frozenset({"COUNTRY", "ORGANIZATION"})
    assert r.target_types == frozenset({"COUNTRY", "ORGANIZATION"})
    assert r.symmetric is True

# Smoke A: OPERATES source narrowed from ACTOR to {COUNTRY, MILITARY_UNIT} —
# ORG-source OPERATES (manufacturer-as-operator) is not gate-reliable.
def test_operates_source_is_country_and_military_unit_only():
    r = RELATION_ROLE_RULES["OPERATES"]
    assert r.source_types == _OPERATES_SOURCE
    assert r.source_types == frozenset({"COUNTRY", "MILITARY_UNIT"})
    assert "ORGANIZATION" not in r.source_types
    assert r.target_types == PLATFORM
    assert r.mode == "canonical" and r.symmetric is False

# Smoke A: COMMANDS target narrowed to MILITARY_UNIT only — civilian/academic leadership
# (Terman→Stanford) was erroneously matching the old {MILITARY_UNIT, ORGANIZATION} target.
def test_commands_target_is_military_unit_only():
    r = RELATION_ROLE_RULES["COMMANDS"]
    assert r.target_types == frozenset({"MILITARY_UNIT"})
    assert "ORGANIZATION" not in r.target_types

# Smoke A: SUPPLIES_TO demoted — supplier↔recipient direction not gate-catchable.
def test_supplies_to_is_candidate_only():
    assert RELATION_ROLE_RULES["SUPPLIES_TO"].mode == "candidate_only"

# Smoke A: COMPETES_WITH demoted — ally-vs-rival not type-gate-catchable.
def test_competes_with_is_candidate_only():
    assert RELATION_ROLE_RULES["COMPETES_WITH"].mode == "candidate_only"

def test_concept_and_policy_in_no_rule():
    for rule in RELATION_ROLE_RULES.values():
        assert "CONCEPT" not in rule.source_types and "CONCEPT" not in rule.target_types
        assert "POLICY" not in rule.source_types and "POLICY" not in rule.target_types
