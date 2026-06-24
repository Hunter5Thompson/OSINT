# Relation v2 — Validated Canonical/Candidate Split for NLM Relations

**Status:** Design approved 2026-06-20. Ready for implementation plan.
**Owner area:** `services/data-ingestion/nlm_ingest/`, taxonomy coherence via `intel-codebook-curator`.
**Related:** memory `project_nlm_relations_taxonomy`, `project_writepath_audit`, `project_graph_integrity_geo`. NLM 81-NB backbone-only run (2026-06-20).

## 1. Problem & Context

The NLM extraction pipeline produces Entity-Entity relations via a 35B model. Audit of the
2026-06 corpus (941 relations over 91 source-extractions) showed a **systematic taxonomy
error**, not a few outliers:

- The relation enum has 9 types but **no `OPERATES`**. The model overloads `OPERATES_IN`
  (locative) to mean "operates [a platform]": `Germany —OPERATES_IN→ F-127`, `USA —OPERATES_IN→ Patriot`.
  `OPERATES_IN` was **307/941 (33%)** of all relations — the dominant, broken type.
- `COMMANDS` reversed/over-broad (`USA —COMMANDS→ USS Lincoln`, `Gerasimov —COMMANDS→ Russia`).
- `CONCEPT`/`POLICY` endpoints abused (`Texas —OPERATES_IN→ Artificial Intelligence`).
- The enum is only a **template-router, not a quality filter**: 0% were skipped as out-of-enum;
  everything mapped to a template and would have been written. ≥26% were type-role-suspect (a
  floor — same-type direction errors like `Europe —TARGETS→ Russia` are not type-detectable).

**Decision already shipped:** the 81-NB run ingested **backbone only** (Source/Document/Entity/
Claim/EXTRACTED_FROM; 80 Documents, 795 Claims = 795 EXTRACTED_FROM = 795 Qdrant points, **0
relation edges**). The 941 relations are preserved as candidates in
`odin-data/notebooklm/relation_candidates.jsonl`. Pre-existing 269 smoke-NB relation edges were
export-first deleted. The canonical graph is now claim-centric and clean.

Relation v2 builds the **validated, derived layer** on top: relations re-enter the canonical
graph only when they pass hard type/direction gates. Direct relations are a derived, validated
layer over the claim-centric truth, not the primary truth.

## 2. Goals / Non-Goals

**Goals**
- Add `OPERATES` and tighten `OPERATES_IN`/`COMMANDS`/`TARGETS`/`ALLIED_WITH` (prompt + role gates).
- A **pure role validator** that splits extracted relations into canonical (written as edges) vs
  candidate (structured staging record with a rejection reason), based on endpoint entity types.
- Canonical edges carry **support-set provenance** (multi-notebook safe, per-NB reversible).
- A mandatory **`relations-preview`** command to measure outcomes before any ingest/re-extract.

**Non-Goals (explicit out of scope for v2)**
- No curation UI, no review/promotion workflow, no `inferred_correct_type` auto-correction.
- No `TARGETS` canonical writes (candidate-only in v2; promotable later).
- No reconciliation of SUV's existing `OPERATES` property model onto the support-set (curator follow-up).
- No RSS write-path adoption of the validator (future; the validator is designed to be reusable there).
- No new `COOPERATES_WITH` type (relations that would need it stay candidate).

## 3. Architecture (Approach A: pure validator at ingest-time)

```
relation_rules.py       RELATION_ROLE_RULES  (declarative role matrix)
relation_validator.py   validate_relations(extraction) -> ValidationResult   (pure, no I/O)
write_templates.py       canonical relation MERGE templates (fixed dict, support-set)
ingest_neo4j.py          builds/sends Neo4j statements for canonical relations ONLY
cli.py                   relations-preview (read-only) ; ingest orchestration:
                           validate -> append candidates jsonl -> neo4j canonical -> qdrant claims
prompts/extraction_v4.txt  prompt with OPERATES + tightened OPERATES_IN/COMMANDS/TARGETS/ALLIED_WITH
```

