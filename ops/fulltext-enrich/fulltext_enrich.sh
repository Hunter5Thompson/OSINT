#!/usr/bin/env bash
# ODIN host-side think-tank full-text enrichment — OPERATIONAL BRIDGE.
#
# Why this exists: the container-native scheduler job (FulltextCollector, gated by
# FULLTEXT_ENABLED) runs inside data-ingestion-spark, which is on osint_default and
# CANNOT reach crawl4ai (:11235) / docling (:5001) — they live in foreign compose
# networks, only published on the host. This host runner uses localhost, where all
# deps are reachable (the same path the one-time backfill used).
#
# This is a bridge, NOT the target architecture. Follow-up (TASKS.md): migrate to a
# container-native fulltext scheduler (attach data-ingestion to crawl4ai_default/
# docling_default, FULLTEXT_ENABLED=true) as a tested branch/PR.
#
# Properties: single-instance (flock), dependency health-gated (skips instead of
# churning when a dep is down), small bounded batch, hard timeout. One batch per run;
# the hourly timer drains any backlog gradually. Logs go to journald via systemd.
set -uo pipefail

REPO=/home/deadpool-ultra/ODIN/OSINT
DI="$REPO/services/data-ingestion"
UV=/home/deadpool-ultra/.local/bin/uv
LOCK=/tmp/odin-fulltext-enrich.lock
OUT=/tmp/odin-fulltext-enrich.last.log
BATCH=${FULLTEXT_BATCH_SIZE:-10}
RUN_TIMEOUT=${FULLTEXT_RUN_TIMEOUT:-600}

log() { echo "[fulltext-enrich $(date -Is)] $*"; }

# --- single instance: never overlap two runs ---
exec 9>"$LOCK"
if ! flock -n 9; then
  log "another run holds the lock — skipping"
  exit 0
fi

# --- dependency health gate: only run when ALL deps are reachable ---
hc() { curl -sf -m 6 -o /dev/null "$@"; }
deps_ok=1
hc http://localhost:6333/readyz  || { log "DEP DOWN: qdrant /readyz";  deps_ok=0; }
hc http://localhost:11235/health || { log "DEP DOWN: crawl4ai /health"; deps_ok=0; }
hc http://localhost:5001/health  || { log "DEP DOWN: docling /health";  deps_ok=0; }
curl -sf -m 6 -o /dev/null -X POST http://localhost:8001/embed \
  -H 'Content-Type: application/json' -d '{"inputs":"healthcheck"}' \
  || { log "DEP DOWN: TEI /embed"; deps_ok=0; }
if [ "$deps_ok" != 1 ]; then
  log "dependencies not all ready — skipping this run (no churn)"
  exit 0
fi

# --- one bounded, throttled batch (hard timeout; small batch) ---
log "starting batch (size=$BATCH, timeout=${RUN_TIMEOUT}s)"
cd "$DI" || { log "FATAL: cannot cd $DI"; exit 1; }
set +e
FULLTEXT_ENABLED=true FULLTEXT_BATCH_SIZE="$BATCH" \
  timeout --kill-after=30 "$RUN_TIMEOUT" \
  "$UV" run python -c \
  "import asyncio; from feeds.fulltext_collector import FulltextCollector; asyncio.run(FulltextCollector().collect())" \
  >"$OUT" 2>&1
rc=$?
set -e
# surface the collector's own structlog lines to journald, minus known noise
grep -vE "UserWarning|show_warning|check_compatibility" "$OUT" || true
if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
  log "batch TIMED OUT after ${RUN_TIMEOUT}s (rc=$rc) — next timer fire retries"
else
  log "batch finished rc=$rc"
fi
exit 0  # never fail the unit on a single bad run; the timer retries hourly
