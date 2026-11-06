# Reliability closure: five sequential packages

Authorized on 2026-11-06 after the repository review. Scope includes fixes,
commits, review PRs, CI integration and targeted releases with a verified rollback.
Source starts at `1846da4`, with remote main independently read as `fe15309`.
Evidence root: `/data/odin-reliability-20261106`. `TASKS.md` owns current status.

Each package records a failing regression or measured baseline before changes,
the smallest correction, caller-visible verification and release evidence where
applicable. Passing software tests does not establish factual truth. Existing
data, foreign dirty worktrees, model services and rollback inputs are preserved.
Only one local LLM; no model downloads or driver changes are planned.

## P1 — integrate the deployed source

1. Correct the three reproduced CI lint violations; re-run the full CI lint scope.
2. Replace stale active-worker/Main claims in TASKS with dated source/runtime facts.
3. Commit and publish the existing notebook/current-research changes in one
   reviewable PR; run actual remote CI and resolve any failures before merging.
4. Record the merged revision. Do not change application containers for formatting.

Done: source is remotely recoverable, full PR CI passes, Main includes the source,
and the registry distinguishes source integration from deployed service revisions.

## P2 — ingestion and individual feed coverage

1. Capture the active ingestion image, settings, mounts and pending GDELT state
   privately; compare runtime source with the existing invalid-event regression.
2. Verify official RSS/OFAC/HAPI endpoints and represent inaccessible providers
   explicitly. Add bounded per-feed last-attempt/last-success/error telemetry;
   one healthy feed must not hide another feed's failure.
3. Test telemetry and collector failure/recovery using synthetic HTTP/Redis.
4. Build a revision-bound ingestion image and qualify its dependencies, catalog,
   codebook and persisted-state compatibility. Rehearse a targeted rollback.
5. Replace only the ingestion service; retain volumes/settings. Observe replay
   of slice `20260827091500`, a fresh collector cycle and honest per-feed status.

Done: the pending slice is processed without inventing spatial evidence; recurring
feed failures are repaired where an official usable endpoint exists, otherwise
explicitly unavailable; healthy peers cannot conceal them. No blanket data cleanup.

## P3 — dossier consistency (BP-03 and remaining BP-04)

1. Add deterministic regressions for disjoint concurrent patches, update/delete,
   null and empty patch semantics, and genuinely empty new dossiers.
2. Replace read/merge/full-upsert with one parameter-bound fixed Cypher update
   that only sets present fields and never creates missing reports.
3. Preserve unknown confidence and empty evidence; keep editor hints in the UI.
   Existing historical values are not silently migrated.
4. Run tests against a marked isolated Neo4j instance plus frontend save/reload
   fixtures, all affected suites, strict types and the full lint scope.
5. Integrate and release the compatible backend/frontend pair with rollback.

Done: both disjoint patches survive; deleted reports stay deleted; empty patches
do not mutate; null/zero are distinct; new dossiers contain no fabricated scores
or evidence, including after reload.

## P4 — qualify source interpretation

1. Freeze a source-only development corpus and a separate held-out corpus before
   tuning. Store original text, expected meaning and case dimensions explicitly.
2. Measure false approvals and false abstentions separately for attribution,
   conditions, negation, modality, event/publication time and source relationships.
3. Correct demonstrated failures using regression tests; do not rename reused
   development examples into independent held-out evidence.
4. Run current research through the real application path with bounded requests,
   record latency, credits, evidence, persistence and reload. Use only dedicated
   synthetic/test dossiers; do not overwrite editorial reports.
5. Publish the measured acceptance decision and remaining limitations. Model
   source checks do not qualify external truth or automatic forecasts.

Initial source-audit acceptance: no false approval in the frozen critical controls;
at least 90% acceptance of faithful summaries; every displayed original exact;
source comparisons preserve attribution, scope and time. A failed held-out run
remains a failure and requires a fresh independent set after tuning. Human workflow
judgment is reported separately and cannot be self-certified by the implementation.

## P5 — readiness, bounded aggregation and sustained operation

1. BP-05: keep Redis recovery bounded after startup failure; test concurrent probes,
   later outage and recovery. Add read-only dependency readiness separate from
   liveness and feed freshness.
2. BP-06: return an honest unavailable state for failed RAG statistics and HTTP 501
   for unimplemented manual ingestion; test invalid JSON and partial failures.
3. BP-07/08: freeze histogram semantics, measure row transfer/latency on isolated
   data, then move exact aggregation to fixed database templates without an event
   LIMIT. Preserve spatial accounting, category/severity normalization and buckets.
4. Reproduce native Cesium memory growth using the existing minimal harness.
   Qualify a measured fix or bounded viewer lifetime strategy; do not claim that
   JS heap alone proves native stability. Run the complete 60-minute native soak.
5. Integrate and release only qualified changes, compare service identities and
   final health, and retain receipts plus the previous images/configuration.

Done: cache recovers, readiness distinguishes required/optional failures, RAG does
not invent successful jobs/counts, histogram output is equivalent with bounded
result rows, and native sustained-operation criteria pass. Residual failures are
kept explicit instead of being closed by a deadline or renamed acceptance gate.

## Status

| Package | State | Evidence |
|---|---|---|
| P1 | In progress | `p1/lint-red.log`; full CI and merge pending |
| P2 | Planned | Review: repeated pending slice and three failed RSS publishers |
| P3 | Planned | Review: deterministic in-memory reproductions |
| P4 | Planned | Existing small controls remain historical evidence |
| P5 | Planned | Existing cache/histogram and native-memory baseline |
