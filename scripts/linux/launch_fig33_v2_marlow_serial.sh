#!/usr/bin/env bash
# Wait for a running Abaqus job to finish, then launch fig33_v2_marlow serial fan-out.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

WAIT_SLUG="${1:-hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_paper_dt1e4}"
LOG="output/logs/fig33_v2_marlow_serial_launch.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

LCK="output/jobs/${WAIT_SLUG}/${WAIT_SLUG}.lck"
if [[ -f "$LCK" ]] || pgrep -f "$WAIT_SLUG" >/dev/null 2>&1; then
  log "Waiting for $WAIT_SLUG to finish before marlow serial queue..."
  while [[ -f "$LCK" ]] || pgrep -f "$WAIT_SLUG" >/dev/null 2>&1; do
    log "  still running: $WAIT_SLUG"
    sleep 60
  done
  log "  $WAIT_SLUG finished"
  sleep 10
else
  log "No active job for $WAIT_SLUG — starting marlow serial immediately"
fi

log "Launching run_fig33_v2_marlow_serial.sh"
exec bash scripts/linux/run_fig33_v2_marlow_serial.sh
