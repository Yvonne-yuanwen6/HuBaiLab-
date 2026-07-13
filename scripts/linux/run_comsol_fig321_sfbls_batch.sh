#!/bin/bash
# Sequential Fig.3.21 SFBLS eigen batch: Q0.5, Q1, Q1.5 (same settings as BCC Marlow rerun).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
LOG="output/logs/fig321_sfbls_batch.log"
mkdir -p output/logs

echo "=== fig321 SFBLS batch $(date) ===" | tee "$LOG"

CASES=(
  "0.5:comsol_fig321_af2q05_444:output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
  "1:comsol_fig321_af2q1_444:output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
  "1.5:comsol_fig321_af2q15_444:output/cad/verified/hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step"
)

for entry in "${CASES[@]}"; do
  IFS=: read -r Q SLUG CAD <<< "$entry"
  echo "--- start $SLUG ---" | tee -a "$LOG"
  bash scripts/linux/run_comsol_fig321_case_continue.sh "$Q" "$SLUG" "$CAD" 2>&1 | tee -a "$LOG"
done

python3 scripts/compare_fig321_eigen_vs_paper.py --pull-summary 2>&1 | tee -a "$LOG"
echo "=== fig321 SFBLS batch done $(date) ===" | tee -a "$LOG"
