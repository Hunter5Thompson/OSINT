# Reliability-First Refactor — Implementation Plan (rev. 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> Each Phase is an **independently executable, independently testable** sub-plan (work spans 4 subsystems — deliberately not one monolith). Execute phases 1–5 (reliability) before 6–10 (dedup/cleanup).

**Goal:** Stabilise the WorldView/ODIN runtime (deployability + resource ownership + read-path integrity) before any deduplication, then do only the verified, low-risk dedup work.

**Architecture:** Reliability-first sequencing. Phases 1–5 fix runtime defects the original dedup plan would have built on; 6–10 are the surviving verified cleanups. Everything is TDD: characterization/contract test (red) → minimal fix (green) → commit.

**Tech Stack:** FastAPI + Pydantic v2 + httpx + Redis + Qdrant + Neo4j (`uv`, per-service), React 19 + Vite + CesiumJS + Vitest. Full-repo ruff gate (CI `lint-python`, 4 services).

---

## Provenance & verification status

Five review rounds fed this plan (external dedup plan → my audit → Codex reliability review → Codex plan-review (round 4) → Codex rev-2 review (round 5)). **Round-4 = 10 corrections, all verified by a 10-agent workflow. Round-5 = 4 blockers + 2 corrections + minors, all verified against `main` and incorporated in rev. 3:** RSS has **three** sync qdrant calls incl `_ensure_collection` in `__init__` (not just `retrieve`); raw-GDELT is a writer with **no** preflight (`grep` empty); the polling hook's `AbortSignal` must thread through `api.ts` (getters take none today); PipelineLayer is the **6th** layer / 7th writer (15 sites); `.dockerignore`/smoke hardened to spec; Task 1.2 ordered before 1.1; `queryIntel`/`deleteReport` + `TASKS.md:190` added to the `/api/v1` scope; `AGENTS.md` is **untracked** (ownership flagged); Phase 10 made deterministic. Round-4 verdicts:

| C# | Topic | Verdict | Net effect on plan |
|---|---|---|---|
| C1 | P0b packaging | confirmed | Phase 1 adopts the existing spec's atomic-commit packaging verbatim |
| C2 | codebook fail-fast | confirmed | always-raise `CodebookConfigError`; drop `CODEBOOK_REQUIRED`; injectable loader |
| C3 | schema-guard test | **refuted my test** | corrected RED test: mock `get_collections`, not `_validate_schema` |
| C4 | writer/reader split | partially confirmed | reclassify 6 targets; rss already has preflight; readers ≠ preflight; +scheduler +cli |
| C5 | intelligence lifecycle | confirmed | add `intelligence/main.py` + `retriever.close()` + intel test |
| C6 | startup rollback | confirmed | wrap lifespan in try/finally + partial-startup test |
| C7 | fallback fork | partially confirmed | single approach; **must propagate exception**, not return `mode:"error"` 200 |
| C8 | `/api/v1` breadth | confirmed | enumerate 11 backend test files, odin.sh, 3 docs; narrow exit; keep negative asserts |
| C9 | indexer guard | confirmed | AST guard (not import); also delete `chunker.py` |
| C10 | polling/cesium | confirmed | widen hook contract; fix path; 14 cast sites (not 5) |

### Verified defect ledger (evidence base, `file:line` on `main`)

| Ref | Defect | Sev |
|---|---|---|
| `docker-compose.yml:262-267` + `:316-321` | both `data-ingestion` and `data-ingestion-spark` use `context: ./services/data-ingestion` → cannot COPY the codebook in `services/intelligence/` | P0 |
| `services/data-ingestion/Dockerfile:10-21` | COPYs only service-relative paths; **omits `qdrant_doctor/` and `infra_atlas/`** → `import scheduler` raises `ModuleNotFoundError: qdrant_doctor` (via `feeds/base.py:18`, `rss_collector.py:18`, `gdelt_collector.py:17`) **before** codebook even loads | P0 |
| `services/data-ingestion/pipeline.py:44-60` (+ `:91-102`) | missing/empty/broken codebook YAML → silent degrade to `other.unclassified` (no raise) | P0 |
| `services/data-ingestion/feeds/base.py:129-130` | `close()` closes only `self.http`, never the sync `QdrantClient` (`base.py:32`). NB: all qdrant calls are already `asyncio.to_thread`-wrapped (`base.py:47,52,64,93,103`) — no async migration needed | P1 |
| `rss_collector.py:170,258,321` | **three** sync qdrant calls on the loop: `_ensure_collection()` runs in `__init__` (`:170`, sync preflight via `:196`), dedup `retrieve` (`:258`), `upsert` (`:321`); no `close()` | P1 |
| `telegram_collector.py:636-637` | bare `QdrantClient` created **per message**, never closed, **no schema preflight** | P1 |
| `gdelt_raw_collector.py:48-51` + `gdelt_raw/cli.py:34-58` + `gdelt_raw/writers/qdrant_writer.py:108` | run path / shipped CLI leak `aioredis` + `AsyncQdrantClient` (only neo4j closed); **AND the writer `upsert`s with NO schema preflight** (`grep validate_collection_schema gdelt_raw/` empty) | P1 |
| `hotspot_updater.py:115` + `:209-212` | **reader**: sync `self.qdrant.scroll(...)` on the loop; `close()` closes only redis, never `self.qdrant` (`:97`) | P1 |
| `correlation_job.py:170` + `:198` | **reader**: scroll already `to_thread`; but **no `close()` method at all** → qdrant never closed | P1 |
| `scheduler.py:136-142` (rss), `:234-242` (correlation) | wrappers have no `finally`/`close()`; `:156-164` (hotspot) + `:167-175` (telegram) close non-qdrant only → any new `close()` is dead unless wired | P1 |
| `backend/app/services/qdrant_client.py:39-52` | `_validate_schema` `except Exception: pass` swallows net errors → caller sets `_schema_validated=True` (`:33`) → guard permanently off; singleton never closed | P1 |
| `intelligence/rag/retriever.py:17,23-31,46` | 2nd module `GraphClient` never closed; temp `AsyncQdrantClient` (`:46`) leaks; `intelligence/main.py:13-15` closes only the **workflow** client (`workflow.py:329`) | P1 |
| `backend/app/services/neo4j_client.py:10` | global `_driver` never closed; lifespan doesn't close it | P1 |
| `backend/app/main.py:60-143` | no `try/finally` around startup-then-`yield` (yield at `:143`, teardown `:145-163`); mid-startup failure leaks proxy (`:65`, started first) / cache (`:69`) / collector (`:73`) | P1 |
| `intelligence/graph/workflow.py:375-405` | `except (TimeoutError, Exception)` → silent legacy fallback (`sources_used=[]`); **and** the react branch is caught and returned as `mode:"error"` HTTP-200 dict → backend never sees failure | P1 |
| `frontend/src/services/api.ts:90` | `fetchWithFallback` replays **POST/PATCH/DELETE** on 404 vs `/api/v1`; unmigrated: `frontend/src/components/graph/EntityExplorer.tsx:16` (hardcoded `/api/v1/graph`), `frontend/src/components/worldview/SearchPanel.tsx:52` (inline v1 fallback) | P1 |
| `frontend/src/services/api.ts:184,~206` | SSE: `currentEvent` declared inside the per-chunk loop → event/data split loses event; `onDone()` fires in-loop **and** after loop | P1 |
| `backend/app/routers/eonet.py:83` (+`firms.py`,`gdacs.py`) | scroll `extend`s a full page then checks `>= _MAX_TOTAL` → overshoots by ≤ `_PAGE_SIZE-1` | P2 |
| `intelligence/rag/indexer.py:24,76-77` | unimported; `client.put(.../points)` writes Qdrant → read/write-separation violation; `rag/chunker.py:4` is dead once indexer goes (sole importer `indexer.py:9`) | P2 |
| frontend layers | **15 sites / 6 layers**: 7 writer-side `_xData=` (`FlightLayer:128,143` ×2, `CableLayer:164`, `ShipLayer:101`, `EventLayer:194`, `SatelliteLayer:164`, `PipelineLayer:158`) + 8 reader casts (`SatelliteLayer:254`, `FlightLayer:245`, `EntityClickHandler:47,78,127,173,218,268`) | P2 |
| `backend/app/services/incident_promoter/config.py:34` (toggle) + `:54-55` (`enabled_detector_ids()` appends `'gdelt'`) + `backend/app/main.py:118-124` (`_detectors` list build — never appends a GdeltDetector) | `gdelt_enabled` advertised by `enabled_detector_ids()` but no detector instantiated → dead toggle | P3 |

