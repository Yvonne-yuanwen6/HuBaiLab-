#!/usr/bin/env bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
for slug in q05_c10_s06r3_el_s45 q05_c10_s05r4_el_s80 q05_c10m_s06r3_el_s45 q05_c10m_s06r3_el_s75 q05_c10m_s06r3_el_s75_cont q05_c10m_s05r4_el_s78; do
  sta="output/jobs/${slug}/${slug}.sta"
  echo "=== ${slug} ==="
  if [[ -f "$sta" ]]; then
    stat -c '%y %n' "$sta" | head -1
    grep -m1 'DATE' "$sta" || true
    grep -E 'COMPLETED SUCCESSFULLY|NOT BEEN COMPLETED|excessively distorted|SIGTERM' "$sta" | tail -1 || true
    tail -1 "$sta" | tr -s ' ' | cut -c1-90
  else
    echo "no sta"
  fi
  for f in output/post/${slug}/*.csv; do
    [[ -f "$f" ]] || continue
    echo "  $(basename "$f"): $(wc -l < "$f") lines peak=$(awk -F, 'NR>1{if($2+0>m)m=$2+0} END{printf "%.4f", m+0}' "$f") MPa"
  done
done
