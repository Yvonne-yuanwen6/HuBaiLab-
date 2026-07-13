#!/usr/bin/env bash
# Build + solve + validate one Fig.2.8 coupling phase (mesh unchanged).
# Usage: PHASE=1|2|3 bash scripts/linux/_remote_phase_coupling.sh
# Keeps mph/solved even on pb_top failure for GUI review.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

PHASE="${PHASE:-1}"
FREQ_MIN="${FREQ_MIN:-10}"
FREQ_MAX="${FREQ_MAX:-300}"
FREQ_STEP="${FREQ_STEP:-10}"
NP="${NP:-32}"
CAD="${CAD:-output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step}"

case "$PHASE" in
  1)
    SLUG="comsol_fig321_bcc_444_mesh_p1"
    COUPLING="p1_continuity"
    DESC="Phase1: identity ap1/ap2 + Continuity"
    ;;
  2)
    SLUG="comsol_fig321_bcc_444_mesh_p2"
    COUPLING="p2_contact_all"
    DESC="Phase2: manual Contact pairs tbl+plt, Penalty"
    ;;
  3)
    SLUG="comsol_fig321_bcc_444_mesh_p3"
    COUPLING="p3_contact_auto"
    DESC="Phase3: fin auto Contact pairs ap1/ap2, Penalty"
    ;;
  *)
    echo "ERROR: PHASE must be 1, 2, or 3 (got $PHASE)"
    exit 1
    ;;
esac

JOB="output/comsol_jobs/${SLUG}"
MPH="${JOB}/${SLUG}.mph"
SOLVED="${JOB}/${SLUG}_solved.mph"
LOG="output/logs/${SLUG}_phase.log"
VALID_LOG="${JOB}/${SLUG}_validation.txt"
BATCH_LOG="${JOB}/${SLUG}_batch.log"

mkdir -p output/logs "$JOB"

exec > >(tee -a "$LOG") 2>&1
echo "=== ${DESC} $(date) ==="
echo "slug=${SLUG} coupling=${COUPLING} freq=${FREQ_MIN}-${FREQ_MAX} step=${FREQ_STEP} np=${NP}"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --cad "$CAD" --slug "$SLUG" \
  --interface-coupling "$COUPLING" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --physics-controlled-mesh \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
  --np 1 --build-only || {
  if [[ -f "$MPH" ]] && grep -qE 'Saved model:|Interface coupling: '"${COUPLING}" "$LOG"; then
    echo "WARN: build exited nonzero but mph + markers present"
  else
    exit 1
  fi
}

python3 scripts/_patch_freq_plist.py "$MPH" \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"

rm -f "$SOLVED" "${SOLVED}.recovery" "${SOLVED}.status" "$BATCH_LOG"

python3 scripts/comsol_run_hu_bai.py \
  --Q 0 --cells 4 --slug "$SLUG" \
  --interface-coupling "$COUPLING" \
  --freq-only --excitation-axis z --base-accel 0.98 \
  --no-top-payload \
  --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
  --solve-only "$MPH" \
  --np "$NP" --background

echo "Submitted batch. Waiting for solved mph..."
INTERVAL=60
TOTAL=$(( (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 ))
while true; do
  if [[ -f "$SOLVED" ]]; then
    sz=$(stat -c%s "$SOLVED" 2>/dev/null || echo 0)
    if [[ "$sz" -gt 50000000 ]]; then
      echo "Solved mph ready ($(numfmt --to=iec "$sz" 2>/dev/null || echo ${sz}B))"
      break
    fi
  fi
  if ! pgrep -f "${SLUG}.*std_freq" >/dev/null 2>&1; then
    if [[ -f "$SOLVED" ]]; then
      echo "Process ended; using solved mph"
      break
    fi
    echo "ERROR: comsol ended without solved mph"
    tail -20 "$BATCH_LOG" 2>/dev/null || true
    exit 1
  fi
  freq_line=$(grep -o '参数 freq = [0-9]*' "$BATCH_LOG" 2>/dev/null | tail -1 || true)
  freq=${freq_line#*= }
  freq=${freq// /}
  if [[ -n "$freq" && "$freq" =~ ^[0-9]+$ ]]; then
    done=$(( (freq - FREQ_MIN) / FREQ_STEP + 1 ))
    pct=$(( done * 100 / TOTAL ))
    echo "[$(date '+%H:%M:%S')] freq=${freq}Hz ${done}/${TOTAL} (${pct}%)"
  else
    echo "[$(date '+%H:%M:%S')] compiling/starting..."
  fi
  sleep "$INTERVAL"
done

{
  echo "=== validation ${SLUG} $(date) ==="
  echo "coupling=${COUPLING}"
  python3 scripts/_validate_pb_top.py "$SOLVED" "$COMSOL_BIN" || echo "RESULT: FAIL pb_top still zero"
} | tee "$VALID_LOG"

echo "=== phase ${PHASE} done $(date) ==="
ls -lh "$MPH" "$SOLVED" "$VALID_LOG" 2>/dev/null || true
echo "GUI: ${MPH}"
