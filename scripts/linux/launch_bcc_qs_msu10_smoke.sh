#!/usr/bin/env bash
# BCC Q=0 smoke: uniform mass scaling ×10 (no BELOW MIN dt=5e-4 mass boost).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs
exec >> output/logs/bcc_qs_material_probe_msu10.log 2>&1
echo "[$(date '+%F %T')] msu10 launcher start (marlow first)"
bash scripts/linux/run_bcc_qs_material_probe.sh \
  --smoke --only marlow_msu10,nh_msu10 --submit
echo "[$(date '+%F %T')] msu10 launcher done"
