# Qdrant Collection Source-of-Truth Sync - Design Spec

**Date:** 2026-04-30
**Status:** Decision-ready
**Scope:** Qdrant collection naming, runtime documentation, Phase 1 schema defense,
and Phase 2 migration guardrails

---

## 1. Motivation

The Graph-RAG audit found a real drift between documentation and runtime:

- `TASKS.md` declares `odin_v2` as the canonical Qdrant collection.
- Backend, intelligence, data-ingestion, and vision-enrichment code default to `odin_intel`.
- Local Qdrant currently contains `odin_intel` with an active corpus. The exact point
  count is a moving snapshot value.
- Local Qdrant does not contain `odin_v2`.

Blindly changing the runtime default to `odin_v2` would point RAG at an empty or missing
collection and break current retrieval. The correct move is to make the current state
explicit, then plan the Phase 2 migration separately.

---

## 2. Decision

`odin_intel` is the current production/runtime collection.

`odin_v2` is the Phase 2 target collection for hybrid retrieval with dense vectors plus
sparse/BM25 vectors.

The project documentation should stop treating `odin_v2` as the current runtime value.
It should describe the two-stage state clearly:

| Name | Status | Schema | Purpose |
|---|---|---|---|
| `odin_intel` | Current runtime | Dense 1024-dim cosine vector | Existing RAG corpus and ingestion target |
| `odin_v2` | Phase 2 target | Named dense vector plus sparse/BM25 vector | Future hybrid search collection |

---

## 3. Evidence

Runtime evidence from local Qdrant on 2026-04-30:

```text
collections:
- odin_intel
- odin_smoke_test

odin_intel:
- points_count: active corpus; observed around 25k-26k during audit
- vectors: size=1024, distance=Cosine
- sparse_vectors: none

odin_v2:
- not found
```

Code evidence:

- `services/backend/app/config.py` defaults `qdrant_collection` to `odin_intel`.
- `services/intelligence/config.py` defaults `qdrant_collection` to `odin_intel`.
- `services/data-ingestion/config.py` defaults `qdrant_collection` to `odin_intel`.
- `services/vision-enrichment/config.py` defaults `qdrant_collection` to `odin_intel`.
- `services/intelligence/rag/retriever.py` treats hybrid search as Phase 2 and falls
  back to dense-only search.
- `services/data-ingestion/gdelt_raw/cli.py` and
  `services/data-ingestion/feeds/gdelt_raw_collector.py` currently bypass Pydantic
  settings with direct `os.getenv("QDRANT_COLLECTION", "odin_intel")` reads; these must
  be refactored before any future cutover.

---

## 4. Current Runtime Contract

All current services should read/write `odin_intel` unless explicitly configured
otherwise through the shared service settings layer.

Runtime code should not read `QDRANT_COLLECTION` directly with `os.getenv`. Direct env
reads create hidden defaults that drift independently from Pydantic settings and must
be treated as contract violations outside tests, config modules, `.env.example`, and
migration scripts.

The current schema is dense-only:

```text
vector:
  size: 1024
  distance: Cosine
```

This matches the active TEI/Qwen3 embedding setup and the current ingestion code paths.

All services that touch Qdrant must fail fast or refuse writes when the configured
collection schema does not match the code path:

- dense-only mode requires unnamed vector `size=1024`, `distance=Cosine`
- hybrid mode requires named dense vector `dense` with `size=1024`, `distance=Cosine`
- hybrid mode requires sparse vector config for the sparse/BM25 branch

The schema check belongs in startup/preflight code, not only in an ad-hoc doctor
command.

---

## 5. Hybrid Activation Flag

The Phase 2 path is activated by an explicit `enable_hybrid` flag, not by collection
name alone.

Current state:

- `services/intelligence/config.py` already exposes `enable_hybrid: bool = False`.
- `services/intelligence/rag/retriever.py` already treats hybrid as Phase 2 and falls
  back to dense-only search when sparse support is unavailable.

Target state before cutover:

- All Qdrant writers and readers that need to discriminate Phase 1 vs Phase 2 behavior
  expose the same explicit flag or consume a shared deployment flag.
