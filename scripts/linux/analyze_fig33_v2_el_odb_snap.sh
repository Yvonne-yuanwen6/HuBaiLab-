#!/usr/bin/env bash
# Analyze fig33_v2_el ODB deformation spread + snap on existing CSV.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

SLUG="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el"
ODB="output/jobs/${SLUG}/${SLUG}.odb"
LOG="output/logs/fig33_v2_el_odb_snap_analysis.log"
OUT="output/logs/fig33_v2_el_odb_snap_analysis.json"

mkdir -p output/logs
exec > >(tee -a "$LOG") 2>&1
echo "=== fig33_v2_el ODB snap analysis $(date) ==="

if [[ ! -f "$ODB" ]]; then
  echo "Missing ODB: $ODB"
  exit 1
fi

ABQ=""
command -v abq >/dev/null && ABQ=abq || ABQ=abaqus

# step times for engineering strain (80% stroke in 768 s): t = eps/0.8*768
STRAIN_FRAMES="288 480 624 691 729"
$ABQ python scripts/peek_odb_u3_spread_py2.py "$ODB" Compression $STRAIN_FRAMES

echo "--- snap detect on post CSV ---"
python3 -c "
import csv, json, sys
sys.path.insert(0, '.')
from scripts.analyze_paperbox_snapthrough import detect_snapthrough
from src.paths import ABAQUS_POST
slug = '$SLUG'
p = ABAQUS_POST / slug / f'{slug}_stress_strain.csv'
rows = list(csv.DictReader(open(p, encoding='utf-8')))
eps = [float(r['engineering_strain']) for r in rows]
sig = [float(r['engineering_stress_MPa']) for r in rows]
snap = detect_snapthrough(eps, sig, band_lo=0.65, band_hi=0.78)
out = {'slug': slug, **snap}
json.dump(out, open('$OUT', 'w'), indent=2)
print(json.dumps(out, indent=2))
"
python3 scripts/evaluate_paperbox_q05_trend.py --slug "$SLUG" --write-json output/logs/eval_q05_fig33_v2_el_recheck.json || true

echo "=== done log=$LOG ==="
