# Disable Legacy GDELT DOC Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the failing Legacy GDELT DOC API collector by default while keeping the working GDELT Raw pipeline active, observable, and easy to operate.

**Architecture:** Keep the Legacy DOC collector code in the repository, but gate its scheduler registration and startup execution behind `ENABLE_LEGACY_GDELT_DOC`, defaulting to `false`. Keep GDELT Raw as the default 15-minute ingestion path and preserve the existing `source=gdelt_gkg` payload naming because Qdrant stores GKG documents, while Neo4j stores `GDELTEvent` and `GDELTDocument` nodes. Add regression tests so future scheduler changes cannot accidentally re-enable the dry DOC collector.

**Tech Stack:** Python 3.12, APScheduler, pydantic-settings, pytest, Docker Compose, Qdrant, Neo4j, Redis, TEI, GDELT Raw Files.

---

## File Structure

- Modify: `services/data-ingestion/config.py`
  - Add `enable_legacy_gdelt_doc: bool = False`.
  - Environment variable name becomes `ENABLE_LEGACY_GDELT_DOC`.

- Modify: `services/data-ingestion/scheduler.py`
  - Import `Awaitable` and `Callable`.
  - Register `gdelt_collector` only when `settings.enable_legacy_gdelt_doc` is true.
  - Add `initial_collection_jobs()` so startup collection is testable without creating unawaited coroutines.
  - Exclude Legacy DOC GDELT from startup collection by default.
  - Keep `gdelt_raw_forward` always registered.

- Create: `services/data-ingestion/tests/test_gdelt_scheduler_mode.py`
  - Assert Legacy DOC job is disabled by default.
  - Assert Raw GDELT job remains enabled.
  - Assert Legacy DOC can still be enabled explicitly.
  - Assert startup initial collection follows the same flag.

- Modify: `services/data-ingestion/tests/test_gdelt_deployment_contract.py`
  - Assert direct CLI execution works in the container image via `ENV PATH="/app/.venv/bin:$PATH"` in `Dockerfile`.

- Modify: `services/data-ingestion/Dockerfile`
  - Add venv bin directory to `PATH` so the documented command `docker exec odin-data-ingestion-spark odin-ingest-gdelt status` works without `uv run`.

- Modify: `.env.example`
  - Document `ENABLE_LEGACY_GDELT_DOC=false`.
  - Document `source=gdelt_gkg` as the Qdrant source label for Raw GKG documents.

- Modify: `README.md`
  - Update operational GDELT notes: Legacy DOC disabled by default, Raw files active by default, Qdrant label is `gdelt_gkg`.

---

## Task 1: Add Scheduler Tests for GDELT Mode

**Files:**
- Create: `services/data-ingestion/tests/test_gdelt_scheduler_mode.py`

- [ ] **Step 1: Write failing scheduler tests**

Create `services/data-ingestion/tests/test_gdelt_scheduler_mode.py`:

```python
"""Scheduler mode tests for Legacy DOC GDELT vs GDELT Raw ingestion."""

from __future__ import annotations


def _job_ids(scheduler) -> set[str]:
    return {job.id for job in scheduler.get_jobs()}


def _initial_job_names() -> set[str]:
    from scheduler import initial_collection_jobs

    return {job.__name__ for job in initial_collection_jobs()}


def test_legacy_gdelt_doc_job_disabled_by_default(monkeypatch):
    from scheduler import create_scheduler, settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", False, raising=False)

    scheduler = create_scheduler()

    assert "gdelt_collector" not in _job_ids(scheduler)
    assert "gdelt_raw_forward" in _job_ids(scheduler)


def test_legacy_gdelt_doc_job_can_be_enabled(monkeypatch):
    from scheduler import create_scheduler, settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", True, raising=False)

    scheduler = create_scheduler()

    assert "gdelt_collector" in _job_ids(scheduler)
    assert "gdelt_raw_forward" in _job_ids(scheduler)


def test_legacy_gdelt_doc_startup_job_disabled_by_default(monkeypatch):
    from scheduler import settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", False, raising=False)

    names = _initial_job_names()

    assert "run_gdelt_collector" not in names
    assert "run_rss_collector" in names


def test_legacy_gdelt_doc_startup_job_can_be_enabled(monkeypatch):
    from scheduler import settings

    monkeypatch.setattr(settings, "enable_legacy_gdelt_doc", True, raising=False)

    names = _initial_job_names()

    assert "run_gdelt_collector" in names
    assert "run_rss_collector" in names
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_gdelt_scheduler_mode.py -v
```

Expected result before implementation:

