#!/bin/bash
# auto_sync.sh - serial one-command pipeline trigger

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/logs/auto_sync.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

MODE="${PIPELINE_MODE:-incremental}"

log "=== Starting auto sync (mode=$MODE) ==="
cd "$PROJECT_DIR"

if [ "$MODE" = "full" ]; then
  python3 scripts/pipeline.py run --mode full 2>&1 | tee -a "$LOG_FILE"
else
  # default incremental; no args keeps scheduler/cron usage minimal
  python3 scripts/pipeline.py 2>&1 | tee -a "$LOG_FILE"
fi

log "=== Sync complete ==="
