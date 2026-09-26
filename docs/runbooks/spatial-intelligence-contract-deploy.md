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
uv sync --locked --all-extras
uv run pytest
uv run ruff check app/
uv run mypy app/

cd ../intelligence
uv sync --locked --all-extras
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

## Catalog rotation: PR #119 review, 2026-09-27

**Not a deployment approval.** The
[source and graph audit](../reports/2026-09-27-spatial-source-graph-audit.md)
found stored non-conflicting assignments that the candidate normalizer now
classifies as conflicts while still accepting their old derivation revisions.
Resolve that semantic compatibility issue before activating this candidate.
Passing catalog-loader tests does not close this gate.

The reviewed pointer transition is:

| Role | Before | Candidate |
|---|---|---|
| Active | `spatial-v1-0180e188358c` | `spatial-v1-a8e3a4af02d0` |
| Previous served | `spatial-v1-e76a16bff799` | `spatial-v1-0180e188358c` |

Derivation compatibility and served `SpatialScopeRefV1` revisions are separate
contracts. Requests pinned to `e76a16bff799` are rejected after this transition,
even if some materialized derivations remain compatible.

Once the semantic compatibility gate has been closed:

1. Record the exact catalog, source-lock, crosswalk and image revisions for
   backend, intelligence and every ingestion/backfill consumer. Coordinate the
   running GDELT backfill explicitly; a restarted scheduler does not update a
   separate backfill process. Avoid a period in which unvalidated old assignments
   are accepted under the new catalog.
2. Prepare separate, fingerprinted dry-run reports for Neo4j and Qdrant with the
   agreed candidate inputs. The Neo4j `graph_integrity reenrich-spatial-scope`
   command does not update Qdrant. Confirm the actual planned work: this candidate
   currently creates 165 full-lane jobs per selected Neo4j lane, and its summed
   report totals do not represent unique records across jobs.
3. Apply only the reviewed reports using each lane's supported checkpoint and
   approval flow. Recheck source drift before application. Measure newly resolved,
   newly conflicting, unresolved and remaining stale records separately; do not
   count a compatible revision token as semantic revalidation.
4. Treat aircraft `name`/`region` cleanup as a separate migration after spatial
   normalization. Export exact before-values and property presence keyed by
   `loc_key`, retain the responsible historical rule revision, and protect
   rollback from concurrent changes. A country retained on a conflict record
   must not become an apparently verified display name. The current spatial
   batch writer does not modify these legacy display fields.
5. Publish the agreed pointer and refresh all long-lived consumers in the
   coordinated cutover. Verify their effective revisions and a real scoped query
   before resuming normal traffic.
6. For expired browser references, use **Aktiven Kartenstand laden** in the
   existing recovery banner. Router/history state stores
   `odinSpatialCatalogRevision`; a browser reload alone is not a guaranteed
   migration. External saved queries must resolve their scope against a served
   revision explicitly. Do not silently replace their pinned context.
7. Verify both served revisions, visible rejection of the retired revision,
   explicit recovery, and consistent Neo4j/Qdrant filtering. Coordinate rollback
   of the reader contract, pointer and materialized assignments: rolling back
   only the pointer does not restore old database property values.
