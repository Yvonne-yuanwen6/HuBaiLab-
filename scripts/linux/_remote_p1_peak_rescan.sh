#!/usr/bin/env bash
# Phase 1 peak rescan: 40–70 Hz @ 2 Hz step (50 Hz resonance region).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

SRC_SLUG="comsol_fig321_bcc_444_mesh_p1"
SLUG="comsol_fig321_bcc_444_mesh_p1_peak"
SRC_JOB="output/comsol_jobs/${SRC_SLUG}"
JOB="output/comsol_jobs/${SLUG}"
SRC_MPH="${SRC_JOB}/${SRC_SLUG}.mph"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"
BATCH="${JOB}/${SLUG}_batch.log"
LOG="output/logs/${SLUG}_rescan.log"

FREQ_MIN="${FREQ_MIN:-40}"
FREQ_MAX="${FREQ_MAX:-70}"
FREQ_STEP="${FREQ_STEP:-2}"
NP="${NP:-32}"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== p1 peak rescan ${FREQ_MIN}-${FREQ_MAX} step=${FREQ_STEP} $(date) ==="

[[ -f "$SRC_MPH" ]] || { echo "ERROR: missing $SRC_MPH"; exit 1; }
cp -f "$SRC_MPH" "$MPH"

python3 scripts/_patch_freq_plist.py "$MPH" \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"

rm -f "$SOLVED" "${SOLVED}.recovery" "$BATCH"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$SLUG" \
  --interface-coupling p1_continuity \
  --freq-only --excitation-axis z --base-accel 0.98 --no-top-payload \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
  --solve-only "$MPH" --np "$NP" --background

echo "Waiting for solve..."
while true; do
  if [[ -f "$SOLVED" ]] && [[ $(stat -c%s "$SOLVED" 2>/dev/null || echo 0) -gt 30000000 ]]; then
    echo "solved ready $(date)"
    break
  fi
  if ! pgrep -f "${SLUG}.*std_freq" >/dev/null 2>&1; then
    [[ -f "$SOLVED" ]] && break
    echo "ERROR: solve failed"
    tail -20 "$BATCH" || true
    exit 1
  fi
  grep -o '参数 freq = [0-9]*' "$BATCH" 2>/dev/null | tail -1 || echo "starting..."
  sleep 45
done

python3 scripts/_validate_pb_top.py "$SOLVED" "$COMSOL_BIN" | tee "${JOB}/${SLUG}_validation.txt"

bash scripts/linux/_remote_postprocess_slug.sh "$SLUG"

echo "=== peak rescan done $(date) ==="
ls -lh "$JOB"/*.{csv,png} 2>/dev/null || true
