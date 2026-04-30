# Codebook and Graph Type Drift - Design Spec

**Date:** 2026-04-30
**Status:** Decision-ready
**Scope:** NLM relation writes, GDELT codebook targets, entity type canonicalization, graph migration, and frontend codebook category rendering

---

## 1. Motivation

The Intel Codebook Curator audit found three independent taxonomy/graph drifts plus
one architecture-level graph fragmentation bug:

- NLM extraction validates `relations`, but NLM Neo4j ingest never writes them.
- GDELT raw CAMEO mapping emits `civil.*`, `conflict.*`, and `posture.*`
  `codebook_type` values that are not present in `event_codebook.yaml`.
- Entity type vocabularies are split: NLM uses uppercase domain types while RSS/main
  ingestion and intelligence extraction use lowercase entity types.
- Both NLM and main ingestion write to `(:Entity {name, type})`; because `type` is
  part of the MERGE key, the same real-world entity can fragment into duplicate nodes
  such as `("China", "COUNTRY")` and `("China", "location")`.

This is not only documentation drift. It affects persisted graph topology, RAG graph
context, analyst queries, and frontend event rendering.

---

## 2. Decisions

### 2.1 Relations Must Be Written Additively

NLM `Relation` objects are part of the validated extraction contract and must be
persisted in Neo4j.

Implementation should be additive:

- Add one deterministic Cypher template per `RelationType`.
- Use `MATCH` for both endpoints and `MERGE` only for the relationship.
- Do not create orphan entities from relation writes.
- Insert the relation-write loop after entity upsert and before claim upsert.
- On re-run, keep relation confidence monotonic with `max(old, new)` semantics.
- Keep `evidence` fresh on match, because later extractions may carry better provenance.

This change needs no data migration because relations were not previously persisted.

### 2.2 Expand Codebook To Match GDELT, Do Not Collapse GDELT

The GDELT raw pipeline already maps CAMEO roots to the following internal types:

```text
civil.protest
posture.military
conflict.coercion
conflict.assault
conflict.armed
conflict.mass_violence
```

Those types should become first-class codebook entries instead of being forced into
existing `military.*`, `political.*`, or `social.*` buckets.

Reasoning:

- `conflict.armed` is broader than `military.airstrike`.
- `conflict.assault` is not equivalent to `military.ground_offensive`.
- `conflict.coercion` can cover sanctions, threats, asset freezes, or pressure.
- `posture.military` captures deployment/mobilization posture without implying combat.

The codebook should preserve that granularity.

The first codebook patch should include all currently emitted CAMEO targets plus a
small reserve set for each new root so the next CAMEO expansion does not immediately
create shadow taxonomy values again.

### 2.3 NLM Uppercase Entity Types Are Canonical

The uppercase NLM entity vocabulary should become the canonical graph write vocabulary:

```text
AIRCRAFT
CONCEPT
COUNTRY
LOCATION
MILITARY_UNIT
ORGANIZATION
PERSON
POLICY
REGION
SATELLITE
TREATY
VESSEL
WEAPON_SYSTEM
```

`LOCATION` is added as a catch-all because main ingestion cannot reliably reclassify
every lowercase `location` into either `COUNTRY` or `REGION`.

Main ingestion and intelligence extraction should output canonical uppercase types
before writing to Neo4j.

The normalizer must have one source of truth. The canonical home is
`services/data-ingestion/nlm_ingest/schemas.py`:

```python
def normalize_entity_type(value: str) -> EntityType: ...
```

The function must be idempotent for already-canonical values, for example
`normalize_entity_type("PERSON") == "PERSON"`. If a service cannot import this module
because of Docker build-context boundaries, it may use a pinned local copy only with a
drift-guard test that compares it to this source.

### 2.4 Existing Entity Duplicates Need A Migration

Changing write code alone is insufficient because historical duplicates remain in
Neo4j. A graph migration must merge duplicate `Entity` nodes after canonicalizing
type values.

Migration requirements:

- Idempotent.
- Preserves all incoming and outgoing relationships.
- Prefers the canonical uppercase node as the survivor when present.
- Merges aliases and confidence/last_seen style properties conservatively.
- Deletes only duplicates whose relationships have been moved.
- Has a dry-run/preflight mode that reports duplicate groups.

Survivor selection must be deterministic:

1. If a duplicate group contains only one canonical uppercase type, choose that node.
2. If it contains `COUNTRY`, `REGION`, and/or `LOCATION` for the same normalized name,
   prefer `COUNTRY`, then `REGION`, then `LOCATION`.
3. If it contains multiple semantic classes outside that hierarchy, such as `PERSON`
   and `ORGANIZATION`, stop and emit a manual-review item instead of merging.
4. Within the selected type, prefer the node with the highest relationship cardinality;
   break ties by earliest `first_seen`, then lowest internal id.

APOC is acceptable if available in the active Neo4j deployment. If APOC is unavailable,
the plan must provide a pure-Cypher/Python-driver fallback.

### 2.5 Frontend Must Render New Codebook Roots Intentionally

The frontend event layer derives category from `codebook_type.split(".")[0]`.
New roots such as `conflict`, `civil`, and `posture` must be added to the color map.

Existing roots currently not covered should also be made explicit where appropriate:

```text
social
humanitarian
infrastructure
other
conflict
civil
posture
```

This is a frontend contract update, not a graph migration.

---

## 3. Evidence

NLM schema validates relations:

- `services/data-ingestion/nlm_ingest/schemas.py`
- `Extraction.relations: list[Relation]`

NLM ingest currently consumes entities and claims but not relations:

