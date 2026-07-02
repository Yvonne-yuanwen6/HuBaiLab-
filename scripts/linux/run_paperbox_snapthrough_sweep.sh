#!/usr/bin/env bash
# Snap-through sweep: sequential variants on server (default SFBLS Q=0.5 only).
#
#   bash scripts/linux/run_paperbox_snapthrough_sweep.sh
#   bash scripts/linux/run_paperbox_snapthrough_sweep.sh --Q 0.5
#   nohup bash scripts/linux/run_paperbox_snapthrough_sweep.sh >> output/logs/paperbox_snapthrough_sweep.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/paperbox_snapthrough_sweep.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
QS=(0.5)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --Q) QS=("$2"); shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--Q 0.5|0|1|1.5]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_failed_early() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] || return 1
  grep -q 'excessively distorted' "$sta" && ! job_completed "$slug"
}

slug_for() {
  local q="$1"
  local variant="$2"
  local tag
  tag="$(python3 -c "from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G; print(G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=float('$q')).variant_name.lower())")"
  echo "hu_bai_${tag}_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${variant}"
}

run_variant_all_q() {
  local variant="$1"
  shift
  local extra=("$@")
  local q slug fail=0
  for q in "${QS[@]}"; do
    echo ""
    echo "[$(date)] === variant=$variant Q=$q ==="
    if ! bash "$VARIANT_SH" --Q "$q" --variant-suffix "$variant" "${extra[@]}"; then
      slug="$(slug_for "$q" "$variant")"
      echo "[$(date)] ERROR pipeline failed variant=$variant Q=$q slug=$slug" | tee -a "$LOG"
      fail=1
    fi
  done
  return "$fail"
}

echo ""
echo "=== paperbox snap-through sweep start $(date) Q=${QS[*]} ==="
echo "ROOT=$ROOT Q=${QS[*]}" | tee -a "$LOG"

# B: no ContactSettle, keep STORE OFFSETS (baseline contact preprocessing removed)
if ! run_variant_all_q "paperbox_nosettle" \
  --contact-store-offsets; then
  echo "[$(date)] B (nosettle) had failures; trying C (settle 5%) for early-fail slugs" | tee -a "$LOG"
  for q in "${QS[@]}"; do
    slug="$(slug_for "$q" "paperbox_nosettle")"
    if job_failed_early "$slug" || [[ ! -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
      echo "[$(date)] retry Q=$q with settle5p" | tee -a "$LOG"
      bash "$VARIANT_SH" --Q "$q" --variant-suffix "paperbox_settle5p" \
        --contact-store-offsets \
        --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02 || true
    fi
  done
fi

# D: nosettle + fixed dt + no mass scaling
run_variant_all_q "paperbox_nosettle_dt1e4" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling || true

# E: D + no hold
run_variant_all_q "paperbox_nosettle_dt1e4_nohold" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling \
  --hold-fraction 0 || true

echo ""
echo "[$(date)] === sweep export+submit done; writing summary ===" | tee -a "$LOG"
python3 scripts/analyze_paperbox_snapthrough.py --write-summary "$ROOT/output/logs/paperbox_snapthrough_summary.json" | tee -a "$LOG"
echo "DONE $(date)" | tee -a "$LOG"
