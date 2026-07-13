#!/bin/bash
# Monitor COMSOL job progress, memory, and mphserver RSS.
#   bash scripts/linux/watch_comsol_job.sh comsol_fig321_bcc_444
#   bash scripts/linux/watch_comsol_job.sh comsol_fig321_bcc_444 30
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SLUG="${1:?usage: watch_comsol_job.sh SLUG [interval_sec]}"
INTERVAL="${2:-30}"
JOB_DIR="$ROOT/output/comsol_jobs/$SLUG"
LOG="$ROOT/output/logs/${SLUG}_comsol_pipeline.log"
BATCH_LOG="$JOB_DIR/${SLUG}_batch.log"
BUILD_LOG="$ROOT/output/logs/${SLUG}_build.log"

echo "Watching slug=$SLUG  interval=${INTERVAL}s"
echo "  job_dir: $JOB_DIR"
echo "  pipeline log: $LOG"
echo "Ctrl+C to stop watching (does not stop COMSOL)"
echo "------------------------------------------------------------"

while true; do
  echo ""
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="

  free -h | awk 'NR==1 || NR==2 {print}'

  ps aux | grep -E '[m]phserver|[c]omsol batch|[c]omsol_run_hu_bai' | while read -r line; do
    pid=$(echo "$line" | awk '{print $2}')
    rss_kb=$(echo "$line" | awk '{print $6}')
    cpu=$(echo "$line" | awk '{print $3}')
    rss_gb=$(awk -v r="$rss_kb" 'BEGIN{printf "%.2f", r/1024/1024}')
    cmd=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf $i" "; print ""}')
    echo "  PID=$pid  RSS=${rss_gb}GB  CPU=${cpu}%  $cmd"
  done

  if [[ -d "$JOB_DIR" ]]; then
    ls -lh "$JOB_DIR"/*.mph 2>/dev/null | awk '{print "  " $0}' || echo "  (no .mph yet)"
  fi

  for f in "$BATCH_LOG" "$BUILD_LOG" "$LOG"; do
    if [[ -f "$f" ]]; then
      echo "  --- tail $(basename "$f") ---"
      tail -n 4 "$f" | sed 's/^/    /'
    fi
  done

  if [[ -f "$BATCH_LOG" ]]; then
    grep -E '当前进度|自由度|DOF|100 %|完成|Error|Exception' "$BATCH_LOG" 2>/dev/null | tail -n 3 | sed 's/^/    [batch] /' || true
  fi

  if [[ -f "$JOB_DIR/${SLUG}_solved.mph" ]]; then
    echo "  *** SOLVED: $JOB_DIR/${SLUG}_solved.mph ***"
    break
  fi

  sleep "$INTERVAL"
done
