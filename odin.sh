#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose)
CORE_SERVICES=(redis qdrant neo4j tei-embed)
INGESTION_SERVICES=(vllm-27b data-ingestion)
INTERACTIVE_SERVICES=(vllm-9b tei-rerank intelligence backend frontend)
VISION_SERVICES=(vllm-vision vision-enrichment)

# Spark (DGX GB10) — ingestion LLM host, overridable for staging/lab setups.
# Exported so docker-compose substitutes the same value into data-ingestion-spark
# (compose env: INGESTION_VLLM_URL=${SPARK_VLLM_URL:-...}). Without export, preflight
# would check one host and the scheduler container would talk to another.
export SPARK_VLLM_URL="${SPARK_VLLM_URL:-http://192.168.178.39:8000}"

MODE="${2:-}"
COMMAND="${1:-help}"

usage() {
  cat <<'USAGE'
Usage:
  ./odin.sh up ingestion       # Start background ingestion stack (27B + embed)
  ./odin.sh up interactive     # Start interactive stack (9B + reranker + UI)
  ./odin.sh up interactive-spark  # Interactive on 5090 + Ingestion via Spark (no GPU swap)
  ./odin.sh swap ingestion     # Swap to ingestion mode (stops active vLLM first)
  ./odin.sh swap interactive   # Swap to interactive mode
  ./odin.sh swap interactive-spark  # Swap to interactive-spark (local 9B + Spark ingestion)
  ./odin.sh down               # Stop all services
  ./odin.sh ps                 # Show running compose services
  ./odin.sh logs [service]     # Tail logs (optional service)
  ./odin.sh doctor             # Check compose + model directories
  ./odin.sh pull 9b-awq        # Download smaller interactive model
  ./odin.sh smoke              # Smoke-test running services (health + basic calls)
  ./odin.sh vision up|down     # Start/stop Vision Enrichment (Qwen3-VL-8B)
USAGE
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found in PATH"
    exit 1
  fi
}

start_mode() {
  local mode="$1"
  case "$mode" in
    ingestion)
      # Prevent port/GPU conflicts when switching from interactive or interactive-spark profile.
      "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-9b tei-rerank intelligence backend frontend data-ingestion-spark 2>/dev/null || true
      echo "Starting INGESTION mode: Qwen3.5-27B + Embedding + Data Ingestion"
      "${COMPOSE[@]}" --profile ingestion up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INGESTION_SERVICES[@]}"
      ;;
    interactive)
      # Prevent port/GPU conflicts when switching from ingestion or interactive-spark profile.
      "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-27b data-ingestion data-ingestion-spark 2>/dev/null || true
      echo "Starting INTERACTIVE mode: Qwen3.5-9B + Reranker + API + UI"
      "${COMPOSE[@]}" --profile interactive up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}"
      ;;
    interactive-spark)
      # Prevent conflicts: stop local 27B ingestion stack so only Spark-backed ingestion runs.
      "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-27b data-ingestion 2>/dev/null || true
      echo "Pre-flight: checking Spark vLLM..."
      if curl -sf --max-time 5 ${SPARK_VLLM_URL}/v1/models > /dev/null; then
        echo "  Spark reachable"
      else
        echo "  WARN: Spark unreachable — scheduler will retry"
      fi
      echo "Starting INTERACTIVE+SPARK mode: 9B local + Ingestion via Spark"
      "${COMPOSE[@]}" --profile interactive --profile interactive-spark up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}" data-ingestion-spark
      ;;
    *)
      echo "Unknown mode: $mode"
      usage
      exit 1
      ;;
  esac
}

doctor() {
  local models_path
  models_path="${MODELS_PATH:-/home/deadpool-ultra/ODIN/models}"

  echo "Compose syntax check..."
  "${COMPOSE[@]}" config --quiet
  echo "OK"

  echo "Checking model directories in $models_path"
  if [[ -d "$models_path/qwen3.5-27b-awq" ]]; then
    echo "OK  qwen3.5-27b-awq found"
  else
    echo "WARN qwen3.5-27b-awq missing"
  fi

  if [[ -d "$models_path/qwen3.5-9b-awq" ]]; then
    echo "OK  qwen3.5-9b-awq found"
  else
    echo "WARN qwen3.5-9b-awq missing"
  fi

  echo "Spark vLLM reachability..."
  if curl -sf --max-time 5 ${SPARK_VLLM_URL}/v1/models > /dev/null; then
    echo "  OK (Spark reachable)"
  else
    echo "  WARN: Spark unreachable — interactive-spark mode will retry but extraction blocks"
  fi
}

pull_model() {
  local target="$1"
  local models_path
  models_path="${MODELS_PATH:-/home/deadpool-ultra/ODIN/models}"

  case "$target" in
    9b-awq)
      local repo
      local dst
      repo="${QWEN35_9B_AWQ_REPO:-cyankiwi/Qwen3.5-9B-AWQ-4bit}"
      dst="$models_path/qwen3.5-9b-awq"
      echo "Downloading $repo -> $dst"
      HF_REPO="$repo" HF_DST="$dst" uv run --with huggingface_hub python -c \
        'import os; from huggingface_hub import snapshot_download; snapshot_download(repo_id=os.environ["HF_REPO"], local_dir=os.environ["HF_DST"], local_dir_use_symlinks=False)'
      ;;
    *)
      echo "Unknown model target: $target"
      echo "Supported: 9b-awq"
      exit 1
      ;;
  esac
}

