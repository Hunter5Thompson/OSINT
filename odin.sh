#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose)
CORE_SERVICES=(redis qdrant neo4j tei-embed)
INGESTION_SERVICES=(vllm-27b data-ingestion)
INTERACTIVE_SERVICES=(vllm-9b tei-rerank intelligence backend frontend)
VISION_SERVICES=(vllm-vision vision-enrichment)

resolve_env_file() {
  local requested="${1:-${ODIN_ENV_FILE:-.env}}"

  if [[ "$requested" == /* ]]; then
    printf '%s' "$requested"
  else
    printf '%s/%s' "$ROOT_DIR" "$requested"
  fi
}

ENV_FILE_REQUESTED="${ODIN_ENV_FILE:-.env}"
ENV_FILE_OPTION_USED=0
case "${1:-}" in
  --env-file)
    if [[ -z "${2:-}" ]]; then
      echo "ERROR --env-file requires a path"
      exit 2
    fi
    ENV_FILE_REQUESTED="$2"
    ENV_FILE_OPTION_USED=1
    shift 2
    ;;
  --env-file=*)
    ENV_FILE_REQUESTED="${1#--env-file=}"
    if [[ -z "$ENV_FILE_REQUESTED" ]]; then
      echo "ERROR --env-file requires a path"
      exit 2
    fi
    ENV_FILE_OPTION_USED=1
    shift
    ;;
esac

MODE="${2:-}"
COMMAND="${1:-help}"

# Backwards compatibility for the previously documented `doctor [env-file]`
# form. New automation should use the global --env-file option so doctor and
# lifecycle commands are guaranteed to select configuration identically.
if [[ "$COMMAND" == "doctor" && -n "$MODE" ]]; then
  if [[ "$ENV_FILE_OPTION_USED" == "1" ]]; then
    echo "ERROR pass the environment file only once"
    exit 2
  fi
  ENV_FILE_REQUESTED="$MODE"
  MODE=""
fi
ENV_FILE="$(resolve_env_file "$ENV_FILE_REQUESTED")"

# Spark (DGX GB10) — ingestion LLM host, overridable for staging/lab setups.
# Exported so docker-compose substitutes the same value into data-ingestion-spark
# (compose env: INGESTION_VLLM_URL=${SPARK_VLLM_URL:-...}). Without export, preflight
# would check one host and the scheduler container would talk to another.
export SPARK_VLLM_URL="${SPARK_VLLM_URL:-http://192.168.178.39:8000}"

usage() {
  cat <<'USAGE'
Usage:
  ./odin.sh [--env-file PATH] COMMAND [ARGS]

  ./odin.sh up ingestion       # Start background ingestion stack (27B + embed)
  ./odin.sh up interactive     # Start interactive stack (9B + reranker + UI)
  ./odin.sh up interactive-spark  # Interactive on 5090 + Ingestion via Spark (no GPU swap)
  ./odin.sh swap ingestion     # Swap to ingestion mode (stops active vLLM first)
  ./odin.sh swap interactive   # Swap to interactive mode
  ./odin.sh swap interactive-spark  # Swap to interactive-spark (local 9B + Spark ingestion)
  ./odin.sh down               # Stop all services
  ./odin.sh ps                 # Show running compose services
  ./odin.sh logs [service]     # Tail logs (optional service)
  ./odin.sh doctor             # Check selected env, exposure, compose + models
  ./odin.sh pull 9b-awq        # Download smaller interactive model
  ./odin.sh smoke              # Smoke-test running services (health + basic calls)
  ./odin.sh vision up|down     # Start/stop Vision Enrichment (Qwen3-VL-8B)
  ./odin.sh gdelt status       # Run odin-ingest-gdelt CLI inside data-ingestion
                               # (also: forward, backfill, resume, etc.)
  ./odin.sh recon bootstrap    # Download Skyfall-GS PLYs and write recon_manifest.json
USAGE
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found in PATH"
    exit 1
  fi
}

compose_run() {
  ODIN_ENV_FILE="$ENV_FILE" "${COMPOSE[@]}" --env-file "$ENV_FILE" "$@"
}

compose_recovery() {
  local action_allowed=0
  local arg
  local compose_env_file="$ENV_FILE"

  for arg in "$@"; do
    case "$arg" in
      up|start|run|create|restart|build|pull)
        echo "ERROR internal safety gate: recovery Compose cannot run '$arg'" >&2
        return 2
        ;;
      config|down|exec|logs|ps|rm|stop)
        action_allowed=1
        ;;
    esac
  done
  if [[ "$action_allowed" != "1" ]]; then
    echo "ERROR internal safety gate: unsupported recovery Compose action" >&2
    return 2
  fi
  if [[ ! -f "$compose_env_file" ]]; then
    compose_env_file=/dev/null
  fi

  # Compose expands the required Neo4j variable for every command, including
  # read-only/recovery operations. This non-secret sentinel is scoped only to
  # explicitly allow-listed actions above and can never reach a start action.
  NEO4J_PASSWORD="__ODIN_RECOVERY_ONLY__" \
    ODIN_ENV_FILE="$compose_env_file" \
    "${COMPOSE[@]}" --env-file "$compose_env_file" "$@"
}

render_preflight_config() {
  local env_file="$1"
  local compose_env_file="$env_file"

  if [[ ! -f "$compose_env_file" ]]; then
    compose_env_file=/dev/null
  fi
  ODIN_ENV_FILE="$compose_env_file" \
    "${COMPOSE[@]}" --env-file "$compose_env_file" -f - config --format json <<'YAML'
services:
  odin-preflight:
    image: scratch
    ports:
      - "${ODIN_BIND_HOST:-127.0.0.1}:1:1"
    environment:
      NEO4J_CONFIGURED: "${NEO4J_PASSWORD:+configured}"
YAML
}

start_mode() {
  local mode="$1"
  case "$mode" in
    ingestion)
      # Prevent port/GPU conflicts when switching from interactive or interactive-spark profile.
      compose_run --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-9b tei-rerank intelligence backend frontend data-ingestion-spark 2>/dev/null || true
      echo "Starting INGESTION mode: Qwen3.5-27B + Embedding + Data Ingestion"
      compose_run --profile ingestion up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INGESTION_SERVICES[@]}"
      ;;
    interactive)
      # Prevent port/GPU conflicts when switching from ingestion or interactive-spark profile.
      compose_run --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-27b data-ingestion data-ingestion-spark 2>/dev/null || true
      echo "Starting INTERACTIVE mode: Qwen3.5-9B + Reranker + API + UI"
      compose_run --profile interactive up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}"
      ;;
    interactive-spark)
      # Prevent conflicts: stop local 27B ingestion stack so only Spark-backed ingestion runs.
      compose_run --profile ingestion --profile interactive --profile interactive-spark stop \
        vllm-27b data-ingestion 2>/dev/null || true
      echo "Pre-flight: checking Spark vLLM..."
      if curl -sf --max-time 5 ${SPARK_VLLM_URL}/v1/models > /dev/null; then
        echo "  Spark reachable"
      else
        echo "  WARN: Spark unreachable — scheduler will retry"
      fi
      echo "Starting INTERACTIVE+SPARK mode: 9B local + Ingestion via Spark"
      compose_run --profile interactive --profile interactive-spark up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}" data-ingestion-spark
      ;;
    *)
      echo "Unknown mode: $mode"
      usage
      exit 1
      ;;
  esac
}

check_bind_host() {
  local env_file="$1"
  local config
  local bind_host

  if ! config="$(render_preflight_config "$env_file")"; then
    echo "ERROR could not resolve ODIN_BIND_HOST from Compose environment: $env_file"
    return 1
  fi
  if ! bind_host="$(printf '%s' "$config" | python3 -c '
import json
import sys

config = json.load(sys.stdin)
port = config["services"]["odin-preflight"]["ports"][0]
print(port.get("host_ip", ""))
')"; then
    echo "ERROR could not inspect resolved ODIN_BIND_HOST"
    return 1
  fi

  if [[ "$bind_host" != "127.0.0.1" ]]; then
    echo "ERROR unauthenticated services require loopback host binding: ODIN_BIND_HOST=$bind_host"
    return 1
  fi
  echo "OK  host exposure: ODIN_BIND_HOST=$bind_host"
}

check_neo4j_password() {
  local env_file="$1"
  local config
  local configured

  if [[ ! -f "$env_file" ]]; then
    echo "ERROR configuration environment file missing: $env_file"
    return 1
  fi
  if ! config="$(render_preflight_config "$env_file")"; then
    echo "ERROR could not resolve NEO4J_PASSWORD from Compose environment: $env_file"
    return 1
  fi
  if ! configured="$(printf '%s' "$config" | python3 -c '
import json
import sys

config = json.load(sys.stdin)
environment = config["services"]["odin-preflight"]["environment"]
print(environment.get("NEO4J_CONFIGURED", ""))
')"; then
    echo "ERROR could not inspect NEO4J_PASSWORD configuration"
    return 1
  fi
  if [[ "$configured" != "configured" ]]; then
    echo "ERROR NEO4J_PASSWORD is required and must be non-empty in $env_file"
    return 1
  fi
  echo "OK  NEO4J_PASSWORD is configured in the selected Compose environment"
}

require_start_configuration() {
  if ! check_bind_host "$ENV_FILE"; then
    echo "Refusing to start or swap services until the selected environment is valid."
    return 1
  fi
  if ! check_neo4j_password "$ENV_FILE"; then
    echo "Refusing to start or swap services until the selected environment is valid."
    return 1
  fi
}

check_secret_file_mode() {
  local env_file="$1"
  local mode

  if [[ ! -f "$env_file" ]]; then
    echo "ERROR secret environment file missing: $env_file"
    return 1
  fi
  mode="$(stat -c '%a' -- "$env_file")"
  if (( (8#$mode & 8#177) != 0 )); then
    echo "ERROR unsafe secret permissions: $env_file (mode $mode; expected mode 600 or stricter)"
    return 1
  fi
  echo "OK  secret permissions: $env_file (mode $mode)"
}

check_secret_files() {
  local primary="$1"
  local candidate
  local failed=0
  local -A checked=()

  checked["$primary"]=1
  if ! check_secret_file_mode "$primary"; then
    failed=1
  fi
  while IFS= read -r -d '' candidate; do
    if [[ -n "${checked[$candidate]:-}" ]]; then
      continue
    fi
    checked["$candidate"]=1
    if ! check_secret_file_mode "$candidate"; then
      failed=1
    fi
  done < <(
    find "$ROOT_DIR" \
      -type d \( -name .git -o -name .venv -o -name node_modules -o -name .quality-loop \) \
      -prune -o -type f \( -name .env -o -name '.env.*' \) \
      ! -name .env.example -print0
  )
  return "$failed"
}

doctor() {
  local failed=0
  local models_path
  models_path="${MODELS_PATH:-/home/deadpool-ultra/ODIN/models}"

  echo "Checking local exposure..."
  if ! check_bind_host "$ENV_FILE"; then
    failed=1
  fi
  if ! check_secret_files "$ENV_FILE"; then
    failed=1
  fi
  if ! check_neo4j_password "$ENV_FILE"; then
    failed=1
  fi

  echo "Compose syntax check..."
  if compose_recovery config --quiet; then
    echo "OK"
  else
    echo "ERROR Compose syntax check failed"
    failed=1
  fi

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

  echo ""
  echo "=== Qdrant Collection Health ==="
  (
    cd "$(dirname "$0")/services/data-ingestion"
    if command -v uv > /dev/null 2>&1; then
      uv run odin-qdrant-doctor || true
    else
      echo "  SKIP: uv not found — cannot run odin-qdrant-doctor"
    fi
  )
  return "$failed"
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
    compose_recovery ps --status running --format '{{.Service}}' 2>/dev/null | grep -Fxq "$service"
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
  running_services=$(compose_recovery ps --status running --format '{{.Service}}' 2>/dev/null || true)
  running_count=$(printf "%s\n" "$running_services" | sed '/^\s*$/d' | wc -l | tr -d ' ')
  if [[ "$running_count" == "0" ]]; then
    echo "No ODIN services are running. Start a profile first:"
    echo "  ./odin.sh up interactive  OR  ./odin.sh up ingestion"
    return 1
  fi

  # Core infrastructure (always running)
  echo "[Core Infrastructure]"
  if _service_running "redis"; then
    if compose_recovery exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
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
  _check_if_running "backend" "Backend health" "http://localhost:8080/api/health"
  echo ""

  # Functional checks (only if backend is up)
  local backend_up
  backend_up="000"
  if _service_running "backend"; then
    backend_up=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:8080/api/health" 2>/dev/null) || backend_up="000"
  fi
  if [[ "$backend_up" == "200" ]]; then
    echo "[Functional]"

    # Config endpoint (cesium token present?)
    local config_json
    config_json=$(curl -sf --max-time 5 "http://localhost:8080/api/config" 2>/dev/null) || config_json=""
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
    flights_code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 15 "http://localhost:8080/api/flights" 2>/dev/null) || flights_code="000"
    if [[ "$flights_code" == "200" ]]; then
      local flight_count
      flight_count=$(curl -sf --max-time 15 "http://localhost:8080/api/flights" 2>/dev/null \
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
    require_start_configuration
    start_mode "$MODE"
    ;;
  swap)
    if [[ -z "$MODE" ]]; then
      echo "Missing mode: ingestion | interactive | interactive-spark"
      usage
      exit 1
    fi
    require_start_configuration
    echo "Stopping active vLLM services..."
    compose_run --profile ingestion --profile interactive --profile interactive-spark stop vllm-27b vllm-9b 2>/dev/null || true
    echo "Swapping mode to: $MODE"
    start_mode "$MODE"
    ;;
  down)
    compose_recovery --profile ingestion --profile interactive --profile interactive-spark down --remove-orphans
    ;;
  ps)
    compose_recovery ps
    ;;
  logs)
    if [[ -n "$MODE" ]]; then
      compose_recovery logs -f "$MODE"
    else
      compose_recovery logs -f
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
        require_start_configuration
        echo "Starting Voxtral for NotebookLM..."
        compose_run --profile notebooklm up -d vllm-voxtral
        ;;
      down)
        echo "Stopping Voxtral..."
        compose_recovery stop vllm-voxtral
        compose_recovery rm -f vllm-voxtral
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
        require_start_configuration
        echo "Starting Vision Enrichment services..."
        compose_run --profile vision up -d "${VISION_SERVICES[@]}"
        ;;
      down)
        echo "Stopping Vision Enrichment services..."
        compose_recovery stop "${VISION_SERVICES[@]}"
        ;;
      *)
        echo "Usage: odin vision up|down"
        exit 1
        ;;
    esac
    ;;
  gdelt)
    shift
    compose_recovery exec data-ingestion odin-ingest-gdelt "$@"
    ;;
  recon)
    case "$MODE" in
      bootstrap)
        echo "Bootstrapping Skyfall-GS recon PLYs..."
        cd "$ROOT_DIR"
        if [ -x "$ROOT_DIR/services/backend/.venv/bin/python" ]; then
          PY="$ROOT_DIR/services/backend/.venv/bin/python"
        elif command -v python3 >/dev/null 2>&1; then
          PY=python3
        elif command -v python >/dev/null 2>&1; then
          PY=python
        else
          echo "ERROR: no python interpreter found on PATH" >&2
          exit 127
        fi
        "$PY" -m scripts.recon.bootstrap_skyfall_plys "${@:3}"
        exit $?
        ;;
      "")
        echo "Usage: ./odin.sh recon bootstrap [--no-strict-sizes] [--allow-partial]"
        exit 1
        ;;
      *)
        echo "Unknown recon subcommand: $MODE"
        echo "Usage: ./odin.sh recon bootstrap"
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