```text
FAILED tests/test_gdelt_scheduler_mode.py::test_legacy_gdelt_doc_job_disabled_by_default
FAILED tests/test_gdelt_scheduler_mode.py::test_legacy_gdelt_doc_startup_job_disabled_by_default
FAILED tests/test_gdelt_scheduler_mode.py::test_legacy_gdelt_doc_startup_job_can_be_enabled
```

The scheduled-job failure proves the legacy DOC job is still registered by default. Both startup tests fail with `ImportError: cannot import name 'initial_collection_jobs'` until Task 3 adds the helper.

- [ ] **Step 3: Commit RED tests**

Do not commit yet if the local process expects green commits only. If red commits are acceptable in the active workflow:

```bash
git add services/data-ingestion/tests/test_gdelt_scheduler_mode.py
git commit -m "test(data-ingestion): cover gdelt scheduler mode"
```

---

## Task 2: Add Config Flag for Legacy DOC GDELT

**Files:**
- Modify: `services/data-ingestion/config.py`

- [ ] **Step 1: Add a focused config assertion**

Append this test to `services/data-ingestion/tests/test_gdelt_scheduler_mode.py`:

```python
def test_legacy_gdelt_doc_config_defaults_disabled(monkeypatch):
    from config import Settings

    monkeypatch.delenv("ENABLE_LEGACY_GDELT_DOC", raising=False)

    settings = Settings(_env_file=None)

    assert settings.enable_legacy_gdelt_doc is False
```

- [ ] **Step 2: Run config test to verify RED**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_gdelt_scheduler_mode.py::test_legacy_gdelt_doc_config_defaults_disabled -v
```

Expected result before implementation:

```text
AttributeError: 'Settings' object has no attribute 'enable_legacy_gdelt_doc'
```

- [ ] **Step 3: Implement config flag**

In `services/data-ingestion/config.py`, add this field after the HTTP settings block:

```python
    # Legacy GDELT DOC API collector.
    # Disabled by default because the DOC API path currently produces empty
    # or rate-limited responses while GDELT Raw files provide reliable slices.
    enable_legacy_gdelt_doc: bool = False
```

The nearby section should read:

```python
    # HTTP settings
    http_timeout: float = 30.0
    http_max_retries: int = 3

    # Legacy GDELT DOC API collector.
    # Disabled by default because the DOC API path currently produces empty
    # or rate-limited responses while GDELT Raw files provide reliable slices.
    enable_legacy_gdelt_doc: bool = False

    # Redis TTLs (seconds)
    tle_cache_ttl: int = 86400  # 24 hours
    hotspot_cache_ttl: int = 21600  # 6 hours
```

- [ ] **Step 4: Run config test to verify GREEN**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_gdelt_scheduler_mode.py::test_legacy_gdelt_doc_config_defaults_disabled -v
```

Expected result:

```text
1 passed
```

---

## Task 3: Gate Legacy DOC GDELT in Scheduler

**Files:**
- Modify: `services/data-ingestion/scheduler.py`
- Test: `services/data-ingestion/tests/test_gdelt_scheduler_mode.py`

- [ ] **Step 1: Update imports**

In `services/data-ingestion/scheduler.py`, replace:

```python
import asyncio
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
```

with:

```python
import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
```

- [ ] **Step 2: Gate scheduled Legacy DOC job**

In `create_scheduler()`, replace the unconditional Legacy DOC block:

```python
    # GDELT events — every 15 minutes
    scheduler.add_job(
        run_gdelt_collector,
        trigger=IntervalTrigger(minutes=15),
        id="gdelt_collector",
        name="GDELT Event Collector",
        replace_existing=True,
    )
```

with:

```python
    # Legacy GDELT DOC API collector. Disabled by default; the Raw files
    # forward sweep below is the production GDELT ingestion path.
    if settings.enable_legacy_gdelt_doc:
        scheduler.add_job(
            run_gdelt_collector,
            trigger=IntervalTrigger(minutes=15),
            id="gdelt_collector",
            name="GDELT DOC API Collector",
            replace_existing=True,
        )
```

- [ ] **Step 3: Add testable startup job helper**

Add this helper immediately above `async def main() -> None:`:

```python
def initial_collection_jobs() -> list[Callable[[], Awaitable[None]]]:
    """Jobs to run once on scheduler startup before interval triggers fire."""
    jobs: list[Callable[[], Awaitable[None]]] = [
        run_rss_collector,
        run_tle_updater,
        run_hotspot_updater,
        run_telegram_collector,
        run_ucdp_collector,
        run_firms_collector,
        run_usgs_collector,
        run_military_collector,
        run_eonet_collector,
        run_gdacs_collector,
        # HAPI runs daily via cron, not on initial startup.
        run_noaa_nhc_collector,
        run_portwatch_collector,
        # OFAC runs daily via cron, not on initial startup.
    ]
    if settings.enable_legacy_gdelt_doc:
        jobs.insert(1, run_gdelt_collector)
    return jobs
```

