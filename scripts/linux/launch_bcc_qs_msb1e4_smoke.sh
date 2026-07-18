#!/usr/bin/env bash
# BCC Q=0 smoke: BELOW MIN uncapped to dt=1e-4 (Marlow first, then Neo-Hooke).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs
exec >> output/logs/bcc_qs_material_probe_msb1e4.log 2>&1
echo "[$(date '+%F %T')] msb1e4 launcher start (marlow first)"
bash scripts/linux/run_bcc_qs_material_probe.sh \
  --smoke --only marlow_msb1e4,nh_msb1e4 --submit
echo "[$(date '+%F %T')] msb1e4 launcher done"
