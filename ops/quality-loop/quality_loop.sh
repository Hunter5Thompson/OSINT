#!/usr/bin/env bash
set -euo pipefail

ROOT="${ODIN_REPO_ROOT:-/home/deadpool-ultra/ODIN/OSINT}"
LOG_DIR="${ODIN_QUALITY_LOG_DIR:-$ROOT/.quality-loop/logs}"
STAMP="${ODIN_QUALITY_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
REPORT="$LOG_DIR/report-$STAMP.md"
HANDOFF="$LOG_DIR/handoff-$STAMP.md"
DRY_RUN="${ODIN_QUALITY_LOOP_DRY_RUN:-0}"
COVERAGE_MODE="${ODIN_COVERAGE_MODE:-ratchet}"
BASELINE="$ROOT/ops/quality-loop/coverage-baseline.json"
CHECKER="$ROOT/ops/quality-loop/check_coverage_ratchet.py"
SUMMARIZER="$ROOT/ops/quality-loop/summarize_report.py"
BACKEND_COVERAGE="$LOG_DIR/backend-coverage-$STAMP.json"
FRONTEND_COVERAGE="$LOG_DIR/frontend-coverage-summary-$STAMP.json"
INTELLIGENCE_COVERAGE="$LOG_DIR/intelligence-coverage-$STAMP.json"
INGESTION_COVERAGE="$LOG_DIR/data-ingestion-coverage-$STAMP.json"
VISION_COVERAGE="$LOG_DIR/vision-enrichment-coverage-$STAMP.json"
COVERAGE_REPORTS=(
  "$BACKEND_COVERAGE"
  "$FRONTEND_COVERAGE"
  "$INTELLIGENCE_COVERAGE"
  "$INGESTION_COVERAGE"
  "$VISION_COVERAGE"
)

mkdir -p "$LOG_DIR"

exec > >(tee "$REPORT") 2>&1

finish() {
  local status=$?
  local handoff_tmp="$HANDOFF.tmp"
  local coverage_args=()

  if [[ -f "$SUMMARIZER" ]]; then
    for coverage_report in "${COVERAGE_REPORTS[@]}"; do
      if [[ -f "$coverage_report" ]]; then
        coverage_args+=(--coverage "$coverage_report")
      fi
    done
    if python3 "$SUMMARIZER" --log-dir "$LOG_DIR" --report "$REPORT" \
        --exit-code "$status" "${coverage_args[@]}" > "$handoff_tmp"; then
      mv "$handoff_tmp" "$HANDOFF"
      printf '\nHandoff: %s\n' "$HANDOFF"
    else
      rm -f "$handoff_tmp"
      printf '\nWARNING: handoff generation failed; no handoff published\n'
    fi
  fi

  exit "$status"
}

trap finish EXIT

rel_path() {
  local path="$1"
  if [[ "$path" == "$ROOT" ]]; then
    printf "."
  else
    printf "%s" "${path#"$ROOT"/}"
  fi
}

print_cmd() {
  local dir="$1"
  shift

  printf '$ cd %s &&' "$(rel_path "$dir")"
  printf ' %s' "$@"
  printf '\n'
}

run_cmd() {
  local dir="$1"
  shift

  print_cmd "$dir" "$@"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi

  (cd "$dir" && "$@")
}

check_coverage() {
  local service="$1"
  local report_format="$2"
  local report_path="$3"

  if [[ "$COVERAGE_MODE" == "off" ]]; then
    printf 'coverage ratchet disabled for %s\n' "$service"
    return 0
  fi

  run_cmd "$ROOT" python3 "$CHECKER" --baseline "$BASELINE" --service "$service" --report "$report_path" --format "$report_format"
}

section() {
  printf '\n## %s\n' "$1"
}

printf '# ODIN Quality Loop %s\n' "$STAMP"
printf '\nReport: %s\n' "$REPORT"
printf 'Coverage mode: %s\n' "$COVERAGE_MODE"

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'DRY RUN: no commands will be executed\n'
fi

section "Git"
run_cmd "$ROOT" git status --short

section "Backend"
run_cmd "$ROOT/services/backend" uv sync --all-extras
run_cmd "$ROOT/services/backend" uv run --with pytest-cov pytest --cov=app --cov-report=term-missing "--cov-report=json:$BACKEND_COVERAGE" --cov-fail-under=0
check_coverage backend coverage.py "$BACKEND_COVERAGE"
run_cmd "$ROOT/services/backend" uv run ruff check app/
run_cmd "$ROOT/services/backend" uv run mypy app/

section "Frontend"
run_cmd "$ROOT/services/frontend" npm install
run_cmd "$ROOT/services/frontend" npm run lint
run_cmd "$ROOT/services/frontend" npm run type-check
run_cmd "$ROOT/services/frontend" npm test
run_cmd "$ROOT/services/frontend" npm run coverage
run_cmd "$ROOT" cp "$ROOT/services/frontend/coverage/coverage-summary.json" "$FRONTEND_COVERAGE"
check_coverage frontend vitest-summary "$FRONTEND_COVERAGE"
run_cmd "$ROOT/services/frontend" npm run build

section "Intelligence"
run_cmd "$ROOT/services/intelligence" uv sync --all-extras
run_cmd "$ROOT/services/intelligence" uv run --with pytest-cov pytest --cov=agents --cov=codebook --cov=config --cov=extraction --cov=graph --cov=main --cov=rag --cov=scripts --cov-report=term-missing "--cov-report=json:$INTELLIGENCE_COVERAGE" --cov-fail-under=0
check_coverage intelligence coverage.py "$INTELLIGENCE_COVERAGE"

section "Data Ingestion"
run_cmd "$ROOT/services/data-ingestion" uv sync --all-extras
run_cmd "$ROOT/services/data-ingestion" uv run --with pytest-cov pytest --cov=canonicalize --cov=config --cov=feeds --cov=gdelt_raw --cov=graph_integrity --cov=infra_atlas --cov=migrations --cov=nlm_ingest --cov=pipeline --cov=qdrant_doctor --cov=scheduler --cov=suv_structured --cov-report=term-missing "--cov-report=json:$INGESTION_COVERAGE" --cov-fail-under=0
check_coverage data-ingestion coverage.py "$INGESTION_COVERAGE"

section "Vision Enrichment"
run_cmd "$ROOT/services/vision-enrichment" uv sync --all-extras
run_cmd "$ROOT/services/vision-enrichment" uv run --with pytest-cov pytest --cov=config --cov=consumer --cov=main --cov=qdrant_schema --cov=vision --cov-report=term-missing "--cov-report=json:$VISION_COVERAGE" --cov-fail-under=0
check_coverage vision-enrichment coverage.py "$VISION_COVERAGE"

section "Smoke"
run_cmd "$ROOT" ./odin.sh smoke
