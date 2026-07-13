#!/usr/bin/env bash
# Wait for in-flight build, then eigen-solve + extract + mode export for all Fig.3.21 cases.
set -euo pipefail
ROOT="/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="/home/art/APP/comsol56/multiphysics/bin/comsol"
export COMSOL_ROOT="/home/art/APP/comsol56/multiphysics"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

LOG="output/logs/fig321_continue.log"
mkdir -p output/logs output/comsol_jobs/fig321_composite

echo "=== fig321 continue $(date) ===" | tee -a "$LOG"

wait_build() {
  local slug="$1"
  local mph="output/comsol_jobs/${slug}/${slug}.mph"
  echo "Waiting for build: $mph" | tee -a "$LOG"
  for _ in $(seq 1 360); do
    if [[ -f "$mph" ]]; then
      ls -lh "$mph" | tee -a "$LOG"
      return 0
    fi
    if ! pgrep -f "comsol_run_hu_bai.py.*${slug}" >/dev/null 2>&1; then
      if [[ -f "$mph" ]]; then return 0; fi
      echo "Build process ended but $mph missing" | tee -a "$LOG"
      return 1
    fi
    sleep 60
  done
  echo "Timeout waiting for $mph" | tee -a "$LOG"
  return 1
}

solve_case() {
  local Q="$1" slug="$2" cad="$3"
  local job="output/comsol_jobs/${slug}"
  local mph="${job}/${slug}.mph"
  local solved="${job}/${slug}_solved.mph"

  if [[ -f "$solved" ]]; then
    echo "Already solved: $solved" | tee -a "$LOG"
  elif [[ -f "$mph" ]]; then
    echo "Batch solve $slug $(date)" | tee -a "$LOG"
    python3 scripts/comsol_run_hu_bai.py \
      --Q "$Q" --cells 4 --eigen-only --excitation-axis z \
      --slug "$slug" --cad "$cad" --np 8 --background 2>&1 | tee -a "$LOG"
    for _ in $(seq 1 720); do
      [[ -f "$solved" ]] && break
      sleep 60
    done
  else
    echo "Build+solve $slug $(date)" | tee -a "$LOG"
    python3 scripts/comsol_run_hu_bai.py \
      --Q "$Q" --cells 4 --eigen-only --excitation-axis z \
      --slug "$slug" --cad "$cad" --np 8 --background 2>&1 | tee -a "$LOG"
    for _ in $(seq 1 720); do
      [[ -f "$solved" ]] && break
      sleep 60
    done
  fi

  if [[ ! -f "$solved" ]]; then
    echo "ERROR: solve failed for $slug" | tee -a "$LOG"
    return 1
  fi

  python3 scripts/comsol_extract_isolation.py "$solved" 2>&1 | tee -a "$LOG"
  python3 scripts/comsol_export_eigen_modes.py "$solved" --modes 3 --min-hz 1.0 2>&1 | tee -a "$LOG"
}

CASES=(
  "0:comsol_fig321_bcc_444:output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
  "0.5:comsol_fig321_af2q05_444:output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
  "1:comsol_fig321_af2q1_444:output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
  "1.5:comsol_fig321_af2q15_444:output/cad/verified/hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step"
)

# Wait for in-flight BCC build
wait_build "comsol_fig321_bcc_444" || true

for entry in "${CASES[@]}"; do
  IFS=: read -r Q SLUG CAD <<< "$entry"
  solve_case "$Q" "$SLUG" "$CAD" || true
done

python3 scripts/plot_comsol_fig321.py \
  --out output/comsol_jobs/fig321_composite/fig321_eigenmodes.png \
  2>&1 | tee -a "$LOG"

echo "=== fig321 continue done $(date) ===" | tee -a "$LOG"
