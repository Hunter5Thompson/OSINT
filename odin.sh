#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose)
CORE_SERVICES=(redis qdrant neo4j tei-embed)
INGESTION_SERVICES=(vllm-27b data-ingestion)
INTERACTIVE_SERVICES=(vllm-9b tei-rerank intelligence backend frontend)

MODE="${2:-}"
COMMAND="${1:-help}"

usage() {
  cat <<'USAGE'
Usage:
  ./odin.sh up ingestion       # Start background ingestion stack (27B + embed)
  ./odin.sh up interactive     # Start interactive stack (9B + reranker + UI)
  ./odin.sh swap ingestion     # Swap to ingestion mode (stops active vLLM first)
  ./odin.sh swap interactive   # Swap to interactive mode
  ./odin.sh down               # Stop all services
  ./odin.sh ps                 # Show running compose services
  ./odin.sh logs [service]     # Tail logs (optional service)
  ./odin.sh doctor             # Check compose + model directories
  ./odin.sh pull 9b-awq        # Download smaller interactive model
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
      echo "Starting INGESTION mode: Qwen3.5-27B + Embedding + Data Ingestion"
      "${COMPOSE[@]}" --profile ingestion up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INGESTION_SERVICES[@]}"
      ;;
    interactive)
      echo "Starting INTERACTIVE mode: Qwen3.5-9B + Reranker + API + UI"
      "${COMPOSE[@]}" --profile interactive up -d --remove-orphans \
        "${CORE_SERVICES[@]}" "${INTERACTIVE_SERVICES[@]}"
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

require_docker

case "$COMMAND" in
  up)
    if [[ -z "$MODE" ]]; then
      echo "Missing mode: ingestion | interactive"
      usage
      exit 1
    fi
    start_mode "$MODE"
    ;;
  swap)
    if [[ -z "$MODE" ]]; then
      echo "Missing mode: ingestion | interactive"
      usage
      exit 1
    fi
    echo "Stopping active vLLM services..."
    "${COMPOSE[@]}" --profile ingestion --profile interactive stop vllm-27b vllm-9b 2>/dev/null || true
    echo "Swapping mode to: $MODE"
    start_mode "$MODE"
    ;;
  down)
    "${COMPOSE[@]}" --profile ingestion --profile interactive down --remove-orphans
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
  pull)
    if [[ -z "$MODE" ]]; then
      echo "Missing model target (example: 9b-awq)"
      usage
      exit 1
    fi
    pull_model "$MODE"
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
