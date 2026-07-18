#!/usr/bin/env bash
# BCC Q=0: quasi-static / material probe after STEP geometry is locked.
#
# Reuses baseline CAE mesh (seed 0.6 / lattice_contact). One knob at a time:
#   nh_ms50      Neo-Hooke + mass scaling ×50   (repo control)
#   marlow_ms50  Marlow(Fig.2.5) + mass scaling ×50
#   nh_noms      Neo-Hooke + no mass scaling + fixed dt=1e-4
#   marlow_noms  Marlow + no mass scaling + fixed dt=1e-4
#
# Add --include-msu for uniform factor mass scaling (no BELOW MIN large-dt boost).
# Add --include-ms10 for legacy below_min×10 (same KE/IE issue as ×50).
# Add --include-noms for no mass scaling + fixed dt (slow; often contact-unstable).
#
#   # server
#   bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --submit
#   bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --only marlow_msu10,nh_msu10 --submit
#   bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --post-only
#
#   # export only (Windows or server)
#   bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --export-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/mesh_convergence

LOG="output/logs/bcc_qs_material_probe.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
EVAL_PY="scripts/evaluate_bcc_qs_material_probe.py"

MODE="smoke"   # smoke | full
SUBMIT=0
EXPORT_ONLY=0
POST_ONLY=0
INCLUDE_NOMS=0
INCLUDE_MS10=0
INCLUDE_MSU=0
ONLY=""
CPUS="${BCC_QS_PROBE_CPUS:-48}"
MEM="${BCC_QS_PROBE_MEMORY_MB:-262144}"

usage() {
  cat <<EOF
Usage: $0 [--smoke|--full] [--submit|--export-only|--post-only]
          [--include-msu] [--include-ms10] [--include-noms]
          [--only id1,id2] [--cpus N] [--memory-mb MB]
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) MODE="smoke"; shift ;;
    --full) MODE="full"; shift ;;
    --submit) SUBMIT=1; shift ;;
    --export-only) EXPORT_ONLY=1; shift ;;
    --post-only) POST_ONLY=1; shift ;;
    --include-noms) INCLUDE_NOMS=1; shift ;;
    --include-ms10) INCLUDE_MS10=1; shift ;;
    --include-msu) INCLUDE_MSU=1; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEM="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

if [[ "$MODE" == "smoke" ]]; then
  STRAIN="0.12"
  TAG="sm12"
else
  STRAIN="0.80"
  TAG="s80"
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# id|suffix|extra export flags
# msb1e4 = BELOW MIN uncapped to dt=1e-4 (vs legacy 5e-4 — ~25× less mass boost)
# msu* = uniform factor only (too slow on this mesh; keep for reference)
VARIANTS=(
  "nh_ms50|qs_${TAG}_nh_ms50|--material-model neo_hooke"
  "marlow_ms50|qs_${TAG}_marlow_ms50|--material-model marlow"
  "marlow_ms10|qs_${TAG}_marlow_ms10|--material-model marlow --mass-scaling-factor 10"
  "nh_ms10|qs_${TAG}_nh_ms10|--material-model neo_hooke --mass-scaling-factor 10"
  "marlow_msb1e4|qs_${TAG}_marlow_msb1e4|--material-model marlow --mass-scaling-mode below_min --mass-scaling-dt 0.0001 --explicit-dt 0.0001 --explicit-dt-mode automatic"
  "nh_msb1e4|qs_${TAG}_nh_msb1e4|--material-model neo_hooke --mass-scaling-mode below_min --mass-scaling-dt 0.0001 --explicit-dt 0.0001 --explicit-dt-mode automatic"
  "marlow_msb1e4_ss077|qs_${TAG}_marlow_msb1e4_ss077|--material-model marlow --tpu-stress-scale 0.77 --mass-scaling-mode below_min --mass-scaling-dt 0.0001 --explicit-dt 0.0001 --explicit-dt-mode automatic"
  "marlow_msu10|qs_${TAG}_marlow_msu10|--material-model marlow --mass-scaling-mode uniform --mass-scaling-factor 10"
  "nh_msu10|qs_${TAG}_nh_msu10|--material-model neo_hooke --mass-scaling-mode uniform --mass-scaling-factor 10"
  "nh_noms|qs_${TAG}_nh_noms|--material-model neo_hooke --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling"
  "marlow_noms|qs_${TAG}_marlow_noms|--material-model marlow --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling"
)

