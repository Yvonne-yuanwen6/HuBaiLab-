#!/bin/bash
# Poll fig321 SFBLS batch until done.
LOG="${1:-output/logs/fig321_sfbls_batch.log}"
for i in $(seq 1 40); do
  echo "=== poll $i $(date +%H:%M:%S) ==="
  grep -E 'start comsol|done comsol|ERROR|batch done' "$LOG" 2>/dev/null | tail -5
  pgrep -af 'comsol batch.*fig321' | head -1 || echo "no eigen batch"
  pgrep -af 'comsol_run_hu_bai.py.*fig321' | head -1 || true
  if grep -q 'fig321 SFBLS batch done' "$LOG" 2>/dev/null; then
    break
  fi
  sleep 120
done
echo "=== final ==="
tail -40 "$LOG"
