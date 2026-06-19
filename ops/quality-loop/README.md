# ODIN Quality Loop

Daily host-side quality gate for the ODIN repo. The timer runs at 01:30 and
executes service checks from each service directory, matching `AGENTS.md`.

## What It Runs

- Backend: `uv sync --all-extras`, pytest with production coverage, Ruff, mypy.
- Frontend: `npm install`, lint, type-check, tests, production coverage, build.
- Intelligence: `uv sync --all-extras`, pytest with production coverage.
- Data ingestion: `uv sync --all-extras`, pytest with production coverage.
- Vision enrichment: `uv sync --all-extras`, pytest with production coverage.
- Smoke: `./odin.sh smoke`.

Coverage gates default to ratchet mode. The loop compares each service against
`coverage-baseline.json` and fails if total coverage or critical-file coverage
drops. Raise baselines after adding meaningful tests.

## Dry Run

```bash
ODIN_QUALITY_LOOP_DRY_RUN=1 ops/quality-loop/quality_loop.sh
```

Reports are written to `.quality-loop/logs/` by default.

## Install Timer

```bash
sudo cp ops/quality-loop/odin-quality-loop.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now odin-quality-loop.timer
systemctl list-timers | grep odin-quality-loop
```

## Operational Overrides

Use these only for controlled transition periods:

```bash
ODIN_COVERAGE_MODE=off ops/quality-loop/quality_loop.sh
ODIN_QUALITY_LOG_DIR=/var/log/odin-quality ops/quality-loop/quality_loop.sh
```

Keep the timer default in ratchet mode. Do not lower
`coverage-baseline.json` without an explicit decision; add tests and raise it.
