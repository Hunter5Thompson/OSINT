# Reliability-First Refactor Handoff After Phase 3

Date: 2026-06-01

## Continue Here

- Worktree: `/home/deadpool-ultra/ODIN/OSINT/.worktrees/ingestion-image-runtime-recovery`
- Branch: `fix/ingestion-image-runtime-recovery`
- Base: `27fac78` (`main`)
- Plan: `docs/superpowers/plans/2026-06-01-reliability-first-refactor.md`
- Next task: **Phase 4 — Legacy Fallback: fail-closed via exception propagation**

Do not continue in the primary checkout. It is on `feature/factbook-almanac` and contains unrelated WIP, including `services/data-ingestion/feeds/_http.py`.

## Completed

Phases 1-3 are implemented as 10 reviewable commits:

```text
4758616 fix(data-ingestion): fail fast on invalid event codebook
c7d6499 fix(data-ingestion): recover ingestion image runtime contract
09c1bb1 fix(data-ingestion): close qdrant reader clients
ad348da fix(data-ingestion): make rss qdrant access async-safe
6ea35ab fix(data-ingestion): own telegram qdrant client lifecycle
1d75252 fix(data-ingestion): close and preflight raw gdelt qdrant
49fd727 fix(data-ingestion): construct qdrant owners off loop
6647c63 fix(backend): keep qdrant schema guard retryable
9d77677 fix(backend): rollback and close lifespan resources
3a4bee3 fix(intelligence): close retriever runtime clients
```

### Phase 1

- Ingestion image now packages `qdrant_doctor`, `infra_atlas`, the event codebook and a tracked ingestion `uv.lock`.
- Codebook file failures are fail-fast; unknown LLM codebook values still map to `other.unclassified`.
- Clean image build and runtime smoke passed.
- Extra smoke-derived fix: `infra_atlas` CLI repo-root discovery works inside the image.

### Phase 2

- Base, hotspot and correlation Qdrant clients close correctly.
- Hotspot scroll no longer blocks the event loop.
- RSS Qdrant setup/retrieve/upsert are off-loop; setup moved out of `__init__`.
- Telegram uses one lazy collector-owned Qdrant client, one preflight and a real close path.
- Raw-GDELT scheduler and CLI close Redis, Neo4j and Async-Qdrant; writer preflight runs once before writes.
- Extra reliability fix: scheduler constructs all Qdrant-owning collectors via `asyncio.to_thread`, because `QdrantClient(...)` can probe compatibility during initialization.

### Phase 3

- Backend Qdrant schema network errors remain best-effort but no longer disable future validation attempts.
- Backend Qdrant and Neo4j singletons expose reset-safe close functions.
- Backend lifespan rolls back partial startup and continues cleanup after individual close failures.
- Intelligence schema preflight always closes its temporary Async-Qdrant client.
- Intelligence shutdown closes both GraphClient owners: retriever and workflow.

## Verification

Fresh verification after Phase 3:

```text
cd services/backend
NEO4J_PASSWORD=test uv run pytest -q
# 274 passed, 1 warning
uv run ruff check app/ tests/
# All checks passed

cd services/intelligence
uv run pytest -q
# 225 passed
uv run ruff check .
# All checks passed
```

Phase-2 full verification:

```text
cd services/data-ingestion
uv run pytest -q
# 654 passed, 1 skipped, 15 deselected
uv run ruff check .
# All checks passed
```

Phase-1 image verification included:

```text
docker build --no-cache -f services/data-ingestion/Dockerfile \
  -t odin-data-ingestion-phase1-audit .
```

The scheduler import, codebook, missing-codebook fail-fast, distribution, secret absence, `qdrant-doctor --help`, `infra-atlas --help` and compose service smokes passed.

## Known Debt

Backend strict Mypy is pre-existing red:

```text
cd services/backend
uv run mypy app/
# Found 62 errors in 19 files
```

The Phase-3 Lifespan change initially introduced three additional type errors; those were fixed. Do not mix the remaining Mypy cleanup into this refactor unless explicitly requested.

Ignored local artifacts in the isolated worktree include backend/intelligence `.venv`, caches and regenerated ignored `uv.lock` files. The tracked ingestion `uv.lock` is intentional.

## Next Execution Slice

Implement Phase 4 exactly as specified:

1. Add a red intelligence workflow test forcing `react_graph.ainvoke` to raise with `use_legacy=False`.
2. Assert the exception propagates instead of returning `mode="legacy_fallback"` or HTTP-200 `mode="error"`.
3. Remove both silent fallback layers for the ReAct branch.
4. Keep explicit `use_legacy=True` behavior and `tests/test_nodes_sources.py` unchanged.
5. Run the intelligence suite and Ruff, then commit the Phase-4 slice separately.

After Phase 4, continue with Phase 5a SSE parsing before any `/api/v1` removal.
