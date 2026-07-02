#!/usr/bin/env bash
# Stop all running HuBaiLab paperbox Abaqus jobs + local orchestrators.
#
#   bash scripts/linux/stop_all_paperbox_running.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
STOP="$ROOT/scripts/linux/stop_paperbox_job.sh"
LOG="output/logs/stop_all_paperbox_running.log"
mkdir -p output/logs

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== stop all paperbox running ==="

for pat in \
  run_paperbox_q05_fig33_improve.sh \
  run_paperbox_q05_parallel_sweep.sh \
  run_paperbox_q1_diagnostic_sweep.sh \
  paperbox_auto_orchestrator.sh \
  paperbox_q15_fig33_auto_orchestrator.sh \
  run_fig33_v2_el_serial.sh; do
  if pgrep -f "$pat" >/dev/null 2>&1; then
    log "TERM orchestrator $pat"
    pkill -TERM -f "$pat" 2>/dev/null || true
  fi
done
sleep 3

mapfile -t LCKS < <(find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | sort)
if [[ ${#LCKS[@]} -eq 0 ]]; then
  log "no .lck files"
else
  for lck in "${LCKS[@]}"; do
    slug="$(basename "$lck" .lck)"
    log "stop slug=$slug"
    bash "$STOP" "$slug" >> "$LOG" 2>&1 || log "WARN stop failed $slug"
  done
fi

sleep 2
rem=$(find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | wc -l || true)
log "remaining .lck: $rem"
log "=== done ==="