smoke() {
  local pass=0
  local fail=0
  local skip=0
  # Arithmetic in set -e: ((0)) returns 1, so use "|| true" pattern via helper
  _inc_pass() { pass=$((pass + 1)); }
  _inc_fail() { fail=$((fail + 1)); }
  _inc_skip() { skip=$((skip + 1)); }

  _check() {
    local label="$1"
    local url="$2"
    local expect="${3:-200}"

    local code
    code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null) || code="000"

    if [[ "$code" == "$expect" ]]; then
      printf "  %-28s %s\n" "$label" "OK ($code)"
      _inc_pass
    else
      printf "  %-28s %s\n" "$label" "FAIL (got $code, want $expect)"
      _inc_fail
    fi
  }

  _service_running() {
    local service="$1"
    "${COMPOSE[@]}" ps --status running --format '{{.Service}}' 2>/dev/null | grep -Fxq "$service"
  }

  _check_container() {
    local service="$1"
    if _service_running "$service"; then
      printf "  %-28s %s\n" "$service" "RUNNING"
      _inc_pass
    else
      printf "  %-28s %s\n" "$service" "NOT RUNNING"
      _inc_skip
    fi
  }

  _check_if_running() {
    local service="$1"
    local label="$2"
    local url="$3"
    local expect="${4:-200}"

    if _service_running "$service"; then
      _check "$label" "$url" "$expect"
    else
      printf "  %-28s %s\n" "$label" "SKIP (service $service not running)"
      _inc_skip
    fi
  }

  echo "=== ODIN Smoke Test ==="
  echo ""

  local running_count
  local running_services
  running_services=$("${COMPOSE[@]}" ps --status running --format '{{.Service}}' 2>/dev/null || true)
  running_count=$(printf "%s\n" "$running_services" | sed '/^\s*$/d' | wc -l | tr -d ' ')
  if [[ "$running_count" == "0" ]]; then
    echo "No ODIN services are running. Start a profile first:"
    echo "  ./odin.sh up interactive  OR  ./odin.sh up ingestion"
    return 1
  fi

  # Core infrastructure (always running)
  echo "[Core Infrastructure]"
  if _service_running "redis"; then
    if "${COMPOSE[@]}" exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
      printf "  %-28s %s\n" "Redis" "OK (PONG)"
      _inc_pass
    else
      printf "  %-28s %s\n" "Redis" "FAIL (no PONG)"
      _inc_fail
    fi
  else
    printf "  %-28s %s\n" "Redis" "SKIP (service redis not running)"
    _inc_skip
  fi
  _check_if_running "qdrant" "Qdrant health" "http://localhost:6333/healthz"
  _check_if_running "neo4j" "Neo4j browser" "http://localhost:7474"
  _check_if_running "tei-embed" "TEI Embed health" "http://localhost:8001/health"
  echo ""

  # vLLM (one of the two profiles)
  echo "[vLLM]"
  local vllm_health
  if _service_running "vllm-27b" || _service_running "vllm-9b"; then
    vllm_health=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 10 "http://localhost:8000/health" 2>/dev/null) || vllm_health="000"
    if [[ "$vllm_health" == "200" ]]; then
      printf "  %-28s %s\n" "vLLM health" "OK"
      _inc_pass

      # Which model is loaded?
      local models_json
      models_json=$(curl -sf --max-time 5 "http://localhost:8000/v1/models" 2>/dev/null) || models_json=""
      if [[ -n "$models_json" ]]; then
        local model_id
        model_id=$(echo "$models_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null) || model_id="unknown"
        printf "  %-28s %s\n" "Loaded model" "$model_id"
      fi
    else
      printf "  %-28s %s\n" "vLLM health" "FAIL (got $vllm_health, want 200)"
      _inc_fail
    fi
  else
    printf "  %-28s %s\n" "vLLM health" "SKIP (no vLLM profile running)"
    _inc_skip
  fi
  echo ""

  # Interactive-profile services
  echo "[Interactive Services]"
  _check_container "tei-rerank"
  _check_if_running "tei-rerank" "TEI Rerank health" "http://localhost:8002/health"
  _check_if_running "intelligence" "Intelligence health" "http://localhost:8003/health"
  _check_if_running "backend" "Backend health" "http://localhost:8080/api/v1/health"
  echo ""

  # Functional checks (only if backend is up)
  local backend_up
  backend_up="000"
  if _service_running "backend"; then
    backend_up=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:8080/api/v1/health" 2>/dev/null) || backend_up="000"
  fi
  if [[ "$backend_up" == "200" ]]; then
    echo "[Functional]"

    # Config endpoint (cesium token present?)
    local config_json
    config_json=$(curl -sf --max-time 5 "http://localhost:8080/api/v1/config" 2>/dev/null) || config_json=""
    if [[ -n "$config_json" ]]; then
      local token_len
      token_len=$(echo "$config_json" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('cesium_ion_token','')))" 2>/dev/null) || token_len=0
      if [[ "$token_len" -gt 10 ]]; then
        printf "  %-28s %s\n" "Cesium Ion token" "OK (${token_len} chars)"
        _inc_pass
      else
        printf "  %-28s %s\n" "Cesium Ion token" "WARN (empty or short)"
        _inc_fail
      fi
    fi

    # Flights endpoint
    local flights_code
    flights_code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 15 "http://localhost:8080/api/v1/flights" 2>/dev/null) || flights_code="000"
    if [[ "$flights_code" == "200" ]]; then
      local flight_count
      flight_count=$(curl -sf --max-time 15 "http://localhost:8080/api/v1/flights" 2>/dev/null \
        | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null) || flight_count="?"
      printf "  %-28s %s\n" "Flights endpoint" "OK ($flight_count aircraft)"
      _inc_pass
    else
      printf "  %-28s %s\n" "Flights endpoint" "FAIL ($flights_code)"
      _inc_fail
    fi

    # Frontend reachable?
    _check_if_running "frontend" "Frontend (Vite)" "http://localhost:5173"
    echo ""
  fi

  # Ingestion-profile services
  echo "[Ingestion Services]"
  _check_container "data-ingestion"
  _check_container "data-ingestion-spark"
  # Spark vLLM (used by interactive-spark mode). Always probed; SKIP if unreachable.
  if curl -sf --max-time 3 ${SPARK_VLLM_URL}/v1/models > /dev/null 2>&1; then
    _check "spark-vllm" "${SPARK_VLLM_URL}/v1/models" 200
  else
    printf "  %-28s %s\n" "spark-vllm" "SKIP (unreachable)"
    _inc_skip
  fi
  echo ""

  # Summary
  echo "=== Results: $pass passed, $fail failed, $skip skipped ==="
  if [[ "$fail" -gt 0 ]]; then
    return 1
  fi
}

