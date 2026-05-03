# Qdrant Collection Source-of-Truth Sync Implementation Plan

**Status:** Phase 1 implementation-ready. Phase 2 hybrid migration requires a separate
implementation spec before work starts.

**Goal:** Make `odin_intel` the documented Phase 1 runtime collection and reserve
`odin_v2` for the Phase 2 hybrid-search migration.

**Architecture:** Documentation and config contracts are aligned first. Runtime defaults
stay on `odin_intel`. Direct `QDRANT_COLLECTION` env reads are removed from runtime
code. `odin_v2` is introduced only through an explicit hybrid flag, schema checks,
dual-write transition, backfill, validation, and rollback in a separate Phase 2 plan.

**Tech Stack:** Qdrant 1.13+, FastAPI backend, data-ingestion, intelligence service,
vision-enrichment, TEI/Qwen3 embeddings, pytest.

---

## File Structure

- Modify: `TASKS.md`
  - Replace the canonical "Collection: odin_v2" line with a Phase 1/Phase 2 split.
  - Keep TASK-103/TASK-104 `odin_v2` content as Phase 2 target language.

- Modify: `architecture.md`
  - Add explicit Qdrant collection lifecycle: `odin_intel` now, `odin_v2` later.

- Modify: `docs/architecture.md`
  - Must mirror the root architecture update; both files currently exist.

- Optional modify: `README.md`
  - Keep operational examples using `odin_intel`.
  - Add a short note that `odin_v2` is the hybrid-search migration target.

- Modify: `services/data-ingestion/gdelt_raw/cli.py`
  - Replace direct `os.getenv("QDRANT_COLLECTION", "odin_intel")` with Settings.

- Modify: `services/data-ingestion/feeds/gdelt_raw_collector.py`
  - Replace direct `os.getenv("QDRANT_COLLECTION", "odin_intel")` with Settings.

- Create/modify: service config tests
  - Backend, intelligence, data-ingestion, and vision-enrichment defaults.
  - Cross-service default consistency.
  - Static guard against direct collection env reads in runtime code.

---

## Task 1: Patch Documentation Truth

- [ ] Update `TASKS.md` tech-stack block:
  - Runtime collection: `odin_intel`
  - Phase 2 target: `odin_v2` with dense + sparse/BM25

- [ ] Update `TASKS.md` TASK-103/TASK-104 wording:
  - Make all `odin_v2` examples clearly Phase 2-only.
  - Add warning: do not flip defaults before backfill and retriever migration.

- [ ] Update `architecture.md`:
  - Document current dense-only collection.
  - Document future hybrid collection.
  - Link the decision to this spec.

- [ ] Update `docs/architecture.md` if it mirrors root `architecture.md`.
  - This is required because both `architecture.md` and `docs/architecture.md` exist.

---

## Task 2: Add Runtime Contract Tests

- [ ] Backend:
  - Assert default `qdrant_collection == "odin_intel"`.

- [ ] Intelligence:
  - Assert default `qdrant_collection == "odin_intel"`.
  - Assert `enable_hybrid` remains false by default.

- [ ] Data-ingestion:
  - Assert default `qdrant_collection == "odin_intel"`.

- [ ] Vision-enrichment:
  - Create `services/vision-enrichment/tests/test_config.py`.
  - Assert default `qdrant_collection == "odin_intel"`.

- [ ] Cross-service consistency:
  - Add a repository-level or AST/grep-based test proving backend, intelligence,
    data-ingestion, and vision-enrichment defaults are all the same.
  - If direct cross-service imports are awkward because service directories use hyphens,
    read the config files with `ast` or text parsing instead of importing modules.

- [ ] Direct-env bypass guard:
  - Refactor `services/data-ingestion/gdelt_raw/cli.py` to use `Settings().qdrant_collection`.
  - Refactor `services/data-ingestion/feeds/gdelt_raw_collector.py` to use
    `Settings().qdrant_collection`.
  - Add a CI/static guard that fails on runtime occurrences of:
    `os.getenv("QDRANT_COLLECTION"` with hardcoded collection defaults.
  - Allow explicit mentions only in config modules, tests, `.env.example`, docs, and
    migration/backfill scripts.

