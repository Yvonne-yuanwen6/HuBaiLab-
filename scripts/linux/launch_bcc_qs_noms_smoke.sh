#!/usr/bin/env bash
# Detached launcher for BCC qs noms smoke (do not re-run ms50 jobs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs
exec >> output/logs/bcc_qs_material_probe_noms.log 2>&1
echo "[$(date '+%F %T')] noms launcher start"
bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --only nh_noms,marlow_noms --submit
echo "[$(date '+%F %T')] noms launcher done"
