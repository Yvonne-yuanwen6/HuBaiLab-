#!/usr/bin/env bash
# Re-extract VLD after patching probes integral→average (no re-solve).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

for SLUG in comsol_fig321_bcc_444_mesh_p1_f1_30 comsol_fig321_bcc_444_mesh_p1_f5_150; do
  SOLVED="output/comsol_jobs/${SLUG}/${SLUG}_solved.mph"
  echo "=== re-extract ${SLUG} (boundary AvSurface) ==="
  python3 scripts/comsol_extract_isolation.py "$SOLVED"
  python3 scripts/plot_comsol_vld.py \
    "output/comsol_jobs/${SLUG}/${SLUG}_transmissibility.csv" --paper-bcc
done

python3 scripts/merge_comsol_freq_csvs.py \
  output/comsol_jobs/comsol_fig321_bcc_444_mesh_p1_f5_150/comsol_fig321_bcc_444_mesh_p1_f5_150_transmissibility.csv \
  output/comsol_jobs/comsol_fig321_bcc_444_mesh_p1_f1_30/comsol_fig321_bcc_444_mesh_p1_f1_30_transmissibility.csv \
  --out-dir output/comsol_jobs/fig321_composite \
  --slug comsol_fig321_bcc_444_mesh_p1_merged_avg \
  --title "BCC P1  VLD 1-150 Hz (avg probes)" \
  --paper-bcc

echo "=== done ==="
