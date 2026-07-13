#!/usr/bin/env bash
# Build mesh mph with plan-B bonded contact (plate–lattice); NO solve — GUI review first.
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
LOG="output/logs/${SLUG}_build_contact.log"
JOB="output/comsol_jobs/${SLUG}"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== plan-B contact build $(date) ==="
echo "Bonded: cp_plt_lat + Contact/Adhesion; ap2 identity removed."
echo "STOP after build — review mph in GUI before solve."

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --physics-controlled-mesh \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --np 1 --build-only || {
  if [[ -f "${JOB}/${SLUG}.mph" ]] && grep -q "Contact pair cp_plt_lat" "$LOG"; then
    echo "WARN: build exited nonzero but mph + contact markers present"
  else
    exit 1
  fi
}

echo "=== build done $(date) ==="
ls -lh "${JOB}/${SLUG}.mph" "${JOB}/case_manifest.json"
echo ""
echo "GUI review checklist:"
echo "  1. 定义 → 一致边界对 ap1 (台–点阵) 仍在"
echo "  2. 定义 → 接触对 cp_plt_lat (板底→点阵顶)"
echo "  3. 固体力学 → 板–点阵粘结接触 (cnt_plt) + 胶接 (adh_plt)"
echo "  4. 派生值: 体最大值 w @ 域2 或 预解 10Hz — 应非 0"
echo "Open: ${JOB}/${SLUG}.mph"
