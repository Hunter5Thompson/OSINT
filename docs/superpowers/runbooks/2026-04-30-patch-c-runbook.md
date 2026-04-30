# Patch C Operator Runbook - Entity-Type Canonicalization

**Date:** 2026-04-30  
**Status:** Draft for operator review. Do not execute until the freeze window is
approved.  
**Scope:** Neo4j `:Entity.type` canonicalization, selective duplicate merge,
manual-review report generation, and controlled ingestion resume.  
**Source Plan:** `docs/superpowers/plans/2026-04-30-patch-c-entity-canonicalization.md`

This runbook is an execution checklist. It intentionally repeats the critical
commands from the plan so the operator can run the maintenance window from one
document. The default stance at every gate is **STOP**.

No command in this document has been executed as part of writing the runbook.

---

## 0. Operating Rules

- Do not begin without explicit operator approval for the maintenance window.
- Do not continue past a stop-gate without the exact confirmation phrase.
- Do not run Phase 1 or Phase 3 if the Phase 0 dump is missing, empty, or has no
  recorded SHA-256.
- Do not use `docker exec neo4j stop` or any in-container stop command for the
  backup path. Stop Neo4j through Compose, then dump/load the Docker volume
  offline.
- Do not commit live graph exports or manual-review CSVs by default.
- If Phase 1 or Phase 3 returns any error, stop and restore from the Phase 0 dump.
  Do not fix forward inside the maintenance window.

---

## 1. Fixed Paths and Service Set

Host backup directory:

```bash
/home/deadpool-ultra/odin-backups
```

Primary dump path:

```bash
/home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
```

Dump checksum path:

```bash
/home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump.sha256
```

Running-service snapshot:

```bash
/home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt
```

Manual-review report:

```bash
/home/deadpool-ultra/odin-reports/manual_review_groups_patch_c_2026-04-30.csv
```

Known Neo4j writers to stop before the snapshot:

```text
data-ingestion
data-ingestion-spark
backend
intelligence
vision-enrichment
```

---

## 2. Pre-Window Review

The first step is mandatory and must run before any other command in this
runbook. Every subsequent `cypher-shell` invocation uses fail-fast `${VAR:?...}`
expansion against `NEO4J_USER` and `NEO4J_PASSWORD` and will halt with a clear
error if the environment is not loaded.

- [ ] Load Neo4j credentials into the current shell:

```bash
export NEO4J_USER=neo4j
export NEO4J_PASSWORD="$(grep '^NEO4J_PASSWORD=' /home/deadpool-ultra/ODIN/OSINT/.env | cut -d= -f2-)"
test -n "$NEO4J_PASSWORD" || { echo "FATAL: NEO4J_PASSWORD not found in .env"; exit 1; }
echo "neo4j auth env loaded for user=$NEO4J_USER"
```

- [ ] Patch A is merged.
- [ ] Patch B is merged.
- [ ] No Patch-C-touching PR is open on another branch.
- [ ] This runbook has been reviewed against the current `docker-compose.yml`.
- [ ] The operator has read the source plan end-to-end.
- [ ] Maintenance window is scheduled and announced.
- [ ] Expected window is at least 30 minutes and at most 2 hours.
- [ ] Host backup target has at least 10 GB free:

```bash
df -h /home/deadpool-ultra/odin-backups /home/deadpool-ultra || true
```

- [ ] Neo4j Docker volume name can be resolved:

```bash
docker volume ls --format '{{.Name}}' | grep '_neo4j-data$'
```

- [ ] APOC is available (Neo4j 5 uses `SHOW PROCEDURES`, not `CALL dbms.procedures()`):

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "SHOW PROCEDURES YIELD name
     WHERE name STARTS WITH 'apoc.'
     RETURN count(name) AS apoc_procedures"
```

Expected: ~190 procedures.

- [ ] The four required APOC procedures are present:

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "SHOW PROCEDURES YIELD name
     WHERE name IN [
       'apoc.periodic.iterate',
       'apoc.refactor.mergeNodes',
       'apoc.refactor.from',
       'apoc.refactor.to'
     ]
     RETURN collect(name) AS found, count(name) AS count"
```

Expected: `count = 4` and all four names in `found`.

