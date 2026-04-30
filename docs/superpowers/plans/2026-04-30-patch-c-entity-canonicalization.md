# Patch C — Entity-Type Canonicalization and Neo4j Duplicate Migration

> **For agentic workers:** This plan is migration-gated. Every phase ends with an
> explicit STOP-GATE. Do **not** proceed past a stop-gate without operator
> confirmation. No phase except Phase 0 may begin if any prior stop-gate is open.

**Status:** Draft — awaiting freeze-window approval. **No write actions authorized yet.**

**Goal:** Canonicalize all `:Entity.type` values to the uppercase NLM vocabulary,
merge or report duplicate entities, and switch write paths to emit canonical
types — without losing relationship topology or fragmenting analytic queries.

**Architecture:** Deterministic write path stays intact. APOC handles the bulk
type-rewrite and the small auto-mergeable subset. Manual-review report covers the
~99% of multi-type groups that are semantically ambiguous and unsafe to auto-merge.

**Parent Plan:** `docs/superpowers/plans/2026-04-30-codebook-graph-drift.md` (§Patch C)

**Spec:** `docs/superpowers/specs/2026-04-30-codebook-graph-drift-design.md`
(§2.3 — entity type canonical, §2.4 — duplicate migration, §4.3 — entity type contract)

**Preflight Snapshot:** Run on `osint-neo4j-1` (Neo4j 5.26.23 community), 2026-04-30.

---

## Preflight Findings (Read-Only Baseline)

These numbers establish the migration scope. They will change once Phase 1 lands;
treat them as a baseline snapshot, not a moving target.

**Topology:**

- 8 813 `:Entity` nodes
- 8 293 distinct lowercased names
- 15 distinct `e.type` values currently in use (canonical vocabulary is 13)

**Type distribution:**

| Type            | Count | Relationships | Case |
|-----------------|------:|--------------:|------|
| `person`        | 2 973 |         4 595 | legacy lowercase |
| `organization`  | 2 565 |        23 659 | legacy lowercase |
| `location`      | 1 939 |        16 431 | legacy lowercase |
| `military_unit` |   523 |           959 | legacy lowercase |
| `weapon_system` |   464 |           693 | legacy lowercase |
| `vessel`        |   158 |           181 | legacy lowercase |
| `aircraft`      |   150 |           202 | legacy lowercase |
| `satellite`     |    12 |            34 | legacy lowercase |
| `COUNTRY`       |     7 |            23 | canonical |
| `PERSON`        |     6 |             5 | canonical |
| `MILITARY_UNIT` |     6 |             6 | canonical |
| `AIRCRAFT`      |     5 |             2 | canonical |
| `ORGANIZATION`  |     2 |             1 | canonical |
| `WEAPON_SYSTEM` |     2 |             2 | canonical |
| `CONCEPT`       |     2 |             1 | canonical |

**~99.7 % of entity nodes use legacy lowercase types.** Phase 1 is therefore mostly
a bulk rewrite, not a merge job.

**Duplicate baseline:**

| Metric                                                   | Value |
|----------------------------------------------------------|------:|
| Multi-type groups (same name, ≥2 distinct types)         |   355 |
| Nodes inside multi-type groups                           |   766 |
| Redundant nodes after ideal merge                        |   411 |
| Same-name groups (any type, ≥2 nodes)                    |   461 |
| Redundant nodes after ideal full merge                   |   520 |

**Conflict-category breakdown of the 355 multi-type groups:**

| Category | Groups | Auto-merge candidate? |
|---|---:|---|
| `geo-vs-org-or-person` (e.g. `ukrainian`, `russian`) | 179 | Mostly NO — adjectival forms; subset YES via COUNTRY > REGION > LOCATION |
| `org-vs-milunit` (e.g. `marines`, `police`)          |  80 | NO — semantic ambiguity |
| `person-vs-org-only`                                  |  39 | NO — explicit STOP-rule per spec §2.4 |
| `multi-class-mixed`                                   |  34 | NO — manual review |
| `other`                                               |  20 | Some — vehicle/weapon-system canonicalization |
| `case-only-PERSON` (lowercase + uppercase same class) |   2 | YES — pure case canonicalization |
| `geo-canonicalize-lower-to-upper`                     |   1 | YES — `location` → `LOCATION/COUNTRY/REGION` |

**Auto-mergeable groups (strict survivor rules): ~3–25.** Everything else goes to
manual review.

**APOC availability** (Neo4j 5.26.23 community):

- 190 APOC procedures available
- All four critical procedures present: `apoc.periodic.iterate`,
  `apoc.refactor.mergeNodes`, `apoc.refactor.from`, `apoc.refactor.to`
