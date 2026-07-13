#!/usr/bin/env bash
set -uo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"
export PYTHONPATH="$ROOT"

SUFFIX="fig33_v2_marlow"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"

slug_for_q() {
  python3 -c "
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
q=float('$1')
suffix='$SUFFIX'
base='cae_tet0p6mm80_5mmin_paperbox'
tag=G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=q).variant_name.lower()
print(f'hu_bai_{tag}_L20_4x4x4_solid_cad_f_{base}_{suffix}')
"
}

lattice_slug_for_q() {
  python3 -c "
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
q=float('$1')
tag=G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=q).variant_name.lower()
print(f'hu_bai_{tag}_L20_4x4x4')
"
}

echo "=== fig33_v2_marlow serial preflight ==="
pgrep -af 'run_fig33_v2_marlow_serial' | grep -v pgrep || echo "serial script: not running"
pgrep -af 'fig33_v2_marlow' | grep -E 'SMAPython|/bin/explicit' | grep -v pgrep || echo "marlow abaqus: none"

echo
echo "=== prerequisites ==="
[[ -f "$FIG25" ]] && echo "fig25 json: OK" || echo "fig25 json: MISSING"
[[ -f scripts/linux/run_fig33_v2_marlow_serial.sh ]] && echo "serial script on server: OK" || echo "serial script on server: MISSING"

echo
echo "=== four structures Q=1.5,0.5,1,0 ==="
for q in 1.5 0.5 1 0; do
  slug=$(slug_for_q "$q")
  lat=$(lattice_slug_for_q "$q")
  cad="output/cad/verified/${lat}_paper_box_array.step"
  base="output/export/${lat}_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/${lat}_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"
  sta="output/jobs/${slug}/${slug}.sta"
  csv="output/post/${slug}/${slug}_stress_strain.csv"
  lck="output/jobs/${slug}/${slug}.lck"
  st="pending"
  [[ -f "$sta" ]] && grep -q 'COMPLETED SUCCESSFULLY' "$sta" && st="COMPLETED"
  [[ -f "$lck" ]] && st="RUNNING"
  pgrep -f "$slug" >/dev/null 2>&1 && st="RUNNING"
  echo "Q=$q status=$st cad=$([[ -f $cad ]] && echo OK || echo MISSING) mesh=$([[ -f $base ]] && echo OK || echo MISSING) csv=$([[ -f $csv ]] && echo yes || echo no)"
  echo "  slug=$slug"
done

echo
echo "=== competing jobs ==="
pgrep -af 'run_hu_bai_paper_box|comsol|paperbox_q05_fig33_improve_supervise' | grep -v pgrep | head -6 || echo "(none notable)"