- [ ] APOC merge property behavior smoke-tested on disposable `:PatchCTest` nodes.
  Run this exact sequence and verify the assertions inline. The block is fully
  self-cleaning — failure at any step still leaves `:PatchCTest` rows for
  manual cleanup, which is a controlled label and does not collide with
  production data.

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "// Setup: two duplicate test nodes with conflicting properties
     CREATE (a:PatchCTest {name: 'smoke', type: 'lower', aliases: ['x'], confidence: 0.4})
     CREATE (b:PatchCTest {name: 'smoke', type: 'UPPER', aliases: ['y'], confidence: 0.9})
     CREATE (a)-[:PATCHC_REL {evidence: 'a-edge'}]->(b)

     // Pre-merge: pull aliases + max confidence into the survivor explicitly
     WITH a, b
     SET b.aliases   = apoc.coll.toSet(coalesce(b.aliases, []) + coalesce(a.aliases, [])),
         b.confidence = CASE WHEN coalesce(a.confidence, 0) > coalesce(b.confidence, 0)
                             THEN a.confidence ELSE b.confidence END

     // Merge survivor=b, loser=a; discard remaining loser props
     WITH b, a
     CALL apoc.refactor.mergeNodes([b, a], {properties: 'discard', mergeRels: true})
     YIELD node

     // Assert: aliases merged, confidence is the max, type stayed UPPER (b's)
     WITH node
     RETURN node.name           AS name,
            node.type           AS type,
            node.confidence     AS confidence,
            apoc.coll.sort(node.aliases) AS aliases"
```

Expected output exactly: `name=smoke, type=UPPER, confidence=0.9, aliases=[x, y]`.
If `aliases` is missing one of x/y, or confidence is not 0.9, **stop and
investigate APOC behavior before proceeding**.

- [ ] Smoke-test cleanup (must run regardless of test outcome):

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (n:PatchCTest) DETACH DELETE n RETURN count(n) AS removed"
```

Expected: `removed = 1` if the merge succeeded (only the survivor remains)
or `removed = 2` if it failed before merge. Either way the label must be
empty afterwards.

- [ ] Phase 5 normalizer PR strategy is decided:
  - default: separate PR before the window
  - required behavior: feature flag default-OFF/no-op
  - flag may only be enabled after Phase 1 verification and before Phase 6

**STOP-GATE 0:** Operator confirms: `go for Phase 0`.

---

## 3. Phase 0 - Freeze and Offline Snapshot

Risk: Low. This phase stops writers, snapshots Neo4j, and verifies the dump.

### 3.1 Capture Current Service Mix

```bash
mkdir -p /home/deadpool-ultra/odin-backups
docker compose ps --services --filter status=running \
    > /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt
cat /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt
```

Keep this file. It is the resume source of truth.

### 3.2 Stop All Known Writers

```bash
docker compose stop \
    data-ingestion \
    data-ingestion-spark \
    backend \
    intelligence \
    vision-enrichment
```

It is acceptable if profile-gated services were not running.

Confirm stopped state:

```bash
docker compose ps data-ingestion data-ingestion-spark backend intelligence vision-enrichment
docker ps --format '{{.Names}}' \
  | grep -E 'data-ingestion|backend|intelligence|vision-enrichment' \
  && echo "STOP: writer still running" || echo "writers stopped"
```

Pause host cron/scheduler jobs if any exist outside Compose.

### 3.3 Resolve Neo4j Volume

```bash
export NEO4J_VOLUME="$(docker volume ls --format '{{.Name}}' | grep '_neo4j-data$' | head -n1)"
test -n "$NEO4J_VOLUME"
echo "$NEO4J_VOLUME"
```

If more than one matching volume appears, stop and resolve manually.

### 3.4 Stop Neo4j and Dump Offline

```bash
docker compose stop neo4j
```

```bash
docker run --rm \
    -v "$NEO4J_VOLUME":/data \
    -v /home/deadpool-ultra/odin-backups:/backups \
    neo4j:5-community \
    neo4j-admin database dump neo4j \
      --to-path=/backups
```

```bash
mv /home/deadpool-ultra/odin-backups/neo4j.dump \
   /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
```

