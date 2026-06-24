from typing import get_args
from nlm_ingest.relation_rules import RELATION_ROLE_RULES, ACTOR, PLACE, PLATFORM
from nlm_ingest.schemas import RelationType, CANONICAL_ENTITY_TYPES

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

def test_operates_is_actor_to_platform_canonical():
    r = RELATION_ROLE_RULES["OPERATES"]
    assert r.source_types == ACTOR and r.target_types == PLATFORM
    assert r.mode == "canonical" and r.symmetric is False

def test_concept_and_policy_in_no_rule():
    for rule in RELATION_ROLE_RULES.values():
        assert "CONCEPT" not in rule.source_types and "CONCEPT" not in rule.target_types
        assert "POLICY" not in rule.source_types and "POLICY" not in rule.target_types
