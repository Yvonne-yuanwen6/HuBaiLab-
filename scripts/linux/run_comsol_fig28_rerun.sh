#!/usr/bin/env bash
# Re-run §2.4.3 BCC 4×4×4 with fixture template + linear mesh (fixed mph_builder).
#   bash scripts/linux/run_comsol_fig28_rerun.sh
#   bash scripts/linux/run_comsol_fig28_rerun.sh --background
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export COMSOL_ROOT="${COMSOL_ROOT:-/home/art/APP/comsol56/multiphysics}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

mkdir -p output/comsol_jobs output/logs

SLUG="comsol_fig321_bcc_444"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
FIXTURE="output/comsol_jobs/comsol_fixture_444/comsol_fixture_444.mph"
BUILD_LOG="output/logs/${SLUG}_build.log"
PIPE_LOG="output/logs/${SLUG}_comsol_pipeline.log"
BACKGROUND=0

if [[ "${1:-}" == "--background" ]]; then
  BACKGROUND=1
fi

run_all() {
  echo "=== COMSOL fig28 rerun $(date) ===" | tee -a "$PIPE_LOG"

  echo "--- Step 1: fixture template ---" | tee -a "$PIPE_LOG"
  python3 scripts/comsol_run_hu_bai.py \
    --Q 0 --cells 4 --build-fixture-template --np 4 \
    2>&1 | tee "output/logs/comsol_fixture_444_build.log"

  echo "--- Step 2: build full model (template + lattice mesh) ---" | tee -a "$PIPE_LOG"
  python3 scripts/comsol_run_hu_bai.py \
    --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
    --eigen-only --excitation-axis z \
    --fixture-template "$FIXTURE" \
    --np 4 --build-only \
    2>&1 | tee "$BUILD_LOG"

  echo "--- Step 3: eigen batch solve ---" | tee -a "$PIPE_LOG"
  python3 scripts/comsol_run_hu_bai.py \
    --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
    --eigen-only --excitation-axis z \
    --fixture-template "$FIXTURE" \
    --solve-only "output/comsol_jobs/${SLUG}/${SLUG}.mph" \
    --np 8 --background \
    2>&1 | tee -a "$PIPE_LOG"

  echo "--- Step 4: extract (after solve completes) ---" | tee -a "$PIPE_LOG"
  SOLVED="output/comsol_jobs/${SLUG}/${SLUG}_solved.mph"
  for _ in $(seq 1 720); do
    [[ -f "$SOLVED" ]] && break
    sleep 60
  done
  if [[ -f "$SOLVED" ]]; then
    python3 scripts/comsol_extract_isolation.py "$SOLVED" 2>&1 | tee -a "$PIPE_LOG"
    python3 scripts/comsol_export_eigen_modes.py "$SOLVED" --modes 3 --min-hz 1.0 2>&1 | tee -a "$PIPE_LOG"
  else
    echo "ERROR: solve did not finish: $SOLVED" | tee -a "$PIPE_LOG"
  fi

  echo "=== Done $(date) ===" | tee -a "$PIPE_LOG"
}

if [[ $BACKGROUND -eq 1 ]]; then
  nohup bash "$0" >> "$PIPE_LOG" 2>&1 &
  echo "Submitted background PID=$!"
  echo "Monitor: bash scripts/linux/watch_comsol_job.sh $SLUG"
else
  run_all
fi
