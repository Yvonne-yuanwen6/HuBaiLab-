#!/usr/bin/env bash
# Q1 OCP444 CAD -> fig33_v2_marlow (Marlow + Fig.2.5 + ContactSettle 5%).
#
#   bash scripts/linux/run_q1_ocp444_fig33_v2_marlow.sh
#   nohup bash scripts/linux/run_q1_ocp444_fig33_v2_marlow.sh >> output/logs/q1_ocp444_fig33_v2_marlow.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q1_ocp444_fig33_v2_marlow.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
SUFFIX="fig33_v2_marlow"
SLUG="hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"
CPUS="${Q1_FIG33_MARLOW_CPUS:-48}"
MEM="${Q1_FIG33_MARLOW_MEMORY_MB:-262144}"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"

CONTACT_ARGS=(
  --contact-store-offsets
  --contact-settle
  --contact-settle-fraction 0.05
  --contact-settle-soft-s0 0.02
)

exec > >(tee -a "$LOG") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

CAD="output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
BASE_MESH="output/export/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"

log "Q1 OCP444 $SUFFIX cpus=$CPUS slug=$SLUG"
[[ -f "$CAD" ]] || { log "ERROR missing CAD: $CAD"; exit 1; }
[[ -f "$BASE_MESH" ]] || { log "ERROR missing baseline mesh: $BASE_MESH"; exit 1; }
[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25"; exit 1; }

log "Clear stale marlow export/job if any..."
rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 1 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --export-only \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25"

bash "$VARIANT_SH" --Q 1 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --submit-background --submit-only \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25"

log "submitted $SLUG (parallel with fig33_v2_el OK)"
grep -c ContactSettle "output/export/${SLUG}/${SLUG}.inp" | xargs -I{} echo "[$(date '+%Y-%m-%d %H:%M:%S')] ContactSettle blocks: {}" | tee -a "$LOG"
grep -A3 'Hyperelastic\|Uniaxial' "output/export/${SLUG}/${SLUG}.inp" | head -10 | tee -a "$LOG" || true
log "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
