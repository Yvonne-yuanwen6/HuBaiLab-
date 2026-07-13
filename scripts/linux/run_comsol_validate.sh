#!/usr/bin/env bash
# Validate COMSOL build/solve/extract pipeline against official Channel Beam eigenfrequencies.
#   bash scripts/linux/run_comsol_validate.sh
#   bash scripts/linux/run_comsol_validate.sh --in-process --mesh-mm 3
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

ARGS=(python3 scripts/comsol_validate_workflow.py --comsol-bin "$COMSOL_BIN")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --in-process) ARGS+=(--in-process); shift ;;
    --mesh-mm) ARGS+=(--mesh-mm "$2"); shift 2 ;;
    --cores) ARGS+=(--cores "$2"); shift 2 ;;
    --rtol) ARGS+=(--rtol "$2"); shift 2 ;;
    -h|--help)
      echo "Usage: run_comsol_validate.sh [--in-process] [--mesh-mm N] [--cores N]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

LOG="output/logs/comsol_validate_workflow.log"
echo "=== COMSOL validate $(date) ===" | tee "$LOG"
"${ARGS[@]}" 2>&1 | tee -a "$LOG"
