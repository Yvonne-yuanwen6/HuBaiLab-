#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

SLUGS=(
  hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p
  hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle
)

for slug in "${SLUGS[@]}"; do
  echo "=== extract $slug $(date) ==="
  mkdir -p "output/post/$slug"
  abq python scripts/extract_live_odb_server_py2.py \
    "output/jobs/$slug/$slug.odb" \
    "output/export/$slug/${slug}_meta.json" \
    "output/post/$slug/${slug}_stress_strain.csv"
  wc -l "output/post/$slug/${slug}_stress_strain.csv"
  tail -3 "output/post/$slug/${slug}_stress_strain.csv"
done
