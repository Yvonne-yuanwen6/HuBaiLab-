#!/usr/bin/env bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
for q in 0 0.5 1 1.5; do
  slug=$(python3 -c "
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
q=float('$q')
tag=G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=q).variant_name.lower()
print(f'hu_bai_{tag}_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow')
")
  sta="output/jobs/${slug}/${slug}.sta"
  if [[ -f "$sta" ]]; then
    status=$(grep -q 'COMPLETED SUCCESSFULLY' "$sta" && echo DONE || echo FAIL)
    echo "Q=$q $status"
  else
    echo "Q=$q PENDING"
  fi
done
