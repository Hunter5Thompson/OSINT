#!/usr/bin/env bash
# Manage the Spark (DGX GB10) ingestion vLLM for the ODIN stack.
#
# Production model: Qwen3.8-27B served from the validated Unsloth NVFP4 checkpoint.
# ODIN's data-ingestion addresses it by served-model-name "Qwen/Qwen3.8-27B",
# matching services/data-ingestion/config.py:ingestion_vllm_model.
#
# Rollback target: the previous Qwen3.6 NVFP4 container. Its served name differs,
# so ODIN must also override INGESTION_VLLM_MODEL when an operator rolls back.
set -euo pipefail

# vLLM 0.27.1 image used by the verified 2026-08-21 Spark deployment, pinned.
IMG_NVFP4="vllm/vllm-openai@sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967"
NEW="vllm-qwen38-nvfp4"       # current production container
ROLLBACK="vllm-qwen36-nvfp4"  # previous NVFP4 container
LEGACY_BF16="vllm-qwen36"     # older BF16 fallback, kept stopped
SERVED="Qwen/Qwen3.8-27B"
ROLLBACK_SERVED="Qwen/Qwen3.6-35B-A3B"
HF="/home/albert/.cache/huggingface"
PORT=8000
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

run_cmd() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

start_nvfp4() {
  run_cmd docker rm -f "$NEW" || true
  run_cmd docker run -d --name "$NEW" --restart unless-stopped \
    --gpus all -p ${PORT}:8000 \
    -v ${HF}:/root/.cache/huggingface \
    "$IMG_NVFP4" \
    --model unsloth/Qwen3.8-27B-NVFP4 \
    --served-model-name "$SERVED" \
    --max-model-len 131072 \
    --gpu-memory-utilization 0.85 \
    --max-num-seqs 4 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3 \
    --speculative-config '{"method":"mtp","num_speculative_tokens":5}'
  echo "started $NEW (serving as '$SERVED')"
}

wait_ready() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would wait for '$SERVED' on localhost:${PORT}"
    return 0
  fi
  for i in $(seq 1 160); do
    if curl -sf -m5 http://localhost:${PORT}/v1/models 2>/dev/null | grep -q "$SERVED"; then
      echo "READY after ~$((i*12))s"; return 0
    fi
    st=$(docker inspect -f '{{.State.Status}}' "$NEW" 2>/dev/null || echo gone)
    if [ "$st" != "running" ]; then
      echo "CONTAINER EXITED (status=$st) — last logs:"; docker logs "$NEW" 2>&1 | tail -30; return 1
    fi
    sleep 12
  done
  echo "TIMEOUT waiting for readiness"; return 1
}

case "${1:-help}" in
  up)
    echo "Starting Qwen3.8 NVFP4 and neutralizing Qwen3.6 rollback containers..."
    run_cmd docker stop "$ROLLBACK" || true
    run_cmd docker update --restart=no "$ROLLBACK" || true
    run_cmd docker stop "$LEGACY_BF16" || true
    run_cmd docker update --restart=no "$LEGACY_BF16" || true
    start_nvfp4
    wait_ready
    ;;
  down)
    run_cmd docker stop "$NEW" || true; echo "stopped $NEW"
    ;;
  status)
    echo "Container:"; docker ps -a --filter name=vllm-qwen3 --format "  {{.Names}} | {{.Status}}"
    docker inspect "$NEW" "$ROLLBACK" "$LEGACY_BF16" --format "  {{.Name}} restart={{.HostConfig.RestartPolicy.Name}} status={{.State.Status}}" 2>/dev/null || true
    echo -n "  endpoint /v1/models -> "
    curl -sf -m5 http://localhost:${PORT}/v1/models | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "(down)"
    ;;
  logs)
    docker logs "${2:-$NEW}" 2>&1 | tail -"${3:-40}"
    ;;
  rollback)
    echo "ROLLBACK -> Qwen3.6 NVFP4 ($ROLLBACK)..."
    run_cmd docker stop "$NEW" || true
    run_cmd docker update --restart=no "$NEW" || true
    run_cmd docker update --restart=unless-stopped "$ROLLBACK" || true
    run_cmd docker start "$ROLLBACK"
    echo "Qwen3.6 starting. Before restarting ingestion, set:"
    echo "  INGESTION_VLLM_MODEL=$ROLLBACK_SERVED"
    echo "Verify with: $0 status"
    ;;
  *)
    echo "usage: $0 [--dry-run] {up|down|status|logs [container] [n]|rollback}"
    ;;
esac
