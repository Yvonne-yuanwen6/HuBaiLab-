#!/usr/bin/env bash
# Stop ellipse batch supervisor + all related Abaqus/export processes.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

LOG="output/logs/ellipse_444_baseline_parallel.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] STOP $*" | tee -a "$LOG"; }

log "=== stop ellipse batch ==="

pkill -f 'bash scripts/linux/run_ellipse_444_marlow_parallel.sh' 2>/dev/null || true
pkill -f 'run_hu_bai_bcc_solid_cad_cae_tet_export.py.*ellipse' 2>/dev/null || true

for tag in ellipse_v2_marlow ellipse_ellmaj_fig33_v2_marlow ellipse_ellmin_fig33_v2_marlow fig33_v2_marlow paperbox_ellipse paperbox_ellipse_ell; do
  ps aux | awk -v t="$tag" '/SMAPython|\/bin\/explicit|mpiexec|mpirun|eliT_DriverLM/ && index($0,t) {print $2}' \
    | xargs -r kill -9 2>/dev/null || true
done

sleep 2
rm -f output/logs/ellipse_444_baseline_parallel.lock output/logs/ellipse_444_marlow_parallel.lock

log "remaining explicit (ellipse): $(ps aux | grep '/bin\/explicit' | grep ellipse | grep -v grep | wc -l)"
log "=== stop done ==="