- The **validator is pure** (relations + entity-type map → canonical[]/candidate[]; no file or DB
  I/O). The CLI/orchestrator owns artifact writes (candidates jsonl) and graph writes; `ingest_neo4j`
  stays focused on Neo4j statements. Graph-write and artifact-write never mix in one module.
- Re-tuning is cheap: change rules → run tests → run preview/ingest. **No re-extract needed for
  taxonomy logic changes.** Re-extract is only needed for prompt changes.

## 4. Role Matrix (`RELATION_ROLE_RULES`)

Rule shape per type: `{source_types: set, target_types: set, symmetric: bool, mode: canonical|candidate_only}`.

Groups: **ACTOR** = {COUNTRY, ORGANIZATION, MILITARY_UNIT} · **PLACE** = {COUNTRY, REGION, LOCATION}
· **PLATFORM** = {WEAPON_SYSTEM, VESSEL, AIRCRAFT, SATELLITE}.

| Type | source ∈ | target ∈ | symmetric | mode |
|---|---|---|---|---|
| `OPERATES` *(new)* | ACTOR | PLATFORM | no | canonical |
| `OPERATES_IN` *(strict locative)* | ACTOR ∪ {PERSON} | PLACE | no | canonical |
| `COMMANDS` *(narrow)* | {PERSON, MILITARY_UNIT, ORGANIZATION} | {MILITARY_UNIT, ORGANIZATION} | no | canonical |
| `SANCTIONS` | {COUNTRY, ORGANIZATION} | {COUNTRY, ORGANIZATION, PERSON} | no | canonical |
| `SUPPLIES_TO` | {COUNTRY, ORGANIZATION} | ACTOR | no | canonical |
| `MEMBER_OF` | ACTOR ∪ {PERSON} | {ORGANIZATION, TREATY} | no | canonical |
| `ALLIED_WITH` | {COUNTRY, ORGANIZATION} | {COUNTRY, ORGANIZATION} | yes | canonical |
| `COMPETES_WITH` | {COUNTRY, ORGANIZATION} | {COUNTRY, ORGANIZATION} | yes | canonical |
| `NEGOTIATES_WITH` | ACTOR ∪ {PERSON} | ACTOR ∪ {PERSON} | yes | canonical |
| `TARGETS` | ACTOR ∪ PLATFORM | ACTOR ∪ PLACE ∪ PLATFORM | no | **candidate_only** |

- `CONCEPT` and `POLICY` appear in **no** rule → any relation with such an endpoint → candidate.
  (Those belong in Claims, not canonical edges.)
- `TARGETS` is **candidate_only** in v2: the type gate cannot catch same-type direction errors
  (COUNTRY→COUNTRY). It is collected as a structured candidate (`failed_gate:
  relation_type_candidate_only`) and measured in the smoke; promotable to canonical later if v4
  proves direction reliability.
- `ALLIED_WITH` excludes MILITARY_UNIT (a unit is not "allied with" strategically; without a
  `COOPERATES_WITH` type, prefer candidate over a false alliance edge).

## 5. Validation Semantics

`validate_relations(extraction) -> ValidationResult` where `ValidationResult` has
`canonical: list[CanonicalRelation]` and `candidates: list[CandidateRelation]`.

Per raw relation:
1. **Resolve endpoint types** from the extraction's `entities` list, keyed by the **same
   `canonicalize` function the write uses for MATCH** (no name mismatch). If either endpoint name
   does not resolve to a known entity/type → candidate `failed_gate: entity_type_unresolved`.
2. **Unknown relation type** (not in `RELATION_ROLE_RULES`) → candidate `failed_gate:
   relation_type_unknown`, `rejection_reason: "Unknown relation type: <type>"`.
   *(Requires `Relation.type` relaxed to `str` at the validator input boundary — see §6. The
   validator is the single classification point; the old silent `_build_items` skip is removed.)*
