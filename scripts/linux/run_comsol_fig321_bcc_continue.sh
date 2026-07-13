#!/bin/bash
# Continue BCC 4x4x4 after fixture template exists (build + eigen solve + extract).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"

SLUG="comsol_fig321_bcc_444"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
PIPE_LOG="output/logs/${SLUG}_comsol_pipeline.log"
BUILD_LOG="output/logs/${SLUG}_build.log"

mkdir -p output/logs output/comsol_jobs

echo "=== continue ${SLUG} $(date) ===" | tee -a "$PIPE_LOG"

echo "--- build ---" | tee -a "$PIPE_LOG"
python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --eigen-only --excitation-axis z \
  --no-top-payload \
  --np 4 --build-only \
  2>&1 | tee "$BUILD_LOG"

echo "--- eigen solve ---" | tee -a "$PIPE_LOG"
SOLVED="output/comsol_jobs/${SLUG}/${SLUG}_solved.mph"
UNSolved="output/comsol_jobs/${SLUG}/${SLUG}.mph"
BATCH_LOG="output/comsol_jobs/${SLUG}/${SLUG}_batch.log"
rm -f "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status" "$BATCH_LOG"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --eigen-only --excitation-axis z \
  --no-top-payload \
  --solve-only "$UNSolved" \
  --np 8 --background \
  2>&1 | tee -a "$PIPE_LOG"

echo "Waiting for fresh $SOLVED (newer than build) ..." | tee -a "$PIPE_LOG"
for _ in $(seq 1 720); do
  if grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG" 2>/dev/null; then
    echo "ERROR: COMSOL batch failed — see $BATCH_LOG" | tee -a "$PIPE_LOG"
    exit 1
  fi
  if [[ -f "$SOLVED" && -f "$UNSolved" && "$SOLVED" -nt "$UNSolved" ]]; then
    if grep -qE '当前进度: 100 % - 完成|总时间:' "$BATCH_LOG" 2>/dev/null \
      && ! grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG" 2>/dev/null; then
      break
    fi
  fi
  sleep 60
done

if [[ -f "$SOLVED" ]]; then
  echo "--- extract ---" | tee -a "$PIPE_LOG"
  python3 scripts/comsol_extract_isolation.py "$SOLVED" 2>&1 | tee -a "$PIPE_LOG"
  echo "--- mode shape PNG (120s cap; use GUI locally if headless hangs) ---" | tee -a "$PIPE_LOG"
  timeout 120 python3 scripts/comsol_export_eigen_modes.py "$SOLVED" --modes 3 \
    2>&1 | tee -a "$PIPE_LOG" || echo "WARN: PNG export skipped/timed out" | tee -a "$PIPE_LOG"
  python3 scripts/compare_fig321_eigen_vs_paper.py 2>&1 | tee -a "$PIPE_LOG"
  echo "=== done $(date) ===" | tee -a "$PIPE_LOG"
else
  echo "ERROR: solve timeout: $SOLVED" | tee -a "$PIPE_LOG"
  exit 1
fi
