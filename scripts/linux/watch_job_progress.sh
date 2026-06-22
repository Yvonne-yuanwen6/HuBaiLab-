#!/usr/bin/env bash
# Lightweight .sta watcher for Linux (similar to watch_job_progress.ps1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SLUG=""
POLL=30
STEP_TIME=0
TARGET_STRAIN=0.8

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --poll) POLL="$2"; shift 2 ;;
    --step-time) STEP_TIME="$2"; shift 2 ;;
    --target-strain) TARGET_STRAIN="$2"; shift 2 ;;
    -h|--help) exit 0 ;;
    *) shift ;;
  esac
done

[[ -n "$SLUG" ]] || { echo "Need --slug"; exit 1; }

STA="$ROOT/output/jobs/$SLUG/${SLUG}.sta"
ODB="$ROOT/output/jobs/$SLUG/${SLUG}.odb"
LCK="$ROOT/output/jobs/$SLUG/${SLUG}.lck"
META="$ROOT/output/export/$SLUG/${SLUG}_meta.json"

if [[ $STEP_TIME -le 0 && -f "$META" ]]; then
  STEP_TIME="$(python3 -c "import json; m=json.load(open('$META')); print(m.get('step_time',0) or 0)" 2>/dev/null || echo 0)"
fi
[[ "$STEP_TIME" == 0 ]] && STEP_TIME=480

status() {
  if [[ -f "$STA" && -f "$ODB" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$STA"; then
    echo COMPLETED
  elif [[ -f "$LCK" ]]; then
    echo RUNNING
  elif [[ -f "$STA" ]]; then
    echo STOPPED
  else
    echo WAITING
  fi
}

echo "=== watch $SLUG (poll=${POLL}s step=${STEP_TIME}s) ==="
echo "sta: $STA"
echo ""

while true; do
  st="$(status)"
  now="$(date +%H:%M:%S)"
  sim_s=0
  if [[ -f "$STA" ]]; then
    line="$(grep -E '^[[:space:]]+[0-9]+[[:space:]]+' "$STA" | tail -1 || true)"
    if [[ -n "$line" ]]; then
      sim_s="$(echo "$line" | awk '{print $3}')"
    fi
  fi
  pct=0
  if [[ -n "$sim_s" && "$STEP_TIME" != 0 ]]; then
    pct="$(python3 -c "print(min(100, 100*float('$sim_s')/float('$STEP_TIME')))")"
  fi
  strain="$(python3 -c "print(float('$TARGET_STRAIN')*float('$sim_s')/float('$STEP_TIME')*100)")"
  printf '[%s] %s  sim %.1f/%.0f s  ~%.1f%% strain  progress %.1f%%\n' "$now" "$st" "$sim_s" "$STEP_TIME" "$strain" "$pct"
  if [[ "$st" == COMPLETED || "$st" == STOPPED ]]; then break
  fi
  sleep "$POLL"
done
