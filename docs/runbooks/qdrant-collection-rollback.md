# Qdrant Collection Phase 1 Rollback Runbook

**Status:** Phase 1 Operator Rollback Procedures  
**Last verified:** 2026-05-03  
**Scope:** Emergency rollback procedures for Phase 1 (dense-only `odin_intel` collection)

---

## Overview

This runbook provides operator-facing procedures to roll back Qdrant collection state during Phase 1 of the Qdrant Collection Source-of-Truth Sync project. Phase 1 locks all services to the `odin_intel` collection with dense-only search enabled.

**Phase 1 contract:**
- All services (backend, intelligence, data-ingestion, vision-enrichment) default to `odin_intel`.
- Hybrid search (`enable_hybrid`) defaults to `False`. Only the `intelligence` service consumes this flag.
- `odin_v2` exists for Phase 2 hybrid migration but is NOT active in Phase 1.

If a service is reading/writing the wrong collection or hybrid is prematurely enabled, follow the recovery steps below.

---

## Phase 1 Default Contract

| Component | Default Collection | Default Hybrid | Schema Expectation |
|---|---|---|---|
| Backend | `odin_intel` | N/A — does not consume `enable_hybrid` | Dense 1024-dim, cosine distance |
| Intelligence | `odin_intel` | `False` | Dense 1024-dim, cosine distance |
| Data-ingestion | `odin_intel` | N/A — does not consume `enable_hybrid` | Dense 1024-dim, cosine distance |
| Vision-enrichment | `odin_intel` | N/A — does not consume `enable_hybrid` | Dense 1024-dim, cosine distance |

The `qdrant_collection` default is defined in each service's Pydantic `Settings` class (e.g., `services/backend/app/config.py`). The `enable_hybrid` field exists only in `services/intelligence/config.py`.

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
| Hybrid search is active but shouldn't be | `enable_hybrid=True` was set prematurely in intelligence. | Recovery 2 |
| Schema mismatch error at startup | Collection has wrong vector config. | Recovery 3 |

---

## Recovery 1: Reset Collection to `odin_intel` via Environment Variable

**Use when:** Service is querying or writing to the wrong collection.

**Step 1: Identify the affected service**

```bash
docker ps --filter status=exited
docker logs <service-container-id> | tail -30
```

**Step 2: Inject `QDRANT_COLLECTION` override**

Edit the affected service's `.env` file or deployment environment variables:

```bash
QDRANT_COLLECTION=odin_intel
```

Restart the affected service:

```bash
docker-compose restart <service-name>
```

**Step 3: Verify**

```bash
docker ps | grep <service-name>
docker logs <service-name> | grep -E "ERROR|CRITICAL|collection"
cd services/data-ingestion && odin-qdrant-doctor
```

Confirm exit code 0 and expected schema in doctor output.

---

## Recovery 2: Disable Hybrid via `ENABLE_HYBRID=false`

**Use when:** Hybrid search is active but Phase 2 migration is incomplete or rolled back.

**Step 1: Identify where `enable_hybrid` is set**

```bash
grep -r ENABLE_HYBRID .env* docker-compose.yml
```

**Step 2: Disable hybrid**

Set `ENABLE_HYBRID=false` in the **intelligence service** deployment env — this is the only service that consumes the flag. Restart `intelligence`:

```bash
docker-compose restart intelligence
```

**Step 3: Verify**

```bash
docker logs intelligence | grep -E "hybrid|enable_hybrid" | head -5
cd services/data-ingestion && odin-qdrant-doctor
```

Confirm exit code 0. Doctor output will show schema and hybrid status.

---

## Recovery 3: Schema Mismatch

**Use when:** Service startup logs show schema errors (e.g., "expected sparse vectors but found none").

If `odin-qdrant-doctor` reports a schema mismatch, **do NOT attempt automated repair.** Take a snapshot of the affected collection via the Qdrant snapshot API and contact the on-call data-ingestion engineer. Then apply Recovery 1 + Recovery 2 to restore the service to a known-good state while the schema issue is investigated.

```bash
# Inspect both collections
cd services/data-ingestion
odin-qdrant-doctor --collection odin_intel
odin-qdrant-doctor --collection odin_v2
```

---

## Verification After Rollback

After applying any recovery, run these checks:

### Check 1: Doctor Run

```bash
cd services/data-ingestion
odin-qdrant-doctor
```

Verify exit code 0 and confirm the expected schema (dense 1024-dim cosine, no sparse vectors) appears in the output.

### Check 2: Service Config Contract Tests

Run `uv run pytest tests/unit/test_config.py -v` in each of `services/backend`, `services/intelligence`, `services/data-ingestion`, `services/vision-enrichment`. All tests must pass, confirming `qdrant_collection == "odin_intel"` and `enable_hybrid == False` (intelligence only).

### Check 3: Static Guard Against Direct Env Reads

Verify that runtime code is NOT reading `QDRANT_COLLECTION` directly via `os.getenv`:

```bash
rg -n 'os\.getenv\("QDRANT_COLLECTION"' services -g '*.py'
```

**Expected:** Only allowlisted hits (paths under `/tests/` or `config.py`). Any hit in production code (`retriever.py`, `ingestion.py`, etc.) is a contract violation — report to the data-ingestion team.

### Check 4: Smoke Test Query

```bash
curl -X POST http://localhost:8003/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test geopolitical event", "top_k": 5}' \
  -w "\nStatus: %{http_code}\n"
```

**Expected:** HTTP 200 with results from `odin_intel`.

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

**For questions or new edge cases, contact the data-ingestion team or file an issue referencing this runbook.**
