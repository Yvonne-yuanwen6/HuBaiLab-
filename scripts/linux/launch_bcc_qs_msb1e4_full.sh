#!/usr/bin/env bash
# BCC Q=0 full-stroke: Marlow + BELOW MIN dt=1e-4 (ε=0.80).
# Continues after smoke qs_sm12_marlow_msb1e4 validated KE/IE < 5%.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs
exec >> output/logs/bcc_qs_material_probe_msb1e4_full.log 2>&1
echo "[$(date '+%F %T')] msb1e4 FULL launcher start (Marlow only, strain=0.80)"
bash scripts/linux/run_bcc_qs_material_probe.sh \
  --full --only marlow_msb1e4 --submit
echo "[$(date '+%F %T')] msb1e4 FULL launcher done"
