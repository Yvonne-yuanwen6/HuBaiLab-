#!/usr/bin/env bash
# Full-curve extract (Py2 readOnly) for completed paperbox jobs on server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"

extract_one() {
  local slug="$1"
  local odb="output/jobs/${slug}/${slug}.odb"
  local meta="output/export/${slug}/${slug}_meta.json"
  local post="output/post/${slug}"
  local csv="${post}/${slug}_stress_strain.csv"
  [[ -f "$odb" && -f "$meta" ]] || { echo "skip missing $slug"; return 1; }
  mkdir -p "$post"
  echo "=== extract $slug ==="
  abq python "$ROOT/scripts/extract_live_odb_server_py2.py" \
    "$odb" "$meta" "$csv"
  wc -l "$csv"
}

SLUGS=(
  hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox
  hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle
  hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p
  hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox
  hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p
)

for slug in "${SLUGS[@]}"; do
  extract_one "$slug" || true
done
