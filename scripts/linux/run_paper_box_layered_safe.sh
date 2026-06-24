#!/usr/bin/env bash
# Paper box 4×4×4 layered fuse: fuse iz=0, copy iz=1..3, merge.
# Resumable — skips z-slabs that already exist on disk.
#
#   Q=1.0  bash scripts/linux/run_paper_box_layered_safe.sh
#   Q=1.5  Q=1.5 bash scripts/linux/run_paper_box_layered_safe.sh
set -euo pipefail

ROOT="${ROOT:-/home/art/Documents/Lattice/LWY/HuBaiLab}"
cd "$ROOT"
export PYTHONPATH="$ROOT"

MIN_FREE_GB="${MIN_FREE_GB:-80}"
MAX_RSS_GB="${MAX_RSS_GB:-48}"
STALL_SEC="${STALL_SEC:-7200}"
TIMEOUT_LAYER_SEC="${TIMEOUT_LAYER_SEC:-10800}"   # 3 h iz=0 fuse
TIMEOUT_MERGE_SEC="${TIMEOUT_MERGE_SEC:-14400}"  # 4 h inter-slab merge
NICE_LEVEL="${NICE_LEVEL:-10}"
Q="${Q:-1.0}"
Q_TAG="${Q_TAG:-$(echo "$Q" | tr '.' 'p')}"
ARRAY_DIR="${ARRAY_DIR:-$ROOT/output/cad/_paper_box_array_q${Q_TAG}}"
LOG="${LOG:-$ROOT/output/logs/paperbox_layered_fuse_q${Q_TAG}.log}"

mkdir -p "$(dirname "$LOG")" "$ARRAY_DIR"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

free_gb() {
  free -g | awk 'NR==2 {print $(NF)}'
}

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]]; then
    echo "$ROOT/.venv/bin/python3"
  else
    echo python3
  fi
}

array_step_path() {
  "$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
gen = HuBaiLatticeGenerator(
    cell_size=20.0, rod_diameter=2.0, amplitude=2.0,
    period_factor=float('$Q'), n_segments=24,
)
gen.build_unitcell()
slug = f\"hu_bai_{gen.variant_name.lower()}_L20_4x4x4\"
print('$ARRAY_DIR/' + slug + '_paper_box_array.step')
"
}

preflight() {
  local avail seed
  avail="$(free_gb)"
  log "preflight: available_mem=${avail}G (need >=${MIN_FREE_GB}G) Q=$Q dir=$ARRAY_DIR"
  if [[ "$avail" -lt "$MIN_FREE_GB" ]]; then
    log "ABORT: insufficient free memory"
    exit 2
  fi
  PY="$(python_cmd)"
  if ! "$PY" -c 'import gmsh' 2>/dev/null; then
    log "ABORT: gmsh not available"
    exit 2
  fi
  seed="$ROOT/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q${Q_TAG}_paper_box.step"
  if [[ "$Q" == "1.0" ]]; then
    seed="$ROOT/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1_paper_box.step"
  fi
  if [[ ! -f "$seed" ]]; then
    log "ABORT: missing seed $seed"
    exit 2
  fi
  export PY
  ARRAY_STEP="$(array_step_path)"
  export ARRAY_STEP
}

watchdog() {
  local target_pid=$1
  local last_size=0
  local stall_count=0
  while kill -0 "$target_pid" 2>/dev/null; do
    sleep 60
    [[ -f "$LOG" ]] || continue
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
      exit 3
    fi
    if [[ "$avail" -lt 20 ]]; then
      log "KILL: system avail mem ${avail}G critically low"
      kill -TERM "$target_pid" 2>/dev/null || true
      exit 3
    fi
    if [[ "$stall_count" -ge "$STALL_SEC" ]]; then
      log "KILL: no log progress for ${STALL_SEC}s"
      kill -TERM "$target_pid" 2>/dev/null || true
      exit 4
    fi
  done
}

run_timed() {
  local timeout_sec=$1
  shift
  log "RUN: timeout=${timeout_sec}s $*"
  set +e
  timeout --signal=TERM "$timeout_sec" nice -n "$NICE_LEVEL" "$@" >> "$LOG" 2>&1 &
  local pid=$!
  set -e
  watchdog "$pid" &
  local wd=$!
  wait "$pid"
  local rc=$?
  kill "$wd" 2>/dev/null || true
  wait "$wd" 2>/dev/null || true
  if [[ $rc -eq 124 ]]; then
    log "FAIL: hard timeout ${timeout_sec}s"
    return 124
  elif [[ $rc -ne 0 ]]; then
    log "FAIL: exit $rc"
    return "$rc"
  fi
  return 0
}

main() {
  log "=== paper box layered fuse Q=$Q ==="
  log "caps: max_rss=${MAX_RSS_GB}G stall=${STALL_SEC}s layer_timeout=${TIMEOUT_LAYER_SEC}s merge_timeout=${TIMEOUT_MERGE_SEC}s"
  preflight

  for iz in 0 1 2 3; do
    out="$ARRAY_DIR/zslab_iz${iz}_4x4_paper_box_fused.step"
    if [[ -f "$out" ]]; then
      log "SKIP iz=$iz (exists): $out"
      continue
    fi
    if [[ "$iz" -eq 0 ]]; then
      log "========== START iz=0 (fuse) =========="
      if ! run_timed "$TIMEOUT_LAYER_SEC" \
          "$PY" scripts/run_hu_bai_paper_box_layered_fuse.py --Q "$Q" --iz 0 \
          --out-dir "$ARRAY_DIR"; then
        log "Stopping after iz=0 failure"
        exit 1
      fi
      log "OK iz=0"
    else
      log "========== COPY iz=$iz from iz=0 (dz=$((iz * 20))mm) =========="
      if ! run_timed 600 \
          "$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from src.export.paper_box_array_fuse import export_paper_box_zslab_copies
ref = '$ARRAY_DIR/zslab_iz0_4x4_paper_box_fused.step'
out = '$ARRAY_DIR/zslab_iz${iz}_4x4_paper_box_fused.step'
export_paper_box_zslab_copies(ref, [out], cell_size=20.0, start_iz=${iz})
"; then
        log "Stopping after iz=$iz copy failure"
        exit 1
      fi
      log "OK iz=$iz (copy)"
    fi
  done

  if [[ -f "$ARRAY_STEP" ]]; then
    log "SKIP merge (array exists): $ARRAY_STEP"
    log "=== ALL DONE Q=$Q ==="
    exit 0
  fi

  log "========== START inter-slab merge =========="
  if ! run_timed "$TIMEOUT_MERGE_SEC" \
      "$PY" scripts/run_hu_bai_paper_box_layered_fuse.py --Q "$Q" --merge-only \
      --out-dir "$ARRAY_DIR"; then
    log "Merge failed"
    exit 1
  fi
  log "=== ALL DONE Q=$Q ==="
}

main "$@"
