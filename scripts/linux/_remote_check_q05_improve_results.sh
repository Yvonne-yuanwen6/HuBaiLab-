#!/usr/bin/env bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
BASE=hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox
for v in fig33_v2_paper fig33_v2_ep paperbox_settle5p fig33_v2_paper_dt1e4; do
  slug="${BASE}_${v}"
  csv="output/post/${slug}/${slug}_stress_strain.csv"
  partial="output/post/${slug}/${slug}_stress_strain_partial.csv"
  sta="output/jobs/${slug}/${slug}.sta"
  status=pending
  if [[ -f "$sta" ]] && grep -q 'COMPLETED SUCCESSFULLY' "$sta"; then
    status=DONE
  elif [[ -f "$sta" ]]; then
    status=FAIL
  fi
  has_csv=0
  has_partial=0
  [[ -f "$csv" ]] && has_csv=1
  [[ -f "$partial" ]] && has_partial=1
  ncsv=0
  npartial=0
  [[ -f "$csv" ]] && ncsv=$(wc -l < "$csv")
  [[ -f "$partial" ]] && npartial=$(wc -l < "$partial")
  echo "$v status=$status csv=$has_csv($ncsv lines) partial=$has_partial($npartial lines)"
done
echo "---"
cat output/logs/q05_fig33_improve_ready.json 2>/dev/null || echo "no ready json"
