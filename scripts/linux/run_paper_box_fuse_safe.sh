#!/usr/bin/env bash
# Safe server-side paper box 4x4x4 auto-fuse (Q=1.0, Q=1.5).
# - Preflight free memory
# - Per-Q hard timeout
# - Stall watchdog (no log progress)
# - RSS cap kills runaway OCC/python
set -euo pipefail

ROOT="${ROOT:-/home/art/Documents/Lattice/LWY/HuBaiLab}"
cd "$ROOT"
export PYTHONPATH="$ROOT"

LOG="${LOG:-$ROOT/output/logs/paperbox_fuse_auto.log}"
PROGRESS="$ROOT/output/logs/paperbox_fuse.progress"
MIN_FREE_GB="${MIN_FREE_GB:-80}"
MAX_RSS_GB="${MAX_RSS_GB:-48}"
STALL_SEC="${STALL_SEC:-7200}"
TIMEOUT_Q_SEC="${TIMEOUT_Q_SEC:-21600}"  # 6 h per Q
NICE_LEVEL="${NICE_LEVEL:-10}"

mkdir -p "$(dirname "$LOG")" "$ROOT/output/cad/_paper_box_array_q1p0" "$ROOT/output/cad/_paper_box_array_q1p5"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }
touch_progress() { date -Iseconds > "$PROGRESS"; echo "Q=$CURRENT_Q phase=$1" >> "$PROGRESS"; }

free_gb() {
  # GNU free -g: last column is available (GiB), numeric on this host
  free -g | awk 'NR==2 {print $(NF)}'
}

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]]; then
    echo "$ROOT/.venv/bin/python3"
  else
    echo python3
  fi
}

preflight() {
  local avail
  avail="$(free_gb)"
  log "preflight: available_mem=${avail}G (need >=${MIN_FREE_GB}G)"
  if [[ "$avail" -lt "$MIN_FREE_GB" ]]; then
    log "ABORT: insufficient free memory (${avail}G < ${MIN_FREE_GB}G)"
    exit 2
  fi
  PY="$(python_cmd)"
  if ! "$PY" -c 'import gmsh' 2>/dev/null; then
    if [[ -x "$ROOT/.venv/bin/pip" ]]; then
      log "installing gmsh into project venv..."
      "$ROOT/.venv/bin/pip" install -q 'gmsh>=4.12'
      PY="$ROOT/.venv/bin/python3"
    else
      log "ABORT: gmsh not available and no venv pip"
      exit 2
    fi
  fi
  if ! "$PY" -c 'import gmsh' 2>/dev/null; then
    log "ABORT: gmsh import failed after install attempt"
    exit 2
  fi
  export PY
  for q in 1.0 1.5; do
    seed="$ROOT/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q${q/./p}_paper_box.step"
    if [[ "$q" == "1.0" ]]; then seed="$ROOT/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1_paper_box.step"; fi
    if [[ "$q" == "1.5" ]]; then seed="$ROOT/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1p5_paper_box.step"; fi
    if [[ ! -f "$seed" ]]; then
      log "ABORT: missing seed $seed"
      exit 2
    fi
  done
}

watchdog() {
  local target_pid=$1
  local last_size=0
  local stall_count=0
  while kill -0 "$target_pid" 2>/dev/null; do
    sleep 60
    if [[ ! -f "$LOG" ]]; then continue; fi
    size=$(stat -c%s "$LOG" 2>/dev/null || echo 0)
    if [[ "$size" -eq "$last_size" ]]; then
      stall_count=$((stall_count + 60))
    else
      stall_count=0
      last_size=$size
    fi
    rss_kb=$(ps -o rss= -p "$target_pid" 2>/dev/null | tr -d ' ' || echo 0)
    rss_gb=$((rss_kb / 1024 / 1024))
    avail=$(free_gb)
    log "watchdog: pid=$target_pid rss=${rss_gb}G avail=${avail}G stall=${stall_count}s"
    if [[ "$rss_gb" -gt "$MAX_RSS_GB" ]]; then
      log "KILL: RSS ${rss_gb}G > cap ${MAX_RSS_GB}G"
      kill -TERM "$target_pid" 2>/dev/null || true
      sleep 5
      kill -KILL "$target_pid" 2>/dev/null || true
      exit 3
    fi
    if [[ "$avail" -lt 20 ]]; then
      log "KILL: system avail mem ${avail}G critically low"
      kill -TERM "$target_pid" 2>/dev/null || true
      exit 3
    fi
    if [[ "$stall_count" -ge "$STALL_SEC" ]]; then
      log "KILL: no log progress for ${STALL_SEC}s (stalled)"
      kill -TERM "$target_pid" 2>/dev/null || true
      sleep 5
      kill -KILL "$target_pid" 2>/dev/null || true
      exit 4
    fi
  done
}

run_q() {
  CURRENT_Q=$1
  log "========== START Q=$CURRENT_Q =========="
  touch_progress "start"
  set +e
  timeout --signal=TERM "$TIMEOUT_Q_SEC" nice -n "$NICE_LEVEL" \
    "$PY" scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q "$CURRENT_Q" --auto-only \
    >> "$LOG" 2>&1 &
  local pid=$!
  set -e
  watchdog "$pid" &
  local wd=$!
  wait "$pid"
  local rc=$?
  kill "$wd" 2>/dev/null || true
  wait "$wd" 2>/dev/null || true
  if [[ $rc -eq 124 ]]; then
    log "FAIL Q=$CURRENT_Q: hard timeout ${TIMEOUT_Q_SEC}s"
    touch_progress "timeout"
    return 124
  elif [[ $rc -ne 0 ]]; then
    log "FAIL Q=$CURRENT_Q: exit $rc"
    touch_progress "fail"
    return "$rc"
  fi
  log "OK Q=$CURRENT_Q"
  touch_progress "ok"
  return 0
}

main() {
  log "=== paper box fuse safe runner ==="
  log "caps: max_rss=${MAX_RSS_GB}G stall=${STALL_SEC}s timeout_q=${TIMEOUT_Q_SEC}s nice=${NICE_LEVEL}"
  preflight
  fail=0
  for q in 1.0 1.5; do
    if ! run_q "$q"; then
      fail=1
      log "Stopping after Q=$q failure (no Q=1.5 if Q=1.0 failed)"
      break
    fi
  done
  if [[ "$fail" -eq 0 ]]; then
    log "=== ALL DONE Q=1.0 Q=1.5 ==="
  else
    log "=== STOPPED WITH FAILURE — use stepwise compound + SW fallback ==="
    exit 1
  fi
}

main "$@"
