#!/usr/bin/env bash
# Q1.5 Fig.3.3 — thesis-aligned paper_box CAE run (SFBLS Q=1.5).
#
# Explicit in thesis / repo paper stack:
#   - geometry: paper_box 4×4×4, L=20 mm, d=2 mm, Q=1.5 (§2.1)
#   - mesh: CAE C3D4 seed 0.6 mm, lattice_curve, rods/d=4 (§2.4.1 + curved-strut refine)
#   - loading: 80% engineering strain @ 5 mm/min (Fig.3.3 axis; §2.4.2 rate)
#   - solver: Explicit dt=1e-4 fixed, mass scaling ×50 (repo paper defaults)
#   - material: Marlow + Fig.2.5 WPD uniaxial (§2.3.2 → hyperelastic)
#   - contact: self-contact ON, μ=0.1, STORE OFFSETS + ContactSettle 5%
#
#   bash scripts/linux/run_paperbox_q15_fig33_paper.sh
#   nohup bash scripts/linux/run_paperbox_q15_fig33_paper.sh \
#     >> output/logs/q15_fig33_paper.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q15_fig33_paper.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
CPUS="${Q15_FIG33_CPUS:-48}"
MEM="${Q15_FIG33_MEMORY_MB:-262144}"
SUFFIX="q15_fig33_paper"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"

CONTACT_ARGS=(
  --contact-store-offsets
  --contact-settle
  --contact-settle-fraction 0.05
  --contact-settle-soft-s0 0.02
)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25"; exit 1; }
CAD="output/cad/verified/hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step"
[[ -f "$CAD" ]] || { log "ERROR missing CAD: $CAD"; exit 1; }

SLUG="hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"

log "=== Q1.5 fig33_paper export cpus=$CPUS mem=$MEM slug=$SLUG ==="
log "  mesh: C3D4 seed=0.6 lattice_curve r=4 (force-remesh)"
log "  solver: strain=80% rate=5mm/min dt=1e-4 fixed Marlow+settle5p self-contact ON"

rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$SUFFIX" \
  --cae-seed 0.6 --cae-element-type C3D4 \
  --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 \
  --force-remesh \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --strain 0.80 --load-rate-mm-min 5 \
  --explicit-dt 0.0001 --explicit-dt-mode fixed \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25" \
  --export-only

INP="output/export/${SLUG}/${SLUG}.inp"
[[ -f "$INP" ]] || { log "ERROR export missing $INP"; exit 1; }

python3 -c "
import json, re
p='$INP'
txt=open(p,encoding='utf-8',errors='replace').read()
checks={
  'ContactSettle': 'ContactSettle' in txt,
  'STORE_OFFSETS': 'STORE OFFSETS' in txt,
  'Marlow': bool(re.search(r'\\*Hyperelastic, MARLOW', txt, re.I)),
  'dt_1e-4': '0.0001' in txt or '1.e-04' in txt.lower(),
}
print(json.dumps(checks, indent=2))
for k,v in checks.items():
    if not v:
        raise SystemExit(f'INP check failed: {k}')
" | tee -a "$LOG"

log "=== submit background slug=$SLUG ==="
bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$SUFFIX" \
  --cae-seed 0.6 --cae-element-type C3D4 \
  --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --strain 0.80 --load-rate-mm-min 5 \
  --explicit-dt 0.0001 --explicit-dt-mode fixed \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25" \
  --submit-only --submit-background

log "=== submitted $SLUG ==="
log "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
