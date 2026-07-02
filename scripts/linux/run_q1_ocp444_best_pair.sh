#!/usr/bin/env bash
# Q1 OCP cell_glue 444 → remesh baseline → submit best two contact variants.
#
#   bash scripts/linux/run_q1_ocp444_best_pair.sh
#   nohup bash scripts/linux/run_q1_ocp444_best_pair.sh >> output/logs/q1_ocp444_best_pair.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/cad/verified

LOG="output/logs/q1_ocp444_best_pair.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
Q="1"
CPUS="${Q1_OCP444_CPUS:-24}"
MEM="${Q1_OCP444_MEMORY_MB:-131072}"

CAD_SRC="output/cad/_paper_box_array_q1p0_ocp/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
CAD_DST="output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
BASE_SUFFIX="cae_tet0p6mm80_5mmin_paperbox"
LATTICE_SLUG="hu_bai_sfbls_af2q1_L20_4x4x4"
BASELINE_SLUG="${LATTICE_SLUG}_solid_cad_f_${BASE_SUFFIX}"
BASELINE_MESH="output/export/${BASELINE_SLUG}/${BASELINE_SLUG}_cae_mesh.inp"

exec > >(tee -a "$LOG") 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "=== Q1 OCP444 best-pair start cpus=$CPUS mem_mb=$MEM ==="

[[ -f "$CAD_SRC" ]] || { log "Missing OCP444 CAD: $CAD_SRC"; exit 1; }

log "Install verified CAD from OCP444"
cp -f "$CAD_SRC" "$CAD_DST"
ls -lh "$CAD_DST"

log "Clear baseline mesh + old Q1 variant exports/jobs (new geometry)"
rm -f "$BASELINE_MESH" \
  "output/export/${BASELINE_SLUG}/${BASELINE_SLUG}.inp" \
  "output/export/${BASELINE_SLUG}/${BASELINE_SLUG}_meta.json" \
  "output/export/${BASELINE_SLUG}/case_manifest.json"
rm -rf "output/jobs/${BASELINE_SLUG}"
for suffix in paperbox_settle5p paperbox_nosettle; do
  slug="${LATTICE_SLUG}_solid_cad_f_${BASE_SUFFIX}_${suffix}"
  rm -rf "output/export/${slug}" "output/jobs/${slug}"
done

log "Fresh baseline CAE mesh (seed=0.6, lattice_contact, store_offsets settle15%)"
EXPORT_ARGS=(
  scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
  --cells 4 --Q "$Q" --profile fast
  --cad "$CAD_DST"
  --cae-seed 0.6
  --cae-mesh-quality lattice_contact
  --strain 0.80 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --material-model paper
  --contact-store-offsets
  --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02
  --case-suffix "$BASE_SUFFIX"
  --cae-virtual-topology
  --mesh-locally
)
python3 "${EXPORT_ARGS[@]}"
[[ -f "$BASELINE_MESH" ]] || { log "Baseline mesh missing: $BASELINE_MESH"; exit 1; }
log "Baseline mesh OK: $BASELINE_MESH"

run_variant() {
  local suffix="$1"
  shift
  local slug="${LATTICE_SLUG}_solid_cad_f_${BASE_SUFFIX}_${suffix}"
  log "=== variant $suffix slug=$slug ==="
  bash "$VARIANT_SH" --Q "$Q" --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --export-only "$@"
  bash "$VARIANT_SH" --Q "$Q" --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --submit-background --submit-only "$@"
  log "Submitted (background) $suffix"
}

# Best pair: orchestrator winner + snap-through baseline B
run_variant "paperbox_settle5p" \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02

run_variant "paperbox_nosettle" \
  --contact-store-offsets

log "=== Q1 OCP444 best-pair launch done ==="
log "Slugs:"
log "  ${LATTICE_SLUG}_solid_cad_f_${BASE_SUFFIX}_paperbox_settle5p"
log "  ${LATTICE_SLUG}_solid_cad_f_${BASE_SUFFIX}_paperbox_nosettle"
log "Watch: bash scripts/linux/watch_job_progress.sh --slug <slug>"
