// WP-04 -- Entity (name, type) composite uniqueness constraint.
//
// Apply ORDER (operator-run against the live Neo4j; not run in CI):
//   1. migrations/neo4j_entity_type_canonicalization.cypher  (lowercase -> UPPERCASE)
//   2. migrations/neo4j_duplicate_merge.cypher               (merge eligible same-name groups)
//   3. The PREFLIGHT below -- it MUST return zero rows before step 4.
//   4. The CREATE CONSTRAINT below.
//
// Why the preflight: neo4j_duplicate_merge.cypher intentionally SKIPS the ~414
// multi-type semantic-conflict groups (e.g. "X" as both PERSON and
// ORGANIZATION). Such a group can still contain *exact* (name, type)
// duplicates (e.g. two "X"/PERSON nodes), which would make CREATE CONSTRAINT
// fail. Resolve any rows the preflight returns by hand, then create the
// constraint.
//
// Edition: Neo4j 5 Community supports composite node *uniqueness* constraints
// (only NODE KEY / EXISTENCE constraints are Enterprise-only). If a specific
// Community build rejects the composite form, the documented fallback is to
// write a derived single property e.entity_key = e.name + <SEP> + e.type, where
// <SEP> is a delimiter that cannot occur in a name (e.g. the ASCII unit
// separator, written '\u001f' in a Cypher string). An EMPTY separator would be
// non-injective -- ('NATOORG','ANIZATION') would collide with
// ('NATO','ORGANIZATION'). Write e.entity_key on BOTH write-paths (pipeline.py
// and nlm_ingest/write_templates.py) and put a plain single-property unique
// constraint on e.entity_key instead. Prefer the composite form; only fall
// back if the live instance refuses it.

// ---- PREFLIGHT (run first; must return zero rows) ----
// MATCH (e:Entity)
// WITH e.name AS name, e.type AS type, count(*) AS c
// WHERE c > 1
// RETURN name, type, c ORDER BY c DESC;

// ---- CONSTRAINT (run only after the preflight is clean) ----
// NOTE: Neo4j auto-creates a backing range index for this constraint, so the
// explicit entity_name_type range index (gdelt_raw/migrations/phase2_indexes.cypher)
// becomes redundant once this is applied and may be dropped by the operator.
CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS
  FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE;
