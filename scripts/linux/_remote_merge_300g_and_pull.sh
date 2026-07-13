#!/usr/bin/env bash
# Merge 300g full + mid sweeps, plot PNGs, print peak summary.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

FULL_SLUG="comsol_fig321_bcc_444_mesh_p1_300g_f1_300"
MID_SLUG="comsol_fig321_bcc_444_mesh_p1_300g_mid"
OUT_DIR="output/comsol_jobs/fig321_composite"
MERGED_SLUG="comsol_fig321_bcc_444_mesh_p1_300g_merged"

FULL_CSV="output/comsol_jobs/${FULL_SLUG}/${FULL_SLUG}_transmissibility.csv"
MID_CSV="output/comsol_jobs/${MID_SLUG}/${MID_SLUG}_transmissibility.csv"

[[ -f "$FULL_CSV" ]] || { echo "ERROR: missing $FULL_CSV"; exit 1; }
[[ -f "$MID_CSV" ]] || { echo "ERROR: missing $MID_CSV"; exit 1; }

python3 scripts/merge_comsol_freq_csvs.py \
  "$FULL_CSV" "$MID_CSV" \
  --out-dir "$OUT_DIR" \
  --slug "$MERGED_SLUG" \
  --title "BCC P1 + 300g  VLD 1-300 Hz (mid-band refined)" \
  --paper-bcc

python3 scripts/compare_freq_peaks_vs_paper.py --key bcc --jobs-root "$ROOT/output/comsol_jobs" 2>/dev/null || true

echo "=== merged outputs ==="
ls -lh "$OUT_DIR/${MERGED_SLUG}"* 2>/dev/null
