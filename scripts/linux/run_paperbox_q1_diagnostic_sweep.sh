#!/usr/bin/env bash
# Q1 diagnostic sweep: serial variants, runs in parallel with Q0.5 snap-through sweep.
#
#   bash scripts/linux/run_paperbox_q1_diagnostic_sweep.sh
#   nohup bash scripts/linux/run_paperbox_q1_diagnostic_sweep.sh >> output/logs/paperbox_q1_diagnostic_sweep.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/paperbox_q1_diagnostic_sweep.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
# Fewer cores than Q0.5 (48) so both can run on the shared host.
Q1_CPUS="${Q1_DIAG_CPUS:-24}"
Q1_MEMORY_MB="${Q1_DIAG_MEMORY_MB:-131072}"

log() { echo "[$(date)] $*" | tee -a "$LOG"; }

run_variant() {
  local suffix="$1"
  shift
  log "=== variant start suffix=$suffix cpus=$Q1_CPUS ==="
  if ! bash "$VARIANT_SH" --Q 1 --variant-suffix "$suffix" --cpus "$Q1_CPUS" --memory-mb "$Q1_MEMORY_MB" "$@"; then
    log "ERROR variant failed suffix=$suffix (continuing)"
    return 1
  fi
  log "=== variant done suffix=$suffix ==="
}

log ""
log "=== Q1 diagnostic sweep start ROOT=$ROOT (parallel with Q0.5, cpus=$Q1_CPUS) ==="

# 1) shorter ContactSettle (5%), keep STORE OFFSETS
run_variant "paperbox_settle5p" \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02 || true

# 2) no settle + paper-like dt / no mass scaling
run_variant "paperbox_nosettle_dt1e4" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling || true

# 3) short settle + dt1e4
run_variant "paperbox_settle5p_dt1e4" \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02 \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling || true

# 4) Q1-only finer rod discretization (global seed 0.6 unchanged), baseline contact
run_variant "paperbox_q1_rods4" \
  --force-remesh --cae-rods-per-diameter 4 \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02 || true

log "writing early-phase summary ..."
python3 scripts/analyze_paperbox_q1_early_phase.py \
  --write-summary "$ROOT/output/logs/paperbox_q1_diagnostic_summary.json" | tee -a "$LOG" || true

log "DONE $(date)"
