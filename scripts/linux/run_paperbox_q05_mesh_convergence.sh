#!/usr/bin/env bash
# Q0.5 mesh convergence: lattice_curve + h-refinement.
#
#   bash scripts/linux/run_paperbox_q05_mesh_convergence.sh --mesh-only
#   bash scripts/linux/run_paperbox_q05_mesh_convergence.sh --submit
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/mesh_convergence

LOG="output/logs/paperbox_q05_mesh_convergence.log"
MESH_ONLY=0
SUBMIT=0
LEVEL_FILTER=""
CPUS="${MESH_CONV_CPUS:-48}"
MEM="${MESH_CONV_MEMORY_MB:-262144}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mesh-only) MESH_ONLY=1; shift ;;
    --submit) SUBMIT=1; shift ;;
    --level) LEVEL_FILTER="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEM="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--mesh-only] [--submit] [--level ID]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

readarray -t LEVEL_IDS < <(python3 -c "
from src.mesh.mesh_convergence import Q05_MESH_CONVERGENCE_LEVELS
filt = '${LEVEL_FILTER}'
for lv in Q05_MESH_CONVERGENCE_LEVELS:
    if filt and lv['id'] != filt:
        continue
    print(lv['id'])
")

if [[ ${#LEVEL_IDS[@]} -eq 0 ]]; then
  log "ERROR no levels"
  exit 1
fi

log "=== Q05 mesh convergence levels=${#LEVEL_IDS[@]} mesh_only=$MESH_ONLY submit=$SUBMIT ==="

for lid in "${LEVEL_IDS[@]}"; do
  log "--- $lid ---"
  if [[ "$MESH_ONLY" -eq 1 ]]; then
    python3 scripts/run_mesh_convergence_level.py --level "$lid" --export-only \
      --cpus "$CPUS" --memory-mb "$MEM" >> "$LOG" 2>&1 || log "WARN export failed $lid"
    continue
  fi

  python3 scripts/run_mesh_convergence_level.py --level "$lid" --export-only \
    --cpus "$CPUS" --memory-mb "$MEM" >> "$LOG" 2>&1 || { log "ERROR export $lid"; continue; }

  if [[ "$SUBMIT" -eq 1 ]]; then
    python3 scripts/run_mesh_convergence_level.py --level "$lid" --submit-only \
      --cpus "$CPUS" --memory-mb "$MEM" >> "$LOG" 2>&1 || log "WARN submit failed $lid"
    SLUG="$(python3 -c "from src.mesh.mesh_convergence import Q05_MESH_CONVERGENCE_LEVELS, slug_for_q05_level; print(slug_for_q05_level([x for x in Q05_MESH_CONVERGENCE_LEVELS if x['id']=='$lid'][0]))")"
    while [[ -f "$ROOT/output/jobs/${SLUG}/${SLUG}.lck" ]]; do
      log "WAIT $SLUG"
      sleep 120
    done
    VARIANT="$(python3 -c "from src.mesh.mesh_convergence import Q05_MESH_CONVERGENCE_LEVELS; print([x['variant_suffix'] for x in Q05_MESH_CONVERGENCE_LEVELS if x['id']=='$lid'][0])")"
    bash scripts/linux/postpull_paperbox_server.sh "$VARIANT" >> "$LOG" 2>&1 || true
  fi
done

python3 scripts/evaluate_mesh_convergence.py >> "$LOG" 2>&1 || true
python3 scripts/plot_mesh_convergence.py >> "$LOG" 2>&1 || true
log "=== done ==="
