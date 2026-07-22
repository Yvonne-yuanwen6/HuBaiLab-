#!/usr/bin/env bash
# Ordered batch: 1x1 + 444 STEP -> output/cad/批量构型/{id}/
#
#   bash scripts/linux/run_param_batch_step_generate.sh
#   nohup bash scripts/linux/run_param_batch_step_generate.sh >> output/logs/param_batch_step.log 2>&1 &
#
# Env: FORCE=1 ONLY="af2q0_deq2_k1 …" TOL_REL=0.03 STOP_ON_FAIL=1 JOBS=2
#      BATCH_STEP_POST_HEAL=0  # skip mass-gated Gmsh heal after 444 write
#
# Locked scheme (see docs/批量构型STEP生成说明.md):
#   444 prefers ocp_seed_scale*_zcopy_* (iz0 fuse + Z-copy);
#   accept only gmsh volume_count==1; --jobs>1 OK (QC measure in child process).
#   Default: structure-preserving post-heal on _444.step (mass_ratio∈[0.95,1.05]).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/param_batch_step.log}"
PROGRESS="${PROGRESS:-$ROOT/output/logs/param_batch_step.progress}"
FORCE="${FORCE:-0}"
TOL_REL="${TOL_REL:-0.03}"
STOP_ON_FAIL="${STOP_ON_FAIL:-0}"
ONLY="${ONLY:-}"
JOBS="${JOBS:-1}"
NICE_LEVEL="${NICE_LEVEL:-10}"
MIN_FREE_GB="${MIN_FREE_GB:-40}"
UNITCELL_TIMEOUT="${UNITCELL_TIMEOUT:-600}"
ARRAY_TIMEOUT="${ARRAY_TIMEOUT:-5400}"
BATCH_STEP_POST_HEAL="${BATCH_STEP_POST_HEAL:-1}"
export BATCH_STEP_POST_HEAL

mkdir -p "$(dirname "$LOG")" "$ROOT/output/cad/批量构型"

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

preflight() {
  local avail
  avail="$(free_gb)"
  log "preflight: available_mem=${avail}G (need >=${MIN_FREE_GB}G)"
  if [[ "$avail" -lt "$MIN_FREE_GB" ]]; then
    log "ABORT: insufficient free memory"
    exit 2
  fi
  if [[ ! -f "$ROOT/output/cad/批量构型/_batch_index.json" ]]; then
    log "ABORT: missing output/cad/批量构型/_batch_index.json"
    exit 3
  fi
}

PY="$(python_cmd)"
log "PY=$PY ROOT=$ROOT JOBS=$JOBS POST_HEAL=$BATCH_STEP_POST_HEAL"
preflight
touch_progress "start"

args=(
  scripts/run_param_batch_step_generate.py
  --index "$ROOT/output/cad/批量构型/_batch_index.json"
  --tol-rel "$TOL_REL"
  --unitcell-attempt-timeout "$UNITCELL_TIMEOUT"
  --array-attempt-timeout "$ARRAY_TIMEOUT"
  --jobs "$JOBS"
)
if [[ "$FORCE" == "1" ]]; then
  args+=(--force)
fi
if [[ "$STOP_ON_FAIL" == "1" ]]; then
  args+=(--stop-on-fail)
fi
if [[ "$BATCH_STEP_POST_HEAL" == "0" ]]; then
  args+=(--no-post-heal)
fi
if [[ -n "$ONLY" ]]; then
  # shellcheck disable=SC2206
  only_arr=($ONLY)
  args+=(--only "${only_arr[@]}")
fi

log "=== run: $PY ${args[*]} ==="
set +e
nice -n "$NICE_LEVEL" "$PY" "${args[@]}" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e
touch_progress "done_rc_${rc}"
log "exit=$rc"
exit "$rc"
