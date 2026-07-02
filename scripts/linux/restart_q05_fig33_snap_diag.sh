#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"

pkill -f 'bash scripts/linux/run_paperbox_q05_fig33_snap_diag.sh' 2>/dev/null || true
rm -f output/logs/paperbox_q05_fig33_snap_diag.lock
nohup bash scripts/linux/run_paperbox_q05_fig33_snap_diag.sh \
  >> output/logs/paperbox_q05_fig33_snap_diag.log 2>&1 &
echo "snap diag PID=$!"
sleep 5
tail -6 output/logs/paperbox_q05_fig33_snap_diag.log
