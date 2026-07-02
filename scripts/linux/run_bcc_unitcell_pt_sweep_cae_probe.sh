#!/usr/bin/env bash
# Export BCC ellmaj with parallel-transport sweep and probe CAE C3D4 mesh.
#
#   bash scripts/linux/run_bcc_unitcell_pt_sweep_cae_probe.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

PY=python3
if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
fi

LOG="output/logs/bcc_unitcell_pt_sweep_cae_probe.log"
mkdir -p output/logs output/cad/pilot

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== ellmaj parallel-transport sweep + CAE probe ==="
"$PY" scripts/pilot_bcc_unitcell_pt_sweep_cae.py \
  --target-area-pi \
  --align major \
  --cae-mesh \
  --mesh-locally \
  >> "$LOG" 2>&1

STEP="output/cad/pilot/hu_bai_bcc_unitcell_L20_ellmaj_Api_pt_z.step"
if [[ -f "$STEP" ]]; then
  log "STEP OK: $STEP"
  grep -E 'Part LATTICE:|Mesh OK|Mesh failed|Elements:' "$ROOT/output/cad/pilot/cae_hex_pilot.log" 2>/dev/null | tail -5 | tee -a "$LOG" || true
else
  log "ERROR missing STEP: $STEP"
  exit 1
fi

log "=== DONE ==="