- [ ] **Step 4: Use helper in startup collection**

In `main()`, replace:

```python
    initial_tasks = [
        run_rss_collector(),
        run_gdelt_collector(),
        run_tle_updater(),
        run_hotspot_updater(),
        run_telegram_collector(),
        run_ucdp_collector(),
        run_firms_collector(),
        run_usgs_collector(),
        run_military_collector(),
        run_eonet_collector(),
        run_gdacs_collector(),
        # HAPI runs daily via cron, not on initial startup
        run_noaa_nhc_collector(),
        run_portwatch_collector(),
        # OFAC runs daily via cron, not on initial startup
    ]
```

with:

```python
    initial_tasks = [job() for job in initial_collection_jobs()]
```

- [ ] **Step 5: Run scheduler mode tests**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_gdelt_scheduler_mode.py -v
```

Expected result:

```text
5 passed
```

- [ ] **Step 6: Run related scheduler tests**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_scheduler_healthcheck.py tests/test_telegram_collector.py::TestSchedulerIntegration -v
```

Expected result:

```text
14 passed
```

The exact count can change if tests are added later; success criterion is zero failures.

---

## Task 4: Make GDELT CLI Directly Executable in Container

**Files:**
- Modify: `services/data-ingestion/tests/test_gdelt_deployment_contract.py`
- Modify: `services/data-ingestion/Dockerfile`

- [ ] **Step 1: Write failing Dockerfile contract test**

Append this test to `services/data-ingestion/tests/test_gdelt_deployment_contract.py`:

```python
def test_data_ingestion_image_exposes_venv_scripts_on_path():
    dockerfile = (REPO_ROOT / "services" / "data-ingestion" / "Dockerfile").read_text()

    assert 'ENV PATH="/app/.venv/bin:$PATH"' in dockerfile
```

- [ ] **Step 2: Run Dockerfile contract test to verify RED**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_gdelt_deployment_contract.py::test_data_ingestion_image_exposes_venv_scripts_on_path -v
```

Expected result before implementation:

```text
AssertionError: assert 'ENV PATH="/app/.venv/bin:$PATH"' in ...
```

- [ ] **Step 3: Add PATH to Dockerfile**

In `services/data-ingestion/Dockerfile`, replace:

```dockerfile
WORKDIR /app
```

with:

```dockerfile
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
```

- [ ] **Step 4: Run Dockerfile contract test to verify GREEN**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest tests/test_gdelt_deployment_contract.py::test_data_ingestion_image_exposes_venv_scripts_on_path -v
```

Expected result:

```text
1 passed
```

---

## Task 5: Update Operator Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Update `.env.example`**

In `.env.example`, add this directly above the existing GDELT Raw Files block:

```dotenv
# Legacy GDELT DOC API Collector
# Disabled by default. The DOC API path is retained for debugging only because
# production ingestion uses the GDELT v2 raw files pipeline below.
ENABLE_LEGACY_GDELT_DOC=false
```

Keep the existing Raw block as-is, including:

```dotenv
GDELT_BASE_URL=http://data.gdeltproject.org/gdeltv2
GDELT_FORWARD_INTERVAL_SECONDS=900
GDELT_DOWNLOAD_TIMEOUT=60
GDELT_MAX_PARSE_ERROR_PCT=5
GDELT_PARQUET_PATH=/data/gdelt
GDELT_FILTER_MODE=alpha
GDELT_CAMEO_ROOT_ALLOWLIST=15,18,19,20
GDELT_THEME_ALLOWLIST=ARMEDCONFLICT,KILL,CRISISLEX_*,TERROR,TERROR_*,MILITARY,NUCLEAR,WMD,WEAPONS_*,WEAPONS_PROLIFERATION,SANCTIONS,CYBER_ATTACK,ESPIONAGE,COUP,HUMAN_RIGHTS_ABUSES,REFUGEE,DISPLACEMENT
GDELT_NUCLEAR_OVERRIDE_THEMES=NUCLEAR,WMD,WEAPONS_PROLIFERATION,WEAPONS_*
GDELT_BACKFILL_PARALLEL_SLICES=4
GDELT_BACKFILL_DEFAULT_DAYS=30
```

- [ ] **Step 2: Update `README.md` GDELT source table**