- `services/data-ingestion/nlm_ingest/ingest_neo4j.py`

GDELT maps to codebook values not present in the current YAML:

- `services/data-ingestion/gdelt_raw/cameo_mapping.py`
- `services/intelligence/codebook/event_codebook.yaml`

Entity MERGE key includes both name and type in both write paths:

- `services/data-ingestion/pipeline.py`
- `services/data-ingestion/nlm_ingest/write_templates.py`

Frontend category rendering derives root category from dotted `codebook_type`:

- `services/frontend/src/components/layers/EventLayer.tsx`

---

## 4. Target Contracts

### 4.1 NLM Relation Contract

Each `RelationType` has a deterministic write template:

```text
ALLIED_WITH
COMMANDS
COMPETES_WITH
MEMBER_OF
NEGOTIATES_WITH
OPERATES_IN
SANCTIONS
SUPPLIES_TO
TARGETS
```

Each template follows the same pattern:

```cypher
MATCH (source:Entity {name: $source})
MATCH (target:Entity {name: $target})
MERGE (source)-[r:ALLIED_WITH]->(target)
ON CREATE SET r.first_seen = datetime(),
              r.evidence = $evidence,
              r.confidence = $confidence,
              r.last_seen = datetime()
ON MATCH SET r.evidence = $evidence,
             r.confidence = CASE
                 WHEN $confidence > coalesce(r.confidence, 0)
                 THEN $confidence
                 ELSE r.confidence
             END,
             r.last_seen = datetime()
```

Each template hardcodes the relationship label matching its `RelationType` key; no
dynamic relationship-label construction is allowed.

If either endpoint is absent, no relationship is written.

### 4.2 Codebook Contract

Every `codebook_type` emitted by production ingestion code must be present in
`event_codebook.yaml`.

This includes:

- LLM extraction prompt values.
- GDELT CAMEO mapping values.
- Synthetic/manual signal values only when they are intended as durable taxonomy.

LLM extraction is still untrusted even with a prompt and JSON schema. Runtime code must
validate produced `codebook_type` values against `event_codebook.yaml`, log unknown
values, and remap them to `other.unclassified` before Neo4j/Qdrant/Redis writes.

### 4.3 Entity Type Contract

All graph writes to `:Entity.type` use uppercase canonical values.

The accepted set is:

```text
AIRCRAFT, CONCEPT, COUNTRY, LOCATION, MILITARY_UNIT, ORGANIZATION, PERSON,
POLICY, REGION, SATELLITE, TREATY, VESSEL, WEAPON_SYSTEM
```

Lowercase extraction outputs may exist at the LLM boundary, but they must be normalized
before Neo4j writes.

The normalizer accepts both lowercase legacy values and uppercase canonical values.
Unknown values must fail closed or map to a documented fallback; they must not be
written to `:Entity.type` silently.

### 4.4 Frontend Rendering Contract

All current codebook roots have explicit event colors or an intentional `other`
fallback. New roots introduced by the codebook update must be covered by tests.

---

## 5. Rollout Strategy

### Phase A: Add NLM Relation Writes

Safe, additive, no migration.

Deliver:

- Relation write templates.
- Ingest loop.
- Tests proving relation statements are emitted.
- Test proving relation writes do not create orphan endpoints.

### Phase B: Align GDELT Codebook And Frontend Roots

Coordinated codebook/frontend change.

Deliver:

- New codebook categories/types.
- Drift test: CAMEO mapping targets are a subset of codebook types.
- Frontend colors for new roots.
- Frontend rendering test for at least one new root.

### Phase C: Canonicalize Entity Types And Migrate Neo4j

Migration-gated change.

Deliver:

- Preflight duplicate report.
- Idempotent duplicate merge migration.
- Code changes that normalize main ingestion and intelligence extraction to uppercase.
- Tests for canonical mapping and graph write parameters.
- Rollback notes.

---

## 6. Non-Goals

This spec does not redesign the whole graph schema.

This spec does not change the Two-Loop rule: write path stays deterministic, read path
stays read-only.

This spec does not add new feed collectors.

This spec does not delete historical prompt versions.

This spec does not require re-running LLM extraction for Patch A.

---

## 7. Open Questions

1. Does NLM persist extracted `Extraction` JSON outside Neo4j?
   - If yes: relation backfill can be done without re-running the LLM.
   - If no: relation backfill requires a controlled re-run or is accepted as
     forward-only.

2. Is APOC guaranteed in every Neo4j runtime profile?
   - If yes: use APOC relationship refactor helpers.
   - If no: implement migration with the Python Neo4j driver.

3. Should `LOCATION` remain long-term, or only as a compatibility bridge?
   - Short-term: needed to stop graph fragmentation.
   - Long-term: can be refined by enrichment/backfill.

---

## 8. Acceptance Criteria

- NLM relations are written through deterministic templates.
- No relation write creates missing endpoint entities.
- Every production GDELT CAMEO mapping target exists in `event_codebook.yaml`.
- Frontend event rendering has explicit colors for new codebook roots.
- All new entity writes use canonical uppercase `Entity.type` values.
- Historical duplicate entity nodes are merged or explicitly reported.
- Drift guard tests fail if CAMEO mappings, prompts, schemas, or graph write contracts
  diverge again.

---

## 9. Risks

Running Patch C before the migration can leave old duplicates and new canonical writes
side by side.

Running the migration while NLM/main ingestion continues writing can race and recreate
duplicates.

Collapsing GDELT types into older categories would lose analytical granularity and make
future CAMEO/backfill work harder.

Changing frontend colors without tests can leave new roots visually indistinguishable
from unknown/default events.
