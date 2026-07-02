#!/usr/bin/env bash
# Q0.5 C3D10M seed0.5 r4 lattice_curve elastic @ 78% strain (fig33 snap baseline mesh).
#
#   bash scripts/linux/run_paperbox_q05_c10m_s05r4_el_s78.sh
#   nohup bash scripts/linux/run_paperbox_q05_c10m_s05r4_el_s78.sh \
#     >> output/logs/q05_c10m_s05r4_el_s78.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q05_c10m_s05r4_el_s78.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
SLUG="q05_c10m_s05r4_el_s78"
CPUS="${Q05_C10M_CPUS:-48}"
MEM="${Q05_C10M_MEMORY_MB:-262144}"
TARGET_STRAIN="${Q05_C10M_STRAIN:-0.78}"

exec > >(tee -a "$LOG") 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Q0.5 C3D10M s05r4 elastic s78 cpus=$CPUS strain=$TARGET_STRAIN slug=$SLUG"

CAD="output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
[[ -f "$CAD" ]] || { echo "Missing CAD: $CAD"; exit 1; }

echo "Clear stale export/job for $SLUG ..."
rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 0.5 --short-slug "$SLUG" \
  --variant-suffix c10m_s05r4_el_s78 \
  --cae-seed 0.5 --cae-element-type C3D10M \
  --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 \
  --force-remesh \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --strain "$TARGET_STRAIN" \
  --export-only

bash "$VARIANT_SH" --Q 0.5 --short-slug "$SLUG" \
  --variant-suffix c10m_s05r4_el_s78 \
  --cae-seed 0.5 --cae-element-type C3D10M \
  --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 \
  --force-remesh \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --strain "$TARGET_STRAIN" \
  --submit-background --submit-only

echo "[$(date '+%Y-%m-%d %H:%M:%S')] submitted $SLUG"
echo "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