### Struck / not real (do not action)
- **P0a "incident rehydrate crash"** — already fixed on `main` (`incident_store.py:225` binds `{"limit": _REHYDRATE_LIMIT}`; redis `aclose()` at `cache_service.py:26`, `signal_stream.py:264`). Re-verify any remaining `2026-05-31-backend-runtime-reliability-design.md` claims before reuse.
- **"`_ensure_collection`/`_content_hash` copied 11×"** — false; `BaseCollector` centralises them (`base.py:85`); only `rss`/`gdelt` duplicate. The real collector issue is resource ownership (Phase 2).

### Hard guardrails (every phase; a PR breaking one is rejected)
- **Evidence contract (TASK-014c, merged):** `sources_used: list[str]` of provider IDs; `routers/intel.py:106` keeps the `[:6]` cap; no credibility on write path; legacy path intentionally returns `sources_used=[]`. **`intelligence/tests/test_nodes_sources.py` and the intel-router tests stay green UNCHANGED.**
- **Two-Loop:** no LLM-generated Cypher on the write path; no writes on the read path; every Neo4j query parameter-bound.
- **Dirty worktree:** parallel-agent WIP — never `git add -A`; stage only files you create/modify by explicit path. **`AGENTS.md` is UNTRACKED** (`git ls-files --error-unmatch AGENTS.md` → "no known files"), as are `feeds/_http.py`, `tests/test_http_retry.py`, the three `docs/.../specs/2026-05-*`; `tests/test_pipeline.py` and `.codex` are modified-tracked. **Resolve `AGENTS.md` ownership before Phase 1 amends it** (the packaging PR would be what first commits it — confirm that is intended, or coordinate with the parallel agent who created it).
- **Green baselines at each phase boundary:** intelligence 221 · data-ingestion 611(+1 skip) · backend 264 · vision-enrichment 22 · frontend vitest. Backend tests need `NEO4J_PASSWORD` (CI dummy).

---

## Phase 1 — P0b: Ingestion Image Runtime Recovery (atomic)

**Why / invariant:** The data-ingestion image must contain every runtime module its scheduler imports **and** the canonical codebook, and must **fail fast** when the codebook file is absent/empty/broken. This is already designed in `docs/superpowers/specs/2026-05-31-ingestion-runtime-recovery-design.md` — adopt it. All packaging changes land in **one atomic commit** (no intermediate root-context-without-dockerignore state).

**Commit ordering (important):** run **Task 1.2 (codebook fail-fast) BEFORE Task 1.1 (packaging)**, or squash both into one commit. If packaging lands first, there is a committable intermediate where the image copies the codebook to `/app/runtime_contracts/` but `pipeline.py` still reads the old hardcoded path and **silently degrades** — exactly the defect this phase removes. Doing 1.2 first means the image fails *loud* (CodebookConfigError) until packaging supplies the file, which is the desired direction.

**Files (atomic packaging commit):**
- Modify: `docker-compose.yml:262-267` (`data-ingestion`) + `:316-321` (`data-ingestion-spark`) → `build: { context: ., dockerfile: services/data-ingestion/Dockerfile }`
- Modify: `services/data-ingestion/Dockerfile` (qualify COPYs, add modules + codebook, pin uv, two-stage sync)
- Create: `/.dockerignore` (root; none exists)
- Track: `services/data-ingestion/uv.lock` (force-add) + `/.gitignore` re-include
- Modify: `AGENTS.md:19` (lockfile exception)
**Files (codebook fail-fast commit):**
- Modify: `services/data-ingestion/pipeline.py:39-102`, `services/data-ingestion/config.py`
- Test: `services/data-ingestion/tests/test_codebook_loading.py` (create)

