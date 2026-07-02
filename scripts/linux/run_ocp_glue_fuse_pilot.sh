#!/usr/bin/env bash
# OCP native Fuse + GlueShift unit-cell pilot (Q=1 centre_stub).
#
#   bash scripts/linux/run_ocp_glue_fuse_pilot.sh
#   nohup bash scripts/linux/run_ocp_glue_fuse_pilot.sh >> output/logs/ocp_glue_pilot.log 2>&1 &
#
# Env overrides:
#   FUZZY_MM=0.02  STRATEGY=sequential_glue_shift  MIN_FREE_GB=32
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/ocp_glue_pilot.log}"
PROGRESS="${PROGRESS:-$ROOT/output/logs/ocp_glue_pilot.progress}"
OUT_DIR="${OUT_DIR:-$ROOT/output/cad/_ocp_glue_pilot}"
FUZZY_MM="${FUZZY_MM:-0.02}"
STRATEGY="${STRATEGY:-sequential_glue_shift}"
MIN_FREE_GB="${MIN_FREE_GB:-32}"
NICE_LEVEL="${NICE_LEVEL:-10}"

mkdir -p "$(dirname "$LOG")" "$OUT_DIR"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }
touch_progress() { date -Iseconds > "$PROGRESS"; echo "phase=$1" >> "$PROGRESS"; }

free_gb() {
  free -g | awk 'NR==2 {print $(NF)}'
}

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]] && "$ROOT/.venv/bin/python3" -c 'import sys' 2>/dev/null; then
    echo "$ROOT/.venv/bin/python3"
  elif [[ -x /home/art/conda/bin/python3 ]]; then
    echo /home/art/conda/bin/python3
  else
    echo python3
  fi
}

pip_cmd() {
  local py="$1"
  if "$py" -m pip --version >/dev/null 2>&1; then
    echo "$py -m pip"
  elif [[ -x "$ROOT/.venv/bin/pip" ]] && head -1 "$ROOT/.venv/bin/pip" | grep -q python; then
    echo "$ROOT/.venv/bin/pip"
  else
    echo ""
  fi
}

ensure_ocp() {
  local py="$1"
  if "$py" -c 'from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse' 2>/dev/null; then
    return 0
  fi
  log "cadquery-ocp not found; installing..."
  local pip
  pip="$(pip_cmd "$py")"
  if [[ -z "$pip" ]]; then
    log "ABORT: no working pip for $py"
    exit 2
  fi
  $pip install -q 'cadquery-ocp>=7.7'
  if ! "$py" -c 'from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse' 2>/dev/null; then
    log "ABORT: cadquery-ocp import still fails after install"
    exit 2
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
}

PY="$(python_cmd)"
ensure_ocp "$PY"
preflight

log "=== OCP Glue fuse pilot start ROOT=$ROOT fuzzy=${FUZZY_MM} strategy=${STRATEGY} ==="
touch_progress "start"

set +e
nice -n "$NICE_LEVEL" "$PY" scripts/_tmp_ocp_glue_fuse_pilot.py \
  --strategy "$STRATEGY" \
  --fuzzy-mm "$FUZZY_MM" \
  --out-dir "$OUT_DIR" \
  2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e

if [[ "$rc" -eq 0 ]]; then
  touch_progress "done"
  log "=== OCP Glue fuse pilot OK (manifest in $OUT_DIR/ocp_glue_pilot_manifest.json) ==="
else
  touch_progress "fail"
  log "=== OCP Glue fuse pilot FAILED (exit=$rc) ==="
  exit "$rc"
fi
