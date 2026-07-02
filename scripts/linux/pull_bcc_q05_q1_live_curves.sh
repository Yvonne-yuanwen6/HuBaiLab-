#!/usr/bin/env bash
# readOnly live extract: BCC baseline (full) + Q0.5 nosettle + Q1 settle5p
set -euo pipefail
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"

BCC=hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox
Q05=hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle
Q1=hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p

for slug in "$BCC" "$Q05" "$Q1"; do
  mkdir -p "output/post/$slug"
done

echo "=== BCC baseline (completed, full curve) ==="
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$BCC/$BCC.odb" \
  "output/export/$BCC/${BCC}_meta.json" \
  "output/post/$BCC/${BCC}_stress_strain.csv"

echo "=== Q0.5 nosettle live ==="
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$Q05/$Q05.odb" \
  "output/export/$Q05/${Q05}_meta.json" \
  "output/post/$Q05/${Q05}_stress_strain_live.csv"

echo "=== Q1 settle5p live ==="
abq python scripts/extract_live_odb_server_py2.py \
  "output/jobs/$Q1/$Q1.odb" \
  "output/export/$Q1/${Q1}_meta.json" \
  "output/post/$Q1/${Q1}_stress_strain_live.csv"

for slug in "$Q05" "$Q1"; do
  if test -f "output/jobs/$slug/$slug.lck"; then
    echo "JOB_STILL_RUNNING $slug"
  fi
done