Find the row that describes GDELT. Replace it with:

```markdown
| GDELT Raw Files | Global event data, mentions, and GKG themes | 15min |
```

- [ ] **Step 3: Add README operational note**

Add this note near the data ingestion or sources section:

```markdown
### GDELT Ingestion Mode

ODIN uses the GDELT v2 raw files pipeline by default. The scheduler runs `gdelt_raw_forward` every 15 minutes, writes raw-filtered slices to Parquet, creates `GDELTEvent` and `GDELTDocument` nodes in Neo4j, and embeds GKG documents into Qdrant with `source=gdelt_gkg`.

The old GDELT DOC API collector is disabled by default because it is prone to empty responses and `429 Too Many Requests`. It can be re-enabled for debugging by setting `ENABLE_LEGACY_GDELT_DOC=true`, but it should not run alongside Raw ingestion in normal operation.

Useful checks:

```bash
docker exec odin-data-ingestion-spark odin-ingest-gdelt doctor
docker exec odin-data-ingestion-spark odin-ingest-gdelt status
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"filter":{"must":[{"key":"source","match":{"value":"gdelt_gkg"}}]},"exact":true}' \
  http://localhost:6333/collections/odin_intel/points/count
docker exec osint-neo4j-1 sh -lc \
  'PASS="${NEO4J_AUTH#*/}"; /var/lib/neo4j/bin/cypher-shell -u neo4j -p "$PASS" "MATCH (e:GDELTEvent) RETURN count(e) AS gdeltEvents; MATCH (d:GDELTDocument) RETURN count(d) AS gdeltDocuments;"'
```
```

- [ ] **Step 4: Review README for stale `gdelt_raw` Qdrant label**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
rg -n "source=gdelt_raw|gdelt_raw=0" README.md .env.example docs --glob '*.md' --glob '.env.example' --glob '!docs/superpowers/plans/**'
```

Expected result:

```text
No output.
```

References to code paths such as `gdelt_raw/` are acceptable.

---

## Task 6: Run Full Verification Locally

**Files:**
- No production file changes.

- [ ] **Step 1: Run full data-ingestion test suite**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion
uv run pytest
```

Expected result:

```text
All selected tests pass; skipped live/integration tests remain skipped.
```

- [ ] **Step 2: Run service test suites**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest
cd /home/deadpool-ultra/ODIN/OSINT/services/intelligence
uv run pytest
cd /home/deadpool-ultra/ODIN/OSINT/services/vision-enrichment
uv run pytest
```

Expected result:

```text
All tests pass.
```

- [ ] **Step 3: Run frontend checks**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npm run lint
npm run type-check
npm run build
```

Expected result:

```text
lint exits 0
type-check exits 0
build exits 0
```

Existing warnings about unused `eslint-disable` directives in `GraphCanvas.tsx` are unrelated to this task and do not block this plan.

---

## Task 7: Rebuild and Deploy Spark Ingestion Container

**Files:**
- No repository file changes beyond earlier tasks.

- [ ] **Step 1: Build updated Spark image**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
docker compose --profile interactive-spark build data-ingestion-spark
```

Expected result:

```text
Image osint-data-ingestion-spark Built
```

- [ ] **Step 2: Restart only Spark ingestion**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
docker compose --profile interactive-spark up -d data-ingestion-spark
```

Expected result:

```text
Container odin-data-ingestion-spark Started
```

- [ ] **Step 3: Verify CLI works without `uv run`**

Run:

```bash
docker exec odin-data-ingestion-spark odin-ingest-gdelt --help
```

Expected result:

```text
Usage: odin-ingest-gdelt [OPTIONS] COMMAND [ARGS]...
Commands:
  backfill
  config
  doctor
  forward
  resume
  status
```

---

## Task 8: Runtime Verification

**Files:**
- No repository file changes.

- [ ] **Step 1: Verify Legacy DOC job no longer appears in scheduler logs**

Run:

```bash
docker logs --since 2m odin-data-ingestion-spark | grep -E "scheduler_running|GDELT"
```

Expected result:

```text
scheduler_running
GDELT Raw Files Forward Collector
```

Expected absence:

```text
GDELT DOC API Collector
GDELT Event Collector
gdelt_collection_started
gdelt_fetch_failed
```

- [ ] **Step 2: Verify Raw GDELT health**

Run:

```bash
docker exec odin-data-ingestion-spark odin-ingest-gdelt doctor
```

Expected result:

```text
GDELT CDN:       ✓
Parquet volume:  ✓ /data/gdelt (writable)
Redis:           ✓
Neo4j:           ✓
Qdrant:          ✓
TEI:             ✓ dim=1024
Filter mode:     alpha
CAMEO roots:     [15, 18, 19, 20]
```

