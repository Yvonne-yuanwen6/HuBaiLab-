#!/usr/bin/env bash
# VLD postprocess for any comsol job slug (default: p1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1

SLUG="${1:-comsol_fig321_bcc_444_mesh_p1}"
JOB="output/comsol_jobs/${SLUG}"
SOLVED="${JOB}/${SLUG}_solved.mph"
LOG="output/logs/${SLUG}_postprocess.log"

mkdir -p output/logs

exec > >(tee -a "$LOG") 2>&1
echo "=== postprocess ${SLUG} $(date) ==="

if [[ ! -f "$SOLVED" ]]; then
  echo "ERROR: missing $SOLVED"
  exit 1
fi

python3 -u scripts/comsol_extract_isolation.py "$SOLVED"
python3 -u scripts/plot_comsol_vld.py "${JOB}/${SLUG}_transmissibility.csv" --paper-bcc
if [[ "${SKIP_FREQ_PLOTGROUPS:-0}" == "1" ]]; then
  python3 -u scripts/comsol_postprocess_thesis.py "$JOB" --slug "$SLUG" --no-harmonic-plots || true
else
  python3 -u scripts/comsol_postprocess_thesis.py "$JOB" --slug "$SLUG" || true
fi

echo "=== postprocess done $(date) ==="
ls -lh "$JOB"/*.{csv,png,json} 2>/dev/null || true
