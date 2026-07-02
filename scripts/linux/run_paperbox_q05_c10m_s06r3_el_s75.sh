#!/usr/bin/env bash
# Q0.5 C3D10M seed0.6 r3 lattice_contact elastic @ 75% strain (reuse s45 mesh).
#
#   bash scripts/linux/run_paperbox_q05_c10m_s06r3_el_s75.sh
#   nohup bash scripts/linux/run_paperbox_q05_c10m_s06r3_el_s75.sh \
#     >> output/logs/q05_c10m_s06r3_el_s75.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/q05_c10m_s06r3_el_s75.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
SLUG="q05_c10m_s06r3_el_s75"
SRC_SLUG="q05_c10m_s06r3_el_s45"
MESH="output/export/${SRC_SLUG}/${SRC_SLUG}_cae_mesh.inp"
CPUS="${Q05_C10M_CPUS:-48}"
MEM="${Q05_C10M_MEMORY_MB:-262144}"
TARGET_STRAIN="${Q05_C10M_STRAIN:-0.75}"

exec > >(tee -a "$LOG") 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Q0.5 C3D10M s06r3 elastic s75 cpus=$CPUS strain=$TARGET_STRAIN slug=$SLUG"
echo "Reuse mesh: $MESH"

[[ -f "$MESH" ]] || { echo "Missing mesh from $SRC_SLUG: $MESH"; exit 1; }

rm -rf "output/export/$SLUG" "output/jobs/$SLUG"

bash "$VARIANT_SH" --Q 0.5 --short-slug "$SLUG" \
  --variant-suffix c10m_s06r3_el_s75 \
  --cae-seed 0.6 --cae-element-type C3D10M \
  --cae-mesh-quality lattice_contact --cae-rods-per-diameter 3 \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --strain "$TARGET_STRAIN" \
  --cae-mesh-inp "$MESH" \
  --export-only

bash "$VARIANT_SH" --Q 0.5 --short-slug "$SLUG" \
  --variant-suffix c10m_s06r3_el_s75 \
  --cae-seed 0.6 --cae-element-type C3D10M \
  --cae-mesh-quality lattice_contact --cae-rods-per-diameter 3 \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --contact-store-offsets --material-model elastic \
  --strain "$TARGET_STRAIN" \
  --cae-mesh-inp "$MESH" \
  --submit-background --submit-only

echo "[$(date '+%Y-%m-%d %H:%M:%S')] submitted $SLUG"
echo "Watch: bash scripts/linux/watch_job_progress.sh --slug $SLUG"
