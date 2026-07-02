#!/usr/bin/env bash
# 4x4x4 Q=1 paper_box layered fuse (default: gmsh octant seed; USE_OCP_SEED=1 for OCP pilot seed).
#
#   bash scripts/linux/run_ocp_q1_4x4x4_array_fuse.sh
#   nohup bash scripts/linux/run_ocp_q1_4x4x4_array_fuse.sh >> output/logs/ocp_q1_4x4x4_array.log 2>&1 &
#
# Env: SEED=... OUT_DIR=... FORCE=1 MIN_FREE_GB=80
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ocp_q1_4x4x4_array.log}"
PROGRESS="${PROGRESS:-$ROOT/output/logs/ocp_q1_4x4x4_array.progress}"
SEED="${SEED:-$ROOT/output/cad/_ocp_glue_pilot/unitcell_af2q1_L20_ocp_stub_sequential-glue-shift.step}"
GMSH_SEED="${GMSH_SEED:-$ROOT/output/cad/_unitcell_paper_box_cut/unitcell_sfbls_af2q1_paper_box.step}"
OUT_DIR="${OUT_DIR:-}"
USE_OCP_SEED="${USE_OCP_SEED:-1}"
FORCE="${FORCE:-1}"
MIN_FREE_GB="${MIN_FREE_GB:-80}"
NICE_LEVEL="${NICE_LEVEL:-10}"

if [[ -z "$OUT_DIR" ]]; then
  if [[ "$USE_OCP_SEED" == "1" ]]; then
    OUT_DIR="$ROOT/output/cad/_paper_box_array_q1p0_ocp"
  else
    OUT_DIR="$ROOT/output/cad/_paper_box_array_q1p0"
  fi
fi

if [[ "$USE_OCP_SEED" == "1" ]]; then
  LOG="${LOG:-$ROOT/output/logs/ocp_q1_4x4x4_array_ocp_seed.log}"
  PROGRESS="${PROGRESS:-$ROOT/output/logs/ocp_q1_4x4x4_array_ocp_seed.progress}"
fi

mkdir -p "$(dirname "$LOG")" "$OUT_DIR"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }
touch_progress() { date -Iseconds > "$PROGRESS"; echo "phase=$1" >> "$PROGRESS"; }

free_gb() { free -g | awk 'NR==2 {print $(NF)}'; }

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]] && "$ROOT/.venv/bin/python3" -c 'import sys' 2>/dev/null; then
    echo "$ROOT/.venv/bin/python3"
  elif [[ -x /home/art/conda/bin/python3 ]]; then
    echo /home/art/conda/bin/python3
  else
    echo python3
  fi
}

ensure_seed() {
  if [[ "$USE_OCP_SEED" == "1" ]]; then
    if [[ -f "$SEED" ]]; then
      return 0
    fi
    log "OCP seed missing; running unit-cell pilot first..."
    bash "$SCRIPT_DIR/run_ocp_glue_fuse_pilot.sh"
    return 0
  fi
  SEED="$GMSH_SEED"
  if [[ -f "$SEED" ]]; then
    return 0
  fi
  log "gmsh seed missing; exporting unitcell Q=1.0..."
  "$PY" scripts/export_unitcell_paper_box_cut.py --Q 1.0
  SEED="$GMSH_SEED"
}

preflight() {
  local avail vols
  avail="$(free_gb)"
  log "preflight: available_mem=${avail}G (need >=${MIN_FREE_GB}G)"
  if [[ "$avail" -lt "$MIN_FREE_GB" ]]; then
    log "ABORT: insufficient free memory"
    exit 2
  fi
  if ! "$PY" -c 'import gmsh' 2>/dev/null; then
    log "installing gmsh..."
    "$PY" -m pip install -q 'gmsh>=4.12'
  fi
  if ! "$PY" -c 'from OCP.STEPControl import STEPControl_Reader' 2>/dev/null; then
    log "installing cadquery-ocp..."
    "$PY" -m pip install -q cadquery-ocp
  fi
  vols="$("$PY" -c "
from src.export.paper_box_array_fuse import _count_seed_volumes
print(_count_seed_volumes('$SEED'))
")"
  log "seed volumes: $vols ($SEED)"
  if [[ "$vols" -ne 1 ]]; then
    log "ABORT: array fuse requires 1-volume seed, got $vols"
    exit 2
  fi
}

PY="$(python_cmd)"
ensure_seed
preflight

log "=== Q1 4x4x4 array fuse start seed=$SEED out=$OUT_DIR ==="
touch_progress "start"

fuse_args=(scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0 --seed "$SEED" --out-dir "$OUT_DIR" --backend ocp)
if [[ "$FORCE" == "1" ]]; then
  fuse_args+=(--force)
fi

set +e
nice -n "$NICE_LEVEL" "$PY" "${fuse_args[@]}" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e

if [[ "$rc" -eq 0 ]]; then
  touch_progress "done"
  log "=== Q1 4x4x4 array fuse OK ==="
  "$PY" -c "
from src.export.sw_parasolid import measure_step_occ_stats as s
import os
p = os.path.join('$OUT_DIR', 'hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step')
if os.path.isfile(p):
    print('array stats:', s(p))
" | tee -a "$LOG"
else
  touch_progress "fail"
  log "=== Q1 4x4x4 array fuse FAILED (exit=$rc) ==="
  exit "$rc"
fi