- **Decision: APOC-based migration.** Python-driver fallback is not needed.

---

## File Structure

Migration artifacts:

- This document
- `services/data-ingestion/migrations/neo4j_entity_type_canonicalization.cypher`
  — to be created in Phase 1 with the APOC bulk rewrite query
- `services/data-ingestion/migrations/neo4j_duplicate_merge.cypher`
  — to be created in Phase 3 with the auto-merge query
- `/home/deadpool-ultra/odin-reports/manual_review_groups_patch_c_2026-04-30.csv`
  — generated in Phase 4 from a Cypher report query; not committed by default

Code-side write-path canonicalization (parent-plan Task C1/C2/C5, executed in
Phase 5 of this plan):

- Modify: `services/data-ingestion/nlm_ingest/schemas.py`
  (add `LOCATION` to `EntityType` literal, add `normalize_entity_type` helper)
- Modify: `services/data-ingestion/pipeline.py`
  (apply normalizer before Neo4j entity-write parameters are built)
- Modify: `services/intelligence/codebook/extractor.py`
  (emit canonical uppercase or normalize before graph write)
- Modify: `services/intelligence/graph/write_templates.py` if any entity-write
  template constrains the type to lowercase
- Modify: `services/data-ingestion/nlm_ingest/prompts/extraction_v*.txt`
  (version a new prompt; do not overwrite the old prompt)
- Modify: tests for canonical mapping in both services

Operational:

- New file: `docs/superpowers/runbooks/2026-04-30-patch-c-runbook.md`
  (operator runbook for the freeze window, written before Phase 0 begins)

---

## Pre-Conditions (Before Phase 0)

- [ ] Patch A merged (commit `7ebfb1d` on main) — confirmed
- [ ] Patch B merged (commit `d6d9cd0` on main) — confirmed
- [ ] No open Patch-C-touching PR on any branch
- [ ] Operator runbook written and reviewed
- [ ] Maintenance window scheduled and announced (≥30 min, ≤2 h)
- [ ] Neo4j backup target on the host has ≥10 GB free
- [ ] Neo4j named Docker volume resolved and recorded:
  `docker volume ls --format '{{.Name}}' | grep '_neo4j-data$'`
- [ ] Offline dump and restore commands have been reviewed against the current
  `docker-compose.yml` volume layout. The plan must not rely on `docker exec`
  after stopping the Neo4j process inside its container.
- [ ] APOC procedures still present (re-run preflight check at the top of the
  window in case of container drift)
- [ ] APOC merge property strategy smoke-tested on disposable `:PatchCTest`
  nodes and cleaned up again. Required because Phase 3 relies on
  `apoc.refactor.mergeNodes` property conflict handling.
- [ ] Operator has read this plan end-to-end and signed off the rollback
  procedure

**STOP-GATE 0:** All boxes ticked AND operator confirms "go for Phase 0".

---

## Phase 0 — Snapshot and Ingestion Freeze

**Risk:** Low. Read + filesystem write + container stop. Reversible.

**Scope:** Stop ingestion, capture full Neo4j snapshot, verify snapshot integrity.

### Task 0.1 — Pause every Neo4j writer

- [ ] Record currently running Compose services so resume restores the same profile
  mix instead of blindly starting extra services:
  ```bash
  docker compose ps --services --filter status=running \
      > /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt
  cat /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt
  ```
- [ ] Stop every service that can write to Neo4j directly or indirectly:
  ```bash
  docker compose stop \
      data-ingestion \
      data-ingestion-spark \
      backend \
      intelligence \
      vision-enrichment
  ```
  It is OK if some profile services are not running.
- [ ] Confirm stopped state:
  ```bash
  docker compose ps data-ingestion data-ingestion-spark backend intelligence vision-enrichment
  ```
- [ ] Pause any cron/`scheduler.py` jobs at the host level if they exist
  outside the compose file
- [ ] Confirm no writer containers are still running:
  ```bash
  docker ps --format '{{.Names}}' \
    | grep -E 'data-ingestion|backend|intelligence|vision-enrichment' \
    && echo "STOP: writer still running" || echo "writers stopped"
  ```

### Task 0.2 — Capture snapshot

- [ ] Resolve the Neo4j Docker volume name and export it for the shell:
  ```bash
  export NEO4J_VOLUME="$(docker volume ls --format '{{.Name}}' | grep '_neo4j-data$' | head -n1)"
  test -n "$NEO4J_VOLUME"
  ```
