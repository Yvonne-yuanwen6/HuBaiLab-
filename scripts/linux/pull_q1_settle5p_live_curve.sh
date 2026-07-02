#!/usr/bin/env bash
# readOnly live extract: Q1 settle5p + baseline partial at same sim time
set -euo pipefail
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"
Q1=hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p
BASE=hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox
SIMT=$(grep -E '^[[:space:]]+[0-9]+' "output/jobs/$Q1/$Q1.sta" | tail -1 | awk '{print $3}')
echo "SIM_TIME=$SIMT"
mkdir -p "output/post/$Q1" "output/post/$BASE"
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$Q1/$Q1.odb" \
  "output/export/$Q1/${Q1}_meta.json" \
  "output/post/$Q1/${Q1}_stress_strain_live.csv"
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$BASE/$BASE.odb" \
  "output/export/$BASE/${BASE}_meta.json" \
  "output/post/$BASE/${BASE}_stress_strain_partial.csv" \
  "$SIMT"
if test -f "output/jobs/$Q1/$Q1.lck"; then
  echo JOB_STILL_RUNNING
fi
