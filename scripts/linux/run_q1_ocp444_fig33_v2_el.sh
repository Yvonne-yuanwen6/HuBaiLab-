#!/usr/bin/env bash
# Q1 OCP444 CAD -> fig33_v2_el (elastic + store offsets, nosettle).
#
#   bash scripts/linux/run_q1_ocp444_fig33_v2_el.sh
#   nohup bash scripts/linux/run_q1_ocp444_fig33_v2_el.sh >> output/logs/q1_ocp444_fig33_v2_el.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q1_ocp444_fig33_v2_el.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
SLUG="hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el"
CPUS="${Q1_FIG33_V2_CPUS:-48}"
MEM="${Q1_FIG33_V2_MEMORY_MB:-262144}"

exec > >(tee -a "$LOG") 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Q1 OCP444 fig33_v2_el cpus=$CPUS slug=$SLUG"

CAD="output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
BASE_MESH="output/export/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"
[[ -f "$CAD" ]] || { echo "Missing CAD: $CAD"; exit 1; }
[[ -f "$BASE_MESH" ]] || { echo "Missing baseline mesh: $BASE_MESH"; exit 1; }

echo "Clear stale fig33_v2_el export/job (old CAD)..."
rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 1 --variant-suffix fig33_v2_el \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --export-only

bash "$VARIANT_SH" --Q 1 --variant-suffix fig33_v2_el \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --submit-background --submit-only

echo "[$(date '+%Y-%m-%d %H:%M:%S')] submitted $SLUG"
echo "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
