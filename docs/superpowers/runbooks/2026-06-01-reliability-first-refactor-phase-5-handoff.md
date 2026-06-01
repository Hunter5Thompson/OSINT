# Reliability-First Refactor Handoff After Phase 5

Date: 2026-06-01
Supersedes: `2026-06-01-reliability-first-refactor-phase-3-handoff.md`

## Continue Here

- Worktree: `/home/deadpool-ultra/ODIN/OSINT/.worktrees/ingestion-image-runtime-recovery`
- Branch: `fix/ingestion-image-runtime-recovery`
- Base: `27fac78` (`main`)
- Plan: `docs/superpowers/plans/2026-06-01-reliability-first-refactor.md`
- **The reliability half (Phases 1–5) is complete.** Recommended next cut: open a
  reliability PR and merge before starting Phase 6 (the dedup/cleanup half).
- Next task after merge: **Phase 6 — delete dead intelligence `indexer.py` + `chunker.py` (AST write-separation guard)**.

Do not continue in the primary checkout. It is on `feature/factbook-almanac` and contains unrelated WIP.

## Completed (Phases 1–5 + review follow-ups)

Phases 1–3 (resource lifecycle / image runtime / startup rollback) were handed off earlier.
Added since the Phase-3 handoff:

```text
962c3db docs(api): de-alias README + architecture tables; reconcile graph/vision
1e0b23b docs(intelligence): drop stale legacy-fallback wording; remove dead mode
4d5773d fix(frontend): parse SSE error payload + harden CRLF; test mutation no-replay
a0f5bed test(contract): fix stale /api/v1 prefix and port in root contract test
ed30e24 docs(api): drop /api/v1 from smoke checks and live runbooks
d4d92c9 refactor(backend): remove /api/v1 back-compat alias mounts
e180f54 refactor(frontend): drop /api/v1 fallback; call /api directly (no replay)
3099852 fix(frontend): carry SSE event type across chunks and fire onDone once
57ce01c fix(intelligence): fail-closed on react failure instead of silent legacy/200-error
55d8484 docs(plan): defer dormant gdelt_collector Phase-2 defect
1fa8e22 test(backend,intelligence): assert QdrantSchemaMismatch propagates through schema guard
```

### Phase 4 — Legacy fallback fail-closed (C7)
- A ReAct failure with `use_legacy=False` now **propagates** (FastAPI 500 → backend
  `raise_for_status` → SSE `INTEL_SERVICE_ERROR`) instead of silently falling back to the
  legacy no-sources pipeline or returning a `mode:"error"` HTTP-200 dict.
- Explicit `use_legacy=True` behaviour unchanged. `test_nodes_sources.py` evidence-contract
  guardrail untouched.

### Phase 5a — SSE parser
- `currentEvent` hoisted across chunk boundaries (event/data split no longer loses the event);
  `onDone` fires exactly once via a `doneEmitted` latch.

### Phase 5b — `/api/v1` prefix removal (C8)
- All `/api/v1` back-compat alias mounts removed (REST routers, recon, health/config).
- Frontend: `LEGACY_BASE`/`fetchWithFallback` gone; `fetchJSON`/`queryIntel`/`deleteReport`
  hit `/api` once with **no 404 replay** (mutations never double-execute).
- 10 backend test files re-pointed to `/api/*`; `test_main_mounts.py` guards that no route
  starts with `/api/v1`. The two negative assertions (`test_signals_stream.py`,
  `apiBase.test.ts`) are intentionally kept.
- Smoke (`odin.sh`) + live docs de-aliased; ADR `0001` and historical specs intentionally retain the string.

### Review follow-ups (external review, all fixed)
- F1: root `tests/contract/test_api_contract.py` re-pointed to `http://localhost:8080/api`.
- F2: `README.md` + both `architecture.md` endpoint tables de-aliased AND reconciled against
  the actually-mounted routes (dropped non-existent `/api/vision/*`, `graph/query`,
  `graph/.../neighborhood`, `graph/events/recent`; real graph routes listed).
- F3: regression tests — `queryIntel`/`deleteReport` make exactly one fetch on a 404.
- F4: SSE error payload parsed (`.error`) + CRLF hardened (`split(/\r?\n/)`).
- F5: stale "automatic legacy fallback" wording removed from `workflow.py`; dead
  `legacy_fallback` value removed from the frontend `IntelAnalysis.mode` union.

### Review follow-ups, round 2 (all fixed)
- Ingestion image `CMD` runs the built venv python directly (was `uv run python`,
  which re-resolved dependencies at container start — pulling dev tooling and
  needing network); the Dockerfile contract test now guards against a uv-run CMD.
- `TASKS.md` active future-task specs (TTS-briefing audio, Fusion-Core endpoints)
  and the completed TASK-105 graph endpoint de-aliased to `/api`
  (`GET /api/graph/network/{name}`); the point7 ops doc health check → `/api/health`.
- Trimmed a trailing blank line flagged by `git diff --check`.

## Verification (fresh, 2026-06-01)

```text
services/backend         275 passed   · ruff clean
services/intelligence    227 passed   · ruff clean
services/data-ingestion  654 passed, 1 skipped (pre-existing)  · ruff clean
services/frontend        257 passed (63 files) · tsc clean · eslint 0 errors
bash -n odin.sh          clean
```

Notes:
- `tests/contract/test_api_contract.py` (root) hits a live backend on `:8080` and is not run
  in CI / not runnable without the stack — the F1 fix is a static prefix/port correction.
- Backend strict Mypy remains pre-existing red (62 errors); no new errors introduced.
- Frontend: 6 pre-existing eslint warnings in `GraphCanvas.tsx` (unused eslint-disable
  directives) are unrelated to this branch.

## Known Debt (tracked, non-blocking)

- **`feeds/gdelt_collector.py`** (legacy GDELT DOC-API collector) still carries the pre-Phase-2
  sync-on-loop + unclosed-client defect class. It is **unscheduled/dormant**, so out of scope;
  tracked in the plan's Deferred section (commit `55d8484`). Resolve (RS-treatment or delete)
  before any re-wiring.
- Phases 6–10 of the plan (dead indexer/chunker delete, scroll-cap helper, polling hook, typed
  primitive metadata, dead GDELT toggle) remain — the dedup/cleanup half.

## Next Execution Slice (Phase 6, after the reliability PR merges)

1. Add the AST write-separation guard test `intelligence/tests/test_no_qdrant_write.py` (red).
2. Confirm `rag/indexer.py` + `rag/chunker.py` are unimported, then delete both.
3. Run intelligence + the AST guard green; update `TASKS.md:99` / `architecture.md:444`.
4. Commit `refactor(intelligence): delete dead indexer+chunker; AST write-separation guard`.