- The code path uses `enable_hybrid` to choose unnamed dense writes versus named
  dense+sparse writes.
- Collection name is configuration, not the schema discriminator.
- If `enable_hybrid=True` and the configured collection lacks the Phase 2 schema, the
  service fails fast before writes or serves a documented read-only fallback.

This keeps rollback explicit: disable hybrid and point readers back to the dense-only
collection. It avoids a silent default flip from `odin_intel` to an empty `odin_v2`.

---

## 6. Phase 2 Target Contract

`odin_v2` should only become the default after a real migration has landed.

Target schema:

```python
vectors_config={
    "dense": VectorParams(size=1024, distance=Distance.COSINE),
}
sparse_vectors_config={
    "bm25": SparseVectorParams(modifier=Modifier.IDF),
}
```

Required before switching defaults:

- Create `odin_v2` with named dense and sparse vector config.
- Update ingestion to write named vectors, not the current unnamed dense vector.
- Implement sparse/BM25 payload generation or Qdrant-side sparse query support.
- Backfill/reindex the existing `odin_intel` corpus into `odin_v2`.
- Update retriever query code to use Qdrant Query API / prefetch / RRF. This is a
  non-trivial Phase 2 design item requiring tokenizer choice, sparse vector generation,
  score fusion/RRF tuning, and latency validation.
- Verify counts, sample retrieval quality, and rollback path.

Cutover must be coordinated in phases:

```text
Phase 0: Phase 1 hardening
  - defaults stay odin_intel
  - direct env bypasses removed
  - schema doctor/startup checks in place

Phase 1: Build odin_v2
  - create named dense+sparse schema
  - backfill from an odin_intel snapshot
  - validate point counts, payload parity, and sample retrieval

Phase 2: Dual-write transition
  - data-ingestion writes to odin_intel and odin_v2 for an agreed window
  - readers remain on odin_intel
  - monitor write parity and Qdrant errors

Phase 3: Atomic read switch
  - switch backend/intelligence/vision readers together via feature flag/deployment flag
  - keep data-ingestion dual-write during validation
  - compare query parity, latency, and recall@k against sample sets

Phase 4: v2-only writes
  - after validation, stop odin_intel writes
  - keep odin_intel read-only as emergency snapshot

Phase 5: Retirement
  - drop odin_intel only after a full validation window and explicit operator approval
```

Backend/readers must not switch to `odin_v2` while data-ingestion still writes only to
`odin_intel`; that creates a split-brain retrieval surface.

---

## 7. Non-Goals

This spec does not migrate data.

This spec does not enable hybrid search.

This spec does not delete `odin_intel`.

This spec does not rename the current live collection in place.

This spec does not fully design the Phase 2 hybrid migration. It defines guardrails and
required cutover discipline; the sparse-vector/backfill/retriever migration needs a
separate implementation spec.

---

## 8. Acceptance Criteria

- `TASKS.md` no longer implies `odin_v2` is the current runtime collection.
- Architecture documentation names `odin_intel` as Phase 1 runtime and `odin_v2` as
  Phase 2 target.
- Service defaults remain `odin_intel` until the Phase 2 migration is implemented.
- Direct `QDRANT_COLLECTION` env reads are removed from runtime code paths.
- Doctor/startup schema checks reject wrong vector size, wrong distance, and missing
  sparse config when hybrid is enabled.
- Cross-service tests prevent qdrant collection defaults from drifting independently.
- A separate migration plan exists for creating, validating, dual-writing, and cutting
  over to `odin_v2`.
- Tests/docs prevent future accidental default flips to a missing collection.

---

## 9. Risks

Changing defaults before migration would make RAG return empty results or collection
not found errors.

Keeping the current documentation unchanged will keep confusing future Qdrant PRs.

Migrating in place is risky because the current schema is unnamed dense-vector only,
while the target hybrid schema needs named vectors and sparse vector config.

Using collection name as the only schema discriminator is risky because a service can
write Phase 2 named vectors to a Phase 1 unnamed-vector collection or the reverse.
The code path must be selected by `enable_hybrid` and defended by schema preflight.
