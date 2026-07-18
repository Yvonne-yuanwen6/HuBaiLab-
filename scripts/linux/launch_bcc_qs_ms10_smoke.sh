#!/usr/bin/env bash
# BCC Q=0 smoke: Marlow/Neo-Hooke with mass scaling ×10 (automatic dt).
# Prefer this after noms + fixed-dt hit excessive element distortion.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs
exec >> output/logs/bcc_qs_material_probe_ms10.log 2>&1
echo "[$(date '+%F %T')] ms10 launcher start (marlow first)"
bash scripts/linux/run_bcc_qs_material_probe.sh \
  --smoke --only marlow_ms10,nh_ms10 --submit
echo "[$(date '+%F %T')] ms10 launcher done"