### 3.5 Record Integrity

```bash
ls -la /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump
sha256sum /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump \
    | tee /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump.sha256
```

### 3.6 Restart Neo4j and Verify

```bash
docker compose up -d neo4j
docker compose ps neo4j
curl -sf http://localhost:7474 >/dev/null
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "RETURN 1 AS ok"
```

### 3.7 Verify Baseline Still Matches

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     RETURN count(e) AS total_entities,
            count(DISTINCT toLower(e.name)) AS distinct_names,
            count(DISTINCT e.type) AS distinct_types"
```

Expected from 2026-04-30 preflight:

```text
total_entities: 8813
distinct_names: 8293
distinct_types: 15
```

If these drifted, stop and re-run preflight before proceeding.

**STOP-GATE 1:** Snapshot exists, SHA-256 is recorded, writers are paused,
baseline is accepted. Operator confirms: `go for Phase 1 prep`.

---

## 4. Phase 1 - Type Canonicalization

Risk: Low to medium. This rewrites legacy lowercase entity types to uppercase
canonical values. Node and relationship counts must not change.

### 4.1 Record Pre-Write Type Distribution

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     RETURN e.type AS type, count(*) AS count
     ORDER BY count DESC" \
    | tee /home/deadpool-ultra/odin-backups/patch-c-pre-phase-1-type-distribution.txt
```

### 4.2 Dry-Run Estimate

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     WHERE e.type IN ['person','organization','location','military_unit',
                      'weapon_system','vessel','aircraft','satellite']
     RETURN count(*) AS rewrite_target"
```

Expected: around `8784`.

### 4.3 Review Migration File

Required file:

```bash
services/data-ingestion/migrations/neo4j_entity_type_canonicalization.cypher
```

The file must be committed or otherwise approved before execution. It must:

- use `apoc.periodic.iterate`
- use `parallel: false`
- map `location` to `LOCATION`
- be idempotent
- avoid node creation, relationship creation, and relationship deletion

**STOP-GATE 2:** Migration file reviewed/committed and dry-run count documented.
Operator confirms: `go for Phase 1 apply`.

### 4.4 Apply Canonicalization

Run the committed migration file:

```bash
docker exec -i osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    < services/data-ingestion/migrations/neo4j_entity_type_canonicalization.cypher \
    | tee /home/deadpool-ultra/odin-backups/patch-c-phase-1-apply.log
```

Expected response:

```text
errorMessages: []
```

Any error means stop and run rollback.

### 4.5 Verify Phase 1

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     WHERE e.type =~ '[a-z].*'
     RETURN count(*) AS remaining_lowercase"
```

Expected: `0`.

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     RETURN count(e) AS total_entities,
            count(DISTINCT toLower(e.name)) AS distinct_names,
            count(DISTINCT e.type) AS distinct_types"
```

Expected total entity count remains `8813` unless the operator accepted a new
baseline before Phase 1.

**STOP-GATE 3:** Zero lowercase types, entity count unchanged, no apply errors.
Operator confirms: `go for Phase 2`.

---

## 5. Phase 2 - Read-Only Re-Preflight

Risk: None. Read-only queries only.

### 5.1 Multi-Type Duplicate Count

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     WITH toLower(e.name) AS name_key,
          collect(e) AS nodes,
          collect(DISTINCT e.type) AS types
     WHERE size(nodes) > 1 AND size(types) > 1
     RETURN count(*) AS multi_type_groups,
            sum(size(nodes)) AS total_nodes_in_groups,
            sum(size(nodes)) - count(*) AS redundant_nodes"
```

Pre-Phase-1 baseline: `355 / 766 / 411`.

### 5.2 Same-Name Any-Type Duplicate Count

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     WITH toLower(e.name) AS name_key, collect(e) AS nodes
     WHERE size(nodes) > 1
     RETURN count(*) AS any_dup_groups,
            sum(size(nodes)) AS any_total_nodes"
```

Pre-Phase-1 baseline: `461 / 981`.

### 5.3 Export Auto-Merge Candidate Review

Store the review artifact outside the source tree by default:

```bash
mkdir -p /home/deadpool-ultra/odin-reports
```

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    --format plain \
    "MATCH (e:Entity)
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
     ORDER BY node_count DESC" \
    | tee /home/deadpool-ultra/odin-reports/auto_merge_candidates_patch_c_2026-04-30.txt
```

