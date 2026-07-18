#!/usr/bin/env bash
# Rebuild Table 2.1 using ASPECT_RATIO threshold=3 (matches literature ~0.03% scale).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export HU_BAI_ASPECT_THR="${HU_BAI_ASPECT_THR:-3.0}"
mkdir -p output/reports/mesh_convergence/verify_aspect3 output/logs
LOG=output/logs/bcc_mesh_verify_aspect3.log
exec > >(tee -a "$LOG") 2>&1

echo "=== ASPECT_RATIO thr=$HU_BAI_ASPECT_THR $(date) ==="

# Keep in sync with src/mesh/bcc_mesh_validation.py
levels=(
  "0.6|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
  "0.7|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_07"
  "0.8|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_08"
  "0.9|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_09"
  "1.0|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_10"
  "1.1|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_11"
  "1.2|hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_12"
)

for item in "${levels[@]}"; do
  seed="${item%%|*}"
  slug="${item##*|}"
  inp="output/export/${slug}/${slug}_cae_mesh.inp"
  out="output/reports/mesh_convergence/verify_aspect3/${slug}.json"
  echo "--- seed=$seed ---"
  export HU_BAI_MESH_INP="$ROOT/$inp"
  export HU_BAI_OUT_JSON="$ROOT/$out"
  abq cae noGUI=scripts/abaqus_mesh_verify_aspect_ratio.py
done

python3 <<'PY'
import json
from pathlib import Path
ROOT=Path('.').resolve()
old={}
op=ROOT/'output/reports/mesh_convergence/bcc_mesh_quality_summary.json'
if op.is_file():
    for r in json.loads(op.read_text(encoding='utf-8')):
        old[str(r['mesh_size_mm'])]=r
rows=[]
for seed,slug in [
 ('0.6','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox'),
 ('0.7','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_07'),
 ('0.8','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_08'),
 ('0.9','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_09'),
 ('1.0','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_10'),
 ('1.1','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_11'),
 ('1.2','hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_12'),
]:
    v=json.loads((ROOT/'output/reports/mesh_convergence/verify_aspect3'/f'{slug}.json').read_text(encoding='utf-8'))
    o=old.get(seed,{})
    rows.append({
        'mesh_size_mm': float(seed),
        'total_number_of_meshes': v['numElements'],
        'warning_meshes': v['warning_meshes_literature'],
        'warning_pct': v['warning_pct'],
        'cpu_time_s': o.get('wall_time_s'),
        'wall_time': o.get('wall_time'),
        'criterion': 'ASPECT_RATIO',
        'threshold': v['threshold'],
        'average_aspect': v.get('average'),
        'worst_aspect': v.get('worst'),
        'slug': slug,
    })
out=ROOT/'output/reports/mesh_convergence/bcc_mesh_quality_literature.json'
out.write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(json.dumps(rows, indent=2))
print('WROTE', out)
PY
echo "=== done $(date) ==="
