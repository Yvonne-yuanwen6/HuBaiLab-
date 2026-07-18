#!/bin/bash
# Wait for /tmp CAE probe to finish, copy mesh if OK, restart ellipse batch.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="$ROOT/output/logs/ellipse_444_baseline_parallel.log"
OUT="/tmp/test_q1_mesh2.inp"
DEST="$ROOT/output/export/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_ellipse_ellmaj/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_ellipse_ellmaj_cae_mesh.inp"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
echo "[$(ts)] watch probe start" >> "$LOG"
while pgrep -f 'ABQcaeK -cae -noGUI scripts/abaqus_cae_hex_mesh_pilot.py' >/dev/null 2>&1; do
  sleep 30
done
echo "[$(ts)] probe CAE exited" >> "$LOG"
if [[ -f "$OUT" ]] && grep -q '^\*Node' "$OUT"; then
  mkdir -p "$(dirname "$DEST")"
  cp -f "$OUT" "$DEST"
  cp -f /tmp/cae_hex_pilot.log "$(dirname "$DEST")/cae_hex_pilot.log" 2>/dev/null || true
  echo "[$(ts)] probe SUCCESS copied to $DEST" >> "$LOG"
else
  echo "[$(ts)] probe FAIL; restart orchestrator cascade" >> "$LOG"
  tail -40 /tmp/cae_hex_pilot.log >> "$LOG" 2>/dev/null || true
fi
rm -f "$ROOT/output/logs/ellipse_444_baseline_parallel.lock"
cd "$ROOT"
ELLIPSE_BASELINE_MAX_PARALLEL=2 nohup bash scripts/linux/run_ellipse_444_marlow_parallel.sh >> "$LOG" 2>&1 </dev/null &
echo "[$(ts)] orchestrator restarted pid=$!" >> "$LOG"
