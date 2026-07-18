#!/usr/bin/env bash
# Launch param-batch CAE sim queue in a dedicated tmux session.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
SESSION="${BATCH_SIM_TMUX:-param_batch_cae_sim}"
LOG="$ROOT/output/logs/param_batch_cae_sim_queue.log"
mkdir -p "$ROOT/output/logs"

export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
export BATCH_SIM_CPUS="${BATCH_SIM_CPUS:-48}"
export BATCH_SIM_MEMORY_MB="${BATCH_SIM_MEMORY_MB:-262144}"
export BATCH_SIM_MAX_PARALLEL="${BATCH_SIM_MAX_PARALLEL:-2}"

chmod +x "$ROOT/scripts/linux/run_param_batch_cae_sim_queue.sh"

python3 "$ROOT/scripts/_tmp_list_batch_sim_ready.py" | tee -a "$LOG" || true

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already exists: $SESSION (kill with: tmux kill-session -t $SESSION)"
  tmux ls | grep "$SESSION" || true
  exit 0
fi

# Single-line env bootstrap — avoid broken multi-line `export ... \` in tmux.
# Optional: BATCH_SIM_SUBMIT_ONLY=1 (skip remesh; keep running ODBs)
EXTRA_ENV=""
if [[ -n "${BATCH_SIM_SUBMIT_ONLY:-}" ]]; then
  EXTRA_ENV="BATCH_SIM_SUBMIT_ONLY='$BATCH_SIM_SUBMIT_ONLY'"
fi
CMD="cd '$ROOT' && env PATH='$PATH' PYTHONPATH='$ROOT' BATCH_SIM_CPUS='$BATCH_SIM_CPUS' BATCH_SIM_MEMORY_MB='$BATCH_SIM_MEMORY_MB' BATCH_SIM_MAX_PARALLEL='$BATCH_SIM_MAX_PARALLEL' $EXTRA_ENV bash scripts/linux/run_param_batch_cae_sim_queue.sh 2>&1 | tee -a '$LOG'; echo EXIT=\$?; exec bash"
tmux new-session -d -s "$SESSION" "$CMD"

echo "started tmux session=$SESSION"
echo "attach: tmux attach -t $SESSION"
echo "log:    $LOG"
sleep 2
tmux capture-pane -t "$SESSION" -p | tail -n 25 || true
