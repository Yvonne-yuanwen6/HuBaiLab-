#!/usr/bin/env bash
# One-shot: stop stale improve/supervisor processes and restart supervisor.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

pkill -f 'bash scripts/linux/paperbox_q05_fig33_improve_supervise.sh' 2>/dev/null || true
pkill -f 'bash scripts/linux/run_paperbox_q05_fig33_improve.sh' 2>/dev/null || true
rm -f output/logs/paperbox_q05_fig33_improve.lock

bash -n scripts/linux/run_paperbox_q05_fig33_improve.sh
nohup bash scripts/linux/paperbox_q05_fig33_improve_supervise.sh \
  >> output/logs/paperbox_q05_fig33_improve_supervise.log 2>&1 &
echo "supervisor PID=$!"
sleep 30
tail -10 output/logs/paperbox_q05_fig33_improve_supervise.log
tail -6 output/logs/paperbox_q05_fig33_improve.log
ls output/jobs/hu_bai_sfbls_af2q0p5*fig33_v2_paper/*.lck 2>/dev/null || echo "fig33_v2_paper: no lck yet"
