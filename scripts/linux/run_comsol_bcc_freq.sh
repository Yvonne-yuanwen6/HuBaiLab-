#!/bin/bash
# BCC 4×4×4 frequency-domain study: build → harmonic solve → VLD curve.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"

SLUG="comsol_fig321_bcc_444_freq"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
PIPE_LOG="output/logs/${SLUG}_pipeline.log"
BUILD_LOG="output/logs/${SLUG}_build.log"
JOB="output/comsol_jobs/${SLUG}"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"

mkdir -p output/logs output/comsol_jobs

echo "=== freq pipeline ${SLUG} $(date) ===" | tee "$PIPE_LOG"

echo "--- build (freq-only, no payload, Z excitation) ---" | tee -a "$PIPE_LOG"
rm -f "$MPH" "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status"
python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --np 4 --build-only \
  2>&1 | tee "$BUILD_LOG"

echo "--- harmonic batch solve ---" | tee -a "$PIPE_LOG"
BATCH_LOG="${JOB}/${SLUG}_batch.log"
rm -f "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status" "$BATCH_LOG"
python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$SLUG" \
  --freq-only --excitation-axis z \
  --no-top-payload \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --solve-only "$MPH" \
  --np 8 --background \
  2>&1 | tee -a "$PIPE_LOG"

echo "Waiting for $SOLVED ..." | tee -a "$PIPE_LOG"
for _ in $(seq 1 720); do
  if [[ -f "$BATCH_LOG" ]] && grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG"; then
    echo "ERROR: COMSOL batch failed — see $BATCH_LOG" | tee -a "$PIPE_LOG"
    exit 1
  fi
  if [[ -f "$SOLVED" && -f "$MPH" && "$SOLVED" -nt "$MPH" ]]; then
    if [[ -f "$BATCH_LOG" ]] && grep -qE '当前进度: 100 % - 完成|总时间:' "$BATCH_LOG"; then
      if ! grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG"; then
        break
      fi
    fi
  fi
  sleep 60
done

if [[ ! -f "$SOLVED" ]]; then
  echo "ERROR: freq solve timeout: $SOLVED" | tee -a "$PIPE_LOG"
  exit 1
fi

echo "--- extract + VLD plot + harmonic plot groups ---" | tee -a "$PIPE_LOG"
bash scripts/linux/_remote_postprocess_slug.sh "$SLUG" 2>&1 | tee -a "$PIPE_LOG"
python3 scripts/compare_table33_vs_paper.py --key bcc 2>&1 | tee -a "$PIPE_LOG" || true

echo "=== done $(date) ===" | tee -a "$PIPE_LOG"
ls -lh "$JOB"/*.csv "$JOB"/*.png 2>/dev/null | tee -a "$PIPE_LOG"
