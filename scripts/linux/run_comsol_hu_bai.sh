#!/usr/bin/env bash
# Hu & Bai COMSOL vibration isolation: eigen + frequency transmissibility from STEP.
#   bash scripts/linux/run_comsol_hu_bai.sh --Q 0 --cells 1 --nz 1 --eigen-only --build-only
#   bash scripts/linux/run_comsol_hu_bai.sh --Q 0 --cells 4 --background
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

ARGS=(python3 scripts/comsol_run_hu_bai.py --comsol-bin "$COMSOL_BIN")
BACKGROUND=0
SLUG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --background) BACKGROUND=1; ARGS+=(--background); shift ;;
    --build-only) ARGS+=(--build-only); shift ;;
    --solve-only) ARGS+=(--solve-only "$2"); shift 2 ;;
    --manifest-only) ARGS+=(--manifest-only); shift ;;
    --in-process) ARGS+=(--in-process); shift ;;
    --eigen-only) ARGS+=(--eigen-only); shift ;;
    --freq-only) ARGS+=(--freq-only); shift ;;
    --no-top-payload) ARGS+=(--no-top-payload); shift ;;
    --slug) SLUG="$2"; ARGS+=(--slug "$2"); shift 2 ;;
    --Q) ARGS+=(--Q "$2"); shift 2 ;;
    --cells) ARGS+=(--cells "$2"); shift 2 ;;
    --nz) ARGS+=(--nz "$2"); shift 2 ;;
    --cad) ARGS+=(--cad "$2"); shift 2 ;;
    --mesh-mm) ARGS+=(--mesh-mm "$2"); shift 2 ;;
    --n-modes) ARGS+=(--n-modes "$2"); shift 2 ;;
    --freq-min) ARGS+=(--freq-min "$2"); shift 2 ;;
    --freq-max) ARGS+=(--freq-max "$2"); shift 2 ;;
    --freq-step) ARGS+=(--freq-step "$2"); shift 2 ;;
    --base-accel) ARGS+=(--base-accel "$2"); shift 2 ;;
    --base-disp-mm) ARGS+=(--base-disp-mm "$2"); shift 2 ;;
    --excitation-axis) ARGS+=(--excitation-axis "$2"); shift 2 ;;
    --no-fig28) ARGS+=(--no-fig28); shift ;;
    --fig28) shift ;;
    --np) ARGS+=(--np "$2"); shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: run_comsol_hu_bai.sh [--Q 0|0.5|1|1.5] [--cells N] [--cad STEP]
                            [--eigen-only] [--freq-only] [--no-fig28] [--build-only] [--background]

COMSOL §2.4.3 vibration isolation (default: shaker table + Al plate + TPU lattice).
--no-fig28: lattice-only simplified model. --base-accel 0.98 (default per thesis).
Requires: pip install mph "jpype1<1.6"
EOF
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

LOG_SLUG="${SLUG:-comsol_iso}"
LOG="output/logs/${LOG_SLUG}_comsol_pipeline.log"
echo "=== COMSOL isolation $(date) ===" | tee -a "$LOG"

if [[ $BACKGROUND -eq 1 ]]; then
  nohup "${ARGS[@]}" >> "$LOG" 2>&1 &
  echo "Submitted background PID=$!"
  echo "Log: $LOG"
else
  "${ARGS[@]}" 2>&1 | tee -a "$LOG"
fi
