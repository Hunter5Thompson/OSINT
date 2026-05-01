// Patch C — Phase 3: Selective duplicate merge
//
// Merges only same-name groups whose survivor is unambiguous per the rules in
// design spec §2.4 / runbook 6.2. Everything else (~414 multi-type semantic
// conflict groups) goes to manual review and is NOT touched here.
//
// Eligibility:
//   1. Single canonical type (e.g. ["ORGANIZATION"] × 3 for "nasa")
//   2. Geographic hierarchy: any group whose types are a subset of
//      {COUNTRY, REGION, LOCATION} → COUNTRY > REGION > LOCATION wins
//   3. Anything else → SKIP
//
// Survivor selection within eligible group is fully deterministic:
//   1. Highest relationship count
//   2. Earliest first_seen (missing first_seen sorts last)
//   3. Lowest elementId (stable tiebreaker)
//
// Pre-merge property treatment:
//   - aliases:    apoc.coll.toSet(survivor.aliases ∪ all losers' aliases)
//   - confidence: max(survivor.confidence, max(losers' confidences))
//   - all other properties: 'discard' policy keeps survivor's pre-merge values
//
// Relationships:
//   - mergeRels: true → parallel edges of same type/endpoints get deduplicated
//   - no relationships are created or deleted other than via APOC's transfer
//
// Properties of this query:
//   - parallel: false for deterministic ordering
//   - batchSize: 50 (each batch ≈ <500 nodes, well under tx commit limits)
//   - Idempotent: a second run finds no eligible groups (since each group
//     collapsed to 1 node)
//   - Rollback: restore from /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
//
// Out of scope:
//   - Multi-type semantic conflicts (PERSON/ORGANIZATION, ORGANIZATION/MILITARY_UNIT, etc.)
//   - Country lift-up (location → COUNTRY for known country names)

CALL apoc.periodic.iterate(

  "MATCH (e:Entity)
   WITH toLower(e.name) AS name_key,
        collect(e) AS nodes,
        collect(DISTINCT e.type) AS types
   WHERE size(nodes) > 1
     AND (
       size(types) = 1
       OR (any(t IN types WHERE t = 'COUNTRY')
           AND all(t IN types WHERE t IN ['COUNTRY','REGION','LOCATION']))
       OR (any(t IN types WHERE t = 'REGION')
           AND all(t IN types WHERE t IN ['REGION','LOCATION']))
     )
   RETURN nodes, types",

  "WITH nodes, types,
        CASE
          WHEN any(t IN types WHERE t = 'COUNTRY') THEN 'COUNTRY'
          WHEN any(t IN types WHERE t = 'REGION')  THEN 'REGION'
          ELSE head(types)
        END AS survivor_type

   // Partition into survivor candidates (matching survivor_type) and cross-type losers
   WITH [n IN nodes WHERE n.type = survivor_type] AS survivor_candidates,
        [n IN nodes WHERE n.type <> survivor_type] AS cross_type_losers

   // Build sortable maps over the survivor candidates
   WITH cross_type_losers,
        [n IN survivor_candidates | {
          n:   n,
          rc:  COUNT { (n)--() },
          fs:  coalesce(n.first_seen, datetime('9999-12-31T23:59:59Z')),
          eid: elementId(n)
        }] AS ranked_raw

   // Deterministic ordering: rel count DESC, first_seen ASC, elementId ASC.
   // NOTE: APOC 5.26.23 sortMulti prefix semantics are inverted vs. its public
   // docs. Empirically, no-prefix = DESCENDING and ^-prefix = ASCENDING.
   // Verified by smoke test on 2026-04-30. Do NOT change to match the public
   // docs without re-verifying against the installed APOC version.
   WITH cross_type_losers,
        apoc.coll.sortMulti(ranked_raw, ['rc','^fs','^eid']) AS ranked

   WITH head(ranked).n AS survivor,
        [r IN tail(ranked) | r.n] + cross_type_losers AS losers

   WHERE survivor IS NOT NULL AND size(losers) > 0

   // Pre-merge: union aliases, max(confidence)
   WITH survivor, losers,
        apoc.coll.toSet(
          coalesce(survivor.aliases, []) +
          reduce(acc = [], n IN losers | acc + coalesce(n.aliases, []))
        ) AS merged_aliases,
        reduce(maxc = coalesce(survivor.confidence, 0.0),
               n IN losers |
               CASE WHEN coalesce(n.confidence, 0.0) > maxc
                    THEN coalesce(n.confidence, 0.0)
                    ELSE maxc END) AS max_conf
   SET survivor.aliases = merged_aliases,
       survivor.confidence = max_conf

   WITH survivor, losers
   CALL apoc.refactor.mergeNodes(
     [survivor] + losers,
     {properties: 'discard', mergeRels: true}
   ) YIELD node
   RETURN count(node) AS merged_groups",

  {batchSize: 50, parallel: false}
)
YIELD batches, total, errorMessages
RETURN batches, total, errorMessages;
