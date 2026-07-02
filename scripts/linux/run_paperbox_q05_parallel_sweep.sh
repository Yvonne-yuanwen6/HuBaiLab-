#!/usr/bin/env bash
# Q0.5 parallel sweep: export all pending variants, then background-submit together.
#
#   bash scripts/linux/run_paperbox_q05_parallel_sweep.sh
#   nohup bash scripts/linux/run_paperbox_q05_parallel_sweep.sh >> output/logs/paperbox_q05_parallel_sweep.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs

LOG="output/logs/paperbox_q05_parallel_sweep.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
# Match Q1 diagnostic sweep: 24 cores, 128 GiB Abaqus heap limit.
Q05_CPUS="${Q05_PARALLEL_CPUS:-24}"
Q05_MEM="${Q05_PARALLEL_MEMORY_MB:-131072}"

log() { echo "[$(date)] $*" | tee -a "$LOG"; }

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

slug_for() {
  echo "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${1}"
}

export_variant() {
  local suffix="$1"
  shift
  local slug
  slug="$(slug_for "$suffix")"
  if job_completed "$slug"; then
    log "skip completed $suffix"
    return 1
  fi
  log "export $suffix"
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" --export-only "$@"
  return 0
}

submit_variant() {
  local suffix="$1"
  shift
  local slug
  slug="$(slug_for "$suffix")"
  if job_completed "$slug"; then
    return 0
  fi
  log "submit background $suffix cpus=$Q05_CPUS"
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" --submit-only \
    --submit-background --cpus "$Q05_CPUS" --memory-mb "$Q05_MEM" "$@"
}

log "=== Q0.5 parallel sweep start cpus=$Q05_CPUS (parallel with Q1) ==="

PENDING=0

# C: settle 5%
if export_variant "paperbox_settle5p" \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02; then
  PENDING=$((PENDING + 1))
fi

# D: dt1e4 nosettle (retry)
if export_variant "paperbox_nosettle_dt1e4" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling; then
  PENDING=$((PENDING + 1))
fi

# E: dt1e4 no hold (retry; amplitude hold=0 fixed in abaqus_compression.py)
if export_variant "paperbox_nosettle_dt1e4_nohold" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling \
  --hold-fraction 0; then
  PENDING=$((PENDING + 1))
fi

# rods4 remesh
if export_variant "paperbox_q05_rods4" \
  --force-remesh --cae-rods-per-diameter 4 \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02; then
  PENDING=$((PENDING + 1))
fi

if [[ "$PENDING" -eq 0 ]]; then
  log "nothing to submit"
  exit 0
fi

log "parallel submit ($PENDING jobs)"
submit_variant "paperbox_settle5p" \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02 &
PID1=$!
sleep 2
submit_variant "paperbox_nosettle_dt1e4" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling &
PID2=$!
sleep 2
submit_variant "paperbox_nosettle_dt1e4_nohold" \
  --contact-store-offsets \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling \
  --hold-fraction 0 &
PID3=$!
sleep 2
submit_variant "paperbox_q05_rods4" \
  --force-remesh --cae-rods-per-diameter 4 \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02 &
PID4=$!

wait "$PID1" "$PID2" "$PID3" "$PID4" || true
log "all Q0.5 background submits launched"
log "DONE $(date)"
