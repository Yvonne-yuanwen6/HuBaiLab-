#!/usr/bin/env bash
# Backfill {case_id}_strut1.step (+ raw) for all batch cases; keep 1x1/444.
#
#   bash scripts/linux/run_param_batch_strut_only.sh
#   ONLY="af2q0_deq2_k1 af2q0_deq2_k2" FORCE=1 bash scripts/linux/run_param_batch_strut_only.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

LOG="${LOG:-$ROOT/output/logs/param_batch_strut_only.log}"
ONLY="${ONLY:-}"
FORCE="${FORCE:-0}"
UNITCELL_TIMEOUT="${UNITCELL_TIMEOUT:-600}"
NICE_LEVEL="${NICE_LEVEL:-10}"
INDEX="${INDEX:-$ROOT/output/cad/批量构型/_batch_index.json}"

mkdir -p "$(dirname "$LOG")"

if [[ ! -f "$INDEX" ]]; then
  echo "ABORT: missing $INDEX (is /media/art/file mounted?)"
  exit 3
fi

PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY=python3

args=(
  scripts/run_param_batch_step_generate.py
  --index "$INDEX"
  --strut-only
  --unitcell-attempt-timeout "$UNITCELL_TIMEOUT"
)
if [[ "$FORCE" == "1" ]]; then
  args+=(--force)
fi
if [[ -n "$ONLY" ]]; then
  # shellcheck disable=SC2206
  only_arr=($ONLY)
  args+=(--only "${only_arr[@]}")
fi

echo "[$(date -Iseconds)] PY=$PY ${args[*]}" | tee -a "$LOG"
set +e
nice -n "$NICE_LEVEL" "$PY" -u "${args[@]}" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e
echo "[$(date -Iseconds)] exit=$rc" | tee -a "$LOG"
exit "$rc"
