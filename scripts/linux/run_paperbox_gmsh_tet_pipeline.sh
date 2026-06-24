#!/usr/bin/env bash
# Gmsh C3D4 mesh + export INP + submit BCC paper_box_array case (self-contact ON).
#   bash scripts/linux/run_paperbox_gmsh_tet_pipeline.sh
#   bash scripts/linux/run_paperbox_gmsh_tet_pipeline.sh --force-remesh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

FORCE_REMESH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-remesh) FORCE_REMESH=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--force-remesh]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

SLUG="hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_gmsh0p6mm80_5mmin_paperbox"
LOG="output/logs/paperbox_gmsh_tet_pipeline.log"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
EXPORT_DIR="output/export/${SLUG}"
JOB_DIR="output/jobs/${SLUG}"

exec > >(tee -a "$LOG") 2>&1

echo ""
echo "=== paperbox Gmsh tet pipeline start $(date) force_remesh=$FORCE_REMESH ==="
echo "ROOT=$ROOT"

[[ -f "$CAD" ]] || { echo "Missing CAD: $CAD"; exit 1; }

if [[ "$FORCE_REMESH" -eq 1 ]]; then
  echo "Removing prior export/job artifacts ..."
  rm -rf "$EXPORT_DIR" "$JOB_DIR"
fi

python3 scripts/run_hu_bai_bcc_solid_cad_export.py \
  --cells 4 --Q 0 --profile fast \
  --cad "$CAD" \
  --mesh-method tet \
  --mesh-size 0.6 \
  --strain 0.80 \
  --load-rate-mm-min 5 \
  --explicit-dt 0.0005 \
  --explicit-dt-mode automatic \
  --material-model paper \
  --case-suffix gmsh0p6mm80_5mmin_paperbox

echo "=== submit $(date) slug=$SLUG ==="
bash scripts/linux/submit_job.sh \
  --slug "$SLUG" \
  --cpus 48 \
  --memory-mb 262144

echo "=== pipeline finished $(date) ==="