want_id() {
  local id="$1"
  if [[ -n "$ONLY" ]]; then
    [[ ",${ONLY}," == *",${id},"* ]]
    return $?
  fi
  case "$id" in
    nh_noms|marlow_noms)
      [[ "$INCLUDE_NOMS" -eq 1 ]]
      ;;
    nh_ms10|marlow_ms10)
      [[ "$INCLUDE_MS10" -eq 1 ]]
      ;;
    nh_msu10|marlow_msu10)
      [[ "$INCLUDE_MSU" -eq 1 ]]
      ;;
    nh_msb1e4|marlow_msb1e4|marlow_msb1e4_ss077)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

slug_for() {
  local suffix="$1"
  echo "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${suffix}"
}

BASELINE_MESH="output/export/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"
if [[ "$POST_ONLY" -eq 0 && ! -f "$BASELINE_MESH" ]]; then
  log "ERROR: missing baseline mesh (run paperbox BCC pipeline first):"
  log "  $BASELINE_MESH"
  exit 1
fi

log "=== BCC qs/material probe mode=$MODE strain=$STRAIN submit=$SUBMIT export_only=$EXPORT_ONLY post_only=$POST_ONLY include_msu=$INCLUDE_MSU include_ms10=$INCLUDE_MS10 include_noms=$INCLUDE_NOMS only=${ONLY:-all-default} ==="

SELECTED_SLUGS=()

for row in "${VARIANTS[@]}"; do
  ID="${row%%|*}"
  rest="${row#*|}"
  SUFFIX="${rest%%|*}"
  EXTRA="${rest#*|}"

  if ! want_id "$ID"; then
    log "skip $ID"
    continue
  fi

  SLUG="$(slug_for "$SUFFIX")"
  SELECTED_SLUGS+=("$SLUG")
  log "--- id=$ID suffix=$SUFFIX slug=$SLUG ---"

  if [[ "$POST_ONLY" -eq 1 ]]; then
    ODB="output/jobs/${SLUG}/${SLUG}.odb"
    ENERGY_CSV="output/post/${SLUG}/${SLUG}_energy.csv"
    if [[ -f "$ODB" ]]; then
      mkdir -p "output/post/${SLUG}"
      if [[ ! -f "$ENERGY_CSV" ]]; then
        abq python scripts/extract_odb_energy_py2.py "$ODB" "$ENERGY_CSV" >> "$LOG" 2>&1 \
          || log "WARN energy extract failed $SLUG"
      fi
      bash scripts/linux/postpull_paperbox_server.sh "$SLUG" >> "$LOG" 2>&1 || true
    else
      log "WARN no ODB yet: $ODB"
    fi
    continue
  fi

  EXPORT_FLAGS=(
    --contact-store-offsets
    --contact-settle
    --strain "$STRAIN"
  )
  # shellcheck disable=SC2206
  EXTRA_ARR=($EXTRA)
  EXPORT_FLAGS+=("${EXTRA_ARR[@]}")

  RUN_ARGS=(
    --Q 0
    --variant-suffix "$SUFFIX"
    --cpus "$CPUS"
    --memory-mb "$MEM"
  )
  if [[ "$EXPORT_ONLY" -eq 1 ]]; then
    RUN_ARGS+=(--export-only)
  elif [[ "$SUBMIT" -eq 1 ]]; then
    :
  else
    log "Neither --submit nor --export-only nor --post-only; dry list only."
    continue
  fi

  log "run_paperbox_variant ${RUN_ARGS[*]} ${EXPORT_FLAGS[*]}"
  bash "$VARIANT_SH" "${RUN_ARGS[@]}" "${EXPORT_FLAGS[@]}" || {
    log "WARN variant failed: $ID"
    continue
  }
done

if [[ "$POST_ONLY" -eq 1 || "$SUBMIT" -eq 1 ]]; then
  if [[ -f "$EVAL_PY" ]]; then
    log "=== evaluate ==="
    python3 "$EVAL_PY" --mode "$MODE" --slugs "${SELECTED_SLUGS[@]}" \
      || log "WARN evaluate incomplete (jobs may still be running)"
  fi
fi

log "=== probe batch finished mode=$MODE ==="
log "Next: watch .sta, then --post-only; if marlow early curve better and KE/IE OK, --full --only marlow_ms50"