Review rules:

- same-name/same-type groups are eligible
- geographic `COUNTRY > REGION > LOCATION` groups are eligible
- `PERSON` vs `ORGANIZATION` is never auto-merged
- ambiguous `ORGANIZATION` vs `MILITARY_UNIT` stays manual review unless the
  operator explicitly creates a separate approved input list

**STOP-GATE 4:** Re-preflight numbers documented, candidate list reviewed,
manual-review-only list accepted. Operator confirms: `go for Phase 3 prep`.

---

## 6. Phase 3 - Selective Auto-Merge

Risk: Medium. This transfers relationships and deletes duplicate loser nodes.
Rollback is the Phase 0 dump.

### 6.1 Capture Relationship and Orphan Baselines

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH ()-[r]->()
     RETURN type(r) AS rel_type, count(*) AS count
     ORDER BY count DESC" \
    | tee /home/deadpool-ultra/odin-backups/patch-c-pre-phase-3-relationship-counts.txt
```

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (n)
     WHERE NOT (n)--()
     RETURN labels(n) AS labels, count(*) AS orphans
     ORDER BY orphans DESC" \
    | tee /home/deadpool-ultra/odin-backups/patch-c-pre-phase-3-orphans.txt
```

### 6.2 Review Migration File

Required file:

```bash
services/data-ingestion/migrations/neo4j_duplicate_merge.cypher
```

The file must be committed or otherwise approved before execution. It must:

- include same-name/same-type groups
- include only deterministic geographic merges for multi-type groups
- order survivor selection by relationship count, then `first_seen`, then
  `elementId`
- preserve `aliases` and max `confidence` explicitly before merge
- use `parallel: false`
- avoid committing manual-review graph data into the repository

**STOP-GATE 5:** Merge Cypher reviewed/committed. Operator confirms:
`go for Phase 3 apply`.

### 6.3 Apply Merge

```bash
docker exec -i osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    < services/data-ingestion/migrations/neo4j_duplicate_merge.cypher \
    | tee /home/deadpool-ultra/odin-backups/patch-c-phase-3-apply.log
```

Expected response:

```text
errorMessages: []
```

Any error means stop and run rollback.

### 6.4 Verify Phase 3

Re-run duplicate counts:

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     WITH toLower(e.name) AS name_key,
          collect(e) AS nodes,
          collect(DISTINCT e.type) AS types
     WHERE size(nodes) > 1 AND size(types) > 1
     RETURN count(*) AS multi_type_groups,
            sum(size(nodes)) AS total_nodes_in_groups,
            sum(size(nodes)) - count(*) AS redundant_nodes"
```

Re-run relationship counts and compare with the pre-Phase-3 file:

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH ()-[r]->()
     RETURN type(r) AS rel_type, count(*) AS count
     ORDER BY count DESC"
```

A small reduction is acceptable only if explained by deduplicated parallel
relationships.

**STOP-GATE 6:** Merge applied successfully, duplicate-count drop matches the
reviewed candidate list, no unexplained relationship loss. Operator confirms:
`go for Phase 4`.

---

## 7. Phase 4 - Manual-Review Report

Risk: None. Read-only query plus host file write.

### 7.1 Generate Manual-Review Report

`cypher-shell --format plain` is whitespace-formatted text, not RFC-4180 CSV
— and the `types` and `detail` columns contain arrays/maps that break naive
CSV parsing. The report is generated through the HTTP API (JSON) and converted
to a real CSV with a small inline Python helper. Array/map cells are
JSON-serialized so analysts can `json.loads()` per cell when needed.

```bash
mkdir -p /home/deadpool-ultra/odin-reports
```

