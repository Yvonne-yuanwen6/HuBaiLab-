#!/usr/bin/env bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
for slug in q05_c10_s06r3_el_s45 q05_c10_s05r4_el_s80 q05_c10m_s06r3_el_s45 q05_c10m_s06r3_el_s75 q05_c10m_s06r3_el_s75_cont q05_c10m_s05r4_el_s78; do
  sta="output/jobs/${slug}/${slug}.sta"
  csv="output/post/${slug}/${slug}_stress_strain.csv"
  partial="output/post/${slug}/${slug}_stress_strain_partial.csv"
  status=pending
  if [[ -f "$sta" ]] && grep -q 'COMPLETED SUCCESSFULLY' "$sta"; then
    status=DONE
  elif [[ -f "$sta" ]]; then
    status=FAIL
  fi
  curve=none
  peak="-"
  if [[ -f "$csv" ]]; then
    curve=csv
    peak=$(awk -F, 'NR>1{if($2+0>m)m=$2+0} END{printf "%.4f", m+0}' "$csv")
  elif [[ -f "$partial" ]]; then
    curve=partial
    peak=$(awk -F, 'NR>1{if($2+0>m)m=$2+0} END{printf "%.4f", m+0}' "$partial")
  fi
  echo "$slug status=$status curve=$curve peak_MPa=$peak"
done
