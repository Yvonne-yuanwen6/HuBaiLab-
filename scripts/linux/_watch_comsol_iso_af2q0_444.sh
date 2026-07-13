#!/usr/bin/env bash
# Watch COMSOL 4x4x4 eigen batch progress (refresh every 20s).
LOG="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab/output/comsol_jobs/comsol_iso_af2q0_444/comsol_iso_af2q0_444_batch.log"
DIR="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab/output/comsol_jobs/comsol_iso_af2q0_444"

while pgrep -f 'comsol_iso_af2q0_444.*batch' >/dev/null 2>&1; do
  echo ""
  echo "========== $(date '+%H:%M:%S')  comsol_iso_af2q0_444  =========="
  grep -E '自由度|当前进度|   [0-9]|Nconv|错误|总时间|100 %' "$LOG" | tail -8
  ls -lh "$DIR"/*solved*.mph 2>/dev/null || echo "  (no solved.mph yet)"
  echo "  STATUS: RUNNING  |  refresh every 20s  |  Ctrl+C to stop watch"
  sleep 20
done

echo ""
echo "========== FINISHED $(date '+%H:%M:%S') =========="
grep -E '自由度|   [0-9]|错误|总时间|100 %|完成' "$LOG" | tail -15
ls -lh "$DIR"/
tail -8 "$DIR/run.log" 2>/dev/null
