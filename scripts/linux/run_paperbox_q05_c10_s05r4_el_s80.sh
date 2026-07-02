#!/usr/bin/env bash
# Q0.5 C3D10 seed0.5 r4 lattice_curve elastic @ 80% strain (Fig.3.3 full stroke).
#
#   bash scripts/linux/run_paperbox_q05_c10_s05r4_el_s80.sh
#   nohup bash scripts/linux/run_paperbox_q05_c10_s05r4_el_s80.sh \
#     >> output/logs/q05_c10_s05r4_el_s80.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q05_c10_s05r4_el_s80.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
SLUG="q05_c10_s05r4_el_s80"
CPUS="${Q05_C10_CPUS:-48}"
MEM="${Q05_C10_MEMORY_MB:-262144}"
TARGET_STRAIN="${Q05_C10_STRAIN:-0.80}"

exec > >(tee -a "$LOG") 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Q0.5 C3D10 s05r4 elastic s80 cpus=$CPUS strain=$TARGET_STRAIN slug=$SLUG"

CAD="output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
[[ -f "$CAD" ]] || { echo "Missing CAD: $CAD"; exit 1; }

echo "Clear stale export/job for $SLUG ..."
rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 0.5 --short-slug "$SLUG" \
  --variant-suffix c10_s05r4_el_s80 \
  --cae-seed 0.5 --cae-element-type C3D10 \
  --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 \
  --force-remesh \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --strain "$TARGET_STRAIN" \
  --export-only

bash "$VARIANT_SH" --Q 0.5 --short-slug "$SLUG" \
  --variant-suffix c10_s05r4_el_s80 \
  --cae-seed 0.5 --cae-element-type C3D10 \
  --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 \
  --force-remesh \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --strain "$TARGET_STRAIN" \
  --submit-background --submit-only

echo "[$(date '+%Y-%m-%d %H:%M:%S')] submitted $SLUG"
echo "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