```bash
curl -sf -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}:${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    -H "Content-Type: application/json" \
    -X POST http://localhost:7474/db/neo4j/tx/commit \
    -d '{"statements":[{"statement":"MATCH (e:Entity) WITH toLower(e.name) AS name_key, collect(e) AS nodes, collect(DISTINCT e.type) AS types WHERE size(nodes) > 1 AND size(types) > 1 RETURN name_key, types, size(nodes) AS node_count, [n IN nodes | {name: n.name, type: n.type, rel_count: COUNT { (n)--() }}] AS detail ORDER BY node_count DESC, name_key"}]}' \
| python3 -c '
import csv, json, sys
data = json.load(sys.stdin)
errors = data.get("errors") or []
if errors:
    sys.stderr.write("Neo4j error: %s\n" % errors); sys.exit(2)
result = data["results"][0]
writer = csv.writer(sys.stdout, quoting=csv.QUOTE_MINIMAL)
writer.writerow(result["columns"])
for row in result["data"]:
    writer.writerow([
        json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v
        for v in row["row"]
    ])
' > /home/deadpool-ultra/odin-reports/manual_review_groups_patch_c_2026-04-30.csv
wc -l /home/deadpool-ultra/odin-reports/manual_review_groups_patch_c_2026-04-30.csv
head -3 /home/deadpool-ultra/odin-reports/manual_review_groups_patch_c_2026-04-30.csv
```

Expected: line count equals `multi_type_groups + 1` (header) from Phase 2's
re-preflight count. Header row should read
`name_key,types,node_count,detail`.

### 7.2 Add Review Guidance

The report handoff must state:

- it is read-only documentation
- no manual-review merges are approved inside this Patch C window
- adjectival forms should usually be treated as language drift, not entities
- `PERSON` vs `ORGANIZATION` requires human decision
- generic nouns may be candidates for `CONCEPT` retagging or deletion in a
  future ticket

**STOP-GATE 7:** Manual-review report exists at the known path and is accepted.
Operator confirms: `go for Phase 5`.

---

## 8. Phase 5 - Code-Side Normalizer

Risk: Low. Code change only. This may be prepared before the maintenance window
as a separate PR, but runtime behavior must remain default-OFF/no-op until the
operator enables it.

Required behavior:

- Add a canonical entity-type normalizer.
- Keep it idempotent on canonical uppercase values.
- Map legacy lowercase values:
  - `person` -> `PERSON`
  - `organization` -> `ORGANIZATION`
  - `location` -> `LOCATION`
  - `military_unit` -> `MILITARY_UNIT`
  - `weapon_system` -> `WEAPON_SYSTEM`
  - `vessel` -> `VESSEL`
  - `aircraft` -> `AIRCRAFT`
  - `satellite` -> `SATELLITE`
- Add `LOCATION` to the NLM entity type literal.
- Version the NLM prompt instead of overwriting the existing prompt.
- Apply the normalizer before Neo4j write parameters are built in every writer.
- Keep feature flag default-OFF/no-op until Phase 1 has verified the live graph.

Minimum gating tests (must pass before flipping the flag):

```bash
cd services/data-ingestion && uv run pytest -q
cd services/intelligence && uv run pytest -q
```

Optional cross-check (Phase 5 does not change frontend code; run only if the
window has slack):

```bash
cd services/frontend && npm run test
```

If Phase 5 fails before resume, revert/fix code and keep ingestion paused. The
database should remain canonicalized.

**STOP-GATE 8:** Tests pass, code is merged or deployed as planned, normalizer
is active for resume. Operator confirms: `go for resume`.

---

## 9. Phase 6 - Resume and Observe

Risk: Low. Resume only the service mix captured before the freeze.

### 9.1 Resume Captured Services

```bash
docker compose up -d $(cat /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt)
```

Do not blindly start profile services that were not running before the freeze.

### 9.2 Health Checks

```bash
curl -sf http://localhost:7474 >/dev/null
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "RETURN 1 AS ok"
```

If running:

```bash
curl -sf http://localhost:8080/api/v1/health
curl -sf http://localhost:8003/health
docker compose ps
```

Tail writer logs for at least 10 minutes:

```bash
docker compose logs -f data-ingestion data-ingestion-spark backend intelligence vision-enrichment
```

### 9.3 Post-Resume Drift Check

