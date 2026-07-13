#!/usr/bin/env bash
# Rebuild BCC freq mph: Fig.2.8 explicit layered mesh + Displacement2 excitation (build-only).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

SLUG="comsol_fig321_bcc_444_freq"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
LOG="output/logs/${SLUG}_rebuild_layered_mesh.log"
JOB="output/comsol_jobs/${SLUG}"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== rebuild layered mesh $(date) ==="
echo "Mesh: explicit hmax lattice=0.6 table=40 plate=8 contact=8mm (NOT physics-controlled hauto)"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --mesh-mm 0.6 \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --np 4 --build-only

echo "=== done $(date) ==="
ls -lh "${JOB}/${SLUG}.mph" "${JOB}/case_manifest.json"
