// Patch C — Phase 1: Type canonicalization
//
// Purpose: rewrite all legacy lowercase :Entity.type values to their canonical
// uppercase equivalents so that the write contract from
// services/data-ingestion/nlm_ingest/schemas.py applies consistently to the
// historical graph as well as new writes.
//
// Properties of this query:
//   - Read uses: legacy lowercase types only.
//   - Write uses: SET on a single property (e.type). No CREATE, MERGE, DELETE.
//   - No relationships are created, modified, or deleted.
//   - No new nodes are created. Total node count must be invariant.
//   - Idempotent: a second run finds zero rows in the read subquery (because
//     the SET clause already moved every legacy value to its canonical form),
//     so it is a no-op.
//   - parallel: false to keep the rewrite ordering deterministic. The graph
//     does not need parallelism for ~9 600 nodes; the bottleneck is per-batch
//     transaction commit, not CPU.
//
// Reversible:
//   Restore from /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
//   via the offline-volume load procedure in section 10 of the runbook.
//
// Mapping (matches LEGACY_ENTITY_TYPE_MAP in
// services/data-ingestion/nlm_ingest/schemas.py — 8 entries, no more, no less):
//
//   person          -> PERSON
//   organization    -> ORGANIZATION
//   location        -> LOCATION
//   military_unit   -> MILITARY_UNIT
//   weapon_system   -> WEAPON_SYSTEM
//   vessel          -> VESSEL
//   aircraft        -> AIRCRAFT
//   satellite       -> SATELLITE

CALL apoc.periodic.iterate(
  "MATCH (e:Entity)
   WHERE e.type IN ['person','organization','location','military_unit',
                    'weapon_system','vessel','aircraft','satellite']
   RETURN e",
  "WITH e,
        CASE e.type
          WHEN 'person'        THEN 'PERSON'
          WHEN 'organization'  THEN 'ORGANIZATION'
          WHEN 'location'      THEN 'LOCATION'
          WHEN 'military_unit' THEN 'MILITARY_UNIT'
          WHEN 'weapon_system' THEN 'WEAPON_SYSTEM'
          WHEN 'vessel'        THEN 'VESSEL'
          WHEN 'aircraft'      THEN 'AIRCRAFT'
          WHEN 'satellite'     THEN 'SATELLITE'
        END AS canonical
   SET e.type = canonical",
  {batchSize: 500, parallel: false}
)
YIELD batches, total, errorMessages
RETURN batches, total, errorMessages;