3. **mode == candidate_only** (TARGETS) → candidate `failed_gate: relation_type_candidate_only`,
   even when endpoint types are plausible.
4. **Role check:** `source_type ∈ rule.source_types` and `target_type ∈ rule.target_types`.
   Fail → candidate `failed_gate: "<TYPE>.source_type"` or `"<TYPE>.target_type"`,
   `rejection_reason: "<TYPE> requires <field> in <allowed>, got <actual>"`.
5. **Pass** → canonical. For symmetric types, normalize endpoints (see §6).

Fail-closed: anything invalid/unclear becomes a structured candidate, never a silent drop.

**Candidate record** (appended by the orchestrator to `relation_candidates.jsonl`):
```json
{ "candidate_id","notebook_id","source_kind","source_id","prompt_version","extraction_model",
  "source","source_type","type","target","target_type","evidence","confidence",
  "status":"candidate","failed_gate":"OPERATES_IN.target_type",
  "rejection_reason":"OPERATES_IN requires target_type in LOCATION|REGION|COUNTRY, got VESSEL",
  "relation_hash","recorded_at" }
```
No `inferred_correct_type`. `failed_gate` categories drive smoke error-rate drilldowns.
`candidate_id = hash(provenance_key | failed_gate)` is **deterministic** so the candidate set is
idempotent under retries (see §10). `recorded_at` is informational and excluded from the id.

## 6. Canonical Write Semantics (support-set, SUV-safe)

Templates are a **fixed dict keyed by RelationType literal** — built at code time, never an
f-string from model output (no dynamic labels / Cypher injection). The dict contains **only
`mode == canonical` types**; candidate_only types (TARGETS) have **no write template** and are
never emitted to Neo4j (enforced by a test).

```cypher
-- Bind TYPE too: entities are MERGE-d on {name,type} (UPSERT_ENTITY), so a name-only MATCH can
-- hit the wrong node or multiple same-named nodes of different types. The validated canonical
-- relation already carries the resolved endpoint types. (The current v1 templates use name-only
-- MATCH and have this latent bug; v2 fixes it.)
MATCH (s:Entity {name:$source, type:$source_type})   -- MATCH not MERGE: endpoints pre-exist
MATCH (t:Entity {name:$target, type:$target_type})   --   (UPSERT_ENTITY ran first); no phantoms
MERGE (s)-[r:OPERATES]->(t)
ON CREATE SET r.first_seen=datetime(), r.last_seen=datetime(),
              r.confidence=$confidence,
              r.provenance_keys=[$prov_key], r.notebook_ids=[$notebook_id],
              r.evidence_samples=[$evidence], r.support_count=1
ON MATCH SET  r.last_seen=datetime(),
              r.confidence = CASE WHEN $confidence > coalesce(r.confidence,0)
                                  THEN $confidence ELSE r.confidence END,
              r.provenance_keys = CASE WHEN NOT $prov_key IN coalesce(r.provenance_keys,[])
                                  THEN coalesce(r.provenance_keys,[]) + [$prov_key]
                                  ELSE r.provenance_keys END,
              r.notebook_ids   = CASE WHEN NOT $notebook_id IN coalesce(r.notebook_ids,[])
                                  THEN coalesce(r.notebook_ids,[]) + [$notebook_id]
                                  ELSE r.notebook_ids END,
              r.evidence_samples = CASE WHEN size(coalesce(r.evidence_samples,[]))<5
                                   AND NOT $evidence IN coalesce(r.evidence_samples,[])
                                   THEN coalesce(r.evidence_samples,[]) + [$evidence]
                                   ELSE r.evidence_samples END
WITH r
SET r.support_count = size(coalesce(r.provenance_keys,[]))   -- exact, AFTER append-dedup
```

