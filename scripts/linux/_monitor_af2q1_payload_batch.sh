#!/usr/bin/env bash
# Poll AF2Q1 payload batch until done (run on server or via ssh).
set -euo pipefail
ROOT="${ROOT:-/media/art/file/XiangLang/Lattice/LWY/HuBaiLab}"
LOG="$ROOT/output/logs/af2q1_payload_f5_150_batch.log"
SLUG_PREFIX="comsol_fig321_af2q1_444_mesh_p1"

monitor_once() {
  echo "[$(date '+%H:%M:%S')] --- AF2Q1 payload batch ---"
  if grep -q '=== batch done' "$LOG" 2>/dev/null; then
    echo "STATUS: DONE"
    tail -8 "$LOG"
    return 0
  fi
  if ! pgrep -f '_remote_payload_f5_150_batch' >/dev/null 2>&1 \
    && ! pgrep -f "${SLUG_PREFIX}.*std_freq" >/dev/null 2>&1; then
    echo "STATUS: STOPPED (no batch/solve process)"
    tail -15 "$LOG"
    return 2
  fi
  current=$(grep -E '^========== comsol_fig321_af2q1' "$LOG" 2>/dev/null | tail -1 || true)
  prog=$(grep -E '^\[.*\] comsol_fig321_af2q1.*freq=' "$LOG" 2>/dev/null | tail -1 || true)
  echo "CASE: ${current:-starting...}"
  echo "PROG: ${prog:-waiting for freq progress...}"
  comsol=$(pgrep -af "comsol batch.*${SLUG_PREFIX}" 2>/dev/null | head -1 || true)
  if [[ -n "$comsol" ]]; then
    echo "SOLVE: active"
  fi
  return 1
}

while true; do
  if monitor_once; then
    exit 0
  fi
  rc=$?
  if [[ "$rc" -eq 2 ]]; then
    exit 2
  fi
  sleep 90
done
