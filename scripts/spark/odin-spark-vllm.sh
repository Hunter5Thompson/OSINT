#!/usr/bin/env bash
# Manage the Spark (DGX GB10) ingestion vLLM for the ODIN stack.
#
# Production model: Qwen3.6-35B-A3B served as NVFP4 (W4A16, modelopt) on vLLM nightly.
# ODIN's data-ingestion addresses it ONLY by served-model-name "Qwen/Qwen3.6-35B-A3B"
# (services/data-ingestion/config.py: ingestion_vllm_model) — so NO ODIN change is needed.
#
# Rollback target: the legacy BF16 container "vllm-qwen36" (image vllm-gemma4:latest, vLLM
# v0.19.0). It is kept STOPPED with restart=no so it never auto-starts and fights for :8000.
set -euo pipefail

# vllm/vllm-openai:nightly pinned by digest on 2026-06-29 (reproducible; tag moves daily)
IMG_NVFP4="vllm/vllm-openai@sha256:907377dddef392f6b679d9c071e1c33c3935b4dc993b61d0352e391a5319ff3e"
NEW="vllm-qwen36-nvfp4"     # NVFP4 production container
OLD="vllm-qwen36"          # legacy BF16, rollback only
SERVED="Qwen/Qwen3.6-35B-A3B"
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
    --model nvidia/Qwen3.6-35B-A3B-NVFP4 \
    --served-model-name "$SERVED" \
    --quantization modelopt \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.90 \
    --trust-remote-code
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
    echo "Cutover -> NVFP4. Stopping legacy BF16 ($OLD) and neutralizing its auto-start..."
    run_cmd docker stop "$OLD" || true
    run_cmd docker update --restart=no "$OLD" || true
    start_nvfp4
    wait_ready
    ;;
  down)
    run_cmd docker stop "$NEW" || true; echo "stopped $NEW"
    ;;
  status)
    echo "Container:"; docker ps -a --filter name=vllm-qwen36 --format "  {{.Names}} | {{.Status}} | restart={{.Label \"x\"}}"
    docker inspect "$NEW" "$OLD" --format "  {{.Name}} restart={{.HostConfig.RestartPolicy.Name}} status={{.State.Status}}" 2>/dev/null || true
    echo -n "  endpoint /v1/models -> "
    curl -sf -m5 http://localhost:${PORT}/v1/models | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "(down)"
    ;;
  logs)
    docker logs "${2:-$NEW}" 2>&1 | tail -"${3:-40}"
    ;;
  rollback)
    echo "ROLLBACK -> BF16 ($OLD)..."
    run_cmd docker stop "$NEW" || true
    run_cmd docker update --restart=no "$NEW" || true
    run_cmd docker update --restart=unless-stopped "$OLD" || true
    run_cmd docker start "$OLD"
    echo "BF16 starting. Verify with: $0 status   (BF16 cold-start ~4-5 min)"
    ;;
  *)
    echo "usage: $0 [--dry-run] {up|down|status|logs [container] [n]|rollback}"
    ;;
esac
