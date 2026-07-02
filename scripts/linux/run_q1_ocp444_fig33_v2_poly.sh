#!/usr/bin/env bash
# Q1 OCP444 CAD -> fig33_v2_poly (Polynomial order-1 test-data hyperelastic + Fig.2.5).
#
#   bash scripts/linux/run_q1_ocp444_fig33_v2_poly.sh
#   nohup bash scripts/linux/run_q1_ocp444_fig33_v2_poly.sh >> output/logs/q1_ocp444_fig33_v2_poly.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q1_ocp444_fig33_v2_poly.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
SUFFIX="fig33_v2_poly"
SLUG="hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"
CPUS="${Q1_FIG33_POLY_CPUS:-48}"
MEM="${Q1_FIG33_POLY_MEMORY_MB:-262144}"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"

exec > >(tee -a "$LOG") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

CAD="output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
BASE_MESH="output/export/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"

log "Q1 OCP444 $SUFFIX cpus=$CPUS slug=$SLUG"
[[ -f "$CAD" ]] || { log "ERROR missing CAD: $CAD"; exit 1; }
[[ -f "$BASE_MESH" ]] || { log "ERROR missing baseline mesh: $BASE_MESH"; exit 1; }
[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25"; exit 1; }

log "Clear stale poly export/job if any..."
rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 1 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --export-only \
  --contact-store-offsets \
  --material-model polynomial \
  --tpu-fig25-json "$FIG25"

bash "$VARIANT_SH" --Q 1 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --submit-background --submit-only \
  --contact-store-offsets \
  --material-model polynomial \
  --tpu-fig25-json "$FIG25"

log "submitted $SLUG"
grep -A5 '^\*Material, name=TPU' "output/export/${SLUG}/${SLUG}.inp" | head -12 | tee -a "$LOG" || true
log "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
