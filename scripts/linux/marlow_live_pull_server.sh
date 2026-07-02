#!/usr/bin/env bash
# readOnly live extract marlow partial curve (history RF3).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"

SLUG="${1:-hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow}"
ODB="output/jobs/${SLUG}/${SLUG}.odb"
META="output/export/${SLUG}/${SLUG}_meta.json"
CSV="output/post/${SLUG}/${SLUG}_stress_strain_partial.csv"

[[ -f "$ODB" ]] || { echo "[skip] no ODB yet"; exit 0; }
[[ -f "$META" ]] || { echo "[skip] no meta"; exit 1; }
mkdir -p "output/post/${SLUG}"

abq python "$ROOT/scripts/extract_live_odb_history_py2.py" "$ODB" "$META" "$CSV"
