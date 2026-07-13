#!/usr/bin/env bash
set -uo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"
SLUG=hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow

echo "=== before ==="
pgrep -af run_fig33_v2_marlow_serial || echo none
pgrep -af "$SLUG" || echo none slug

pkill -9 -f run_fig33_v2_marlow_serial 2>/dev/null || true
ps aux | awk -v s="$SLUG" '/SMAPython|\/bin\/explicit|mpiexec|mpirun/ && index($0,s) {print $2}' | xargs -r kill -9 2>/dev/null || true
sleep 2

rm -rf "output/jobs/${SLUG}" "output/export/${SLUG}"
rm -f output/logs/fig33_v2_marlow_serial.lock

echo "=== after ==="
pgrep -af run_fig33_v2_marlow_serial || echo none
pgrep -af "$SLUG" || echo none slug
ls output/jobs/${SLUG} 2>&1 || true