- [ ] Create host backup directory:
  ```bash
  mkdir -p /home/deadpool-ultra/odin-backups
  ```
- [ ] Stop the Neo4j container through Compose so no process has the store open:
  ```bash
  docker compose stop neo4j
  ```
- [ ] Dump database:
  ```bash
  docker run --rm \
      -v "$NEO4J_VOLUME":/data \
      -v /home/deadpool-ultra/odin-backups:/backups \
      neo4j:5-community \
      neo4j-admin database dump neo4j \
        --to-path=/backups
  ```
- [ ] Rename the dump with a timestamp:
  ```bash
  mv /home/deadpool-ultra/odin-backups/neo4j.dump \
     /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
  ```
- [ ] Record the dump file size and SHA-256 for integrity verification:
  ```bash
  ls -la /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
  sha256sum /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump \
      | tee /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump.sha256
  ```
- [ ] Restart Neo4j through Compose and wait for health:
  ```bash
  docker compose up -d neo4j
  docker compose ps neo4j
  curl -sf http://localhost:7474 >/dev/null
  docker exec osint-neo4j-1 cypher-shell \
      -u "${NEO4J_USER:-neo4j}" \
      -p "${NEO4J_PASSWORD:-odin1234}" \
      "RETURN 1 AS ok"
  ```

### Task 0.3 — Verify snapshot integrity

- [ ] Confirm dump file is non-empty and SHA-256 was recorded
- [ ] Re-run the topology overview query and compare to the preflight numbers:
  ```cypher
  MATCH (e:Entity)
  RETURN count(e) AS total_entities,
         count(DISTINCT toLower(e.name)) AS distinct_names,
         count(DISTINCT e.type) AS distinct_types;
  ```
  Expected (preflight 2026-04-30): `8813, 8293, 15`. If these have drifted,
  STOP and re-run preflight before proceeding.

**STOP-GATE 1:** Snapshot exists at known path, SHA recorded, ingestion
confirmed paused, topology matches preflight. Operator says "go for Phase 1".

---

## Phase 1 — Type Canonicalization via APOC

**Risk:** Low–medium. Bulk write to ~8 800 nodes, but pure property update
with no relationship changes. Fully recoverable from Phase 0 dump.

**Scope:** Rewrite all legacy lowercase `e.type` values to canonical uppercase
in a single APOC batch.

### Task 1.1 — Pre-write count by type

- [ ] Snapshot the type distribution into a file for comparison after Phase 1:
  ```cypher
  MATCH (e:Entity)
  RETURN e.type AS type, count(*) AS count
  ORDER BY count DESC;
  ```

### Task 1.2 — Decide LOCATION strategy

The `location` lowercase type currently has 1 939 nodes. Per spec §2.3, the
canonical set adds `LOCATION` as a catch-all because main ingestion cannot
reliably reclassify each into `COUNTRY` or `REGION`.

- [ ] Confirm in this plan whether all `location` → `LOCATION`, or whether a
  pre-pass attempts to lift well-known country names to `COUNTRY`. **Default
  for first pass: `location` → `LOCATION`. Country lift-up is out of scope
  for Patch C and can be done later as a data-quality enrichment job.**

### Task 1.3 — Write the canonicalization Cypher

Create `services/data-ingestion/migrations/neo4j_entity_type_canonicalization.cypher`
with this content:

```cypher
// Patch C — Phase 1: Type canonicalization
// Idempotent: re-running is a no-op once all values are uppercase.
// Reversible: restore from /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-*.dump
//
// Mapping:
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
```

- [ ] Commit this Cypher file (no execution yet) so the exact query is
  reviewable before run-time.

### Task 1.4 — Dry-run estimate

- [ ] Run the **estimate-only** counterpart to predict batch count:
  ```cypher
  MATCH (e:Entity)
  WHERE e.type IN ['person','organization','location','military_unit',
                   'weapon_system','vessel','aircraft','satellite']
  RETURN count(*) AS rewrite_target;
  ```
  Expected: ~8 784 (sum of lowercase legacy counts). Document the actual
  number in the operator runbook.

**STOP-GATE 2:** Cypher file committed, dry-run count documented, operator
confirms "go for Phase 1 apply".

### Task 1.5 — Execute canonicalization

- [ ] Run the canonicalization Cypher via the Neo4j HTTP transactional API
  (same auth as preflight).
- [ ] Capture the response: `batches`, `total`, `errorMessages`. Expected
  `errorMessages = []`.
- [ ] If any error appears, **stop and roll back** via Phase 0 dump. Do not
  attempt to fix forward.