**Hashing / provenance composition** (symmetric sort happens BEFORE the hash):
```
endpoint        = (name, type)                                    # full tuple, never name-only
canonical_pair  = (source_endpoint, target_endpoint)              # asymmetric: as-is
canonical_pair  = sort(source_endpoint, target_endpoint)          # symmetric: sort the (name,type) tuples
relation_hash   = hash(src.name | src.type | type | tgt.name | tgt.type | normalized_evidence)
provenance_key  = notebook_id | source_kind | source_id | prompt_version | extraction_model | relation_hash
```
`normalized_evidence` = whitespace-collapsed, trimmed evidence text, so the *same* citation hashes
stably; a *different* evidence sentence for the same edge is a distinct support instance (so
`support_count` reflects supports, not just notebooks). `notebook_ids` is deduped separately.
- Same factual extract from same source → idempotent (provenance_key unchanged).
- Same edge from another notebook/source → additional support (append-deduped; support_count++).
- Symmetric A–B and B–A → same `canonical_pair` → same MERGE target AND same `relation_hash`/
  `provenance_key` (sorting before hashing prevents divergent keys for the two directions).

**Property rules**
- Cypher list append is always list-concat: `coalesce(r.x,[]) + [$v]`.
- `support_count = size(provenance_keys)`, set in a trailing `WITH r SET` so it reflects the
  post-append list.
- `confidence` is the max/aggregate over supports.
- `evidence_samples` (≤5) are **debug/inspectability only, not the provenance store**. Full
  provenance = `provenance_keys` + the candidate/extraction backups.

**SUV-safety:** the template never touches `r.data_source`. A shared `OPERATES` edge already
written by SUV (`data_source:"suv.report"`) keeps its property; v2 only **adds** the support-set
props. Full reconciliation of the shared OPERATES property model is a curator follow-up (out of
scope). v2 must not clobber existing SUV scalar props.

**Reversal:** for a given `notebook_id`, drop every `provenance_keys` entry whose leading
`notebook_id|` component matches (a notebook may contribute several supports), drop that id from
`notebook_ids`, recompute `support_count = size(provenance_keys)`; delete the edge only when
`support_count → 0`.

## 7. Prompt v4 + Taxonomy Change Surface

`prompts/extraction_v4.txt` (new `prompt_version`):
- **`OPERATES` (new):** "actor operates a platform/system → `USA —OPERATES→ Patriot`, `Germany —OPERATES→ F-127`."
- **`OPERATES_IN` strictly locative:** "actor operating IN a location/region/country → `NATO —OPERATES_IN→ Baltic Sea`. For operating a weapon/platform use `OPERATES`."
- **`COMMANDS` narrow:** "person/unit/org commands a military unit/org, NOT a country → `Gerasimov —COMMANDS→ Russian Armed Forces`, not `→ Russia`."
- **`TARGETS` direction + counter-examples:** "source = attacker/threatener, target = the attacked → `Russia —TARGETS→ Ukraine`." (Still candidate-only in v2; the prompt fix serves the smoke measurement of whether direction is learnable.)
- **`ALLIED_WITH`:** COUNTRY/ORGANIZATION only.

**`OPERATES` must be synced coherently across four points** (via `intel-codebook-curator`, TDD):
1. `schemas.py` `RelationType` literal. 2. `RELATION_TEMPLATES` (write). 3.
`services/intelligence/codebook/extractor.py` (drift guard). 4. the v4 prompt.

## 8. Out-of-enum / schema relaxation (in scope, small)

Today `Relation.type` is a `Literal` and out-of-enum relations are silently skipped at
`_build_items` — bad for measurability. Relax the validator-input relation type to `str` so
unknown types are preserved and become structured candidates (`relation_type_unknown`). The
validator becomes the single classifier: known+valid-roles → canonical; known+bad-roles →
candidate(role); candidate_only → candidate; unknown → candidate. If this proves larger than a
small change during implementation, it may be split out — but the intent is to remove the silent
skip.

## 9. Preview command (mandatory)

`odin-ingest-nlm relations-preview [--report]`:
- reads extraction JSONs, builds the entity-type map, runs `validate_relations` (read-only, no
  DB/edge writes),
- prints: **canonical by type**, **candidates by `failed_gate`**, **unresolved-endpoint count**,
  (optional confidence ranges),
