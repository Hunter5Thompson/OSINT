# Qdrant Collection Phase 1 Rollback Runbook

**Status:** Phase 1 Operator Rollback Procedures  
**Last verified:** 2026-05-03  
**Scope:** Emergency rollback procedures for Phase 1 (dense-only `odin_intel` collection)

---

## Overview

This runbook provides operator-facing procedures to roll back Qdrant collection state during Phase 1 of the Qdrant Collection Source-of-Truth Sync project. Phase 1 locks all services to the `odin_intel` collection with dense-only search enabled.

**Phase 1 contract:**
- All services (backend, intelligence, data-ingestion, vision-enrichment) default to `odin_intel`.
- Hybrid search (`enable_hybrid`) defaults to `False` in all services.
- `odin_v2` exists for Phase 2 hybrid migration but is NOT active in Phase 1.

If a service is reading/writing the wrong collection or hybrid is prematurely enabled, follow the recovery steps below.

---

## Phase 1 Default Contract

| Component | Default Collection | Default Hybrid | Schema Expectation |
|---|---|---|---|
| Backend | `odin_intel` | `False` | Dense 1024-dim, cosine distance |
| Intelligence | `odin_intel` | `False` | Dense 1024-dim, cosine distance |
| Data-ingestion | `odin_intel` | `False` | Dense 1024-dim, cosine distance |
| Vision-enrichment | `odin_intel` | `False` | Dense 1024-dim, cosine distance |

The defaults are defined in each service's Pydantic `Settings` class (e.g., `services/backend/app/config.py`).

---

## What Never to Do

- **DO NOT** change a service's code default from `odin_intel` to `odin_v2` without executing the full Phase 2 cutover plan.
- **DO NOT** enable `enable_hybrid=True` at the code level. Use only deployment-level feature flags (see Phase 2 spec).
- **DO NOT** delete `odin_intel` while Phase 2 is in progress or during Phase 1. `odin_intel` is the production fallback.
- **DO NOT** assume service defaults are correct; verify via `odin-qdrant-doctor` before asserting a service is healthy.

---

## Emergency Symptoms

| Symptom | Likely Cause | Recovery Path |
|---|---|---|
| Service startup fails: "collection not found" | Service is configured to read a missing collection. | Recovery 1 |
| Service queries return empty/wrong results | Service is reading the wrong collection. | Recovery 1 |
| Hybrid search is active but shouldn't be | `enable_hybrid=True` was set prematurely. | Recovery 2 |
| Schema mismatch error at startup | Service expects hybrid but collection has dense-only schema (or vice versa). | Recovery 3 |

---

## Recovery 1: Reset Collection to `odin_intel` via Environment Variable

**Use when:** Service is querying or writing to the wrong collection.

**Step 1: Identify the affected service**

```bash
# Check which service(s) are failing
docker ps --filter status=exited
docker logs <service-container-id> | tail -30
```

**Step 2: Inject `QDRANT_COLLECTION` override**

Edit the affected service's `.env` file or deployment environment variables:

```bash
# In the service's .env or deployment config:
QDRANT_COLLECTION=odin_intel
```

Redeploy or restart the affected service:

```bash
docker-compose restart <service-name>
# OR via deployment:
# kubectl set env deployment/<service-name> QDRANT_COLLECTION=odin_intel
```

**Step 3: Verify the fix**

```bash
# Check service is running
docker ps | grep <service-name>

# Check logs for startup errors
docker logs <service-name> | grep -E "ERROR|CRITICAL|collection"
```

**Why this works:**

Pydantic Settings resolves environment variables BEFORE code defaults. If `QDRANT_COLLECTION=odin_intel` is set in the environment, all services will read from `odin_intel` regardless of their code defaults.

---

## Recovery 2: Disable Hybrid via `ENABLE_HYBRID=false`

**Use when:** Hybrid search is active but Phase 2 migration is incomplete or rolled back.

**Step 1: Identify where `enable_hybrid` is set**

```bash
# Check environment variables across all services
grep -r ENABLE_HYBRID .env* docker-compose.yml deployment-config.yaml
```

**Step 2: Disable hybrid**

Set `ENABLE_HYBRID=false` in the affected service's environment:

```bash
# In backend/.env, intelligence/.env, data-ingestion/.env, vision-enrichment/.env:
ENABLE_HYBRID=false
```

Restart all affected services:

```bash
docker-compose restart backend intelligence data-ingestion vision-enrichment
```

**Step 3: Verify**

```bash
# Check that services are using dense-only search
docker logs intelligence | grep -E "hybrid|enable_hybrid" | head -5

# Run a test query
curl -X POST http://localhost:8003/intelligence/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "top_k": 5}'
```

**Why this works:**

The intelligence service's retriever (`services/intelligence/rag/retriever.py`) checks the `enable_hybrid` flag before attempting hybrid RRF fusion. With `enable_hybrid=False`, all queries fall back to dense-only search on `odin_intel`.

---

## Recovery 3: Schema Mismatch — Collection Has Wrong Vector Config

**Use when:** Service startup logs show "expected sparse vectors but found none" or similar schema errors.

**Step 1: Check the configured collection's schema**

```bash
# Run the Qdrant doctor to inspect collection state
cd services/data-ingestion
odin-qdrant-doctor --collection odin_intel --schema-only
odin-qdrant-doctor --collection odin_v2 --schema-only
```

**Expected output for Phase 1:**

```
Collection: odin_intel
  Status: exists
  Points: ~25000 (example value)
  Vectors:
    - unnamed dense vector: size=1024, distance=Cosine
  Sparse vectors: none
  Hybrid enabled: false
```

**Step 2: If schema is wrong, decide which collection to use**

