# Spatial Intelligence Contract Deployment Runbook

**Status:** Required for Spatial Scope Plan 07B

**Last verified:** 2026-08-10

**Scope:** Backend ↔ Intelligence `/query` compatibility boundary

## Deployment rule

Deploy the backend and intelligence service as one lock-step release. Do not leave a
new intelligence image serving traffic from an old backend image.

Plan 07B makes `spatial_relation` mandatory on the internal intelligence
`POST /query` contract. The matching backend always sends the field and defaults its
public request model to `either`. An old backend omits the field, so a new
intelligence service correctly rejects that stale internal request with HTTP 422.
The intelligence model intentionally has no compatibility default: silently filling
the field at the service boundary would hide a partially deployed contract.

## Pre-deployment gates

Run from the individual service directories:

```bash
cd services/backend
uv sync
uv run pytest
uv run ruff check app/
uv run mypy app/

cd ../intelligence
uv sync
uv run pytest
uv run ruff check .
```

Record the backend and intelligence image revisions that belong to the release.

## Cutover

1. Drain or pause interactive intelligence traffic.
2. Replace both backend and intelligence images in the same maintenance window.
3. Start the matching pair; do not mark the release ready while only one service is
   on the new revision.
4. Run `./odin.sh smoke` from the repository root.
5. Verify that the intelligence health endpoint is ready and exercise one backend
   `/api/intel/query` request. The backend-to-intelligence payload must contain
   `spatial_relation` (`either` when the caller did not select another relation).
6. Resume traffic only after both checks pass.

Direct callers of the intelligence service must be migrated before cutover and must
send one of `about`, `occurrence`, or `either`.

## Rollback

Roll back backend and intelligence together to the previously recorded matching
image revisions. Rolling back only one side recreates an unverified mixed-version
pair. After rollback, run `./odin.sh smoke` again before resuming traffic.
