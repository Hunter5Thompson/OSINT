# Spatial Scope 07B — Munin Scope Enforcement

> **Canonical slice:** 7 (agent half) · **Requires:** Plans 06B and 07A
>
> **Load with:** [Spec 10](../../specs/2026-07-31-spatial-scope-drilldown/10-munin-scope-enforcement.md),
> [Spec 09 §16.3–16.4](../../specs/2026-07-31-spatial-scope-drilldown/09-qdrant-retrieval.md),
> [Spec 12 §§20–22](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 7](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Resolve a committed frontend scope once in the backend, pin it into LangGraph state,
and inject it into tools through `ToolRuntime`. The model sees query/question
arguments but cannot supply scope, relation, region, filter fields, or image URL.
Scoped runs bind only safe capabilities and fail before network/Neo4j on any bypass.

## File surface

Backend: modify intel models/router/stream, briefing/report store/read queries and
tests. Intelligence: modify `main.py`, `graph/state.py`, `graph/workflow.py`,
`agents/react_agent.py`, tool registry and all six tools, graph templates, and tests.
Extend frontend/backend `IntelAnalysis` with `spatial_application` without dropping it
through SSE/report persistence.

## Work order 1 — Backend token resolution and caller contract

- [ ] **RED:** Test `region + spatial_scope` and `use_legacy + spatial_scope` 422,
  default relation `either`, invalid/unserved revision, server-generated compatibility
  list, country briefing canonical resolution, alias dossier lookup, canonical-over-
  alias duplicate conflict logging, and no browser-supplied token trust.
- [ ] **GREEN:** Extend `IntelQuery`; resolve `SpatialQueryRef` through the catalog into
  `SpatialScopeTokenV1` before calling intelligence. Add parameterized
  `REPORT_BY_SCOPE_KEYS`; persist new reports canonically and never auto-merge.
- [ ] **REFACTOR:** One backend resolver serves interactive and briefing entry points.
  `region` remains legacy-only and is never translated heuristically.
- [ ] **VERIFY:** Run intel model/router/stream, briefing and report-scope tests.
- [ ] **COMMIT:** `feat(backend): resolve intelligence spatial tokens`

## Work order 2 — Pinned state and model-visible schemas

- [ ] **RED:** Inspect bound tool JSON schemas: Qdrant has only `query`; graph only
  `question`; vision only `question`; none exposes scope/region/image URL. Test run
  state remains unchanged after simulated UI scope switch and output echoes original
  scope/catalog/derivation.
- [ ] **GREEN:** Validate the internal request in intelligence, add frozen token and
  required relation to `AgentState`, initialize once in `run_intelligence_query`, and
  accept injected `ToolRuntime[dict[str, object], AgentState]` in tools.
- [ ] **REFACTOR:** Prompt may describe scope but no enforcement depends on prompt
  text. Remove `region` from `qdrant_search` and image URL from `analyze_image`.
- [ ] **VERIFY:** Run `test_spatial.py`, workflow and tool-schema tests.
- [ ] **COMMIT:** `feat(intelligence): pin spatial scope in agent state`

## Work order 3 — Scoped Qdrant and graph tools

- [ ] **RED:** Test Qdrant receives the 07A filter plus unchanged lane policy; outage,
  partial, and no-hit cause no global retry. For graph, test each allowed template and
  scope kind binds `$scope_key/$compatible_revisions`, duplicate events collapse, all
  unsupported intents/free-Cypher execute zero queries, and failure remains closed.
- [ ] **GREEN:** Read token/relation from runtime in `qdrant_search`. Add complete
  `SCOPED_TEMPLATES[(template_id, scope_kind)]`; route non-global graph calls only
  through that registry. Preserve global read-only fallback solely for global runs.
- [ ] **REFACTOR:** Formatting and spatial-application metadata wrap execution but do
  not rewrite arbitrary Cypher.
- [ ] **VERIFY:** Run Qdrant tool, graph query/template, and workflow focused suites.
- [ ] **COMMIT:** `feat(munin): enforce scope in retrieval tools`

## Work order 4 — Capability binding and defense in depth

- [ ] **RED:** Scoped binding excludes GDELT/RSS and vision without attached image;
  direct calls to blocked tools return unsupported before mocked HTTP; vision reads
  exactly state image; global runs retain approved capabilities. Assert scoped ReAct
  failure never invokes legacy. Test external GDELT URL comes from settings.
- [ ] **GREEN:** Implement `tools_for_state`; pass its result to `create_react_agent`
  while the lifecycle-owned `ToolNode` may know all tools. Add runtime guards to
  GDELT/RSS and vision. Move hardcoded external URL to config.
- [ ] **REFACTOR:** One closed capability matrix drives binding, blocked-tool
  accounting, and guard tests.
- [ ] **VERIFY:** Run workflow/tool tests with HTTP and graph clients mocked as
  fail-on-call sentinels.
- [ ] **COMMIT:** `fix(munin): block unscoped tool capabilities`

## Work order 5 — Trusted application codec and propagation

- [ ] **RED:** Parse marker only on first ToolMessage line, validate consumer against
  actual tool name, reject malformed/spoofed document text, aggregate not-called/
  unsupported/failed/worst successful completeness, retain earlier failure detail,
  and ensure marker is not evidence. Test backend SSE/frontend/report persistence does
  not relabel an old run under current UI scope.
- [ ] **GREEN:** Implement closed `[SPATIAL_APPLICATION]` codec/aggregation in
  `spatial.py`; add `SpatialRunApplicationV1` to analysis models and every mapping.
  Populate blocked tools and coverage revision deterministically.
- [ ] **REFACTOR:** Keep trusted metadata separate from synthesis research and
  `[EVIDENCE]` lineage.
- [ ] **VERIFY:** Run full intelligence and backend quality commands plus frontend
  result-model tests.
- [ ] **COMMIT:** `feat(munin): report spatial application truthfully`

## Exit gate

The model cannot override scope/relation/image source; blocked tools make zero external
calls; scoped graph has no free-Cypher path; Qdrant retains corpus policy; results and
stored reports echo the pinned token and per-consumer truth. No scoped failure falls
back to legacy or global retrieval.
