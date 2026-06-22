#!/usr/bin/env bash
# Stop all HuBaiLab Abaqus jobs and queue scripts; remove stale .lck files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

echo "=== stop HuBaiLab jobs $(date) ==="

pkill -9 -f 'run_autodt_batch.sh' 2>/dev/null || true
pkill -9 -f 'submit_queue.sh' 2>/dev/null || true
pkill -9 -f 'submit_after_wait.sh' 2>/dev/null || true
pkill -9 -f 'submit_job.sh' 2>/dev/null || true
pkill -9 -f 'HuBaiLab/output/jobs/hu_bai' 2>/dev/null || true
pkill -9 -f 'hu_bai_.*L20_4x4x4' 2>/dev/null || true
pkill -9 -f 'SMAPython.*hu_bai_' 2>/dev/null || true
pkill -9 -f 'eliT_DriverLM.*hu_bai_' 2>/dev/null || true

sleep 2
find "$ROOT/output/jobs" -name '*.lck' -delete 2>/dev/null || true

n=$(ps aux | grep -E 'explicit.*hu_bai|submit_queue|run_autodt' | grep -v grep | wc -l || true)
echo "remaining hu_bai/queue processes: $n"
echo "=== done ==="