### Task 1.6 — Post-write verification

- [ ] Re-run type distribution query. Expected: only canonical uppercase
  types remain; no lowercase legacy types.
- [ ] Run negative check:
  ```cypher
  MATCH (e:Entity)
  WHERE e.type =~ '[a-z].*'
  RETURN count(*) AS remaining_lowercase;
  ```
  Expected: `0`. If non-zero, **stop and roll back**.
- [ ] Confirm total node count unchanged: must still be `8 813`. Drift here
  would mean accidental node creation/deletion — **stop and roll back**.

**STOP-GATE 3:** Canonicalization successful, zero lowercase remaining, node
count unchanged. Operator confirms "go for Phase 2".

---

## Phase 2 — Read-Only Re-Preflight

**Risk:** None. Pure read.

**Scope:** Re-run the duplicate-baseline queries to see how many multi-type
groups remain after canonicalization. Many groups should collapse because
case-only and `location/LOCATION`-style conflicts are gone.

### Task 2.1 — Re-run baseline queries

- [ ] Multi-type duplicate count (post-canonicalization):
  ```cypher
  MATCH (e:Entity)
  WITH toLower(e.name) AS name_key,
       collect(e) AS nodes,
       collect(DISTINCT e.type) AS types
  WHERE size(nodes) > 1 AND size(types) > 1
  RETURN count(*) AS multi_type_groups,
         sum(size(nodes)) AS total_nodes_in_groups,
         sum(size(nodes)) - count(*) AS redundant_nodes;
  ```
  Pre-Phase-1 baseline: `355 / 766 / 411`. Expected post-Phase-1: lower —
  case-only and `location`/`LOCATION` collisions are gone.

- [ ] Same-name (any-type) duplicates:
  ```cypher
  MATCH (e:Entity)
  WITH toLower(e.name) AS name_key, collect(e) AS nodes
  WHERE size(nodes) > 1
  RETURN count(*) AS any_dup_groups,
         sum(size(nodes)) AS any_total_nodes;
  ```
  Pre-Phase-1 baseline: `461 / 981`.

- [ ] Re-categorize the remaining multi-type groups using the same
  conflict-category Cypher from preflight (see this plan's Preflight section
  query 3). Document the new distribution.

### Task 2.2 — Decide what is auto-mergeable

The strict survivor rules from spec §2.4:

1. Single canonical uppercase type → auto-merge candidate
2. `COUNTRY` > `REGION` > `LOCATION` for geographic ambiguity → auto-merge
3. `PERSON` vs `ORGANIZATION` → manual review, **do not** auto-merge
4. Within selected type, highest relationship cardinality wins; tie-break by
   earliest `first_seen`, then lowest internal id

- [ ] Generate the auto-mergeable candidate list with this query, save to
  `migrations/auto_merge_candidates.csv` for operator review:

  ```cypher
  MATCH (e:Entity)
  WITH toLower(e.name) AS name_key,
       collect(e) AS nodes,
       collect(DISTINCT e.type) AS types
  WHERE size(nodes) > 1
  WITH name_key, nodes, types,
       CASE
         WHEN size(types) = 1
           THEN head(types)
         WHEN any(t IN types WHERE t = 'COUNTRY')
              AND all(t IN types WHERE t IN ['COUNTRY','REGION','LOCATION'])
           THEN 'COUNTRY'
         WHEN any(t IN types WHERE t = 'REGION')
              AND all(t IN types WHERE t IN ['REGION','LOCATION'])
           THEN 'REGION'
         ELSE NULL
       END AS survivor_type
  WHERE survivor_type IS NOT NULL
  RETURN name_key, types, survivor_type, size(nodes) AS node_count
  ORDER BY node_count DESC;
  ```

**STOP-GATE 4:** Re-preflight numbers documented, auto-mergeable candidate
list reviewed by operator, manual-review-only list reviewed. Operator confirms
"go for Phase 3".

---

## Phase 3 — Selective Auto-Merge

**Risk:** Medium. Relationship transfer + node deletion. Recoverable only via
Phase 0 dump (Phase 3 does not produce its own snapshot — see rollback).

**Scope:** Merge only groups that the survivor rules can resolve
deterministically. Everything else stays for manual review.

### Task 3.1 — Capture pre-merge baseline

- [ ] Document the exact list of `name_key` values about to be merged. Persist
  to `migrations/auto_merge_applied.csv`. The list **must not** be regenerated
  on the fly during Phase 3 — fix the input set.
- [ ] Count of groups: should match Phase 2 Task 2.2 list. If counts differ,
  **stop and re-investigate**.

