#!/usr/bin/env bash
# Q1.5 Fig.3.3 — fast path: reuse baseline CAE mesh + automatic dt.
#
# Skips heavy lattice_curve r=4 remesh (~30–90+ min). Reuses completed baseline mesh
# (lattice_contact r=3, ~1.3M C3D4). Solver: Marlow + self-contact + settle5p,
# explicit dt=5e-4 automatic (vs fixed 1e-4 on strict paper run).
#
#   bash scripts/linux/run_paperbox_q15_fig33_fast.sh
#   nohup bash scripts/linux/run_paperbox_q15_fig33_fast.sh \
#     >> output/logs/q15_fig33_fast.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q15_fig33_fast.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
CPUS="${Q15_FIG33_CPUS:-48}"
MEM="${Q15_FIG33_MEMORY_MB:-262144}"
SUFFIX="q15_fig33_fast"
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

BASE_SLUG="hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
BASE_MESH="output/export/${BASE_SLUG}/${BASE_SLUG}_cae_mesh.inp"
[[ -f "$BASE_MESH" ]] || { log "ERROR missing baseline mesh: $BASE_MESH"; exit 1; }

SLUG="hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"

log "=== Q1.5 fig33_fast export+submit cpus=$CPUS mem=$MEM slug=$SLUG ==="
log "  mesh: REUSE baseline $BASE_MESH (~1.3M C3D4 lattice_contact r=3)"
log "  solver: strain=80% rate=5mm/min dt=5e-4 automatic Marlow+settle5p self-contact ON"

rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$SUFFIX" \
  --cae-seed 0.6 --cae-element-type C3D4 \
  --cae-mesh-quality lattice_contact --cae-rods-per-diameter 3 \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --strain 0.80 --load-rate-mm-min 5 \
  --explicit-dt 0.0005 --explicit-dt-mode automatic \
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
  'dt_automatic': 'automatic' in txt.lower() or '0.0005' in txt,
}
print(json.dumps(checks, indent=2))
for k,v in checks.items():
    if not v:
        raise SystemExit(f'INP check failed: {k}')
" | tee -a "$LOG"

log "=== submit background slug=$SLUG ==="
bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$SUFFIX" \
  --cae-seed 0.6 --cae-element-type C3D4 \
  --cae-mesh-quality lattice_contact --cae-rods-per-diameter 3 \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --strain 0.80 --load-rate-mm-min 5 \
  --explicit-dt 0.0005 --explicit-dt-mode automatic \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25" \
  --submit-only --submit-background

log "=== submitted $SLUG ==="
log "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
