#!/usr/bin/env bash
# Rebuild mesh mph (with plate bonding fix) then submit harmonic sweep.
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
BUILD_LOG="output/logs/${SLUG}_build.log"
PIPE_LOG="output/logs/${SLUG}_freq_solve.log"
CHAIN_LOG="output/logs/${SLUG}_rebuild_solve_chain.log"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$CHAIN_LOG") 2>&1
echo "=== rebuild+solve chain $(date) ==="

echo "--- phase 1: mesh build ---"
BUILD_MARK="output/logs/${SLUG}_build_ok.stamp"
rm -f "$BUILD_MARK"
bash scripts/linux/_remote_build_mesh_only.sh 2>&1 | tee -a "$BUILD_LOG" || {
  # MPh teardown sometimes segfaults after a successful save — recover if mph exists.
  if [[ -f "$MPH" ]] && grep -q "Form assembly: imprint=on" "$BUILD_LOG" && grep -q "Saved model:.*${SLUG}.mph" "$BUILD_LOG"; then
    echo "WARN: build exited nonzero but mph saved with imprint — continuing"
  elif [[ -f "$MPH" ]]; then
    echo "ERROR: build exited nonzero; mph exists but imprint/save markers missing — aborting solve"
    exit 1
  else
    echo "ERROR: build failed and $MPH missing"
    exit 1
  fi
}

if [[ ! -f "$MPH" ]]; then
  echo "ERROR: missing $MPH after build"
  exit 1
fi
if ! grep -q "Form assembly: imprint=on" "$BUILD_LOG"; then
  echo "ERROR: build log missing imprint=on — aborting solve (plate bonding not applied)"
  exit 1
fi
touch "$BUILD_MARK"
ls -lh "$MPH" "${JOB}/case_manifest.json"

echo "--- phase 2: freq solve ---"
rm -f "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status" "${JOB}/${SLUG}_batch.log"
bash scripts/linux/_remote_solve_mesh_freq.sh 2>&1 | tee -a "$PIPE_LOG"

echo "=== chain submitted $(date) ==="
echo "Monitor solve: ${JOB}/${SLUG}_batch.log"
