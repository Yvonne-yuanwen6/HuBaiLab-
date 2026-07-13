#!/usr/bin/env bash
# Phase 1 solve + validate only (mph already built).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"

SLUG="comsol_fig321_bcc_444_mesh_p1"
JOB="output/comsol_jobs/${SLUG}"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"
BATCH="${JOB}/${SLUG}_batch.log"
VALID="${JOB}/${SLUG}_validation.txt"
LOG="output/logs/${SLUG}_solve_watch.log"

exec >>"$LOG" 2>&1
echo "=== p1 solve+validate $(date) ==="

python3 scripts/_patch_freq_plist.py "$MPH" --freq-min 10 --freq-max 300 --freq-step 10
rm -f "$SOLVED" "${SOLVED}.recovery" "$BATCH"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$SLUG" \
  --interface-coupling p1_continuity \
  --freq-only --excitation-axis z --base-accel 0.98 --no-top-payload \
  --freq-min 10 --freq-max 300 --freq-step 10 \
  --solve-only "$MPH" --np 32 --background

while true; do
  if [[ -f "$SOLVED" ]] && [[ $(stat -c%s "$SOLVED") -gt 50000000 ]]; then
    echo "solved ready $(date)"
    break
  fi
  if ! pgrep -f "${SLUG}.*std_freq" >/dev/null 2>&1; then
    [[ -f "$SOLVED" ]] && break
    echo "ERROR: solve ended without mph"
    tail -20 "$BATCH" || true
    exit 1
  fi
  grep -o '参数 freq = [0-9]*' "$BATCH" 2>/dev/null | tail -1 || echo "starting..."
  sleep 60
done

{
  echo "=== validation $(date) ==="
  python3 scripts/_validate_pb_top.py "$SOLVED" || true
} | tee "$VALID"
echo "=== p1 done $(date) ==="