- with `--report`, writes `odin-data/notebooklm/relation_validation_preview.json`.
This is how outcomes are measured before any ingest or 81-NB re-extract.

## 10. Ingest orchestration (cli.py)

Per notebook source: `validate_relations(extraction)` → record `candidates` → build+send Neo4j
statements for `canonical` relations (support-set MERGE) → existing claim Qdrant writes. The
backbone writes (Source/Document/Entity/Claim/EXTRACTED_FROM) are unchanged.

**Candidate write is idempotent** (the validator is pure, so the candidate set is a deterministic
function of extractions + rules). The orchestrator does **not** blind-append per notebook — a
retry after a partial failure (e.g. the Neo4j-auth 401/429 we hit on the 81-NB run) must not
duplicate records. Implementation: recompute the candidate set and write
`relation_candidates.jsonl` **atomically** (temp → rename), or upsert keyed by the deterministic
`candidate_id` (dedup on write). Either way, re-running ingest yields the same candidate file and
clean smoke metrics. (The Neo4j support-set MERGE is already idempotent by construction.)

## 11. Testing (TDD gates)

Unit (pure, fast):
- Every `RelationType` literal has exactly one rule; every rule references only known `EntityType`.
- `TARGETS.mode == candidate_only`; `ALLIED_WITH` source/target == {COUNTRY, ORGANIZATION}.
- `OPERATES_IN`→PLATFORM target ⇒ candidate (`failed_gate` set).
- COUNTRY `OPERATES` PLATFORM ⇒ canonical.
- `COMMANDS` PERSON→COUNTRY ⇒ candidate.
- CONCEPT/POLICY endpoint ⇒ candidate.
- `entity_type_unresolved` ⇒ candidate; unknown type ⇒ candidate(`relation_type_unknown`).
- Validator is pure (no I/O).
- Symmetric: A–B and B–A yield same `canonical_pair`, `relation_hash`, `provenance_key`.
- Support-set: same source idempotent (provenance_keys length stable); different notebook →
  support_count++ and both notebook_ids present.
- **SUV-safety:** existing edge with `data_source` set → after NLM write, `data_source` preserved,
  support-set added, `support_count` exact.
- Templates are a fixed dict (no dynamic label); Cypher list append uses `+ [$v]`.
- **TARGETS (candidate_only) has no canonical write template** and is never emitted to Neo4j
  (assert the template dict has no TARGETS key; assert validator never returns TARGETS as canonical).
- Canonical write **MATCH binds both `name` and `type`** for each endpoint (not name-only).
- **Candidate write idempotency:** running ingest twice over the same extractions yields the same
  `relation_candidates.jsonl` — no duplicate `candidate_id`s (atomic recompute or id-dedup).

## 12. 5-NB Smoke + hard Go/No-Go

Smoke NB (same problem set): F127, Pentagon/Tech, Hybrid Warfare, Petraeus, Drone Warfare.
Flow: re-extract these 5 with v4 → `relations-preview --report` → measure.

**Go for the 81-NB re-extract/ingest requires ALL of:**
- `OPERATES_IN → PLATFORM` in canonical == **0**
- `COMMANDS → COUNTRY` in canonical == **0**
- CONCEPT/POLICY endpoint in canonical == **0**
- manual spot-check **canonical precision ≥ 90%** on the 5 smoke NB
- `TARGETS` 100% candidate-only

If canonical precision < 90% (or any hard class > 0): sharpen prompt/rules, repeat the smoke. Do
**not** start the 81-NB run regardless.

## 13. Open considerations / future

- `TARGETS` promotion to canonical once v4 direction is proven (needs a direction signal the type
  gate lacks — e.g., evidence-based or a future asymmetry cue).
- SUV `OPERATES` property-model reconciliation onto the support-set (curator).
- Validator reuse on the RSS write-path (same taxonomy problem exists there).
- Possible `COOPERATES_WITH` type to rescue MILITARY_UNIT alliances currently sent to candidate.
