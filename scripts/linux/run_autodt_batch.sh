#!/usr/bin/env bash
# Export (on Windows), sync, serial submit four autodt cases — or submit only if INPs exist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SUFFIX="voxel0p8mm80_15mmin_autodt"

if [[ -d /home/art/APP/abaqus2022/Commands ]]; then
  export PATH="/home/art/APP/abaqus2022/Commands:${PATH:-/usr/bin:/bin}"
fi

SLUGS=(
  "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_${SUFFIX}"
  "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_${SUFFIX}"
  "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_${SUFFIX}"
  "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_${SUFFIX}"
)

mkdir -p "$ROOT/output/logs"
LOG="$ROOT/output/logs/autodt_batch_${SUFFIX}.log"

{
  echo "=== autodt batch start $(date) ==="
  bash "$SCRIPT_DIR/submit_queue.sh" --cpus 32 --memory-mb 131072 \
    --slugs-csv "$(IFS=,; echo "${SLUGS[*]}")"
  echo "=== autodt batch end $(date) ==="
} >> "$LOG" 2>&1
