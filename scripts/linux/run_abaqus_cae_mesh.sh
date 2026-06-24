#!/usr/bin/env bash
# Run Abaqus/CAE built-in mesh (C3D4 tet or hex) on Linux server.
# Usage:
#   bash scripts/linux/run_abaqus_cae_mesh.sh \
#     --step output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.step \
#     --out output/export/cae_hex_pilot/bcc_cae_tet_mesh.inp \
#     --seed 0.6 --mesh-mode tet --part-name LATTICE
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STEP=""
OUT=""
SEED="1.2"
PART_NAME="LATTICE"
MESH_MODE="tet"
MESH_QUALITY="lattice_contact"
ROD_DIAMETER="2.0"
RODS_PER_DIAMETER="3.0"
MERGE_SOLIDS=0
VIRTUAL_TOPOLOGY=0

usage() {
  echo "Usage: $0 --step STEP --out OUT [--seed MM] [--mesh-mode tet|hex]"
  echo "       [--mesh-quality fast|lattice|lattice_contact|paper] [--rod-diameter MM]"
  echo "       [--rods-per-diameter N] [--part-name NAME] [--merge-solids]"
  echo "       [--virtual-topology] [--vtopo-small-face MM2] [--vtopo-short-edge MM]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --step) STEP="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --part-name) PART_NAME="$2"; shift 2 ;;
    --mesh-mode) MESH_MODE="$2"; shift 2 ;;
    --mesh-quality) MESH_QUALITY="$2"; shift 2 ;;
    --rod-diameter) ROD_DIAMETER="$2"; shift 2 ;;
    --rods-per-diameter) RODS_PER_DIAMETER="$2"; shift 2 ;;
    --merge-solids) MERGE_SOLIDS=1; shift ;;
    --virtual-topology) VIRTUAL_TOPOLOGY=1; shift ;;
    --vtopo-small-face) export HU_BAI_VTOPO_SMALL_FACE="$2"; shift 2 ;;
    --vtopo-short-edge) export HU_BAI_VTOPO_SHORT_EDGE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ -n "$STEP" && -n "$OUT" ]] || usage

if [[ "$STEP" != /* ]]; then STEP="$ROOT/$STEP"; fi
if [[ "$OUT" != /* ]]; then OUT="$ROOT/$OUT"; fi

[[ -f "$STEP" ]] || { echo "STEP not found: $STEP"; exit 1; }

ABQ=""
if command -v abq >/dev/null; then
  ABQ=abq
elif command -v abaqus >/dev/null; then
  ABQ=abaqus
else
  echo "Neither abq nor abaqus in PATH. Try: bash scripts/linux/setup_abaqus_env.sh"
  exit 1
fi

OUT_DIR="$(dirname "$OUT")"
mkdir -p "$OUT_DIR"

export HU_BAI_ROOT="$ROOT"
export HU_BAI_STEP="$STEP"
export HU_BAI_OUT="$OUT"
export HU_BAI_SEED="$SEED"
export HU_BAI_PART_NAME="$PART_NAME"
export HU_BAI_MESH_MODE="$MESH_MODE"
export HU_BAI_MESH_QUALITY="$MESH_QUALITY"
export HU_BAI_ROD_DIAMETER="$ROD_DIAMETER"
export HU_BAI_RODS_PER_DIAMETER="$RODS_PER_DIAMETER"
if [[ "$MERGE_SOLIDS" -eq 1 ]]; then export HU_BAI_MERGE_SOLIDS=1; else unset HU_BAI_MERGE_SOLIDS; fi
if [[ "$VIRTUAL_TOPOLOGY" -eq 1 ]]; then export HU_BAI_VIRTUAL_TOPOLOGY=1; else unset HU_BAI_VIRTUAL_TOPOLOGY; fi

echo "=== CAE mesh (Linux) ==="
echo "  STEP: $STEP"
echo "  seed: ${SEED} mm  mode: $MESH_MODE  quality: $MESH_QUALITY  part: $PART_NAME  vtopo: $VIRTUAL_TOPOLOGY"
echo "  OUT:  $OUT"

cd "$ROOT"
"$ABQ" cae noGUI=scripts/abaqus_cae_hex_mesh_pilot.py

[[ -f "$OUT" ]] || { echo "Mesh INP not written: $OUT"; exit 1; }
if ! grep -q '^\*Node' "$OUT"; then
  echo "Mesh INP has no *Node section: $OUT"
  exit 1
fi
echo "OK: $OUT"