require_docker

case "$COMMAND" in
  up)
    if [[ -z "$MODE" ]]; then
      echo "Missing mode: ingestion | interactive | interactive-spark"
      usage
      exit 1
    fi
    start_mode "$MODE"
    ;;
  swap)
    if [[ -z "$MODE" ]]; then
      echo "Missing mode: ingestion | interactive | interactive-spark"
      usage
      exit 1
    fi
    echo "Stopping active vLLM services..."
    "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark stop vllm-27b vllm-9b 2>/dev/null || true
    echo "Swapping mode to: $MODE"
    start_mode "$MODE"
    ;;
  down)
    "${COMPOSE[@]}" --profile ingestion --profile interactive --profile interactive-spark down --remove-orphans
    ;;
  ps)
    "${COMPOSE[@]}" ps
    ;;
  logs)
    if [[ -n "$MODE" ]]; then
      "${COMPOSE[@]}" logs -f "$MODE"
    else
      "${COMPOSE[@]}" logs -f
    fi
    ;;
  doctor)
    doctor
    ;;
  smoke)
    smoke
    ;;
  pull)
    if [[ -z "$MODE" ]]; then
      echo "Missing model target (example: 9b-awq)"
      usage
      exit 1
    fi
    pull_model "$MODE"
    ;;
  nlm)
    subcmd="${2:-help}"
    case "$subcmd" in
      up)
        echo "Starting Voxtral for NotebookLM..."
        docker compose --profile notebooklm up -d vllm-voxtral
        ;;
      down)
        echo "Stopping Voxtral..."
        docker compose stop vllm-voxtral && docker compose rm -f vllm-voxtral
        ;;
      smoke)
        echo "Running Voxtral healthcheck..."
        cd services/data-ingestion && uv run odin-ingest-nlm healthcheck
        ;;
      run)
        echo "Running NotebookLM ingestion pipeline..."
        cd services/data-ingestion && uv run odin-ingest-nlm run
        ;;
      status)
        cd services/data-ingestion && uv run odin-ingest-nlm status
        ;;
      *)
        echo "Usage: odin nlm {up|down|smoke|run|status}"
        ;;
    esac
    ;;
  vision)
    subcmd="${2:-help}"
    case "$subcmd" in
      up)
        echo "Starting Vision Enrichment services..."
        "${COMPOSE[@]}" --profile vision up -d "${VISION_SERVICES[@]}"
        ;;
      down)
        echo "Stopping Vision Enrichment services..."
        "${COMPOSE[@]}" stop "${VISION_SERVICES[@]}"
        ;;
      *)
        echo "Usage: odin vision up|down"
        exit 1
        ;;
    esac
    ;;
  help|--help|-h|"")
    usage
    ;;
  *)
    echo "Unknown command: $COMMAND"
    usage
    exit 1
    ;;
esac
