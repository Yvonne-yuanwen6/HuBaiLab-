#!/usr/bin/env bash
# Kill msu10 smoke (too slow) then ready for msb1e4 resubmit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
echo "[$(date '+%F %T')] stop msu10 / launcher"
bash scripts/linux/stop_paperbox_job.sh qs_sm12_marlow_msu10 || true
bash scripts/linux/stop_paperbox_job.sh qs_sm12_nh_msu10 || true
pkill -KILL -f launch_bcc_qs_msu10_smoke || true
pkill -KILL -f 'run_bcc_qs_material_probe.sh --smoke --only marlow_msu10' || true
pkill -KILL -f 'variant-suffix qs_sm12_marlow_msu10' || true
pkill -KILL -f 'variant-suffix qs_sm12_nh_msu10' || true
sleep 2
echo "remaining msu10:"
pgrep -af msu10 || echo none
echo "[$(date '+%F %T')] stop done"
