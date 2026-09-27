# Spatial audit remediation — 2026-09-27

This is the implementation follow-up to the [read-only audit](2026-09-27-spatial-source-graph-audit.md).
Historical counts in that report remain observations of the old runtime. No deployment,
Neo4j repair, Qdrant rewrite or pointer activation in running services was performed.

## Implemented behavior

| Audit finding | Code change | Regression evidence |
|---|---|---|
| A1, unsafe derivation carry-forward | Every assignment binds the complete resolver context; automatic compatibility requires unchanged derivation. Legacy manifests retain their canonical bytes. | Adding containment and changing a neighbor invalidate old derivations; all eight committed live conflict examples are rejected by the corrected candidate. |
| A2, USGS wrong edge and false success | Join `Document-DESCRIBES-Event`, count actual edges, retry proximity even for a deduplicated Qdrant point. | Zero/one-edge acknowledgments and retry after dedup. |
| A3, FIRMS/GDELT correlation mismatch | Use canonical Event IDs and admitted graph locations, preserve indexed versus occurred time, remove obsolete explosion filter, write `SPATIOTEMPORAL_PROXIMITY`. | Current Event join without a GKG coordinate proxy, zero-edge failure, accepted derivation filter, no second Qdrant source scan. |
| A4, structured source gaps | Shared coordinate adapter feeds graph and vector projections for USGS, FIRMS, precise UCDP, EONET and GDACS. Mutable source locations refresh in place. | Same normalized identity in both stores, invalid coordinates/precision rejected, old optional projection state removed, stable source identity. |
| A5, stale fields and repair paths | Clear revoked/conflicting assignment fields; repair aircraft labels while preserving old label values; normalize legacy GDELT backfill; correct writer inventory. | Invalid old assignments lose admission; label backup and cleanup are planned; legacy geo writer emits normalized fields. |
| A5, repeated scans/count-only approvals | One grouped scan per graph lane; hash the raw inputs and proposed updates. Qdrant fingerprints also bind complete vectors, including named sparse vectors. | One scan per lane; same counts with changed coordinates rejected; hybrid-vector fingerprints; existing interrupted-run tests remain green. |
| A7, expired client references | Keep the actual live predecessor served; document explicit reference recovery and coordinated store cutover. | Pointer-driven backend/router tests and both served intelligence revisions. |

## Source and compatibility limits

The corrected catalog is `spatial-v1-2ff6da288a58`, with 220 scopes, containment for
all 176 current country scopes and 438 verified assets (6,833,332 bytes). A second
offline build from the locked source cache generated the same catalog revision.
All 220 former scope derivations are invalidated; the old 6,124/17,414 compatibility
claim is intentionally withdrawn. The actual runtime remains on its prior revision.

A6 is a source-policy/accuracy boundary: no unreviewed higher-resolution boundary
source or guessed GDELT alias was introduced. Unknown codes stay unresolved.
The source lock still identifies Natural Earth 1:110m; zero representation error
does not mean zero geographic uncertainty.

UCDP `where_prec` and `date_prec` are retained. Only `where_prec=1` becomes point
occurrence evidence; legacy records without that property require source replay.
This follows the [official GED 26.1 codebook, pp. 10 and 23](https://ucdp.uu.se/downloads/ged/ged261.pdf).
GDACS remains a reported centroid, EONET a reported point, FIRMS a thermal observation
and USGS a reported epicenter; neither the adapter nor proximity edges claim an
entire affected area or independent corroboration. Confidence `1.0` in the adapter
means direct structured evidence, not certainty that the source report is true.

The seven Qdrant lanes are GDELT-GKG, NotebookLM, USGS, FIRMS, UCDP, EONET and GDACS.
GDELT re-projection requires stored raw evidence and an exact linked Event ID;
NotebookLM remains about-only. Missing evidence removes tokens and is reported
explicitly. No Qdrant aircraft lane was invented: the aircraft writer is graph-only.
Correlation replays seven days of observations on each successful run to include
late-arriving events; arbitrary older history needs a separately bounded replay.

## Operator artifacts

- [Offline cross-store job plan](2026-09-27-spatial-renormalization-plan.json): five
  Neo4j scans and seven Qdrant filters, bound to one target catalog/projection map.
- [Updated deployment and re-normalization runbook](../runbooks/spatial-intelligence-contract-deploy.md):
  source-bound previews, paused-writer requirement, exact snapshots, separate apply
  contracts, resume behavior, coverage checks and rollback.
- `scripts/prepare_spatial_renormalization.py`: generates the offline plan; optional
  `--preview` joins both existing batch engines with no mutation or activation option.
  The plan is not a live dry-run approval.

## Validation

TDD was performed in incremental red/green cycles for compatibility, source adapters,
revocation, fingerprint drift, graph joins and migration planning. Validation uses
the existing locked service environments with the PR worktree as CWD; no fresh CI
image build or live apply is claimed. Backend mypy passes for all 90 source files;
Ruff and `git diff --check` pass. Six new/changed parameterized Cypher templates
passed Neo4j `EXPLAIN` against the running server without executing their statements.

Final full-suite counts are recorded in `TASKS.md` for this implementation session.
The existing ingestion skip and integration deselections were not expanded.
