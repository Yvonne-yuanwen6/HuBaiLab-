#!/usr/bin/env bash
set -euo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

pkill -f 'bash scripts/linux/run_fig33_v2_marlow_serial.sh' 2>/dev/null || true
sleep 2
rm -f output/logs/fig33_v2_marlow_serial.lock

SLUG=hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow
rm -rf "output/jobs/${SLUG}"
rm -rf "output/export/${SLUG}"

LOG="output/logs/fig33_v2_marlow_serial.log"
echo "[$(date -Iseconds)] clean relaunch Q1.5+ after marlow column fix" >> "$LOG"

nohup env FIG33_V2_CPUS=48 FIG33_V2_MEMORY_MB=262144 FIG33_V2_MAX_PARALLEL=1 \
  bash scripts/linux/run_fig33_v2_marlow_serial.sh >> "$LOG" 2>&1 &

sleep 8
tail -10 "$LOG"
