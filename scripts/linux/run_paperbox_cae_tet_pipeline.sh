#!/usr/bin/env bash
# Server pipeline: CAE mesh + export INP + submit paper_box_array case (BCC or SFBLS).
#   bash scripts/linux/run_paperbox_cae_tet_pipeline.sh
#   bash scripts/linux/run_paperbox_cae_tet_pipeline.sh --Q 0.5
#   bash scripts/linux/run_paperbox_cae_tet_pipeline.sh --force-remesh
#   bash scripts/linux/run_paperbox_cae_tet_pipeline.sh --force-remesh --cae-mesh-quality paper
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

FORCE_REMESH=0
CAE_MESH_QUALITY="lattice_contact"
CAE_VIRTUAL_TOPOLOGY=1
Q="0"
CAD_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-remesh) FORCE_REMESH=1; shift ;;
    --cae-mesh-quality) CAE_MESH_QUALITY="$2"; shift 2 ;;
    --no-virtual-topology) CAE_VIRTUAL_TOPOLOGY=0; shift ;;
    --Q) Q="$2"; shift 2 ;;
    --cad) CAD_OVERRIDE="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--Q 0|0.5|1|1.5] [--cad PATH] [--force-remesh] [--cae-mesh-quality fast|lattice|lattice_contact|paper] [--no-virtual-topology]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

CASE_SUFFIX="cae_tet0p6mm80_5mmin_paperbox"
LATTICE_TAG="$(python3 -c "from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G; print(G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=float('$Q')).variant_name.lower())")"
LATTICE_SLUG="hu_bai_${LATTICE_TAG}_L20_4x4x4"
SLUG="${LATTICE_SLUG}_solid_cad_f_${CASE_SUFFIX}"
LOG="output/logs/${LATTICE_TAG}_paperbox_cae_tet_pipeline.log"
CAD="${CAD_OVERRIDE:-output/cad/verified/${LATTICE_SLUG}_paper_box_array.step}"
EXPORT_DIR="output/export/${SLUG}"
JOB_DIR="output/jobs/${SLUG}"
MESH_INP="${EXPORT_DIR}/${SLUG}_cae_mesh.inp"

exec > >(tee -a "$LOG") 2>&1

echo ""
echo "=== paperbox CAE tet pipeline start $(date) Q=$Q slug=$SLUG force_remesh=$FORCE_REMESH quality=$CAE_MESH_QUALITY vtopo=$CAE_VIRTUAL_TOPOLOGY store_offsets=1 settle=0.15 ==="
echo "ROOT=$ROOT"

[[ -f "$CAD" ]] || { echo "Missing CAD: $CAD"; exit 1; }

if [[ "$FORCE_REMESH" -eq 1 ]]; then
  echo "Removing cached CAE mesh and prior job artifacts ..."
  rm -f "$MESH_INP" "${EXPORT_DIR}/cae_hex_pilot.log" \
    "${EXPORT_DIR}/${SLUG}.inp" "${EXPORT_DIR}/${SLUG}_meta.json" \
    "${EXPORT_DIR}/case_manifest.json"
  rm -rf "$JOB_DIR"
else
  echo "Re-export only (reuse mesh); clearing prior job dir ..."
  rm -rf "$JOB_DIR"
fi

EXPORT_ARGS=(
  scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
  --cells 4 --Q "$Q" --profile fast
  --cad "$CAD"
  --cae-seed 0.6
  --cae-mesh-quality "$CAE_MESH_QUALITY"
  --strain 0.80 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --material-model paper
  --contact-store-offsets
  --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02
  --case-suffix "$CASE_SUFFIX"
  --mesh-locally
)
if [[ "$CAE_VIRTUAL_TOPOLOGY" -eq 1 ]]; then
  EXPORT_ARGS+=(--cae-virtual-topology)
fi
if [[ -f "$MESH_INP" ]]; then
  echo "Reusing CAE mesh INP: $MESH_INP"
  EXPORT_ARGS+=(--cae-mesh-inp "$MESH_INP")
else
  echo "Fresh CAE mesh @ seed=0.6 mm quality=$CAE_MESH_QUALITY ..."
fi

python3 "${EXPORT_ARGS[@]}"

echo "=== submit $(date) slug=$SLUG ==="
bash scripts/linux/submit_job.sh \
  --slug "$SLUG" \
  --cpus 48 \
  --memory-mb 262144

echo "=== pipeline finished $(date) ==="
