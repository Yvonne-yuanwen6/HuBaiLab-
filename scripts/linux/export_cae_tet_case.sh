#!/usr/bin/env bash
# Export one CAE-tet compression case on the Linux server (mesh runs locally on server).
# Usage:
#   bash scripts/linux/export_cae_tet_case.sh --Q 0.5 --cae-seed 0.6 \
#     --case-suffix cae_tet0p6mm80_5mmin_paper --strain 0.8 --load-rate-mm-min 5 \
#     --explicit-dt 0.0001 --no-mass-scaling --material-model paper
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

Q=""
CASE_SUFFIX=""
CAE_SEED="0.6"
CAE_MESH_QUALITY="lattice_contact"
STRAIN=""
LOAD_RATE=""
EXPLICIT_DT=""
EXPLICIT_DT_MODE="fixed"
NO_MASS=0
MATERIAL="paper"
PROFILE="fast"
CELLS=4
EXTRA=()

usage() {
  echo "Usage: $0 --Q Q --case-suffix SUFFIX [options]"
  echo "  --cae-seed MM  --cae-mesh-quality fast|lattice|paper"
  echo "  --strain F  --load-rate-mm-min F"
  echo "  --explicit-dt F  --explicit-dt-mode fixed|automatic"
  echo "  --no-mass-scaling  --material-model paper|elastic_plastic"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --Q) Q="$2"; shift 2 ;;
    --case-suffix) CASE_SUFFIX="$2"; shift 2 ;;
    --cae-seed) CAE_SEED="$2"; shift 2 ;;
    --cae-mesh-quality) CAE_MESH_QUALITY="$2"; shift 2 ;;
    --strain) STRAIN="$2"; shift 2 ;;
    --load-rate-mm-min) LOAD_RATE="$2"; shift 2 ;;
    --explicit-dt) EXPLICIT_DT="$2"; shift 2 ;;
    --explicit-dt-mode) EXPLICIT_DT_MODE="$2"; shift 2 ;;
    --material-model) MATERIAL="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --cells) CELLS="$2"; shift 2 ;;
    --no-mass-scaling) NO_MASS=1; shift ;;
    -h|--help) usage ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

[[ -n "$Q" && -n "$CASE_SUFFIX" ]] || usage

PY=""
if command -v python3 >/dev/null; then PY=python3
elif command -v py >/dev/null; then PY=py
else echo "python3 not found"; exit 1
fi

ARGS=(
  scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
  --cells "$CELLS"
  --Q "$Q"
  --profile "$PROFILE"
  --cae-seed "$CAE_SEED"
  --cae-mesh-quality "$CAE_MESH_QUALITY"
  --case-suffix "$CASE_SUFFIX"
  --mesh-locally
  --material-model "$MATERIAL"
  --explicit-dt-mode "$EXPLICIT_DT_MODE"
)
[[ -n "$STRAIN" ]] && ARGS+=(--strain "$STRAIN")
[[ -n "$LOAD_RATE" ]] && ARGS+=(--load-rate-mm-min "$LOAD_RATE")
[[ -n "$EXPLICIT_DT" ]] && ARGS+=(--explicit-dt "$EXPLICIT_DT")
[[ "$NO_MASS" -eq 1 ]] && ARGS+=(--no-mass-scaling)
ARGS+=("$EXTRA")

echo "=== export CAE tet Q=$Q suffix=$CASE_SUFFIX (server-local mesh) ==="
if [[ "$PY" == py ]]; then
  py -3 "${ARGS[@]}"
else
  python3 "${ARGS[@]}"
fi