After at least one full ingestion cycle. The check is intentionally broader
than Phase 1's lowercase-only verification — it catches **any** non-canonical
entity-type drift from any writer (lowercase legacy, TitleCase from a future
wired-up `services/intelligence/extraction/entity_extractor.py`, or any
unknown vocabulary):

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     WHERE NOT e.type IN [
       'AIRCRAFT', 'CONCEPT', 'COUNTRY', 'LOCATION', 'MILITARY_UNIT',
       'ORGANIZATION', 'PERSON', 'POLICY', 'REGION', 'SATELLITE',
       'TREATY', 'VESSEL', 'WEAPON_SYSTEM'
     ]
     RETURN count(*) AS non_canonical,
            collect(DISTINCT e.type)[0..10] AS sample_types"
```

Expected: `non_canonical = 0`, `sample_types = []`.

If non-zero:

1. Stop ingestion writers again.
2. Inspect `sample_types` to identify the writer surface:
   - lowercase legacy → Phase 5 flag is OFF or normalizer not deployed
   - TitleCase (`Person`, `Organization`, …) → a dormant intelligence path
     became wired up; check `services/intelligence/extraction/entity_extractor.py`
     callers
   - other → unknown writer; grep for raw `e.type`/`type:` Cypher in the codebase
3. Verify the deployed Phase 5 image and feature flag.
4. Re-run Phase 1 canonicalization only after the writer is patched or paused.
5. Do **not** restore the Phase 0 dump for a post-resume drift event — that
   would discard valid Phase 1+3 work.

**STOP-GATE 9:** Ingestion stable for at least 1 hour, `non_canonical = 0`,
operator confirms: `Patch C complete`.

---

## 10. Rollback

Patch C has one database rollback path: restore the Phase 0 dump into the offline
Neo4j volume.

Use this for Phase 1 or Phase 3 failures.

### 10.1 Stop Writers

```bash
docker compose stop \
    data-ingestion \
    data-ingestion-spark \
    backend \
    intelligence \
    vision-enrichment
```

### 10.2 Stop Neo4j

```bash
docker compose stop neo4j
```

### 10.3 Verify Dump Integrity

```bash
sha256sum -c /home/deadpool-ultra/odin-backups/neo4j-pre-patch-c-2026-04-30.dump.sha256
```

### 10.4 Resolve Volume

```bash
export NEO4J_VOLUME="$(docker volume ls --format '{{.Name}}' | grep '_neo4j-data$' | head -n1)"
test -n "$NEO4J_VOLUME"
echo "$NEO4J_VOLUME"
```

### 10.5 Load Dump Offline

```bash
docker run --rm \
    -v "$NEO4J_VOLUME":/data \
    -v /home/deadpool-ultra/odin-backups:/backups \
    neo4j:5-community \
    neo4j-admin database load neo4j \
      --from-path=/backups \
      --overwrite-destination=true
```

### 10.6 Restart and Verify

```bash
docker compose up -d neo4j
curl -sf http://localhost:7474 >/dev/null
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "RETURN 1 AS ok"
```

Re-run baseline:

```bash
docker exec osint-neo4j-1 cypher-shell \
    -u "${NEO4J_USER:?NEO4J_USER must be exported (see section 2 first)}" \
    -p "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be exported (see section 2 first)}" \
    "MATCH (e:Entity)
     RETURN count(e) AS total_entities,
            count(DISTINCT toLower(e.name)) AS distinct_names,
            count(DISTINCT e.type) AS distinct_types"
```

Expected: the accepted Phase 0 baseline. For the 2026-04-30 preflight that was
`8813 / 8293 / 15`.

### 10.7 Resume or Stay Paused

If the operator decides to abandon Patch C for the window:

```bash
docker compose up -d $(cat /home/deadpool-ultra/odin-backups/patch-c-running-services-before-freeze.txt)
```

If the failure requires investigation, leave writers paused and document the
failure log paths.

---

## 11. Completion Artifacts

At the end of the window, record:

- backup dump path
- dump SHA-256
- Phase 1 apply log path
- Phase 3 apply log path, if Phase 3 ran
- pre/post entity counts
- pre/post duplicate counts
- manual-review report path
- Phase 5 commit or PR reference
- final lowercase regression check result
- operator who approved Stop-Gate 9

Do not add `/home/deadpool-ultra/odin-reports/*.csv` to git unless the operator
creates a sanitized report explicitly for repository history.
