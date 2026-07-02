#!/usr/bin/env bash
# Q0.5 Fig.3.3 — Marlow + ContactSettle 5% (fix nosettle contact hang).
#
# V2 + settle5p (same slug fig33_v2_marlow — shorter path than *_settle5p suffix).
# contact + STORE OFFSETS alone loops on unresolved overclosure (~0.2–0.3 mm).
#
# V2 + settle5p: STORE OFFSETS, ContactSettle 5% (soft s0=0.02), self-contact ON,
# 80% strain, 5 mm/min. Material: Marlow + Fig.2.5 WPD uniaxial test data.
#
#   bash scripts/linux/run_paperbox_q05_fig33_v2_marlow.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/paperbox_q05_fig33_v2_marlow.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
CPUS="${Q05_V2_CPUS:-48}"
MEM="${Q05_V2_MEMORY_MB:-262144}"
SUFFIX="fig33_v2_marlow"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"

CONTACT_ARGS=(
  --contact-store-offsets
  --contact-settle
  --contact-settle-fraction 0.05
  --contact-settle-soft-s0 0.02
)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25 — run import_webplotdigitizer_tpu_fig25.py"; exit 1; }

log "=== Q05 $SUFFIX export+submit cpus=$CPUS (Marlow + settle5p) ==="
bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --export-only \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25"

bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --submit-only \
  "${CONTACT_ARGS[@]}" \
  --material-model marlow \
  --tpu-fig25-json "$FIG25"

SLUG="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"
log "=== submitted slug=$SLUG ==="
grep -c ContactSettle "output/export/${SLUG}/${SLUG}.inp" | xargs -I{} echo "ContactSettle blocks: {}" | tee -a "$LOG"
grep -A2 'Hyperelastic\|Uniaxial' "output/export/${SLUG}/${SLUG}.inp" | head -8 | tee -a "$LOG" || true
