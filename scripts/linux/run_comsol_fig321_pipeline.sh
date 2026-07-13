#!/usr/bin/env bash
# Build + eigen-solve + extract + mode export for thesis Fig. 3.21 (4 variants).
#   bash scripts/linux/run_comsol_fig321_pipeline.sh
#   bash scripts/linux/run_comsol_fig321_pipeline.sh --background
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export COMSOL_ROOT="${COMSOL_ROOT:-/home/art/APP/comsol56/multiphysics}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

mkdir -p output/comsol_jobs output/logs output/comsol_jobs/fig321_composite

BACKGROUND=0
NP=8
if [[ "${1:-}" == "--background" ]]; then
  BACKGROUND=1
  shift
fi

LOG="output/logs/fig321_pipeline.log"

run_pipeline() {
  echo "=== Fig.3.21 pipeline $(date) ===" | tee -a "$LOG"

  # Q:slug:cad_basename (under output/cad/verified/)
  CASES=(
    "0:comsol_fig321_bcc_444:hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array"
    "0.5:comsol_fig321_af2q05_444:hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array"
    "1:comsol_fig321_af2q1_444:hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array"
    "1.5:comsol_fig321_af2q15_444:hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array"
  )

  for entry in "${CASES[@]}"; do
    IFS=: read -r Q SLUG CAD <<< "$entry"
    CAD_PATH="output/cad/verified/${CAD}.step"
    echo "--- Case Q=$Q slug=$SLUG ---" | tee -a "$LOG"

    python3 scripts/comsol_run_hu_bai.py \
      --Q "$Q" --cells 4 --eigen-only --excitation-axis z \
      --slug "$SLUG" --cad "$CAD_PATH" --np "$NP" \
      2>&1 | tee -a "$LOG"

    SOLVED="output/comsol_jobs/${SLUG}/${SLUG}_solved.mph"
    if [[ ! -f "$SOLVED" ]]; then
      echo "ERROR: missing $SOLVED" | tee -a "$LOG"
      continue
    fi

    python3 scripts/comsol_extract_isolation.py "$SOLVED" 2>&1 | tee -a "$LOG"
    python3 scripts/comsol_export_eigen_modes.py "$SOLVED" --modes 3 --min-hz 1.0 2>&1 | tee -a "$LOG"
  done

  python3 scripts/plot_comsol_fig321.py \
    --out output/comsol_jobs/fig321_composite/fig321_eigenmodes.png \
    2>&1 | tee -a "$LOG"

  echo "=== Fig.3.21 pipeline done $(date) ===" | tee -a "$LOG"
}

if [[ $BACKGROUND -eq 1 ]]; then
  nohup bash "$0" >> "$LOG" 2>&1 &
  echo "Submitted background PID=$!"
  echo "Log: $LOG"
else
  run_pipeline
fi
