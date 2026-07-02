#!/usr/bin/env bash
# Probe gmsh/BREP heal routes for OCP fused unit-cell STEP validity.
#
#   bash scripts/linux/run_ocp_step_heal_probe.sh
#   nohup bash scripts/linux/run_ocp_step_heal_probe.sh >> output/logs/ocp_step_heal_probe.log 2>&1 &
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ocp_step_heal_probe.log}"
PROGRESS="${PROGRESS:-$ROOT/output/logs/ocp_step_heal_probe.progress}"
MIN_FREE_GB="${MIN_FREE_GB:-16}"
NICE_LEVEL="${NICE_LEVEL:-10}"

mkdir -p "$(dirname "$LOG")" "$ROOT/output/cad/_ocp_glue_pilot"

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

PY="$(python_cmd)"
if ! "$PY" -c 'from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse' 2>/dev/null; then
  log "installing cadquery-ocp..."
  "$PY" -m pip install -q 'cadquery-ocp>=7.7'
fi
if ! "$PY" -c 'import gmsh' 2>/dev/null; then
  log "installing gmsh..."
  "$PY" -m pip install -q 'gmsh>=4.12'
fi

avail="$(free_gb)"
log "preflight: available_mem=${avail}G (need >=${MIN_FREE_GB}G)"
if [[ "$avail" -lt "$MIN_FREE_GB" ]]; then
  log "ABORT: insufficient memory"
  exit 2
fi

log "=== OCP STEP heal probe start ==="
touch_progress "start"

set +e
nice -n "$NICE_LEVEL" "$PY" scripts/_tmp_ocp_step_heal_probe.py 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e

if [[ "$rc" -eq 0 ]]; then
  touch_progress "done"
  log "=== OCP STEP heal probe OK ==="
else
  touch_progress "fail"
  log "=== OCP STEP heal probe FAILED (exit=$rc) ==="
  exit "$rc"
fi
