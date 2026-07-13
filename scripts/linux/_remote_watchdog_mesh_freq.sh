#!/usr/bin/env bash
# Watchdog: monitor freq solve → postprocess → validate pb_top; alert on failure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"

SLUG="${1:-comsol_fig321_bcc_444_mesh}"
JOB="output/comsol_jobs/${SLUG}"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"
BATCH_LOG="${JOB}/${SLUG}_batch.log"
WATCH_LOG="output/logs/${SLUG}_watchdog.log"
INTERVAL="${INTERVAL:-60}"
FREQ_MIN="${FREQ_MIN:-10}"
FREQ_MAX="${FREQ_MAX:-300}"
FREQ_STEP="${FREQ_STEP:-2}"
TOTAL=$(( (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 ))

mkdir -p output/logs

exec >>"$WATCH_LOG" 2>&1
echo ""
echo "=== watchdog start $(date) slug=${SLUG} ==="

_fail() {
  echo "ERROR: $*"
  echo "=== watchdog failed $(date) ==="
  exit 1
}

_check_batch_errors() {
  if [[ ! -f "$BATCH_LOG" ]]; then
    return 0
  fi
  if grep -qiE 'failed|failure|error|exception|aborted' "$BATCH_LOG" 2>/dev/null; then
    echo "WARN: possible errors in batch log:"
    grep -iE 'failed|failure|error|exception|aborted' "$BATCH_LOG" | tail -8 || true
  fi
}

_progress() {
  local freq_line freq done pct elapsed
  freq_line=$(grep -o '参数 freq = [0-9]*' "$BATCH_LOG" 2>/dev/null | tail -1 || true)
  freq=${freq_line#*= }
  freq=${freq// /}
  if [[ -n "$freq" && "$freq" =~ ^[0-9]+$ ]]; then
    done=$(( (freq - FREQ_MIN) / FREQ_STEP + 1 ))
    [[ $done -lt 0 ]] && done=0
    [[ $done -gt $TOTAL ]] && done=$TOTAL
    pct=$(( done * 100 / TOTAL ))
    echo "[$(date '+%H:%M:%S')] solve running: freq=${freq}Hz ${done}/${TOTAL} (${pct}%)"
  else
    echo "[$(date '+%H:%M:%S')] solve starting..."
  fi
}

_wait_solve() {
  local start
  start=$(date +%s)
  while true; do
    if [[ -f "$SOLVED" ]]; then
      local sz
      sz=$(stat -c%s "$SOLVED" 2>/dev/null || echo 0)
      if [[ "$sz" -gt 100000000 ]]; then
        echo "[$(date '+%H:%M:%S')] solved mph ready ($(numfmt --to=iec "$sz" 2>/dev/null || echo ${sz}B))"
        return 0
      fi
    fi
    if ! pgrep -f "${SLUG}.*std_freq" >/dev/null 2>&1; then
      if [[ -f "$SOLVED" ]]; then
        echo "[$(date '+%H:%M:%S')] process ended, solved mph exists"
        return 0
      fi
      echo "batch log tail:"
      tail -20 "$BATCH_LOG" 2>/dev/null || true
      _fail "comsol process ended without valid solved mph"
    fi
    _check_batch_errors
    _progress
    sleep "$INTERVAL"
  done
}

_validate_pb_top() {
  echo "[$(date '+%H:%M:%S')] validating pb_top on solved mph..."
  python3 -u -c "
import sys; sys.path.insert(0,'.')
import numpy as np
from pathlib import Path
from src.comsol.mph_builder import _ensure_comsol_env,_import_mph
p=Path('$SOLVED')
_ensure_comsol_env('$COMSOL_BIN')
c=_import_mph().start(cores=1)
m=c.load(str(p))
tops=np.abs(np.array(m.evaluate('pb_top')).ravel())
bases=np.abs(np.array(m.evaluate('pb_base')).ravel())
nz=int((tops>1e-15).sum())
print(f'pb_top nonzero: {nz}/{tops.size}')
print(f'pb_base[0]={bases[0]:.6g} pb_top[0]={tops[0]:.6g}')
c.clear()
sys.exit(0 if nz>0 else 2)
"
}

_run_postprocess() {
  echo "[$(date '+%H:%M:%S')] running postprocess..."
  bash scripts/linux/_remote_postprocess_mesh_freq.sh
}

# --- main ---
[[ -f "$MPH" ]] || _fail "missing input mph $MPH"
grep -q "imprint=on" output/logs/${SLUG}_build.log 2>/dev/null || \
  echo "WARN: build log may lack imprint=on marker"

_wait_solve

_validate_pb_top || {
  echo "ERROR: pb_top validation failed — plate still disconnected"
  echo "=== watchdog failed $(date) ==="
  exit 2
}

_run_postprocess

echo "=== watchdog complete $(date) ==="
ls -lh "${JOB}/${SLUG}"*.{csv,png} 2>/dev/null | tail -10 || true