- [ ] Hybrid default:
  - Assert `enable_hybrid` is false by default wherever the flag exists.
  - Add or keep a retriever test that `enable_hybrid=True` degrades or fails according
    to the documented behavior when sparse vectors are absent.

---

## Task 3: Add Qdrant Doctor Check

- [ ] Add or extend a doctor/check command to show:
  - configured collection name
  - whether collection exists
  - point count
  - vector schema
  - whether sparse vector config exists

- [ ] Doctor should warn, not fail, when:
  - `odin_v2` is absent while hybrid is disabled.

- [ ] Doctor should fail when:
  - configured collection is missing for active dense-only runtime.
  - hybrid is enabled but sparse vector config is absent.
  - dense vector size is not `1024`.
  - dense vector distance is not `Cosine`.
  - `enable_hybrid=True` but named `dense` vector config is absent.
  - `enable_hybrid=True` but sparse/BM25 vector config is absent.

- [ ] Add startup/preflight schema validation in services that write or read Qdrant:
  - dense-only mode expects unnamed vector `size=1024`, `distance=Cosine`.
  - hybrid mode expects named `dense` vector `size=1024`, `distance=Cosine`, plus
    sparse vector config.
  - Wrong schema must be detected before the Qdrant write/search call.

- [ ] Add a test proving Phase 2 write/search code refuses a Phase 1 collection before
  issuing the Qdrant request.

---

## Task 4: Define Phase 2 Migration As Separate Spec

- [ ] Do not implement the full Phase 2 migration in this Phase 1 plan.

- [ ] Create a separate Phase 2 spec/plan covering:
  - sparse-vector generation and tokenizer choice
  - Qdrant named dense+sparse schema creation
  - Qdrant Query API / prefetch / RRF retriever changes
  - backfill strategy for existing `odin_intel` points
  - dual-write transition
  - query parity and recall@k validation
  - latency validation
  - rollback and retirement windows

- [ ] The Phase 2 plan must use `enable_hybrid` as the code-path discriminator, not
  collection name alone.

- [ ] Required cutover sequence for that separate plan:
  1. Data-ingestion dual-writes to `odin_intel` and `odin_v2` for an agreed window.
  2. Backfill `odin_v2` from an `odin_intel` snapshot.
  3. Validate point counts, source distribution, payload parity, recall@k, and latency.
  4. Atomically switch all readers via feature/deployment flag.
  5. Continue dual-write through validation.
  6. Switch writes to `odin_v2` only.
  7. Keep `odin_intel` read-only as emergency snapshot.
  8. Drop `odin_intel` only after a full validation window and explicit approval.

- [ ] Backend/readers must never switch to `odin_v2` while data-ingestion still writes
  only to `odin_intel`.

---

## Task 5: Rollback Plan

- [ ] Code defaults stay on `odin_intel` throughout Phase 1.

- [ ] Phase 2 activation must use an explicit feature/deployment flag such as
  `enable_hybrid`, not a silent code-default change to `odin_v2`.

- [ ] Keep environment-variable override available as an emergency override:
  - `QDRANT_COLLECTION=odin_intel`

- [ ] Roll back by disabling hybrid and pointing all services back to `odin_intel`.

- [ ] Do not delete `odin_intel` until `odin_v2` has survived a full validation window.

---

## Verification

Run documentation grep:

```bash
rg -n "odin_intel|odin_v2|QDRANT_COLLECTION|enable_hybrid" TASKS.md architecture.md docs README.md services -S
```

Run direct-env bypass guard:

```bash
rg -n 'os\.getenv\("QDRANT_COLLECTION"' services -g '*.py'
```

Expected runtime hits after this plan: none outside tests or explicitly allowed migration/backfill tooling.

Run backend tests:

```bash
cd services/backend
uv run pytest tests/unit/test_config.py
```

Run intelligence tests after adding contract tests:

```bash
cd services/intelligence
uv run pytest
```

Run data-ingestion tests after adding contract tests:

```bash
cd services/data-ingestion
uv run pytest
```

Run vision-enrichment tests after adding config test:

```bash
cd services/vision-enrichment
uv run pytest
```
