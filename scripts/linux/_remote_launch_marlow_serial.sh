#!/usr/bin/env bash
set -euo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

sed -i 's/\r$//' scripts/linux/run_fig33_v2_marlow_serial.sh 2>/dev/null || true
chmod +x scripts/linux/run_fig33_v2_marlow_serial.sh

LOG="output/logs/fig33_v2_marlow_serial.log"
LOCK="output/logs/fig33_v2_marlow_serial.lock"

if pgrep -f 'bash scripts/linux/run_fig33_v2_marlow_serial.sh' >/dev/null 2>&1; then
  echo "Already running:"
  pgrep -af 'run_fig33_v2_marlow_serial'
  exit 0
fi

mkdir -p output/logs
echo "[$(date -Iseconds)] launch fig33_v2_marlow serial (Q=1.5,0.5,1,0) cpus=${FIG33_V2_CPUS:-48}" >> "$LOG"

nohup env FIG33_V2_CPUS="${FIG33_V2_CPUS:-48}" \
  FIG33_V2_MEMORY_MB="${FIG33_V2_MEMORY_MB:-262144}" \
  FIG33_V2_MAX_PARALLEL=1 \
  bash scripts/linux/run_fig33_v2_marlow_serial.sh >> "$LOG" 2>&1 &

sleep 3
echo "=== launched pid=$! ==="
pgrep -af 'run_fig33_v2_marlow_serial' | grep -v pgrep || true
tail -8 "$LOG"