### Task 3.2 — Write the merge Cypher

Create `services/data-ingestion/migrations/neo4j_duplicate_merge.cypher`:

```cypher
// Patch C — Phase 3: Selective duplicate merge.
// Only merges groups where survivor_type is unambiguous per spec §2.4 rules 1-2.
// Idempotent: re-running on already-merged groups is a no-op
//             (only one node remains, MATCH yields nothing to merge).
// Reversible: restore from /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-*.dump
//             (the merge does not produce a separate snapshot).

CALL apoc.periodic.iterate(
  "MATCH (e:Entity)
   WITH toLower(e.name) AS name_key, e, count { (e)--() } AS rel_count
   ORDER BY name_key, rel_count DESC, coalesce(toString(e.first_seen), '9999-12-31T00:00:00Z') ASC, elementId(e) ASC
   WITH name_key,
        collect(e) AS nodes,
        collect(DISTINCT e.type) AS types
   WHERE size(nodes) > 1
   WITH name_key, nodes, types,
        CASE
          WHEN size(types) = 1 THEN head(types)
          WHEN any(t IN types WHERE t = 'COUNTRY')
               AND all(t IN types WHERE t IN ['COUNTRY','REGION','LOCATION'])
            THEN 'COUNTRY'
          WHEN any(t IN types WHERE t = 'REGION')
               AND all(t IN types WHERE t IN ['REGION','LOCATION'])
            THEN 'REGION'
          ELSE NULL
        END AS survivor_type
   WHERE survivor_type IS NOT NULL
   RETURN name_key, nodes, types, survivor_type",
  "WITH name_key, nodes, types, survivor_type,
        [n IN nodes WHERE n.type = survivor_type] AS survivor_candidates,
        [n IN nodes WHERE n.type <> survivor_type] AS type_losers
   WITH name_key, types, survivor_type,
        head(survivor_candidates) AS survivor,
        tail(survivor_candidates) + type_losers AS losers
   WHERE survivor IS NOT NULL AND size(losers) > 0
   SET survivor.aliases = apoc.coll.toSet(
         coalesce(survivor.aliases, []) +
         reduce(acc = [], n IN losers | acc + coalesce(n.aliases, []))
       ),
       survivor.confidence = reduce(
         c = coalesce(survivor.confidence, 0.0),
         n IN losers |
           CASE
             WHEN coalesce(n.confidence, 0.0) > c THEN coalesce(n.confidence, 0.0)
             ELSE c
           END
       )
   CALL apoc.refactor.mergeNodes(
     [survivor] + losers,
     {
       properties: {
         name: 'discard',
         type: 'discard',
         aliases: 'discard',
         confidence: 'discard',
         first_seen: 'discard',
         last_seen: 'discard',
         '.*': 'discard'
       },
       mergeRels: true
     }
   ) YIELD node
   RETURN count(node) AS merged",
  {batchSize: 50, parallel: false}
)
YIELD batches, total, errorMessages
RETURN batches, total, errorMessages;
```

Notes on `apoc.refactor.mergeNodes` config:

- The input query orders nodes deterministically by relationship cardinality,
  then `first_seen`, then `elementId`. The first survivor candidate is therefore
  the spec §2.4 survivor, not arbitrary `head(collect(...))` order.
- Same-name/same-type groups are included (`size(nodes) > 1`), not only
  multi-type groups. This catches case-collapsed duplicates after Phase 1.
- Survivor `aliases` and `confidence` are preserved explicitly before
  `mergeNodes`; then `properties: {... discard ...}` prevents APOC from turning
  scalar survivor properties into arrays.
- `mergeRels: true` deduplicates parallel relationships of the same type
  between the same endpoints. Properties on duplicate edges merge per
  APOC defaults.

- [ ] Commit this Cypher file (no execution yet).

**STOP-GATE 5:** Merge Cypher reviewed and committed. Operator confirms "go
for Phase 3 apply".

### Task 3.3 — Execute merge

- [ ] Run the merge Cypher.
- [ ] Capture response: `batches`, `total`, `errorMessages`. Expected
  `errorMessages = []`.
- [ ] If any error appears, **stop and roll back via Phase 0 dump**.

### Task 3.4 — Post-merge verification

- [ ] Re-run the multi-type duplicate count from Phase 2 Task 2.1. The number
  must drop by the count of groups merged in Task 3.2 (and not more).
- [ ] Confirm relationship count unchanged or only reduced by deduplicated
  parallel edges. Run:
  ```cypher
  MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS count
  ORDER BY count DESC;
  ```
  Compare to a pre-Phase-3 snapshot of the same query (capture in Task 3.1).
