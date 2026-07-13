#!/usr/bin/env bash
# Mid-band dense sweep on existing 300g P1 mph (no remesh / no payload re-patch).
# Usage: FREQ_MIN=35 FREQ_MAX=90 FREQ_STEP=2 bash scripts/linux/_remote_p1_300g_midfreq_sweep.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

SRC_SLUG="${SRC_SLUG:-comsol_fig321_bcc_444_mesh_p1_300g_f1_300}"
SLUG="${SLUG:-comsol_fig321_bcc_444_mesh_p1_300g_mid}"
SRC_MPH="output/comsol_jobs/${SRC_SLUG}/${SRC_SLUG}.mph"
JOB="output/comsol_jobs/${SLUG}"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"
BATCH="${JOB}/${SLUG}_batch.log"
LOG="output/logs/${SLUG}_sweep.log"

FREQ_MIN="${FREQ_MIN:-35}"
FREQ_MAX="${FREQ_MAX:-90}"
FREQ_STEP="${FREQ_STEP:-2}"
NP="${NP:-32}"
TOTAL=$(( (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 ))

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== 300g mid sweep ${FREQ_MIN}-${FREQ_MAX} step=${FREQ_STEP} (${TOTAL} pts) $(date) ==="

[[ -f "$SRC_MPH" ]] || { echo "ERROR: missing $SRC_MPH"; exit 1; }
cp -f "$SRC_MPH" "$MPH"

python3 scripts/_patch_freq_plist.py "$MPH" \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"

rm -f "$SOLVED" "${SOLVED}.recovery" "$BATCH"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$SLUG" \
  --interface-coupling p1_continuity \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
  --solve-only "$MPH" \
  --np "$NP" --background

echo "Waiting for solve (${TOTAL} freq points)..."
while true; do
  if [[ -f "$SOLVED" ]] && [[ $(stat -c%s "$SOLVED" 2>/dev/null || echo 0) -gt 100000000 ]]; then
    echo "solved ready $(date)"
    break
  fi
  if ! pgrep -f "${SLUG}.*std_freq" >/dev/null 2>&1; then
    [[ -f "$SOLVED" ]] && break
    echo "ERROR: solve failed"
    tail -20 "$BATCH" || true
    exit 1
  fi
  freq_line=$(grep -o '参数 freq = [0-9]*' "$BATCH" 2>/dev/null | tail -1 || true)
  freq=${freq_line#*= }
  freq=${freq// /}
  if [[ -n "$freq" && "$freq" =~ ^[0-9]+$ ]]; then
    done=$(( (freq - FREQ_MIN) / FREQ_STEP + 1 ))
    pct=$(( done * 100 / TOTAL ))
    echo "[$(date '+%H:%M:%S')] freq=${freq}Hz ${done}/${TOTAL} (${pct}%)"
  else
    echo "[$(date '+%H:%M:%S')] starting..."
  fi
  sleep 60
done

python3 scripts/_validate_pb_top.py "$SOLVED" "$COMSOL_BIN" | tee "${JOB}/${SLUG}_validation.txt"
bash scripts/linux/_remote_postprocess_slug.sh "$SLUG"

echo "=== mid sweep done $(date) ==="
ls -lh "$JOB"/*.{csv,png} 2>/dev/null || true
