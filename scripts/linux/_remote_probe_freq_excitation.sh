#!/usr/bin/env bash
# Build BCC freq mph with BodyLoad excitation, quick-solve, write probe JSON.
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
LOG="output/logs/${SLUG}_excitation_probe.log"
JOB="output/comsol_jobs/${SLUG}"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== excitation probe $(date) ==="

python3 scripts/probe_freq_excitation.py \
  --build --solve --slug "$SLUG" --cad "$CAD" \
  --plist "10,30,68" \
  --out-json "${JOB}/${SLUG}_excitation_probe.json"

echo "=== done $(date) ==="
