#!/usr/bin/env bash
# Live progress monitor for comsol_fig321_bcc_444_mesh freq sweep.
set -euo pipefail

SLUG="${1:-comsol_fig321_bcc_444_mesh}"
ROOT="${2:-/media/art/file/XiangLang/Lattice/LWY/HuBaiLab}"
LOG="${ROOT}/output/comsol_jobs/${SLUG}/${SLUG}_batch.log"
SOLVED="${ROOT}/output/comsol_jobs/${SLUG}/${SLUG}_solved.mph"
TOTAL=146
INTERVAL="${INTERVAL:-30}"
START=$(date +%s)

echo "=== Monitor ${SLUG} (32 cores) ==="
echo "Log: $LOG"
echo "Interval: ${INTERVAL}s — Ctrl+C stops watching only"
echo ""

while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START))
  EM=$((ELAPSED / 60))
  ES=$((ELAPSED % 60))

  if [[ -f "$SOLVED" ]]; then
    echo "[$(date '+%H:%M:%S')] DONE — solved mph written"
    ls -lh "$SOLVED"
    exit 0
  fi

  FREQ_LINE=$(grep -o '参数 freq = [0-9]*' "$LOG" 2>/dev/null | tail -1 || true)
  FREQ=${FREQ_LINE#*= }
  FREQ=${FREQ// /}
  COUNT=$(grep -c '参数 freq' "$LOG" 2>/dev/null || echo 0)

  if [[ -n "$FREQ" && "$FREQ" =~ ^[0-9]+$ ]]; then
    DONE=$(( (FREQ - 10) / 2 + 1 ))
    [[ $DONE -lt 0 ]] && DONE=0
    [[ $DONE -gt $TOTAL ]] && DONE=$TOTAL
    PCT=$(( DONE * 100 / TOTAL ))
    if [[ $DONE -gt 0 ]]; then
      SEC_PER=$(( ELAPSED / DONE ))
      REM=$(( TOTAL - DONE ))
      ETA_M=$(( SEC_PER * REM / 60 ))
    else
      SEC_PER=0
      ETA_M="?"
    fi
  else
    DONE=0
    PCT=0
    SEC_PER=0
    ETA_M="?"
    FREQ="starting"
  fi

  CPU=$(ps aux | grep "${SLUG}" | grep comsollauncher | grep -v grep | awk '{print $3"%"}' | head -1)
  CPU=${CPU:-n/a}

  printf '[%s] elapsed %dm%02ds | freq %s Hz | %d/%d (%d%%) | ~%ss/pt | ETA ~%sm | CPU %s\n' \
    "$(date '+%H:%M:%S')" "$EM" "$ES" "$FREQ" "$DONE" "$TOTAL" "$PCT" "$SEC_PER" "$ETA_M" "$CPU"

  if ! pgrep -f "${SLUG}.*std_freq" >/dev/null 2>&1; then
    echo "[$(date '+%H:%M:%S')] comsol process ended"
    tail -8 "$LOG" 2>/dev/null || true
    [[ -f "$SOLVED" ]] && exit 0
    exit 1
  fi

  sleep "$INTERVAL"
done
