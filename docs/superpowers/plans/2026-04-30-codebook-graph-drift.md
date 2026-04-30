# Codebook and Graph Type Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or an equivalent TDD workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Implementation-ready for Patch A; decision-ready for Patch B/C

**Goal:** Fix the audited taxonomy/graph drifts without introducing new graph fragmentation:
persist NLM relations, align GDELT codebook targets, canonicalize entity type writes,
migrate historical duplicate entities, and update frontend category rendering.

**Architecture:** Deterministic write path only. Codebook YAML is the durable event
taxonomy. Uppercase NLM entity types become the graph write contract. Graph migration
precedes broad write-path canonicalization.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, Neo4j 5, APOC where available,
Qdrant, FastAPI, React/TypeScript, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-04-30-codebook-graph-drift-design.md`

---

## File Structure

Patch A:

- Modify: `services/data-ingestion/nlm_ingest/write_templates.py`
- Modify: `services/data-ingestion/nlm_ingest/ingest_neo4j.py`
- Modify: `services/data-ingestion/tests/test_nlm_ingest.py`
- Create: `services/data-ingestion/tests/test_nlm_relations.py`

Patch B:

- Modify: `services/intelligence/codebook/event_codebook.yaml`
- Modify: `services/data-ingestion/tests/test_gdelt_cameo_mapping.py`
- Modify: `services/data-ingestion/pipeline.py`
- Modify: `services/intelligence/tests/test_codebook.py`
- Modify: `services/frontend/src/components/layers/EventLayer.tsx`
- Modify/create: frontend event-layer test covering new roots
- Optional modify: `docs/contracts/signals-stream.md`

Patch C:

- Modify: `services/data-ingestion/nlm_ingest/schemas.py`
- Modify: `services/data-ingestion/nlm_ingest/prompts/extraction_v*.txt`
- Modify: `services/data-ingestion/pipeline.py`
- Modify: `services/intelligence/codebook/extractor.py`
- Modify: `services/intelligence/graph/write_templates.py`
- Modify: `services/data-ingestion/nlm_ingest/write_templates.py`
- Create: `services/data-ingestion/migrations/neo4j_entity_type_canonicalization.cypher`
- Optional create: `services/data-ingestion/migrations/neo4j_entity_type_canonicalization.py`
- Add/modify tests for canonical entity type mapping

Operational:

- Update: runbook/session notes if NLM ingestion is paused.
- Optional update: `CLAUDE.md` / architecture docs after implementation.

---

## Preflight: Freeze Writes Before Migration Work

Run this block only before Patch C migration work. Patch A and Patch B do not require
an ingestion freeze.

- [ ] Check whether NLM ingestion or main ingestion is currently running.

- [ ] If migration work begins, pause NLM ingestion and any job that writes
  `(:Entity {name, type})` until duplicate preflight and migration strategy are
  approved.

- [ ] Capture current duplicate baseline:

```cypher
MATCH (e:Entity)
WITH toLower(e.name) AS name_key, collect(e) AS nodes, collect(DISTINCT e.type) AS types
WHERE size(nodes) > 1 AND size(types) > 1
RETURN name_key, types, size(nodes) AS node_count
ORDER BY node_count DESC
LIMIT 50;
```

- [ ] Record whether APOC is available:

```cypher
CALL dbms.procedures()
YIELD name
WHERE name STARTS WITH "apoc."
RETURN count(*) AS apoc_procedures;
```

- [ ] Determine whether NLM extraction JSON is persisted outside Neo4j:

```bash
rg -n "json.dump|write_text|model_dump|Extraction\\(" services/data-ingestion/nlm_ingest/extract.py services/data-ingestion/nlm_ingest -S
```

- [ ] Decide relation backfill mode:
  - persisted JSON exists: backfill relations from stored `Extraction` payloads
  - no persisted JSON: accept Patch A as forward-only or schedule a controlled re-run

---

## Patch A: Persist NLM Relations

Safe, additive, no historical data migration.

### Task A1: Add Relation Templates

- [ ] Add a mapping in `services/data-ingestion/nlm_ingest/write_templates.py`:
  `RELATION_TEMPLATES: dict[str, str]`.

- [ ] Include one deterministic template per `RelationType`:
  `ALLIED_WITH`, `COMMANDS`, `COMPETES_WITH`, `MEMBER_OF`,
  `NEGOTIATES_WITH`, `OPERATES_IN`, `SANCTIONS`, `SUPPLIES_TO`, `TARGETS`.

- [ ] Each template must:
  - `MATCH` source entity by `$source`
  - `MATCH` target entity by `$target`
  - `MERGE` the relationship
  - use `ON CREATE SET` before `ON MATCH SET`
  - set `first_seen`, `evidence`, `confidence`, `last_seen` on create
  - on match, refresh `evidence`, set `last_seen`, and keep confidence as
    `max(existing, new)`

- [ ] Use this Cypher shape for every relation label, with the label hardcoded to the
  template key:

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

- [ ] Do not use generic dynamic relationship-type Cypher.

### Task A2: Write Relations In NLM Ingest

- [ ] In `services/data-ingestion/nlm_ingest/ingest_neo4j.py`, import
  `RELATION_TEMPLATES`.

- [ ] In `_build_statements`, insert relation statements after entity upsert and before
  claim upsert.

- [ ] Skip unknown relation types defensively, but log a warning.

- [ ] Use only validated model fields:
  - `relation.source`
  - `relation.target`
  - `relation.type`
  - `relation.evidence`
  - `relation.confidence`

### Task A3: Tests

- [ ] Put relation-specific coverage in
  `services/data-ingestion/tests/test_nlm_relations.py`.

- [ ] Add/update tests proving the batch contains a relation statement when
  `Extraction.relations` is non-empty.

- [ ] Add a test that all schema `RelationType` literals have a template.

- [ ] Add a test that relation templates use `MATCH` for endpoints and do not contain
  `MERGE (source:Entity` or `MERGE (target:Entity`.

- [ ] Add a test that template labels match their keys:

```python
def test_relation_template_label_matches_key():
    for rel_type, template in RELATION_TEMPLATES.items():
        assert f"[r:{rel_type}]" in template
```

- [ ] Add a test that `_build_statements` orders entity upserts before relation writes
  so relation endpoint `MATCH` clauses can succeed in the same transaction.

- [ ] Run:

```bash
cd services/data-ingestion
uv run pytest tests/test_nlm_ingest.py tests/test_nlm_schemas.py tests/test_nlm_relations.py -q
uv run pytest -q
```

---

## Patch B: Align GDELT CAMEO Mapping With Codebook And Frontend

Coordinated taxonomy/frontend change.

### Task B1: Expand Codebook

- [ ] Add top-level category `civil` with at least:
  - `civil.protest`
  - two reserve types, for example `civil.demonstration` and `civil.unrest`

- [ ] Add top-level category `posture` with at least:
  - `posture.military`
  - two reserve types, for example `posture.deployment` and `posture.mobilization`

- [ ] Add top-level category `conflict` with at least:
  - `conflict.coercion`
  - `conflict.assault`
  - `conflict.armed`
  - `conflict.mass_violence`
  - two reserve types, for example `conflict.clash` and `conflict.shelling`

- [ ] Use English labels and descriptions.

- [ ] Keep `other.unclassified` unchanged.

### Task B2: Drift Guard Test

- [ ] Add a data-ingestion test:

```python
def test_cameo_targets_subset_of_codebook_types():
    from gdelt_raw.cameo_mapping import CAMEO_ROOT_TO_CODEBOOK
    from pathlib import Path
    import yaml

    codebook_path = Path(__file__).parents[2] / "intelligence" / "codebook" / "event_codebook.yaml"
    codebook = yaml.safe_load(codebook_path.read_text())
    types = {
        entry["type"]
        for category in codebook["categories"].values()
        for entry in category["types"]
    }
    assert set(CAMEO_ROOT_TO_CODEBOOK.values()) <= types
```

- [ ] Add or extend intelligence codebook validation to check uniqueness and dotted
  `category.specific` format.

### Task B2.5: Runtime Guard For LLM Codebook Drift

- [ ] In `services/data-ingestion/pipeline.py`, validate LLM-produced
  `codebook_type` values against `event_codebook.yaml` before any Neo4j, Qdrant, or
  Redis write.

- [ ] Unknown values must be logged and remapped to `other.unclassified`.

- [ ] Add a test where `_call_vllm` returns `{"codebook_type": "nonsense.invalid"}`
  and the downstream enrichment/write payload uses `other.unclassified`.

### Task B3: Frontend Category Colors

- [ ] Update `services/frontend/src/components/layers/EventLayer.tsx` color map for:
  - `civil`
  - `conflict`
  - `posture`
  - `social`
  - `humanitarian`
  - `infrastructure`
  - `other`

- [ ] Add or extend EventLayer tests so at least one `conflict.*` event does not render
  with the default unknown color.

- [ ] Optionally update `docs/contracts/signals-stream.md` examples to include one
  `conflict.*` or `civil.*` codebook type.

### Task B4: Verification

```bash
cd services/intelligence
uv run pytest tests/test_codebook.py -q
uv run pytest -q

cd services/data-ingestion
uv run pytest tests/test_gdelt_cameo_mapping.py tests/test_pipeline.py -q
uv run pytest -q

cd services/frontend
npm run test -- EventLayer
```

---

## Patch C: Canonicalize Entity Types And Migrate Neo4j

Migration-gated. Do not ship write-path changes before migration preflight is reviewed.

### Task C1: Define Canonical Mapping

- [ ] Add the canonical entity type set and normalizer in
  `services/data-ingestion/nlm_ingest/schemas.py`; this is the single source of truth.

```text
AIRCRAFT, CONCEPT, COUNTRY, LOCATION, MILITARY_UNIT, ORGANIZATION, PERSON,
POLICY, REGION, SATELLITE, TREATY, VESSEL, WEAPON_SYSTEM
```

- [ ] Add lowercase-to-uppercase mapping:

```text
person -> PERSON
organization -> ORGANIZATION
location -> LOCATION
weapon_system -> WEAPON_SYSTEM
satellite -> SATELLITE
vessel -> VESSEL
aircraft -> AIRCRAFT
military_unit -> MILITARY_UNIT
```

- [ ] The normalizer must be idempotent:
  `normalize_entity_type("PERSON") == "PERSON"`.

- [ ] If `services/intelligence/codebook/extractor.py` cannot import the normalizer
  because of build-context boundaries, add a pinned local mirror plus a drift test
  comparing its canonical set and mapping to `nlm_ingest.schemas`.

- [ ] Add `LOCATION` to `services/data-ingestion/nlm_ingest/schemas.py`.

- [ ] Version the NLM prompt instead of overwriting the old prompt:
  create `extraction_v2.txt` or `extraction_v1_1.txt`, depending on local convention.

### Task C2: Add Canonicalization Tests

- [ ] Main ingestion test: extracted lowercase entity types are normalized before
  Neo4j write parameters are built.

- [ ] Intelligence extractor test: entity schema/prompt accepts or emits canonical
  uppercase values.

- [ ] NLM schema test: `LOCATION` is accepted and invalid values still fail.

- [ ] Normalizer idempotence test: uppercase canonical input returns itself.

- [ ] Normalizer legacy test: lowercase legacy input returns the canonical uppercase
  value.

- [ ] Drift test: graph write paths never pass lowercase values to `:Entity.type`.

### Task C3: Migration Preflight

- [ ] Create a dry-run report query or Python script that lists duplicate groups by
  normalized name and canonicalized type.

- [ ] Include counts for:
  - duplicate groups
  - nodes to merge
  - relationships to move
  - nodes with ambiguous type conflicts

- [ ] Apply survivor rules:
  - single canonical uppercase type wins
  - `COUNTRY` > `REGION` > `LOCATION` for geographic ambiguity
  - highest relationship cardinality breaks same-type ties
  - semantic conflicts such as `PERSON` vs `ORGANIZATION` go to manual review

- [ ] Treat manual-review conflicts as a stop condition for automated merge apply.

- [ ] Review the report before applying writes.

### Task C4: Migration Apply

- [ ] If APOC is available, implement idempotent merge with relationship transfer.

- [ ] If APOC is not available, implement a Python-driver migration:
  - choose survivor node
  - recreate outgoing relationships from duplicate to survivor
  - recreate incoming relationships to survivor
  - merge properties conservatively
  - delete duplicate node after relationship transfer

- [ ] Migration must be re-runnable without creating duplicate relationships.

- [ ] Migration must not merge two semantically different entities solely because names
  match. Ambiguous cases go to a report.

### Task C5: Switch Write Paths

- [ ] Update `services/data-ingestion/pipeline.py` to normalize entity types before
  building Neo4j statements by calling the shared normalizer.

- [ ] Update `services/intelligence/codebook/extractor.py` prompt/schema to use
  uppercase canonical types or normalize before graph writes.

- [ ] Update any tests or fixtures that assert lowercase entity types in graph writes.

### Task C6: Verification

```bash
cd services/data-ingestion
uv run pytest tests/test_pipeline.py tests/test_nlm_schemas.py tests/test_nlm_ingest.py -q
uv run pytest -q

cd services/intelligence
uv run pytest tests/test_codebook.py tests/test_entity_extractor_refactor.py tests/test_write_templates.py -q
uv run pytest -q
```

- [ ] Run duplicate preflight after migration; expected duplicate groups should be zero
  or explicitly waived.

- [ ] Resume paused ingestion only after post-migration preflight is clean.

---

## CI Hardening

- [ ] Add relation coverage guard:
  every `RelationType` literal has a write template.

- [ ] Add relation label guard:
  every relation template uses a relationship label matching its `RelationType` key.

- [ ] Add relation statement ordering guard:
  NLM entity upsert statements appear before relation statements.

- [ ] Add CAMEO/codebook guard:
  every `CAMEO_ROOT_TO_CODEBOOK` value exists in `event_codebook.yaml`.

- [ ] Add entity type guard:
  every graph write path uses canonical uppercase `Entity.type`.

- [ ] Add frontend category guard:
  every top-level codebook root has either an explicit color or an explicit
  documented fallback.

---

## Rollback

Patch A rollback:

- Remove relation loop and templates.
- No data migration required, but existing relation edges can remain harmlessly.

Patch B rollback:

- Revert codebook additions only if no GDELT data with those types has been written,
  or keep aliases/fallback mapping until data is migrated.
- Revert frontend colors independently if needed.

Patch C rollback:

- Prefer rolling back code defaults to the previous entity type mapping.
- Do not attempt to split already merged entities without a database snapshot.
- Keep a Neo4j backup before applying the migration.

---

## Implementation Order

1. Patch A: relation writes and tests.
2. Patch B: codebook/frontend drift fix, runtime codebook guard, and drift tests.
3. Pause ingestion only for Patch C migration work.
4. Patch C preflight.
5. Patch C migration.
6. Patch C write-path canonicalization.
7. Run full service test suites and post-migration duplicate preflight.
8. Resume ingestion.

Do not ship Patch C write-path changes before the migration preflight and migration
plan are approved.