- [ ] Confirm no orphan endpoints exist for relations that referenced merged
  losers:
  ```cypher
  MATCH (n) WHERE NOT (n)--() RETURN labels(n) AS l, count(*) AS orphans;
  ```
  Compare against a pre-merge baseline.

**STOP-GATE 6:** Merge applied successfully, expected duplicate-count drop
observed, no relationship loss. Operator confirms "go for Phase 4".

---

## Phase 4 — Manual-Review Report

**Risk:** None. Pure read + filesystem write of a CSV/JSON report.

**Scope:** Persist the unmerged multi-type groups to a structured report so
analysts can decide on each one outside the migration window.

### Task 4.1 — Generate report

- [ ] Run the report query and stream to a CSV at
  `/home/deadpool-ultra/odin-reports/manual_review_groups_patch_c_2026-04-30.csv`.
  Do not commit live graph data into `services/.../migrations` by default.

  ```cypher
  MATCH (e:Entity)
  WITH toLower(e.name) AS name_key,
       collect(e) AS nodes,
       collect(DISTINCT e.type) AS types
  WHERE size(nodes) > 1 AND size(types) > 1
  RETURN name_key,
         types,
         size(nodes) AS node_count,
         [n IN nodes | {
           name: n.name,
           type: n.type,
           rel_count: COUNT { (n)--() }
         }] AS detail
  ORDER BY node_count DESC, name_key;
  ```

- [ ] Each row's `detail` array shows per-node relationship cardinality so the
  reviewer can apply spec §2.4 rule 4 ("highest relationship cardinality wins")
  manually.

### Task 4.2 — Categorize the report rows

- [ ] Add a `suggested_action` column heuristically:

  | Pattern | Suggested action |
  |---|---|
  | Adjectival form (e.g. ends in `-ian`, `-ese`, `-i`) with mixed person/location/military types | Likely sprach-drift, NOT a real entity. Suggest deletion or re-link to country node. |
  | Same name, both `MILITARY_UNIT` and `ORGANIZATION` | Often legitimate (e.g. `marines`). Suggest manual decision per case. |
  | `PERSON` and `ORGANIZATION` | Hard semantic conflict. Manual decision required. |
  | Single-token generic noun (`bandits`, `terrorists`, `police`) | Often not a real entity. Suggest re-tagging as `CONCEPT` or deletion. |

- [ ] Hand-off note in the report header explaining how to use it: the report
  is read-only documentation; merges or deletions for manual-review groups
  must go through a separate ticket and a separate maintenance window.

**STOP-GATE 7:** Report generated, categorized, and stored at a known path.
Operator decides separately whether a sanitized summary belongs in `docs/reports/`.
Operator confirms "go for Phase 5".

---

## Phase 5 — Code-Side Write-Path Canonicalization

**Risk:** Low. Code change only. Tests already exist for canonical types in
patches earlier in this branch. Ingestion remains frozen during this phase.

**Scope:** Make sure no future ingestion run reintroduces lowercase types.
This phase implements parent-plan tasks C1, C2 and C5 with the live numbers
from Phase 4.

### Task 5.1 — Add canonical normalizer

- [ ] In `services/data-ingestion/nlm_ingest/schemas.py`:
  - Add `LOCATION` to the `EntityType` literal
  - Add a `normalize_entity_type(value: str) -> EntityType` function that maps
    the eight legacy lowercase forms to the eight canonical uppercase forms
    and is idempotent on already-canonical input
- [ ] Unit-test idempotence and legacy mapping in `tests/test_nlm_schemas.py`.

### Task 5.2 — Apply normalizer on the main pipeline write path

- [ ] In `services/data-ingestion/pipeline.py` `_write_to_neo4j`, normalize
  `entity["type"]` before binding it as the `$type` parameter.
- [ ] Add a test (in `tests/test_pipeline.py`) that asserts the Cypher
  parameters for an entity emitted by the LLM with `type: "organization"`
  carry `type: "ORGANIZATION"`.

### Task 5.3 — Apply normalizer on the intelligence extractor

- [ ] In `services/intelligence/codebook/extractor.py` (or wherever the entity
  is mapped before being passed to `services/intelligence/graph/write_templates.py`),
  normalize before graph write. If `nlm_ingest.schemas` cannot be imported
  across Docker build contexts (per parent plan task C1 escape hatch), copy
  the canonical set + mapping locally and add a drift-guard test comparing
  the local mirror to the source.

### Task 5.4 — Version a new NLM extraction prompt

