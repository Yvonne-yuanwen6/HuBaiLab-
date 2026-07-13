#!/usr/bin/env bash
# Step 2: three-part split mesh (table hauto → plate thin → lattice hauto).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

SLUG="comsol_fig321_bcc_444_mesh"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
LOG="output/logs/${SLUG}_build.log"
JOB="output/comsol_jobs/${SLUG}"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== mesh build $(date) ==="
echo "Table hauto=5; plate thin explicit; lattice hauto=4."

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --physics-controlled-mesh \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --np 1 --build-only

echo "=== done $(date) ==="
ls -lh "${JOB}/${SLUG}.mph" "${JOB}/case_manifest.json"
echo "Open in COMSOL GUI: ${JOB}/${SLUG}.mph"