### Task 1.1 — Atomic packaging
- [ ] **Step 1** — `git ls-files '*uv.lock'` → confirm 0 (codebook + lock both absent from image today). `docker build` the current image and `docker run … python -c "import scheduler"` → capture the `ModuleNotFoundError: qdrant_doctor` (this is the characterization of the P0).
- [ ] **Step 2** — Add root `/.dockerignore` (match the spec's list at `2026-05-31-ingestion-runtime-recovery-design.md:154`): `.git`, `.claude/worktrees`, `**/.venv`, `**/__pycache__`, `*.pyc`, `**/.pytest_cache`, `**/.ruff_cache`, `**/.env`, `**/.env.*`, `**/node_modules`, `**/dist`, `services/frontend`, `docs`, `*.dump`.
- [ ] **Step 3** — `docker-compose.yml`: both services → `context: .`, `dockerfile: services/data-ingestion/Dockerfile`.
- [ ] **Step 4** — Dockerfile: pin `COPY --from=ghcr.io/astral-sh/uv:0.10.0` (was `:latest` at `:7`); qualify every COPY with `services/data-ingestion/`; **add** `COPY services/data-ingestion/qdrant_doctor/ qdrant_doctor/`, `COPY services/data-ingestion/infra_atlas/ infra_atlas/`, and `COPY services/intelligence/codebook/event_codebook.yaml runtime_contracts/event_codebook.yaml` + `ENV EVENT_CODEBOOK_PATH=/app/runtime_contracts/event_codebook.yaml`; use two-stage `uv sync --locked --no-dev --no-install-project` then `uv sync --locked --no-dev`. Do **not** copy `migrations/` (spec-excluded).
- [ ] **Step 5** — `/.gitignore`: first `grep -n 'uv.lock\|\.lock' .gitignore` to confirm the real ignore pattern (today: `.gitignore:23 services/**/uv.lock`). Add the negation `!services/data-ingestion/uv.lock` immediately after that exact pattern line. **Load-bearing action is `git add -f services/data-ingestion/uv.lock`** (git negations don't re-include a file whose parent dir is excluded, so treat the `!` line as future-hygiene, not the mechanism). `uv lock` in the service first to (re)generate it.
- [ ] **Step 6** — `AGENTS.md:19`: the current line is `**Lockfiles are gitignored** — \`uv sync\` regenerates \`uv.lock\`, \`npm install\` regenerates \`package-lock.json\`.` Replace it **preserving the regeneration clause**, e.g.: `**Lockfiles are gitignored** (\`uv sync\` / \`npm install\` regenerate them) **except** the tracked deployment lock \`services/data-ingestion/uv.lock\`.`
- [ ] **Step 7 — Clean-build smoke (match spec `:287`, stronger than file-existence):** `docker build -f services/data-ingestion/Dockerfile .` then in the container assert: (a) `python -c "import scheduler"` raises no `ModuleNotFoundError`; (b) the **codebook actually loads** — `python -c "from pipeline import _load_codebook_types; assert len(_load_codebook_types()) > 1"` (proves more than the `other.unclassified` fallback, i.e. the real file resolved via `EVENT_CODEBOOK_PATH`); (c) **no secrets leaked** — `! ls /app/.env* 2>/dev/null` and the build context excludes `.env` (Step 2); (d) **both console-script entrypoints exist** — `python -c "import importlib.metadata as m; m.distribution('worldview-data-ingestion')"` / run `odin-qdrant-doctor --help` and `odin-infra-atlas --help` (the two-stage `--no-install-project` then full sync makes these real). Add a static test `test_uv_lock_tracked` that runs **from the service dir**: `cd services/data-ingestion && git ls-files --error-unmatch uv.lock` exits 0 (do NOT pass the repo-relative path as the arg).
- [ ] **Step 8 — Commit** (one): `fix(data-ingestion): root build-context image with qdrant_doctor+infra_atlas+codebook, tracked uv.lock`.

### Task 1.2 — Codebook fail-fast (injectable loader, always-raise)
- [ ] **Step 1 — Failing tests** (injectable loader, no `importlib.reload`):
```python
# services/data-ingestion/tests/test_codebook_loading.py
import pytest
from pathlib import Path
from pipeline import _load_codebook_types, CodebookConfigError

def _write(p: Path, text: str) -> Path:
    p.write_text(text); return p

def test_valid_codebook_loads(tmp_path):
    f = _write(tmp_path / "cb.yaml",
               "categories:\n  military:\n    types:\n      - {type: 'military.airstrike'}\n")
    assert "military.airstrike" in _load_codebook_types(f)

def test_missing_codebook_raises(tmp_path):
    with pytest.raises(CodebookConfigError):
        _load_codebook_types(tmp_path / "nope.yaml")

def test_empty_codebook_raises(tmp_path):
    with pytest.raises(CodebookConfigError):
        _load_codebook_types(_write(tmp_path / "e.yaml", ""))

def test_broken_codebook_raises(tmp_path):
    with pytest.raises(CodebookConfigError):
        _load_codebook_types(_write(tmp_path / "b.yaml", "categories: [unterminated"))

def test_codebook_error_is_not_extraction_config_error():
    from pipeline import ExtractionConfigError
    assert not issubclass(CodebookConfigError, ExtractionConfigError)
```
- [ ] **Step 2 — Run, expect FAIL** (`uv run pytest tests/test_codebook_loading.py -v`): no `CodebookConfigError`, loader not injectable.
- [ ] **Step 3 — Implement** in `pipeline.py`:
  - add `class CodebookConfigError(RuntimeError): ...`;
  - refactor `_load_codebook_types()` → `_load_codebook_types(path: Path | None = None)` that resolves the path as `Path(path or settings.event_codebook_path)` and **always raises `CodebookConfigError`** on missing/unreadable/empty/no-types/`YAMLError`/`KeyError` (replaces the silent-degrade `except` at `:44-60`);
  - **also route `_build_system_prompt()` (`:88-102`) through the SAME resolved path / a shared loader** so it no longer opens the hardcoded `_CODEBOOK_PATH` and no longer silently degrades to its 6-type minimal prompt — it must raise `CodebookConfigError` when the file is absent (this is a SECOND silent-degrade path; in the image the codebook lives at `/app/runtime_contracts/…`, not `../intelligence/codebook/…`, so without this fix `_build_system_prompt` would always degrade);
  - in `config.py`, set the default to the real current path, **not** an empty string: `event_codebook_path: str = str(Path(__file__).parent.parent / "intelligence" / "codebook" / "event_codebook.yaml")` (env `EVENT_CODEBOOK_PATH` overrides). An empty default would make `Path("")` → always-raise and break local/test runs.
  - **Leave `_validate_codebook_type` (`:66-85`) and its `other.unclassified` fallback for unknown LLM types untouched** — only the file-load path fails fast.
  - Add a test `test_build_system_prompt_raises_when_codebook_missing` (monkeypatch `settings.event_codebook_path` to a nonexistent path → `pytest.raises(CodebookConfigError)`), and a happy-path test that `_build_system_prompt()` returns a prompt containing a real codebook type when the path is valid.
- [ ] **Step 4 — Run** `uv run pytest -q` (611+1 + 5 new green).
- [ ] **Step 5 — Commit:** `fix(data-ingestion): fail-fast CodebookConfigError on missing/empty/broken codebook`.

**Risk:** Medium (packaging). **Exit:** clean image boots `import scheduler`; codebook present-or-`CodebookConfigError`; `uv.lock` tracked; unknown-LLM-type fallback preserved.

---

## Phase 2 — Active-Writer + Reader Qdrant Lifecycle & Loop-Safety

**Why / invariant:** Every Qdrant/Redis client is owned: closed on shutdown and (for **writers**) gated by schema preflight; no sync Qdrant call on the event loop. Writers ≠ readers — do not impose writer preflight on readers.

**Target classification (verified):**
| Target | Role | Tasks |
|---|---|---|
| `feeds/base.py:129` | base | `close()` also closes `self.qdrant` (`to_thread(self.qdrant.close)`); **no async migration** (calls already `to_thread`) |
| `rss_collector.py:170,258,321` | writer | preflight logic exists (`_ensure_collection` validates at `:196`) **but is SYNC and called in `__init__` (`:170`) → blocks the loop**. Fix **all three** sync qdrant calls via `to_thread`: `_ensure_collection` (get_collections/create/get), dedup `retrieve` (`:258`), `upsert` (`:321`). Move `_ensure_collection` out of `__init__` into an async setup run via `await asyncio.to_thread(...)` at the start of `collect()`. Add `close()`. |
| `telegram_collector.py:636` | writer | **add preflight**; one client for collector lifetime (not per-message); close it |
| `gdelt_raw_collector.py:48` + `gdelt_raw/writers/qdrant_writer.py:108` | writer (async-native) | **(a) leak-closure** (close `aioredis`+`AsyncQdrantClient`) **AND (b) ADD a one-time schema preflight before the first `upsert`** — `grep` confirms gdelt_raw has NO `validate_collection_schema`/`ensure_collection` today, violating the Phase-2 writer invariant. Preflight must run on both the scheduler path and the CLI path. |
| `gdelt_raw/cli.py:34-58` | shipped CLI | close `aioredis`+`AsyncQdrantClient` in every command `finally`; run the same one-time preflight before first write |
| `hotspot_updater.py:115,209` | **reader** | `to_thread` the scroll; `close()` also closes `self.qdrant`; **no preflight** |
| `correlation_job.py:170,198` | **reader** | add `close()` closing `self.qdrant` (scroll already `to_thread`); **no preflight** |
| `scheduler.py:136,234,156,167` | wiring | every wrapper `try/finally`-closes its collector |

- [ ] **Step 1 — Contract test (red):** `tests/test_writer_lifecycle.py` — for each target assert (a) `close()` closes the qdrant client, (b) no sync qdrant call runs unwrapped on the loop. Plus a scheduler test: each `run_*` wrapper invokes `close()` in `finally` (assert `qdrant.close`/`aclose` awaited).
- [ ] **Step 2 — Run, expect FAIL** (base/rss/telegram/correlation lack qdrant-close; scheduler lacks finally).
- [ ] **Step 3 — base.py:** `close()` → also `await asyncio.to_thread(self.qdrant.close)`.
- [ ] **Step 4 — per-target (one commit each):** rss (**move `_ensure_collection` out of `__init__`**; wrap all three sync calls — `_ensure_collection`, `retrieve` `:258`, `upsert` `:321` — in `asyncio.to_thread`; add `close()`; **tests for all three** asserting no unwrapped sync qdrant call on the loop), telegram (collector-lifetime client + `_ensure_collection`/`validate_collection_schema` preflight + close), gdelt_raw collector + **cli** (close redis+qdrant in `finally` **and** add a one-time schema preflight before first `upsert` on both paths), hotspot (`to_thread` scroll + close qdrant), correlation (add `close()`).
- [ ] **Step 5 — scheduler.py:** `run_rss_collector` (`:136`) + `run_correlation_job` (`:234`) get `try/finally: await collector.close()`; `run_hotspot_updater` (`:156`) + `run_telegram_collector` (`:167`) `finally` also close qdrant.
- [ ] **Step 6 — Run** `uv run pytest -q` after each; **commit per target**.

**Risk:** Medium (loop + shutdown ordering). **Exit:** no unwrapped sync qdrant on loop; every client closed; scheduler invokes every `close()`; writers preflight, readers don't.

---

## Phase 3 — Backend + Intelligence Client Lifecycle, Schema Guards, Startup Rollback

**Why / invariant:** A transient network error must **not** permanently disable the schema guard; long-lived clients (Qdrant, Neo4j, both GraphClients) close on shutdown; a mid-startup failure rolls back already-started resources.

**Files:**
- `backend/app/services/qdrant_client.py:31-52` (guard re-validates after transient error; add close)
- `backend/app/services/neo4j_client.py:10` (add `async def close_driver()`)
- `backend/app/main.py:60-163` (try/finally rollback; close qdrant+neo4j on exit)
- `intelligence/rag/retriever.py:17,23-31,46` (add `close()`; `async with` the temp qdrant client)
- `intelligence/main.py:13-15` (lifespan: also close retriever clients)
- Tests (create): `backend/tests/unit/test_qdrant_guard.py`, `backend/tests/test_lifespan_startup_failure.py`, `backend/tests/unit/test_lifespan_closes_clients.py`, `intelligence/tests/test_retriever_lifecycle.py`

### Task 3.1 — Schema guard stays retryable (CORRECTED test — C3)
> The earlier draft patched `_validate_schema` to raise; that is **green today** (the caller never reaches `_schema_validated=True`). The real bug is the swallow **inside** `_validate_schema`. Drive the test through the real validator.
- [ ] **Step 1 — Failing test:**
```python
# backend/tests/unit/test_qdrant_guard.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import app.services.qdrant_client as qc

@pytest.fixture(autouse=True)
def _reset_globals():
    client, validated = qc._client, qc._schema_validated
    qc._client, qc._schema_validated = None, False
    yield
    qc._client, qc._schema_validated = client, validated

@pytest.mark.asyncio
async def test_transient_error_keeps_guard_retryable():
    inst = MagicMock()
    inst.get_collections = AsyncMock(side_effect=ConnectionError("boom"))
    with patch("app.services.qdrant_client.AsyncQdrantClient", return_value=inst):
        await qc.get_qdrant_client()                 # today: swallowed → returns
        assert qc._schema_validated is False         # FAILS today (swallow sets True)
        await qc.get_qdrant_client()                 # must re-validate
        assert inst.get_collections.call_count == 2  # proves retryable
```
- [ ] **Step 2 — Run, expect FAIL** (`_schema_validated` is `True` after the swallow; `call_count == 1`).
- [ ] **Step 3 — Fix** `_validate_schema`: re-raise transient errors (drop the bare `except Exception: pass`; let it propagate, or return a sentinel) so the caller sets `_schema_validated = True` **only** on clean validation; keep `except QdrantSchemaMismatch: raise`. Add a `close()` for the qdrant singleton.
- [ ] **Step 4 — Run** backend (264 + new) green; **commit**.

### Task 3.2 — Backend lifespan rollback + neo4j close
- [ ] **Step 1 — Failing test** (`test_lifespan_startup_failure.py`): monkeypatch `CacheService.connect` to raise; run lifespan; assert the already-started `proxy.stop()` was awaited. Plus `test_lifespan_closes_clients.py`: normal shutdown awaits qdrant close + `neo4j_client.close_driver()`.
- [ ] **Step 2 — Run, expect FAIL** (no try/finally; neo4j never closed).
- [ ] **Step 3 — Implement:** wrap startup-then-`yield` in `try/finally` (or staged reverse-order rollback tracking what started — proxy is started **first** at `:65`); add `close_driver()` to `neo4j_client.py` and call it + qdrant close in the teardown.
- [ ] **Step 4 — Run** backend green; **commit**.

### Task 3.3 — Intelligence retriever lifecycle
- [ ] **Step 1 — Failing test** (`intelligence/tests/test_retriever_lifecycle.py`): (a) `retriever.close()` awaits the module `GraphClient.close()` and resets `_graph_client`/`_schema_validated`; (b) temp `AsyncQdrantClient` not leaked on the validate path; (c) transient error in `_ensure_schema_validated` leaves `_schema_validated False`; (d) `QdrantSchemaMismatch` re-raised, flag stays False. Plus an intelligence-lifespan test: shutdown awaits `retriever.close()`.
- [ ] **Step 2 — Run, expect FAIL** (no `close()`; temp client leaks).
- [ ] **Step 3 — Implement:** add `async def close()` to `retriever.py`; wrap the temp `AsyncQdrantClient` (`:46`) in `async with`; in `intelligence/main.py:13-15` call `await retriever.close()` alongside `shutdown_graph_client()`. **No DI framework** (deferred).
- [ ] **Step 4 — Run** intelligence (221 + new) green; **commit**.

**Risk:** Medium. **Exit:** transient failure ≠ permanent guard-off; partial startup rolls back; all clients (backend qdrant/neo4j, intelligence workflow+retriever graph, temp qdrant) closed.

---

## Phase 4 — Legacy Fallback: fail-closed via exception propagation (single approach, C7)

**Why / invariant:** An analytical report must never silently come from the legacy (no-sources) path. **Single** approach — no `degraded:true` flag (it would need new model+SSE+UI fields, none in scope; `grep degraded` → none).

**Critical nuance (C7):** deleting the fallback line is **not enough**. `workflow.py:382-405` also catches the react failure and returns a `mode:"error"` HTTP-200 dict; `intelligence/main.py:34-41` returns it without raising → backend `raise_for_status` (`intel.py:76`) never trips → the existing SSE error path (`intel.py:119-140`, `INTEL_SERVICE_ERROR`) never fires. The failure **must reach the backend as non-2xx**.

**Files:** `intelligence/graph/workflow.py:367-405`; rely on existing `backend/app/routers/intel.py:76,119-140`. Test: `intelligence/tests/test_workflow.py` (extend).

**Guardrail:** must NOT touch `test_nodes_sources.py` (it pins legacy `sources_used==[]` and stays green unchanged).

- [ ] **Step 1 — Failing test:** force `react_graph.ainvoke` to raise with `use_legacy=False`; assert `run_intelligence_query` **propagates** (raises) rather than returning a `mode in {"legacy_fallback","error"}` dict.
- [ ] **Step 2 — Run, expect FAIL** (today returns a 200 dict).
- [ ] **Step 3 — Implement:** in `workflow.py`, for `use_legacy=False`, remove the silent legacy fallback (`:375-380`) **and** the catch-and-return-`mode:"error"` for the react branch (`:382-405`) so the exception propagates out of `run_intelligence_query` → FastAPI 500 → `intel.py:76` → existing SSE `error` event. Keep `use_legacy=True` (`:368-369`) working on success. Update any existing test that asserted `mode:"error"` for a react failure (red→green); leave legacy-node tests untouched.
- [ ] **Step 4 — Run** intelligence green; **commit:** `fix(intelligence): fail-closed (propagate) on react failure instead of silent legacy/200-error`.

**Risk:** Medium (error semantics). **Exit:** no silent no-source report; react failure surfaces as a visible SSE `error`; evidence-contract tests untouched.

---

## Phase 5 — SSE parser fix → then two-stage `/api/v1` removal

### 5a — SSE parser (do first)
**Files:** `frontend/src/services/api.ts:178-210`; Test: `src/services/__tests__/api.sse.test.ts` (create).
- [ ] **Step 1 — Failing test:** stream where `event: result\n` and `data: {...}\n` arrive in **separate** chunks; assert `onResult` called once and `onDone` called exactly once.
- [ ] **Step 2 — Run, expect FAIL.**
- [ ] **Step 3 — Fix:** hoist `currentEvent` **outside** the chunk loop (carry across chunks like `buffer`); guard `onDone` to fire once (drop the unconditional post-loop call or add a `done` flag).
- [ ] **Step 4 — Run vitest green; commit.**

### 5b — `/api/v1` removal (only after 5a) — full footprint (C8)
**Active code:** `services/frontend/src/services/api.ts:4,31,33,35,90` (drop `LEGACY_BASE`/`fetchWithFallback`) — **including the direct `fetchWithFallback` callers that the earlier draft missed: `queryIntel()` (`api.ts:160`, POST) and `deleteReport()` (`api.ts:269`, DELETE)** — both are **mutations** whose 404-replay against `/api/v1` is the dangerous case; route them through the no-replay path. Plus `services/frontend/src/components/graph/EntityExplorer.tsx:16`, `services/frontend/src/components/worldview/SearchPanel.tsx:52`, `backend/app/main.py:181-192,259-275` (drop both alias mounts), `backend/app/routers/recon.py:1` (docstring `+ /api/v1 alias`).
**Tests to re-point (10 positive backend files):** `unit/test_{cables,intel_router_reports,eonet,reports,graph,firms,aircraft,gdacs}_router.py` (8) + `test_recon_router.py` + `integration/test_health.py` → all re-pointed to `/api/*`; frontend `services/frontend/src/components/worldview/SearchPanel.test.tsx:16`; create `backend/tests/unit/test_main_mounts.py` (assert no route starts with `/api/v1`). (The 11th backend file, `test_signals_stream.py`, is a **negative** assertion — see KEEP.)
**KEEP (negative assertions — do NOT strip):** `backend/tests/unit/test_signals_stream.py:577-578`, `services/frontend/src/test/services/apiBase.test.ts:6`.
**Smoke + docs:** `odin.sh:275,282,289,304,307`; `docs/demo-playbook.md:10`; `docs/superpowers/runbooks/2026-04-30-patch-c-runbook.md:742`; `docs/architecture.md:176-206,255`; **`TASKS.md:190`** (references `POST /api/v1/intel/query`).
- [ ] **Step 1 — Backend snapshot test (red):** no route path starts with `/api/v1`.
- [ ] **Step 2 — Migrate frontend first:** `EntityExplorer` → `/api/graph`, `SearchPanel` drop v1 fallback, `api.ts` direct `fetch(`${BASE}${path}`)` **no replay** (incl. `queryIntel`/`deleteReport`); re-point `SearchPanel.test.tsx:16`; keep `apiBase.test.ts:6`. Vitest green.
- [ ] **Step 3 — Re-point the 10 positive backend test files** to `/api/*` (keep `test_signals_stream.py:577-578` unchanged); run backend green.
- [ ] **Step 4 — Backend:** mount only `prefix="/api"` at `:181-192,259-275`; fix `recon.py:1` docstring.
- [ ] **Step 5 — Smoke/docs:** update `odin.sh` 5 sites + the 3 live docs + `TASKS.md:190`; run `./odin.sh smoke`.
- [ ] **Step 6 — Commit** (frontend migration, backend removal, docs/smoke as separate commits).

**Exit (narrowed):** No `/api/v1` in active backend `app/` + frontend `src/` (non-test) paths, backend+frontend tests (except the two intentional negative assertions), `odin.sh` smoke, and live runbooks (demo-playbook, patch-c-runbook, architecture.md endpoint table). Historical specs and `docs/adr/0001-api-prefix-consolidation.md` may retain the string; future versioned APIs allowed. Mutations never replayed.

**Risk:** Medium (mutation replay — 5a + frontend-first removes it).

---

## Phase 6 — Delete dead intelligence indexer + chunker (AST guard) — partial TASK-014B

**Why:** Intelligence has **no** Qdrant write path. Import-based tests can't catch writes in function bodies (`indexer.py:24,76`) — use an **AST static guard**. `chunker.py` is dead once `indexer.py` (its sole importer, `:9`) is removed. **Does not** fully close TASK-014B — `backend/app/routers/rag.py:45` ingest endpoint is still a placeholder.

**Files:** delete `intelligence/rag/indexer.py` + `intelligence/rag/chunker.py`; Test: `intelligence/tests/test_no_qdrant_write.py` (create); docs `TASKS.md:99`, `docs/architecture.md:444`.
- [ ] **Step 1 — AST guard test (red):**
```python
# intelligence/tests/test_no_qdrant_write.py
import ast, pathlib
RAG = pathlib.Path(__file__).resolve().parents[1] / "rag"

def _writes(tree):
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "upsert":
                hits.append("upsert")
            if n.func.attr in ("put", "post") and n.args:
                a = n.args[0]
                s = a.value if isinstance(a, ast.Constant) else (
                    "".join(p.value for p in getattr(a, "values", []) if isinstance(p, ast.Constant))
                    if isinstance(a, ast.JoinedStr) else "")
                # write = bare /points (NOT the read paths /points/search or /points/count)
                if s.rstrip("/").endswith("/points") or s.endswith("/points/upsert"):
                    hits.append(s)
    return hits

def test_intelligence_rag_has_no_qdrant_write():
    offenders = {p.name: _writes(ast.parse(p.read_text()))
                 for p in RAG.glob("*.py") if _writes(ast.parse(p.read_text()))}
    assert offenders == {}, offenders
```
- [ ] **Step 2 — Run, expect FAIL** — `indexer.py` is flagged by its **PUT to `…/points`** at `:77` (it uses `client.put`, there is **no** `.upsert` call in indexer; the `upsert` matcher is for other writers). Confirms read paths `retriever.py:106` `/points/search` and `backend rag.py:67` `/points/count` are **not** flagged.
- [ ] **Step 3 — Confirm unimported** (`grep -rn 'indexer\|chunker' intelligence --include=*.py` → only self-refs) → delete `rag/indexer.py` **and** `rag/chunker.py`.
- [ ] **Step 4 — Run** intelligence green; AST test green.
- [ ] **Step 5 — Docs:** `TASKS.md:99` (Teil B write-path removed; ingest endpoint still pending), `architecture.md:444`.
- [ ] **Step 6 — Commit:** `refactor(intelligence): delete dead indexer+chunker; AST write-separation guard`.

**Guard scope (honest):** this AST guard catches **point-writes** (`.upsert(` and PUT/POST to `…/points`), which is exactly the `indexer.py:77` write. It does **not** catch collection-level writes such as `client.put(.../collections/<name>)` (the `indexer.py:24` `ensure_collection` create). That's acceptable now (indexer.py is deleted), but state it in the test docstring so the "write-separation guard" claim isn't overstated; optionally extend `_writes` later to also flag `put`/`delete` to `/collections/<name>` paths without a `/points` suffix.

**Risk:** Low. **Exit:** AST guard green (point-write scope); `indexer.py` + `chunker.py` gone; TASK-014B marked **partial** (ingest endpoint `rag.py:45` still placeholder).

---

## Phase 7 — Qdrant scroll-cap helper (hard cap; not a router factory)

**Files:** create `backend/app/services/qdrant_scroll.py`; modify `routers/eonet.py:83`, `firms.py`, `gdacs.py`; Test: `backend/tests/unit/test_qdrant_scroll.py`.
- [ ] **Step 1 — Failing test:** `_PAGE_SIZE=200`, `_MAX_TOTAL=500`, source of 1000 → helper returns **exactly 500** (today: 600).
- [ ] **Step 2 — Run, expect FAIL.**
- [ ] **Step 3 — Implement** `async def scroll_capped(client, *, collection, flt, page_size, max_total) -> list`: stop and truncate (`results[:max_total]`) once the cap is reached.
- [ ] **Step 4 — Rewire** eonet/firms/gdacs (keep their models/mapping/cache-keys/TTLs unchanged).
- [ ] **Step 5 — Run backend green; commit.**

**Risk:** Low. **Exit:** hard cap tested; cache keys identical.

---

## Phase 8 — Reliability-capable polling hook (widened contract, C10)

**Why / invariant:** The ~10 JSON pollers differ in cancellation/hidden-tab handling and all allow overlapping requests. The shared hook is a **reliability primitive**, and its contract must cover the real shapes: composite (`useCables` splits one object into 3 states, `:20-22`), transform (`useEvents:18` filters by coords), reset-on-`enabled=false` (`useCables:32-37`, `useEvents:28-31`, `useFIRMSHotspots:13-17`), and real cancellation (only `useFIRMSHotspots:18` has a cooperative flag + hidden-tab skip `:20`).

**API-layer prerequisite (the cancellation is real only if the signal reaches `fetch`):** today `frontend/src/services/api.ts:98` `fetchJSON<T>(path, init?)` and the 10 getters (`getCables()` etc.) take **no** `AbortSignal`, so a `fetcher: (signal) => getCables(signal)` would silently drop it (the getter ignores the arg) and nothing is actually cancelled. **Phase 8 must include `api.ts`:** give `fetchJSON<T>(path, init?, signal?: AbortSignal)` (or fold into `init`) and the 10 getters a `signal?: AbortSignal` param threaded into the underlying `fetch(url, { ...init, signal })`. A test must assert the real `fetch` call receives the `signal`.

**Files:** modify `frontend/src/services/api.ts:98` (+ the 10 getters); create `src/hooks/usePeriodicJson.ts` + `__tests__/usePeriodicJson.test.ts`; migrate the 10 hooks one per commit.
- [ ] **Step 1 — Failing tests:** (a) late response of request N-1 does not overwrite N (sequence guard); (b) unmount mid-flight does not setState; (c) `skipWhenHidden` pauses when `document.hidden`; (d) `transform` applied; (e) state resets when `enabled=false`; (f) the `fetcher` receives an `AbortSignal`.
- [ ] **Step 2 — Run, expect FAIL.**
- [ ] **Step 3 — Implement** widened signature:
```ts
function usePeriodicJson<TRaw, TState = TRaw>(opts: {
  enabled: boolean;
  fetcher: (signal: AbortSignal) => Promise<TRaw>;
  intervalMs: number;
  transform?: (raw: TRaw) => TState;
  skipWhenHidden?: boolean;
  onError?: (e: unknown) => void;
}): { data: TState | null; loading: boolean; lastUpdate: Date | null };
```
with an in-flight sequence counter (ignore stale resolutions), `AbortController` + mounted-ref teardown, `visibilitychange` handling, and reset-on-`!enabled`. **Composite `useCables` decision (no longer optional):** keep `useCables`'s public return shape unchanged for its consumers by using `transform` to map the fetched object into a single `{cables, landingPoints, source}` state — i.e. `usePeriodicJson<CableDataset, {cables,landingPoints,source}>({ fetcher: getCables, transform: d => ({cables:d.cables, landingPoints:d.landing_points, source:d.source}) })` — then `useCables` destructures `data` back into the three values its callers expect. Do **not** leave this as an open choice.
- [ ] **Step 4 — `api.ts`:** thread `signal?: AbortSignal` through `fetchJSON` + the 10 getters into `fetch(url, {…init, signal})`; test asserts `fetch` receives the signal. **Do this before migrating the hooks** so the hook's `AbortController` actually cancels in-flight requests.
- [ ] **Step 5 — Migrate** the 10 hooks (one commit each); vitest green after each. (`useTPlus`=countdown and `useSignalFeed`=stream are out of scope.)

**Risk:** Low-Medium (timer/async correctness). **Exit:** no overlapping-response races; unmount-safe; hidden-tab + stale-response covered; composite/transform supported; **the abort signal reaches the real `fetch`** (proven by test).

---

## Phase 9 — Typed primitive metadata (tagged interfaces; 15 sites, 6 layers, C10)

**Why / invariant:** Replace the cast hacks with **typed tagged-primitive interfaces** (the existing `PipelineBillboard` pattern at `services/frontend/src/components/layers/PipelineLayer.tsx:14`, applied at `:156/:158`, is the model). The central reader `services/frontend/src/components/globe/EntityClickHandler.tsx:47` reads tags off the picked primitive, so the type lives **on the primitive**, not a per-layer WeakMap. Registry only if typed interfaces prove insufficient.

**Scope — 15 sites across 6 layers (corrected):** **7 writer-side** assignments (`FlightLayer.tsx:128,143` — **two writes**, `CableLayer.tsx:164`, `ShipLayer.tsx:101`, `EventLayer.tsx:194`, `SatelliteLayer.tsx:164`, **`PipelineLayer.tsx:158`** — the 7th writer the earlier draft missed) + **8 reader casts** (`SatelliteLayer.tsx:254`, `FlightLayer.tsx:245`, `EntityClickHandler.tsx:47,78,127,173,218,268` — incl the pipeline reader at `:127`). PipelineLayer is the **6th** layer: it currently writes `_pipelineData` (`:158`) and EntityClickHandler reads `_pipelineData` (`:127`); if the readers unify on `_odinTag` but PipelineLayer keeps writing `_pipelineData`, **pipeline clicks break** — so its writer must migrate too.

**Discriminator (the HOW):** today the writers use 6 *heterogeneous* keys (`_flightData`, `_pipelineData`, `_eventData`, `_cableData`, `_shipData`, `_satelliteData`), and the central reader can't narrow without knowing which to read. Replace them with **one canonical discriminated key** `_odinTag?: OdinTag` where `type OdinTag = {kind:'flight';data:FlightTag} | {kind:'event';data:EventTag} | {kind:'cable';data:CableTag} | {kind:'ship';data:ShipTag} | {kind:'satellite';data:SatelliteTag} | {kind:'pipeline';data:PipelineTag}`. `readTag(primitive)` returns `OdinTag | undefined`; callers `switch (tag.kind)` to narrow (no cast). Each existing `_xData` key migrates to `tag(primitive, {kind, data})`.

**Files:** create `src/lib/cesiumTags.ts` (the `OdinTag` union + per-kind `*Tag` interfaces + `tag(primitive, t: OdinTag)` / `readTag(primitive): OdinTag | undefined` over a single `_odinTag` property); modify the **6 layers** (`FlightLayer`, `CableLayer`, `ShipLayer`, `EventLayer`, `SatelliteLayer`, **`PipelineLayer`**) + `EntityClickHandler.tsx`; Test: `src/lib/__tests__/cesiumTags.test.ts`.
- [ ] **Step 1 — Failing test:** `tag(bb, {kind:'flight', data})` then `const t = readTag(bb); if (t?.kind === 'flight') t.data.<field>` narrows with **no** `as`/`unknown` at the call site; `readTag` on an untagged primitive returns `undefined`.
- [ ] **Step 2 — Run, expect FAIL.**
- [ ] **Step 3 — Implement** the union + helpers; migrate all **7 writer** assignments to `tag(...)` (incl FlightLayer's two writes at `:128,143` and `PipelineLayer.tsx:158` — replacing its `_pipelineData`/`PipelineBillboard` writer) and all **8 reader** casts to `readTag(...).kind`-switches (`SatelliteLayer:254`, `FlightLayer:245`, `EntityClickHandler:47,78,127,173,218,268`). `EntityClickHandler` becomes one `switch (readTag(picked.primitive)?.kind)`.
- [ ] **Step 4 — Run vitest + `npm run type-check` green; commit.**

**Risk:** Low. **Exit:** 0 `as … Record<string, unknown>` casts across the **6 layers** AND `EntityClickHandler`; pipeline clicks still resolve (PipelineLayer migrated to `_odinTag`).

---

## Phase 10 (cleanup) — Dead GDELT toggle

**Why:** `backend/app/services/incident_promoter/config.py:34` `gdelt_enabled` is advertised by `enabled_detector_ids()` (`config.py:54-55`) while `backend/app/main.py:118-124` builds `_detectors` (firms/telegram/severity) and **never appends a GdeltDetector** (Promoter wired at `:126`). Keep `detectors/gdelt.py` as a deferred feature (per `project_auto_promoter_v1`); just kill the lying toggle.
- [ ] **Step 1 — Test (red), deterministic single approach:** assert that **startup fail-fasts** when `gdelt_enabled=true` while no GdeltDetector is wired in `main.py:118-124` — e.g. a startup/validation that raises `RuntimeError("gdelt_enabled set but no GDELT detector wired")`. (No either/or: fail-fast is the chosen behaviour; the detector file stays for the deferred feature.)
- [ ] **Step 2 — Implement + run backend green + commit** (`fix(backend): fail-fast when gdelt_enabled set but detector unwired`).

**Risk:** Low. **Exit:** no toggle that misreports active.

---

## Deferred (both reviews agree — NOT in this plan)
- **`feeds/gdelt_collector.py` (legacy GDELT DOC-API collector) — dormant Phase-2 defect, found in the Phase 1–3 review (2026-06-01).** Sync `_ensure_collection` in `__init__` (`:73`), bare sync `retrieve` (`:153`) / `upsert` (`:215`) on the loop, no `close()`. **Not scheduled** (only `run_gdelt_raw_collector` is wired, `scheduler.py:524`) → not on a live loop, so correctly out of Phase 2's declared scope. But it is still exported (`feeds/__init__.py`) and instantiated in tests (`test_feeds.py`, `test_pipeline.py`), so re-wiring would re-introduce all three defects. Resolve by either (a) applying the RSS treatment (move `_ensure_collection` to async setup, `to_thread`-wrap `retrieve`/`upsert`, add `close()` + scheduler `finally`) or (b) deleting it if `gdelt_raw` supersedes the DOC-API path. Until then, Phase 2's "no unwrapped sync qdrant on loop" exit claim is honest only for the *wired* collectors.
- `useLayerPrimitives` Cesium lifecycle hook (after Phase 9 if still wanted).
- Config centralisation (keep 6 per-service `config.py`; at most a `settings-registry.md`).
- Broad runtime DI / `IntelligenceRuntime` (tie to TASK-112).
- LLM-factory (`llm_factory.py`) — low value until legacy retirement.
- Extraction-ownership move (delete intelligence extractors + HTTP hop) — **rejected** for a refactor pass (changes runtime topology, breaks many mocks); belongs to TASK-112.
- Full legacy retirement (`osint_agent`/`analyst_agent`/`build_legacy_graph`) — deliberate task; touches the evidence-contract guardrail test.
- `_http.py` consolidation — **separate review** (retries only status codes, not transport/timeout; `http_max_retries` from `config.py:23` unused; helper unwired). Do **not** fold into Phase 1.

## Self-review notes
- Every round-4 correction (C1–C10) maps to a phase change above and was verified with `file:line` evidence (C3 invalidated the earlier draft's test — fixed in Task 3.1).
- No fabricated symbols: `CodebookConfigError`, `_load_codebook_types(path)`, `scroll_capped`, `usePeriodicJson<TRaw,TState>`, `TaggedPrimitive`/`tag`/`readTag`, `close_driver`, `retriever.close()`, `event_codebook_path` are each introduced where first used.
- Type consistency: `EVENT_CODEBOOK_PATH` env ↔ `settings.event_codebook_path`; `_schema_validated`/`_client` reset in the same fixture; `/points` write-match deliberately excludes `/points/search` + `/points/count` reads.
- Where exact line-level code depends on per-file reading not yet done (Phase 2 per-writer bodies, Phase 1 Dockerfile final form), the plan gives the contract test + verified `file:line` + approach + exit criteria; full bite-sized code is produced per file at execution time.
