# Tracing — baked client and failure boundaries

G02 tracing is integrated in the isolated current-main-based source. Neither
the foreign dirty observability worktree nor production services were changed.
Image transport validation is a separate clean-commit checkpoint under
`/data/odin-goals/2026-10-09-repo-hardening/evidence/G02/`.

## Observed cause and result

The old external overlay supplied Python adapters and a reporter through code
binds. Those runtime inputs were not represented by the new release contract.
On 10 October, the fresh inventory confirmed that overlay on Intelligence;
Spark ingestion had no tracing mounts or environment configuration. Earlier
notes claiming both active clients carried the overlay are superseded.

Only tracing hooks were ported into the current workflow, SDK tool calls,
RSS and Notebook extraction. No complete old workflow or pipeline was copied.
The dependency-free reporter is vendored with recorded source provenance and
byte-identical service copies. Existing independent wheels and Docker images
package it without an import or mount from another checkout.

The existing adapters could replace application results, provider errors or
cancellation when starting or finishing spans failed. New boundaries preserve
the original result/exception. Context-local spans preserve parallel query
isolation and direct SDK generation ancestry within tools. Query error
responses remain failed traces; unavailable TTFT/usage remain unknown.
Reporter shutdown is bounded and off the event loop, including failure of
another cleanup operation.

`odin.sh --release --tracing` selects an explicit final overlay. Only the
socket directory and token file are mounted read-only, without automatic
host-path creation. The release guard validates their contract before
lifecycle actions. Capture defaults to metadata; retaining the old
Intelligence text capture requires an explicit reviewed setting. See
[operations/tracing.md](../operations/tracing.md) for transport, capture,
rollout and rollback limits.

## Tests and evidence

- Behavioral REDs observed missing spans through the actual public query and
  RSS parser entry points, then span-start/finish failures replacing results,
  exceptions or cancellation. Parallel real LangGraph model/tool callbacks
  and direct SDK lineage are exercised without a live model.
- Notebook RED used a valid source fixture and observed missing terminal
  spans. An earlier invalid-source setup failure is not behavioral evidence.
  Provider request budgets, timeouts and parsing contracts remain unchanged.
- Shutdown REDs observed missing flush during resource-close failures. Queue
  overflow, offline transport, bounded close, text redaction/UTF-8 limits and
  metadata capture are tested independently of the external collector.
- Whole Intelligence: **610 passed**. Whole ingestion: **1699 passed,
  1 existing skip, 23 opt-in live tests deselected**. Ops: **96 passed**.
  Service Ruff, changed ops/script Ruff, shell syntax and diff checks passed.
- The first whole-ingestion run found an old static Docker assertion requiring
  an unpinned UV tag. It now requires the exact existing UV 0.10.0 digest and
  the explicit tracing copy. The image was not unpinned; the subsequent whole
  service run is green. This closes a check gap in the earlier image checkpoint.
- CI now additionally probes the two tracing-enabled application images using
  a disposable Unix collector: online, absent and recreated socket, with one
  reporter instance. `--network none` and fixture providers prevent external
  model/data access. The separate generic image smoke retains real CMD checks.

Raw RED/GREEN logs, the accurate runtime inventory and subsequent image proof
live in the external evidence directory. Backend/frontend source did not
change in this checkpoint; their Recon tests are not needlessly repeated.
Local source tests are not remote CI, live collector freshness, real model/feed
quality, deployment or human acceptance. Image config IDs are not published
registry manifest digests. DEP-01 and the complete release gates remain open.
