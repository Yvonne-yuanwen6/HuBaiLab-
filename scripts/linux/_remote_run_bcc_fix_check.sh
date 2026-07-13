#!/usr/bin/env bash
# Re-run BCC COMSOL cases after free1/eigen-extract fixes; post-process for Table 3.3 check.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

LOG="output/logs/bcc_fix_check_$(date +%Y%m%d_%H%M%S).log"
mkdir -p output/logs

exec > >(tee -a "$LOG") 2>&1

echo "=== BCC fix check $(date) ==="
echo "LOG=$LOG"

EIGEN_SLUG="comsol_fig321_bcc_444"
FREQ_SLUG="comsol_fig321_bcc_444_freq"
CAD="output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
EIGEN_SOLVED="output/comsol_jobs/${EIGEN_SLUG}/${EIGEN_SLUG}_solved.mph"

# 1) Re-extract eigen from existing solved mph (eigen_extract fix)
if [[ -f "$EIGEN_SOLVED" ]]; then
  echo "--- re-extract eigen: $EIGEN_SOLVED ---"
  python3 scripts/comsol_extract_isolation.py "$EIGEN_SOLVED"
  python3 scripts/compare_fig321_eigen_vs_paper.py --key bcc 2>/dev/null || \
    python3 scripts/compare_fig321_eigen_vs_paper.py
else
  echo "WARN: missing $EIGEN_SOLVED — will full eigen rebuild below"
fi

# 2) Rebuild freq mph (free1 off in study activate)
echo "--- rebuild freq mph (build-only) ---"
python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$FREQ_SLUG" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --np 4 --build-only

# 3) Quick validate 3 frequency points before full sweep
echo "--- quick freq validate (10,30,68 Hz) ---"
python3 scripts/_tmp_validate_freq_build.py && echo "QUICK VALIDATE PASS" || echo "QUICK VALIDATE FAIL"

# 4) Full harmonic batch solve
FREQ_MPH="output/comsol_jobs/${FREQ_SLUG}/${FREQ_SLUG}.mph"
echo "--- harmonic batch solve ---"
rm -f "output/comsol_jobs/${FREQ_SLUG}/${FREQ_SLUG}_solved.mph" \
  "output/comsol_jobs/${FREQ_SLUG}/${FREQ_SLUG}_batch.log"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$FREQ_SLUG" \
  --freq-only --excitation-axis z \
  --no-top-payload \
  --freq-min 10 --freq-max 300 --freq-step 2 \
  --solve-only "$FREQ_MPH" \
  --np 8 --background

FREQ_SOLVED="output/comsol_jobs/${FREQ_SLUG}/${FREQ_SLUG}_solved.mph"
BATCH_LOG="output/comsol_jobs/${FREQ_SLUG}/${FREQ_SLUG}_batch.log"
echo "Waiting for $FREQ_SOLVED ..."
for _ in $(seq 1 360); do
  if [[ -f "$BATCH_LOG" ]] && grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG"; then
    echo "ERROR: batch failed — see $BATCH_LOG"
    tail -30 "$BATCH_LOG"
    exit 1
  fi
  if [[ -f "$FREQ_SOLVED" && -f "$FREQ_MPH" && "$FREQ_SOLVED" -nt "$FREQ_MPH" ]]; then
    if grep -qE '当前进度: 100 % - 完成|总时间:' "$BATCH_LOG" 2>/dev/null; then
      if ! grep -qE '/\*+\*错误\*+\*/|/*****错误/' "$BATCH_LOG" 2>/dev/null; then
        break
      fi
    fi
  fi
  sleep 30
done

if [[ ! -f "$FREQ_SOLVED" ]]; then
  echo "ERROR: freq solve timeout"
  exit 1
fi

# 5) Extract + compare
echo "--- extract freq + table33 compare ---"
python3 scripts/comsol_extract_isolation.py "$FREQ_SOLVED"
python3 scripts/plot_comsol_vld.py \
  "output/comsol_jobs/${FREQ_SLUG}/${FREQ_SLUG}_transmissibility.csv" \
  --paper-bcc || true
python3 scripts/comsol_postprocess_thesis.py \
  "output/comsol_jobs/${FREQ_SLUG}" --slug "$FREQ_SLUG" || true
python3 scripts/compare_table33_vs_paper.py --key bcc

echo "=== done $(date) ==="
ls -lh "output/comsol_jobs/${EIGEN_SLUG}/"*.csv 2>/dev/null || true
ls -lh "output/comsol_jobs/${FREQ_SLUG}/"*.csv 2>/dev/null || true