- [ ] **Step 3: Run one forward tick**

Run:

```bash
docker exec odin-data-ingestion-spark odin-ingest-gdelt forward
```

Expected result:

```text
No traceback.
```

- [ ] **Step 4: Verify Raw status has no pending store writes**

Run:

```bash
docker exec odin-data-ingestion-spark odin-ingest-gdelt status
```

Expected result:

```text
last_slice[parquet]: <slice id>
last_slice[  neo4j]: <same slice id>
last_slice[ qdrant]: <same slice id>
pending[ neo4j]: 0
pending[qdrant]: 0
```

- [ ] **Step 5: Verify Qdrant Raw GKG documents**

Run:

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"filter":{"must":[{"key":"source","match":{"value":"gdelt_gkg"}}]},"exact":true}' \
  http://localhost:6333/collections/odin_intel/points/count
```

Expected result:

```json
{"result":{"count":326},"status":"ok"}
```

The count can be higher than `326` after additional forward slices. It must not go down.

- [ ] **Step 6: Verify Neo4j GDELT nodes**

Run:

```bash
docker exec osint-neo4j-1 sh -lc \
  'PASS="${NEO4J_AUTH#*/}"; /var/lib/neo4j/bin/cypher-shell -u neo4j -p "$PASS" "MATCH (e:GDELTEvent) RETURN count(e) AS gdeltEvents; MATCH (d:GDELTDocument) RETURN count(d) AS gdeltDocuments;"'
```

Expected result:

```text
gdeltEvents
42
gdeltDocuments
326
```

The counts can be higher after additional forward slices. They must not go down.

- [ ] **Step 7: Verify Legacy DOC noise is gone**

Run:

```bash
docker logs --since 5m odin-data-ingestion-spark | grep -E "gdelt_collection_started|gdelt_fetch_failed|429 Too Many Requests|Expecting value" || true
```

Expected result:

```text
No output.
```

---

## Task 9: Final Git and Status Review

**Files:**
- No repository file changes.

- [ ] **Step 1: Check worktree**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git status --short
```

Expected result includes only intentional files from this plan plus pre-existing unrelated files:

```text
 M .env.example
 M README.md
 M services/data-ingestion/Dockerfile
 M services/data-ingestion/config.py
 M services/data-ingestion/scheduler.py
 M services/data-ingestion/tests/test_gdelt_deployment_contract.py
?? services/data-ingestion/tests/test_gdelt_scheduler_mode.py
```

Known pre-existing unrelated work may still appear:

```text
 D .claude/scheduled_tasks.lock
?? docs/superpowers/plans/2026-04-25-odin-s4-war-room.md
```

Do not revert unrelated files.

- [ ] **Step 2: Summarize changed files**

Run:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git diff --stat
```

Expected result:

```text
Only the files listed in Task 9 Step 1 have meaningful diffs for this work.
```

- [ ] **Step 3: Commit if requested**

If the user asks for a commit:

```bash
cd /home/deadpool-ultra/ODIN/OSINT
git add .env.example README.md \
  services/data-ingestion/Dockerfile \
  services/data-ingestion/config.py \
  services/data-ingestion/scheduler.py \
  services/data-ingestion/tests/test_gdelt_deployment_contract.py \
  services/data-ingestion/tests/test_gdelt_scheduler_mode.py
git commit -m "fix(data-ingestion): disable legacy gdelt doc collector by default"
```

Do not add `.claude/scheduled_tasks.lock` or unrelated plan files unless the user explicitly asks.

---

## Self-Review

- Spec coverage:
  - Disable Legacy DOC GDELT by default: Task 3.
  - Keep Raw GDELT processing active: Task 3 and Task 8.
  - Avoid a dry pipeline: Task 8 verifies Qdrant and Neo4j writes.
  - Keep rollback/debug option: Task 2 and Task 3 via `ENABLE_LEGACY_GDELT_DOC=true`.
  - Smooth operations: Task 4 direct CLI, Task 5 docs, Task 7 deployment.

- Placeholder scan:
  - No `TBD`, `TODO`, or unspecified "add tests" steps.
  - Each code change step includes the target file and concrete code.

- Type consistency:
  - `enable_legacy_gdelt_doc` is defined in `Settings` and read from `scheduler.settings`.
  - `initial_collection_jobs()` returns `list[Callable[[], Awaitable[None]]]`.
  - Qdrant source label remains `gdelt_gkg`, matching `gdelt_raw/writers/qdrant_writer.py`.
