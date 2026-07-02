#!/usr/bin/env bash
# Daily progress digest (run via cron ~08:00).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

REPORT="output/logs/paperbox_morning_report.txt"
STATE="output/logs/paperbox_orchestrator_state.json"
ORCH_LOG="output/logs/paperbox_orchestrator.log"

{
  echo "=============================================="
  echo " HuBaiLab paperbox — morning report"
  echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "=============================================="
  echo

  if [[ -f "$STATE" ]]; then
    echo "--- orchestrator state ---"
    python3 -c "
import json
s=json.load(open('$STATE'))
print('phase:', s.get('phase'))
w=s.get('winner')
if w:
    print('winner:', w.get('slug'), 'variant=', w.get('variant'))
    ev=w.get('eval',{})
    print('  peak MPa:', ev.get('peak_stress_MPa'))
    print('  snap:', ev.get('has_snapthrough'))
    print('  ranking:', ev.get('ranking',{}).get('ranking_ok'))
else:
    print('winner: (not yet)')
"
    echo
  fi

  echo "--- running ---"
  n=0
  while IFS= read -r lck; do
    slug=$(basename "$(dirname "$lck")")
    line=$(grep -E '^[[:space:]]+[0-9]+' "output/jobs/$slug/$slug.sta" 2>/dev/null | tail -1 || true)
    echo "  $slug"
    echo "    $line"
    n=$((n + 1))
  done < <(find output/jobs -name '*.lck' 2>/dev/null | grep paperbox || true)
  [[ "$n" -eq 0 ]] && echo "  (none)"

  echo
  echo "--- completed (paperbox) ---"
  find output/jobs -name '*.sta' 2>/dev/null | grep paperbox | while read -r sta; do
    grep -q 'COMPLETED SUCCESSFULLY' "$sta" || continue
    echo "  $(basename "$(dirname "$sta")")"
  done

  echo
  echo "--- system ---"
  uptime
  echo "  explicit ranks: $(pgrep -c -f '/code/bin/explicit' 2>/dev/null || echo 0)"
  echo
  echo "--- orchestrator log (last 15 lines) ---"
  tail -15 "$ORCH_LOG" 2>/dev/null || echo "(no log yet)"
  echo
  echo "Full snapshot: output/logs/paperbox_progress_snapshot.txt"
} | tee "$REPORT"
