#!/usr/bin/env bash
# Auto-check batch QC and FORCE-regenerate only failed / missing cases.
# Each strategy attempt has a hard wall-clock timeout (no multi-hour hangs).
#
#   bash scripts/linux/run_param_batch_auto_repair.sh
#   ONLY=af2q1_deq1p5_k1 bash scripts/linux/run_param_batch_auto_repair.sh
#   CHECK_ONLY=1 bash scripts/linux/run_param_batch_auto_repair.sh
#
# Env:
#   ONLY="id1 id2"
#   CHECK_ONLY=1          # status scan only
#   UNITCELL_TIMEOUT=600  # seconds per 1x1 strategy
#   ARRAY_TIMEOUT=5400    # seconds per 444 strategy
#   TOL_REL=0.03
#   NICE_LEVEL=10
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/param_batch_auto_repair.log}"
PROGRESS="${PROGRESS:-$ROOT/output/logs/param_batch_auto_repair.progress}"
TOL_REL="${TOL_REL:-0.03}"
ONLY="${ONLY:-}"
CHECK_ONLY="${CHECK_ONLY:-0}"
ARRAY_ONLY="${ARRAY_ONLY:-0}"
UNITCELL_TIMEOUT="${UNITCELL_TIMEOUT:-600}"
ARRAY_TIMEOUT="${ARRAY_TIMEOUT:-5400}"
NICE_LEVEL="${NICE_LEVEL:-10}"

mkdir -p "$(dirname "$LOG")" "$ROOT/output/cad/批量构型"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }
touch_progress() { date -Iseconds > "$PROGRESS"; echo "phase=$1" >> "$PROGRESS"; }

python_cmd() {
  if [[ -x "$ROOT/.venv/bin/python3" ]] && "$ROOT/.venv/bin/python3" -c 'import sys' 2>/dev/null; then
    echo "$ROOT/.venv/bin/python3"
  elif [[ -x /home/art/conda/bin/python3 ]]; then
    echo /home/art/conda/bin/python3
  else
    echo python3
  fi
}

# Stop any prior batch so we don't leave hung remelts running.
while read -r pid; do
  [[ -z "$pid" || "$pid" == "$$" ]] && continue
  log "kill prior batch pid=$pid"
  kill "$pid" 2>/dev/null || true
done < <(pgrep -f 'scripts/run_param_batch_step_generate.py' || true)
sleep 2
while read -r pid; do
  [[ -z "$pid" || "$pid" == "$$" ]] && continue
  kill -9 "$pid" 2>/dev/null || true
done < <(pgrep -f 'scripts/run_param_batch_step_generate.py' || true)

PY="$(python_cmd)"
log "PY=$PY ROOT=$ROOT UNITCELL_TIMEOUT=${UNITCELL_TIMEOUT}s ARRAY_TIMEOUT=${ARRAY_TIMEOUT}s"
touch_progress "start"

args=(
  scripts/run_param_batch_step_generate.py
  --index "$ROOT/output/cad/批量构型/_batch_index.json"
  --tol-rel "$TOL_REL"
  --unitcell-attempt-timeout "$UNITCELL_TIMEOUT"
  --array-attempt-timeout "$ARRAY_TIMEOUT"
)
if [[ "$CHECK_ONLY" == "1" ]]; then
  args+=(--check-only)
else
  args+=(--repair)
fi
if [[ "$ARRAY_ONLY" == "1" ]]; then
  args+=(--array-only)
fi
if [[ -n "$ONLY" ]]; then
  # shellcheck disable=SC2206
  only_arr=($ONLY)
  args+=(--only "${only_arr[@]}")
fi

log "cmd: $PY ${args[*]}"
set +e
nice -n "$NICE_LEVEL" "$PY" "${args[@]}" >>"$LOG" 2>&1
rc=$?
set -e
touch_progress "done_rc_${rc}"
log "exit=$rc"
exit "$rc"
