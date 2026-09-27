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

## Catalog rotation and cross-store re-normalization (2026-09-27)

The [audit](../reports/2026-09-27-spatial-source-graph-audit.md) found unsafe
compatibility in the unpublished `a8e3a4af02d0` candidate. The corrected candidate
is `spatial-v1-2ff6da288a58`. Keep the actual former live revision served:

| Role | Before | Corrected candidate |
|---|---|---|
| Active | `spatial-v1-0180e188358c` | `spatial-v1-2ff6da288a58` |
| Previous served | `spatial-v1-e76a16bff799` | `spatial-v1-0180e188358c` |

### Compatibility contract

1. **Reference resolution:** only the two pointer revisions accept
   `SpatialScopeRefV1`. The retired `e76…` reference returns an explicit resolution
   error. Existing frontend history needs **Aktiven Kartenstand laden**; a reload
   alone is insufficient. Saved external queries must explicitly resolve a served
   reference; never silently replace the pinned context.
2. **Assignment admission:** a scope revision binds the complete resolver context
   (all assignment geometry, scope paths, boundary policy, crosswalk and resolver
   contract). Adding a neighboring polygon can invalidate an unchanged country's
   assignments. Automatic compatibility requires the same derivation. Labels and
   display-only LOD changes do not invalidate it. Explicit reviewed compatibility
   declarations remain a separate operator assertion, never an inferred property.
3. **This transition:** all 220 previous scope derivations become incompatible.
   No promise that the old Neo4j or Qdrant revisions remain admissible is valid.
   Serving the old catalog supports old pinned queries; it does not grant its
   assignments admission under the new catalog.
4. **Qdrant:** projection revision binds the same scope revision map. Rebuild from
   stored source evidence, not old tokens, display countries or theatre boxes.
   Missing/malformed raw evidence withdraws admission. GDELT requires an exact
   `linked_event_ids` join; NotebookLM remains `about` only. Legacy points without
   raw audits need a separate source replay to recover evidence.
5. **Readers:** the optional `resolution_context_sha256` manifest field preserves
   legacy canonical bytes. Old readers reject new manifests. Deploy backend,
   intelligence, collectors and standalone backfills together; their in-process
   catalog caches require restarting these consumers.

### Prepare and review

The checked-in [plan](../reports/2026-09-27-spatial-renormalization-plan.json) is
an **offline job plan, not an approved live dry-run**. It contains five Neo4j lane
scans and seven explicit Qdrant source filters. Generate a fresh copy from a full
checkout using the locked ingestion environment (run from `services/data-ingestion`):

```bash
uv run python ../../scripts/prepare_spatial_renormalization.py \
  --previous ../backend/data/spatial/catalogs/spatial-v1-0180e188358c \
  --target ../backend/data/spatial/catalogs/spatial-v1-2ff6da288a58 \
  --output /data/odin-backups/spatial-cutover-plan.json
```

Add `--preview` to read both configured stores using Settings/environment credentials.
The script never applies writes or activates a pointer, uses fresh full-lane scans,
and refuses to overwrite an existing output. It joins the existing Neo4j batch
engine and Qdrant preview engine with the same deterministic source projector.

1. Pause affected collectors **and** the independent GDELT backfill, plus incident
   writers. Drain scoped queries during the materialized cutover. There is no
   cross-database transaction or compare-and-swap protection against concurrent
   writers; fingerprints do not replace this maintenance boundary.
2. Take a durable Neo4j backup and Qdrant snapshot including vectors. Record image,
   catalog, source-lock and crosswalk hashes. Check fresh free disk space on `/data`
   before multi-GB snapshots. Verify that the backups can be restored before apply.
3. Run the joint read-only preview. Review resolved, conflicting, unsupported,
   missing-evidence and stale coverage separately for each source. A successful
   job with empty tokens is not evidence of complete source coverage.
4. Neo4j reports fingerprint ordered raw rows **and** planned updates. Qdrant reports
   include IDs, payloads, dense/named/sparse vectors and proposed projections.
   Identical counts with changed input are rejected. Retain the exact reports.

### Apply in the coordinated maintenance window

Use the existing Neo4j CLI with `SPATIAL_CATALOG_PATH` set to the candidate's
immutable directory. Generate its own dry-run envelope (the nested `neo4j_preview`
from the joint tool is the same engine, but whole joint output is not an approval):

```bash
SPATIAL_CATALOG_PATH=../backend/data/spatial/catalogs/spatial-v1-2ff6da288a58 \
uv run python -m graph_integrity.cli reenrich-spatial-scope \
  --previous-catalog ../backend/data/spatial/catalogs/spatial-v1-0180e188358c \
  --checkpoint /data/odin-backups/spatial-neo4j-checkpoint.json \
  --dry-run --report-out /data/odin-backups/spatial-neo4j-preview.json
```

After review, use the same command with `--apply`,
`--approved-report /data/odin-backups/spatial-neo4j-preview.json`, and a separate
`--report-out`. A fresh run starts with a new checkpoint file. After interruption,
Neo4j requires a fresh approved dry-run for the remaining checkpoint suffix; retain
all earlier applied reports. Scope maps are hashed into grouped checkpoint keys,
so old per-revision jobs cannot accidentally resume this transition.

Qdrant uses `rag.spatial_reenrich.apply_spatial_reenrichment`, explicit lane filters
from the plan, `spatial_reprojection.reproject_payload` as projector and a durable
`JsonCheckpointStore`. Supply each lane's reviewed full-lane report, not the joint
envelope. Its existing approval fingerprint is retained across resumed pages.
There is deliberately no joint apply switch: this change prepares the cutover;
both store applies and their verification remain operator steps.

Neo4j conflict/unresolved transitions clear obsolete assignment fields. The aircraft
lane also derives `name` from a non-conflicting country or `unresolved`, removes
`region`, and saves `spatial_previous_name`, `spatial_previous_region` and
`spatial_label_backup_taken` once. In Neo4j, absent properties and null are equivalent;
these saved values preserve exact label presence. They do not replace the full backup
needed to restore all spatial properties. Raw coordinates and source codes remain.

Only after both stores are verified publish coverage, activate the coordinated
release and pointer, restart all consumers, test both served revisions and a real
scoped query, then resume traffic. Old pinned clients can have incomplete coverage
while records carry new derivations; do not promise lossless old-session results.

### Rollback and evidence limits

Rollback restores matching images, pointer **and materialized store snapshots**
while writers remain paused. A pointer rollback alone cannot restore erased fields
or old token arrays. Label-only rollback may restore the saved label values only
inside the same protected maintenance boundary; do not overwrite newer observations.

The source lock still uses Natural Earth 1:110m. Complete containment means all
176 current country scopes, not every small state or survey-grade borders. Finer
geometry and new GDELT aliases require reviewed source/boundary-policy inputs.
UCDP records without precise `where_prec=1` remain non-filterable pending source
replay; GDACS projects its reported centroid, not the complete affected area.
Military-aircraft observations remain graph-only; this change adds no Qdrant writer.

The aircraft cursor gate distinguishes typed `aircraft_observation` records and
point-bearing legacy locations from historical theatre aggregate nodes. A theatre
node without its own coordinates is not an observation missing an ID. Preserve
those aggregate nodes and their original `SPOTTED_AT` edge evidence; they are not
newly admitted spatial observations. Edge-to-observation materialization remains a
separate migration. Run the read-only predicate regression against configured
Neo4j with `pytest -m live tests/integration/test_aircraft_lane_live.py`.
