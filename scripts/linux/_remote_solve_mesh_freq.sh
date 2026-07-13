#!/usr/bin/env bash
# Harmonic sweep on meshed Fig2.8 BCC mph (10–300 Hz; FREQ_STEP env, default 2 Hz).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

SLUG="comsol_fig321_bcc_444_mesh"
JOB="output/comsol_jobs/${SLUG}"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"
PIPE_LOG="output/logs/${SLUG}_freq_solve.log"
BATCH_LOG="${JOB}/${SLUG}_batch.log"
FREQ_MIN="${FREQ_MIN:-10}"
FREQ_MAX="${FREQ_MAX:-300}"
FREQ_STEP="${FREQ_STEP:-2}"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$PIPE_LOG") 2>&1
echo "=== freq solve ${SLUG} $(date) step=${FREQ_STEP}Hz ==="

if [[ ! -f "$MPH" ]]; then
  echo "ERROR: missing $MPH — run _remote_build_mesh_only.sh first"
  exit 1
fi

python3 scripts/_patch_freq_plist.py "$MPH" \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"

rm -f "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status" "$BATCH_LOG"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$SLUG" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
  --solve-only "$MPH" \
  --np 32 --background

echo "Submitted. Monitor: $BATCH_LOG"
echo "When done: $SOLVED"
