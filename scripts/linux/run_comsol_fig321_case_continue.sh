#!/bin/bash
# Build + eigen + extract for one Fig.3.21 case (Marlow mat, no payload, physics mesh).
# Usage: bash scripts/linux/run_comsol_fig321_case_continue.sh Q SLUG CAD_REL_PATH
set -euo pipefail

Q="${1:?Q required}"
SLUG="${2:?slug required}"
CAD="${3:?cad path required}"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"

PIPE_LOG="output/logs/${SLUG}_comsol_pipeline.log"
BUILD_LOG="output/logs/${SLUG}_build.log"
SOLVED="output/comsol_jobs/${SLUG}/${SLUG}_solved.mph"
UNSolved="output/comsol_jobs/${SLUG}/${SLUG}.mph"
BATCH_LOG="output/comsol_jobs/${SLUG}/${SLUG}_batch.log"

mkdir -p output/logs output/comsol_jobs

echo "=== continue ${SLUG} Q=${Q} $(date) ===" | tee -a "$PIPE_LOG"

echo "--- build ---" | tee -a "$PIPE_LOG"
python3 scripts/comsol_run_hu_bai.py \
  --Q "$Q" --cells 4 --cad "$CAD" --slug "$SLUG" \
  --eigen-only --excitation-axis z \
  --no-top-payload \
  --np 4 --build-only \
  2>&1 | tee "$BUILD_LOG"

echo "--- eigen solve ---" | tee -a "$PIPE_LOG"
rm -f "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status" "$BATCH_LOG"

python3 scripts/comsol_run_hu_bai.py \
  --Q "$Q" --cells 4 --cad "$CAD" --slug "$SLUG" \
  --eigen-only --excitation-axis z \
  --no-top-payload \
  --solve-only "$UNSolved" \
  --np 8 --background \
  2>&1 | tee -a "$PIPE_LOG"

echo "Waiting for fresh $SOLVED ..." | tee -a "$PIPE_LOG"
for _ in $(seq 1 720); do
  if grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG" 2>/dev/null; then
    echo "ERROR: COMSOL batch failed — see $BATCH_LOG" | tee -a "$PIPE_LOG"
    exit 1
  fi
  if [[ -f "$SOLVED" && -f "$UNSolved" && "$SOLVED" -nt "$UNSolved" ]]; then
    if grep -q '当前进度: 100 % - 完成' "$BATCH_LOG" 2>/dev/null; then
      break
    fi
  fi
  sleep 60
done

if [[ ! -f "$SOLVED" ]]; then
  echo "ERROR: solve timeout: $SOLVED" | tee -a "$PIPE_LOG"
  exit 1
fi

echo "--- extract ---" | tee -a "$PIPE_LOG"
python3 scripts/comsol_extract_isolation.py "$SOLVED" 2>&1 | tee -a "$PIPE_LOG"
echo "--- mode shape PNG (120s cap) ---" | tee -a "$PIPE_LOG"
timeout 120 python3 scripts/comsol_export_eigen_modes.py "$SOLVED" --modes 3 --min-hz 1.0 \
  2>&1 | tee -a "$PIPE_LOG" || echo "WARN: PNG export skipped/timed out" | tee -a "$PIPE_LOG"
echo "=== done ${SLUG} $(date) ===" | tee -a "$PIPE_LOG"