- [ ] Copy `services/data-ingestion/nlm_ingest/prompts/extraction_v1.txt` (or
  current version) to `extraction_v2.txt`. Edit `v2` to include `LOCATION` in
  the entity-type list. Do not delete `v1`. Update the default prompt
  selection in code to point at `v2`.

### Task 5.5 — Run all test suites

- [ ] `cd services/data-ingestion && uv run pytest -q`
- [ ] `cd services/intelligence && uv run pytest -q`
- [ ] `cd services/frontend && npm run test`

All must pass. Patch B's drift guards must continue to pass — a regression
here means the canonicalization broke runtime LLM-output validation.

**STOP-GATE 8:** All tests green, code merged to main (separate PR), normalizer
verified live in the deployed image. Operator confirms "go for resume".

---

## Phase 6 — Resume Ingestion and Verify

**Risk:** Low. Ingestion restart and one short observation window.

### Task 6.1 — Resume

- [ ] Resume the services that were running before the freeze:
  ```bash
  docker compose up -d $(cat /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt)
  ```
- [ ] Confirm services come up healthy using their actual endpoints:
  - backend: `http://localhost:8080/api/v1/health`
  - intelligence: `http://localhost:8003/health`
  - Neo4j: `curl -sf http://localhost:7474` plus authenticated `RETURN 1`
  - data-ingestion / vision-enrichment: `docker compose ps` and logs
- [ ] Tail logs for 10 min and confirm normalized writes:
  ```bash
  docker logs -f osint-data-ingestion-1 | grep -iE "neo4j_write|entity"
  ```

### Task 6.2 — Post-resume drift check

- [ ] Wait for at least one full feed-collection cycle (depends on
  `scheduler.py`). Then re-run:
  ```cypher
  MATCH (e:Entity) WHERE e.type =~ '[a-z].*' RETURN count(*) AS regressed;
  ```
  Expected: `0`. If non-zero, the deployed code change is not yet active —
  pause ingestion again, verify image deployment.

### Task 6.3 — Restore stable monitoring

- [ ] Confirm Patch B's runtime drift guard is still emitting only valid
  `codebook_type` values (no spike in
  `codebook_type_unknown_remapped` log entries).
- [ ] Update `/home/deadpool-ultra/.claude/projects/.../memory/project_active_plans.md`
  to reflect Patch C completion.

**STOP-GATE 9:** Ingestion stable for ≥1 hour, no lowercase regression,
operator declares "Patch C complete".

---

## Rollback Procedures

Patch C does not have a "fix forward" mode. Any failure in Phase 1 or Phase 3
restores from the Phase 0 dump.

### Rollback from Phase 1 failure

1. Stop all writer services if any were restarted:
   ```bash
   docker compose stop \
       data-ingestion \
       data-ingestion-spark \
       backend \
       intelligence \
       vision-enrichment
   ```
2. Stop Neo4j through Compose:
   ```bash
   docker compose stop neo4j
   ```
3. Verify the backup SHA-256:
   ```bash
   sha256sum -c /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump.sha256
   ```
4. Resolve the Neo4j Docker volume:
   ```bash
   export NEO4J_VOLUME="$(docker volume ls --format '{{.Name}}' | grep '_neo4j-data$' | head -n1)"
   test -n "$NEO4J_VOLUME"
   ```
5. Restore dump into the offline volume:
   ```bash
   docker run --rm \
       -v "$NEO4J_VOLUME":/data \
       -v /home/deadpool-ultra/odin-backups:/backups \
       neo4j:5-community \
       neo4j-admin database load neo4j \
         --from-path=/backups \
         --overwrite-destination=true
   ```
6. Restart Neo4j and verify:
   ```bash
   docker compose up -d neo4j
   curl -sf http://localhost:7474 >/dev/null
   docker exec osint-neo4j-1 cypher-shell \
       -u "${NEO4J_USER:-neo4j}" \
       -p "${NEO4J_PASSWORD:-odin1234}" \
       "RETURN 1 AS ok"
   ```
7. Re-run preflight to confirm `8 813 / 8 293 / 15`.
8. Resume ingestion. Patch C is **not** rolled back code-side because Phase 5
   has not run yet — code is still legacy.

### Rollback from Phase 3 failure

Same procedure as Phase 1. Phase 3 does not have its own snapshot because
the merge is small and the Phase 0 dump is recent.

### Rollback from Phase 5 failure

Code-side: `git revert` the Phase 5 commits. Database stays canonicalized.
Ingestion will then write lowercase types again, regenerating drift. This is
acceptable as a temporary state — re-deploy Phase 5 once the code bug is
fixed. The drift guard from Patch B will not catch it (it covers `codebook_type`,
not `entity.type`); add a follow-up monitoring query to catch this case.

