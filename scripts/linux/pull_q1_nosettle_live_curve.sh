#!/usr/bin/env bash
set -euo pipefail
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"
NOS=hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle
BASE=hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox
SIMT=$(grep -E '^[[:space:]]+[0-9]+' "output/jobs/$NOS/$NOS.sta" | tail -1 | awk '{print $3}')
echo "SIM_TIME=$SIMT"
mkdir -p "output/post/$NOS" "output/post/$BASE"
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$NOS/$NOS.odb" \
  "output/export/$NOS/${NOS}_meta.json" \
  "output/post/$NOS/${NOS}_stress_strain_live.csv"
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$BASE/$BASE.odb" \
  "output/export/$BASE/${BASE}_meta.json" \
  "output/post/$BASE/${BASE}_stress_strain_partial.csv" \
  "$SIMT"
if test -f "output/jobs/$NOS/$NOS.lck"; then
  echo JOB_STILL_RUNNING
fi
