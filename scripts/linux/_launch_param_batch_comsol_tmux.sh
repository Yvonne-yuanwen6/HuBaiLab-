#!/usr/bin/env bash
# Launch param-batch COMSOL queue in tmux.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
SESSION="${BATCH_COMSOL_TMUX:-param_batch_comsol}"
LOG="$ROOT/output/logs/param_batch_comsol_queue.log"
mkdir -p "$ROOT/output/logs"

export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH:-}"
export PYTHONPATH="$ROOT"
# MPh mphserver starts with -graphics; without DISPLAY, gtk_init fails and
# "MPh: starting COMSOL" hangs forever under SSH/tmux.
export DISPLAY="${DISPLAY:-:1}"
export BATCH_COMSOL_NP="${BATCH_COMSOL_NP:-8}"
export BATCH_COMSOL_FREQ_MIN="${BATCH_COMSOL_FREQ_MIN:-10}"
export BATCH_COMSOL_FREQ_MAX="${BATCH_COMSOL_FREQ_MAX:-500}"
export BATCH_COMSOL_FREQ_STEP="${BATCH_COMSOL_FREQ_STEP:-10}"
export BATCH_COMSOL_PYTHON="${BATCH_COMSOL_PYTHON:-/home/art/conda/bin/python3}"
export BATCH_COMSOL_FORCE="${BATCH_COMSOL_FORCE:-0}"
export BATCH_COMSOL_ONLY="${BATCH_COMSOL_ONLY:-}"
export BATCH_COMSOL_LATTICE_HAUTO="${BATCH_COMSOL_LATTICE_HAUTO:-4}"
export BATCH_COMSOL_FIXTURE_HAUTO="${BATCH_COMSOL_FIXTURE_HAUTO:-5}"
# Ensure tmux does not inherit an isolated .venv that masks conda site-packages.
unset VIRTUAL_ENV
export PATH="/home/art/conda/bin:${PATH}"

chmod +x "$ROOT/scripts/linux/run_param_batch_comsol_queue.sh"
chmod +x "$ROOT/scripts/linux/_tmp_monitor_param_batch_comsol.sh"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already exists: $SESSION"
  tmux ls | grep "$SESSION" || true
  exit 0
fi

CMD="cd '$ROOT' && unset VIRTUAL_ENV && env PATH='/home/art/conda/bin:$PATH' PYTHONPATH='$ROOT' COMSOL_BIN='$COMSOL_BIN' DISPLAY='$DISPLAY' BATCH_COMSOL_PYTHON='$BATCH_COMSOL_PYTHON' BATCH_COMSOL_NP='$BATCH_COMSOL_NP' BATCH_COMSOL_FREQ_MIN='$BATCH_COMSOL_FREQ_MIN' BATCH_COMSOL_FREQ_MAX='$BATCH_COMSOL_FREQ_MAX' BATCH_COMSOL_FREQ_STEP='$BATCH_COMSOL_FREQ_STEP' BATCH_COMSOL_FORCE='$BATCH_COMSOL_FORCE' BATCH_COMSOL_ONLY='$BATCH_COMSOL_ONLY' BATCH_COMSOL_LATTICE_HAUTO='$BATCH_COMSOL_LATTICE_HAUTO' BATCH_COMSOL_FIXTURE_HAUTO='$BATCH_COMSOL_FIXTURE_HAUTO' HU_BAI_COMSOL_CLIP_TOP='${HU_BAI_COMSOL_CLIP_TOP:-0}' bash scripts/linux/run_param_batch_comsol_queue.sh 2>&1 | tee -a '$LOG'; echo EXIT=\$?; exec bash"
tmux new-session -d -s "$SESSION" "$CMD"

echo "started tmux session=$SESSION"
echo "attach: tmux attach -t $SESSION"
echo "log:    $LOG"
sleep 3
tmux capture-pane -t "$SESSION" -p | tail -n 30 || true
