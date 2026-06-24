from nlm_ingest.relation_validator import (
    normalize_evidence, canonical_pair, relation_hash, provenance_key, candidate_id,
)

def test_normalize_evidence_collapses_whitespace():
    assert normalize_evidence("  a\n  b\t c ") == "a b c"

def test_symmetric_pair_is_order_independent():
    a, b = ("Russia", "COUNTRY"), ("Iran", "COUNTRY")
    assert canonical_pair(a, b, symmetric=True) == canonical_pair(b, a, symmetric=True)

def test_asymmetric_pair_keeps_direction():
    a, b = ("USA", "COUNTRY"), ("Patriot", "WEAPON_SYSTEM")
    assert canonical_pair(a, b, symmetric=False) == (a, b)
    assert canonical_pair(b, a, symmetric=False) != (a, b)

def test_symmetric_relation_hash_equal_both_directions():
    a, b = ("Russia", "COUNTRY"), ("Iran", "COUNTRY")
    (s1, t1) = canonical_pair(a, b, True)
    (s2, t2) = canonical_pair(b, a, True)
    h1 = relation_hash(s1, "ALLIED_WITH", t1, "they are allied")
    h2 = relation_hash(s2, "ALLIED_WITH", t2, "they are allied")
    assert h1 == h2

def test_candidate_id_is_deterministic():
    pk = provenance_key("nb1", "transcript", "transcript", "v4", "qwen", "abc")
    assert candidate_id(pk, "OPERATES_IN.target_type") == candidate_id(pk, "OPERATES_IN.target_type")

def test_candidate_id_golden_value():
    # Golden value pins the provenance_key composition + candidate_id hash format.
    # If this breaks, the provenance/identity contract changed — update deliberately.
    pk = provenance_key("nb1", "transcript", "transcript", "v4", "qwen", "abc")
    assert candidate_id(pk, "OPERATES_IN.target_type") == "372ca39ca72b2a353b430c9aa5ff2a528fa09777b23a1af5f25f227ee91b088f"

def test_symmetric_pair_uses_type_as_tiebreak():
    # Same name, different type: order-independence must still hold, proving the sort
    # compares the full (name, type) tuple, not name-only.
    a, b = ("Alpha", "COUNTRY"), ("Alpha", "ORGANIZATION")
    assert canonical_pair(a, b, symmetric=True) == canonical_pair(b, a, symmetric=True)
    s1, t1 = canonical_pair(a, b, True)
    s2, t2 = canonical_pair(b, a, True)
    assert relation_hash(s1, "ALLIED_WITH", t1, "ev") == relation_hash(s2, "ALLIED_WITH", t2, "ev")
