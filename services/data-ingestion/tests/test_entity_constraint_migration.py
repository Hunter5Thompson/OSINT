"""Content locks for the WP-04 Entity index/constraint migrations.

These are operator-applied .cypher files (not run in CI), so we lock their
content to prevent the dead-index regression (an index on a property nothing
writes) and to pin the composite-unique key shape."""

from __future__ import annotations

from pathlib import Path

DI = Path(__file__).resolve().parents[1]


def test_entity_name_type_index_references_a_written_property():
    cypher = (DI / "gdelt_raw" / "migrations" / "phase2_indexes.cypher").read_text()
    # The index must key on e.name (written by both write-paths), not the dead
    # e.normalized_name (WP-04).
    assert "entity_name_type" in cypher
    assert "(e.name, e.type)" in cypher
    assert "normalized_name" not in cypher


def test_entity_uniqueness_constraint_is_composite_name_type():
    cypher = (DI / "migrations" / "neo4j_entity_name_type_unique.cypher").read_text()
    assert "FOR (e:Entity)" in cypher
    assert "REQUIRE (e.name, e.type) IS UNIQUE" in cypher
    # Must be IF NOT EXISTS (idempotent) and must NOT be a node-key constraint
    # (Enterprise-only on this Community deployment).
    assert "IF NOT EXISTS" in cypher
    assert "IS NODE KEY" not in cypher
    # The preflight (the operationally critical step — running the constraint
    # without it could fail against a live DB with exact-dup nodes) must remain.
    assert "PREFLIGHT" in cypher
    assert "count(*)" in cypher