- **If `odin_intel` schema is correct:** Ensure service is pointed to `odin_intel` (Recovery 1) and `enable_hybrid=False` (Recovery 2).
- **If `odin_v2` has the right schema but is empty:** This indicates Phase 2 backfill is incomplete. DO NOT switch services yet.
- **If both collections are wrong:** Contact the data-ingestion team. The Qdrant instance may be corrupted.

**Step 3: Restart the service with correct config**

```bash
# Apply Recovery 1 + Recovery 2
QDRANT_COLLECTION=odin_intel ENABLE_HYBRID=false docker-compose restart <service-name>
```

**Step 4: Verify startup logs**

```bash
docker logs <service-name> | grep -E "schema|collection|vector"
```

Should show:

```
Qdrant collection: odin_intel
Schema validation: dense-only (1024-dim, cosine)
Hybrid mode: disabled
Ready to serve queries.
```

---

## Verification After Rollback

After applying Recovery 1, 2, or 3, run these checks:

### Check 1: Doctor Preflight

```bash
cd services/data-ingestion
odin-qdrant-doctor --preflight
```

**Expected output:**

```
Collection: odin_intel
  ✓ Exists
  ✓ Point count: ~25000
  ✓ Schema: dense 1024-dim cosine
  ✓ Hybrid mode: disabled
  ✓ No sparse vector config present (correct for Phase 1)

Preflight: PASS
```

### Check 2: Service Config Contract Tests

Run the configuration test suite for each service to confirm defaults:

```bash
cd services/backend
uv run pytest tests/unit/test_config.py -v

cd services/intelligence
uv run pytest tests/unit/test_config.py -v

cd services/data-ingestion
uv run pytest tests/unit/test_config.py -v

cd services/vision-enrichment
uv run pytest tests/unit/test_config.py -v
```

**Expected result:** All tests pass, confirming:
- `qdrant_collection == "odin_intel"`
- `enable_hybrid == False`
- Cross-service defaults are consistent

### Check 3: Static Guard Against Direct Env Reads

Verify that runtime code is NOT reading `QDRANT_COLLECTION` directly:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
rg -n 'os\.getenv\("QDRANT_COLLECTION"' services -g '*.py' --type-list
```

**Expected output:** Only hits in:
- `.env.example` (documentation)
- `test_config.py` or similar test files (allowed for contract validation)
- Migration/backfill scripts (Phase 2 only)

If there are hits in production code (`retriever.py`, `ingestion.py`, etc.), that's a contract violation. Report to the data-ingestion team.

### Check 4: Smoke Test Query

Test that a simple intelligence query works:

```bash
# Port 8003 is the intelligence service
curl -X POST http://localhost:8003/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test geopolitical event", "top_k": 5}' \
  -w "\nStatus: %{http_code}\n"
```

**Expected result:** HTTP 200 with results from `odin_intel`.

---

## Pre-Deletion Gate for `odin_intel`

**DO NOT delete `odin_intel` unless all of the following are true:**

1. Phase 2 hybrid migration (cutover to `odin_v2`) is COMPLETE and has been live for at least 30 days.
2. `enable_hybrid=True` has been stable in production (no emergency rollbacks).
3. Dual-write validation window has passed (Phase 2 spec §10 Step 5).
4. **Joint written approval** from engineering lead AND operations lead has been obtained and documented.
5. A backup/archive of `odin_intel` has been taken and stored offline (if required by policy).

Until ALL five conditions are met, `odin_intel` remains online as the read-only emergency snapshot.

If you are asked to delete `odin_intel` before 30 days post-cutover, refuse and escalate to the engineering lead and operations lead.

---

## Cross-References

**Phase 1 Contract + Design Details:**
- [Qdrant Collection Source-of-Truth Sync - Design Spec](../superpowers/specs/2026-04-30-qdrant-collection-sot-design.md) — §4 Current Runtime Contract, §5 Hybrid Activation Flag

**Phase 2 Cutover + Rollback Windows:**
- [Qdrant v2 Hybrid Migration Design Spec](../superpowers/specs/2026-05-03-qdrant-v2-hybrid-migration-design.md) — §9 Rollback Windows, §10 Required Cutover Sequence (steps 4–8)

**Qdrant Doctor Implementation:**
- `services/data-ingestion/qdrant_doctor/` — preflight checks, schema validation, collection metadata

---

## Incident Response Checklist

**During an incident, use this checklist:**

- [ ] Identify the symptom (check "Emergency Symptoms" table above).
- [ ] Confirm which service(s) are affected: `docker ps`, `docker logs`.
- [ ] Apply the corresponding recovery (1, 2, or 3).
- [ ] Run verification checks (doctor, config tests, query smoke test).
- [ ] If verification passes, declare incident resolved.
- [ ] If verification fails, escalate to data-ingestion team with doctor output and service logs.
- [ ] Post-incident: update this runbook if a new symptom or recovery pattern emerges.

---

## Glossary

- **Dense vector:** Unnamed vector of size 1024, distance metric Cosine. Phase 1 only.
- **Sparse vector:** Named vector for BM25-based retrieval. Phase 2 only.
- **Hybrid search:** Combination of dense and sparse signals via RRF. Phase 2 only.
- **`enable_hybrid`:** Boolean flag that selects Phase 1 (dense-only) vs Phase 2 (hybrid) code path.
- **`odin_intel`:** Current production collection with dense vectors. Phase 1 and Phase 2 read-only fallback.
- **`odin_v2`:** Future production collection with hybrid vectors. Phase 2 target.
- **Qdrant doctor:** Command-line tool (`odin-qdrant-doctor`) that validates collection schema and metadata.

---

**For questions or new edge cases, contact the data-ingestion team or file an issue referencing this runbook.**