### Rollback during Phase 6 (post-resume regression)

- Stop ingestion immediately.
- Investigate the deployed image (Phase 5 may not be live).
- Optionally re-run Phase 1 canonicalization to re-fix the regressed nodes.
  Do **not** restore from the Phase 0 dump — that would discard valid
  Phase 1+3 work.

---

## Stop-Gate Summary

| Gate | After | Operator confirms |
|------|-------|---|
| 0 | Pre-conditions checklist | "go for Phase 0" |
| 1 | Phase 0 (snapshot + freeze) | "go for Phase 1 prep" |
| 2 | Phase 1 Cypher committed, dry-run done | "go for Phase 1 apply" |
| 3 | Phase 1 applied + verified | "go for Phase 2" |
| 4 | Phase 2 re-preflight + auto-merge candidates list | "go for Phase 3 prep" |
| 5 | Phase 3 Cypher committed | "go for Phase 3 apply" |
| 6 | Phase 3 applied + verified | "go for Phase 4" |
| 7 | Phase 4 manual-review report stored | "go for Phase 5" |
| 8 | Phase 5 code change merged + tests green | "go for resume" |
| 9 | Phase 6 ingestion stable | "Patch C complete" |

**Default stance at every gate is STOP.** No phase auto-advances.

---

## Risks

- **Race during freeze:** any cron/scheduler outside the compose file could
  write during the freeze window. Mitigation: stop all known writer services,
  pause host schedulers, record pre-freeze running services, and verify no writer
  containers remain in Task 0.1.
- **APOC absence between preflight and migration:** APOC was confirmed today,
  but a future `docker compose up` could load a different Neo4j image.
  Mitigation: re-check APOC in pre-conditions (Task 0).
- **Property loss in `apoc.refactor.mergeNodes`:** the merge query explicitly
  preserves survivor `aliases` and max `confidence`, then discards other loser
  properties to avoid array-ifying scalar fields. This favors topology safety
  over full property preservation; revisit if analyst feedback shows missing
  property coverage.
- **Manual-review queue grows during freeze window:** if the report cannot
  be acted on inside the window, ingestion resumes with the unmerged groups
  still present. Acceptable; they were already there before Patch C.
- **Lowercase regression after Phase 6:** if Phase 5 code is not actually
  live in the deployed image, ingestion will write lowercase again. The
  Phase 6 verification query catches this; the drift-guard test from Patch B
  does not.

## Non-Goals

- Country-name lift-up (`location` → `COUNTRY` for known country names).
  Out of scope; can be a follow-up enrichment job.
- Deletion of "noise" entities like `terrorists`, `bandits`, adjectival forms.
  Out of scope; flagged in the manual-review report.
- Schema changes to relationship types. Patch A locked the relation contract.
- Frontend changes. Patch B already covered the codebook side; entity types
  are not user-visible.

## Open Questions

1. Should `apoc.refactor.mergeNodes` use `properties: 'combine'` instead of
   explicit pre-merge consolidation plus `'discard'`? Decision: stay with the
   explicit strategy in Phase 3. It preserves aliases and max confidence while
   avoiding accidental arrays for `name`, `type`, and timestamp fields.
2. Should Phase 5 ship as a separate PR before the maintenance window, with
   a feature flag that gates the normalizer? This would let the deployed
   image be ready before the freeze. Recommended: yes, ship Phase 5 PR ahead
   of the freeze window with the normalizer behind a default-OFF/no-op flag;
   flip the flag only after Phase 1 is verified and before Phase 6 resume.
3. Does the manual-review report flow into a ticket queue (Linear, GitHub
   issues, runbook follow-up)? Operator decision; not blocking the migration.

---

## Implementation Order

1. Pre-conditions checklist + runbook draft (no Neo4j writes).
2. Operator sign-off on freeze window.
3. Phase 5 PR prepared and merged with normalizer behind a default-OFF flag,
   but ingestion still scheduled to run with current behavior — see Open
   Question 2.
4. Phase 0 — freeze + snapshot.
5. Phase 1 — canonicalization apply.
6. Phase 2 — re-preflight read.
7. Phase 3 — selective merge apply.
8. Phase 4 — manual-review report.
9. Phase 5 — verify deployed normalizer is live (if not pre-deployed).
10. Phase 6 — resume ingestion + verify.
11. Memory + plan-tracker update.

Patch C is complete only after Stop-Gate 9.
