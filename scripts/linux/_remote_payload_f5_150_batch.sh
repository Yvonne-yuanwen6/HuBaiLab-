#!/usr/bin/env bash
# P1 payload sweep: 5–150 Hz step 5, top payload 0/100/300/500 g.
# Override via env, e.g. for AF2Q0.5:
#   Q=0.5 VARIANT_PREFIX=comsol_fig321_af2q05_444 VARIANT_LABEL=AF2Q0.5 \
#   OUT_DIR=af2q05_payload_composite OVERLAY_SLUG=af2q05_p1_f5_150_payload_overlay \
#   BATCH_LOG=af2q05_payload_f5_150_batch.log \
#   bash scripts/linux/_remote_payload_f5_150_batch.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

Q="${Q:-0}"
VARIANT_PREFIX="${VARIANT_PREFIX:-comsol_fig321_bcc_444}"
VARIANT_LABEL="${VARIANT_LABEL:-BCC}"
CAD="${CAD:-output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step}"
PREFIX="${PREFIX:-${VARIANT_PREFIX}_mesh_p1}"
SRC_MPH="output/comsol_jobs/${PREFIX}/${PREFIX}.mph"
FREQ_MIN="${FREQ_MIN:-5}"
FREQ_MAX="${FREQ_MAX:-150}"
FREQ_STEP="${FREQ_STEP:-5}"
NP="${NP:-32}"
TOTAL=$(( (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 ))
BATCH_LOG="${BATCH_LOG:-output/logs/bcc_payload_f5_150_batch.log}"
OUT_DIR="${OUT_DIR:-output/comsol_jobs/bcc_payload_composite}"
OVERLAY_SLUG="${OVERLAY_SLUG:-bcc_p1_f5_150_payload_overlay}"
PAPER_OVERLAY="${PAPER_OVERLAY:-bcc}"
MESH_P1_FREQ_MIN="${MESH_P1_FREQ_MIN:-10}"
MESH_P1_FREQ_MAX="${MESH_P1_FREQ_MAX:-300}"
MESH_P1_FREQ_STEP="${MESH_P1_FREQ_STEP:-10}"

mkdir -p output/logs "$OUT_DIR"

exec > >(tee -a "$BATCH_LOG") 2>&1
echo "=== ${VARIANT_LABEL} payload sweep ${FREQ_MIN}-${FREQ_MAX} step=${FREQ_STEP} Q=${Q} $(date) ==="
echo "Cases: 0g 100g 300g 500g (${TOTAL} freq pts each)"

recover_mesh_p1_build() {
  local build_rc=$1
  local p1_mph=$2
  local build_log=$3

  if [[ "$build_rc" -eq 0 ]]; then
    return 0
  fi
  if [[ -f "$p1_mph" ]] \
    && grep -q 'Form assembly: imprint=on' "$build_log" \
    && grep -qE "Saved model:.*${PREFIX}\\.mph|Saved model: ${p1_mph}" "$build_log"; then
    echo "  WARN: mesh_p1 build exited ${build_rc} (likely MPh segfault) but mph saved — continuing" >&2
    return 0
  fi
  return 1
}

ensure_mesh_p1() {
  local build_log="output/logs/${PREFIX}_build.log"
  if [[ -f "$SRC_MPH" ]]; then
    if python3 scripts/_validate_mesh_p1_pairs.py "$SRC_MPH" "$COMSOL_BIN"; then
      echo "  mesh_p1 ready (pairs OK): $SRC_MPH"
      return 0
    fi
    echo "  WARN: stale mesh_p1 missing ap1/ap2 — rebuilding ${PREFIX}" >&2
    rm -f "$SRC_MPH"
  fi

  echo "  mesh_p1 missing — building ${PREFIX} from ${CAD} ..."
  mkdir -p "output/comsol_jobs/${PREFIX}" output/logs
  : >"$build_log"

  local build_rc=0 attempt
  for attempt in 1 2; do
    set +e
    python3 scripts/comsol_run_hu_bai.py \
      --Q "$Q" --cells 4 --cad "$CAD" --slug "$PREFIX" \
      --interface-coupling p1_continuity \
      --freq-only --excitation-axis z --base-accel 0.98 \
      --no-top-payload \
      --physics-controlled-mesh \
      --freq-min "$MESH_P1_FREQ_MIN" --freq-max "$MESH_P1_FREQ_MAX" --freq-step "$MESH_P1_FREQ_STEP" \
      --np 1 --build-only 2>&1 | tee -a "$build_log"
    build_rc=${PIPESTATUS[0]}
    set -e

    if recover_mesh_p1_build "$build_rc" "$SRC_MPH" "$build_log"; then
      break
    fi
    if [[ "$attempt" -eq 1 && "$build_rc" -eq 139 && ! -f "$SRC_MPH" ]]; then
      echo "  WARN: mesh_p1 build segfault before save — retry (attempt 2/2)" >&2
      sleep 5
      continue
    fi
    echo "ERROR: mesh_p1 build failed — see $build_log"
    exit 1
  done

  if [[ ! -f "$SRC_MPH" ]]; then
    echo "ERROR: mesh_p1 mph missing after build: $SRC_MPH"
    exit 1
  fi
  python3 scripts/_validate_mesh_p1_pairs.py "$SRC_MPH" "$COMSOL_BIN" || {
    echo "ERROR: mesh_p1 built but ap1/ap2 still missing — check plate Z snap"
    exit 1
  }
  echo "  mesh_p1 ready: $SRC_MPH"
}

ensure_mesh_p1

wait_solve() {
  local slug=$1
  local solved="output/comsol_jobs/${slug}/${slug}_solved.mph"
  local blog="output/comsol_jobs/${slug}/${slug}_batch.log"
  while true; do
    local sz
    sz=$(stat -c%s "$solved" 2>/dev/null || echo 0)
    if [[ -f "$solved" ]] && [[ "$sz" -gt 500000000 ]] \
      && grep -q '参数 freq = '"${FREQ_MAX}" "$blog" 2>/dev/null; then
      echo "  solved ready: $slug $(date)"
      return 0
    fi
    if ! pgrep -f "${slug}.*std_freq" >/dev/null 2>&1; then
      if [[ -f "$solved" ]] && [[ "$sz" -gt 500000000 ]] \
        && ! grep -qE '错误|ERROR|compilation error|必须非空' "$blog" 2>/dev/null; then
        echo "  solved ready: $slug $(date)"
        return 0
      fi
      echo "ERROR: $slug ended without valid solved mph"
      tail -20 "$blog" 2>/dev/null || true
      return 1
    fi
    freq_line=$(grep -o '参数 freq = [0-9]*' "$blog" 2>/dev/null | tail -1 || true)
    freq=${freq_line#*= }
    freq=${freq// /}
    if [[ -n "$freq" && "$freq" =~ ^[0-9]+$ ]]; then
      done=$(( (freq - FREQ_MIN) / FREQ_STEP + 1 ))
      pct=$(( done * 100 / TOTAL ))
      echo "  [$(date '+%H:%M:%S')] ${slug} freq=${freq}Hz ${done}/${TOTAL} (${pct}%)"
    fi
    sleep 60
  done
}

run_case() {
  local payload_g=$1
  local payload_kg=$2
  local slug=$3
  local job="output/comsol_jobs/${slug}"
  local mph="${job}/${slug}.mph"
  local solved="${job}/${slug}_solved.mph"
  local csv="${job}/${slug}_transmissibility.csv"
  local valid="${job}/${slug}_validation.txt"

  echo ""
  echo "========== ${slug} (${payload_g} g) $(date) =========="

  if [[ -f "$csv" ]] && grep -q 'RESULT: PASS' "$valid" 2>/dev/null; then
    echo "  SKIP: CSV + pb_top PASS"
    return 0
  fi

  mkdir -p "$job"
  python3 scripts/_patch_payload_and_freq.py \
    "$SRC_MPH" "$mph" \
    --payload-kg "$payload_kg" \
    --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"

  if [[ ! -f "$solved" ]] || ! grep -q 'RESULT: PASS' "$valid" 2>/dev/null; then
    rm -f "$solved" "${solved}.recovery" "${job}/${slug}_batch.log"
    python3 scripts/comsol_run_hu_bai.py \
      --Q "$Q" --cells 4 --slug "$slug" \
      --interface-coupling p1_continuity \
      --freq-only --excitation-axis z --base-accel 0.98 \
      --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
      --solve-only "$mph" \
      --np "$NP" --background
    wait_solve "$slug"
  fi

  python3 scripts/_validate_pb_top.py "$solved" "$COMSOL_BIN" | tee "$valid"
  grep -q 'RESULT: PASS' "$valid" || { echo "ERROR: pb_top validation failed"; return 1; }

  bash scripts/linux/_remote_postprocess_slug.sh "$slug"
  echo "  done ${slug}"
}

run_case 0   0.0   "${PREFIX}_f5_150"
run_case 100 0.1   "${PREFIX}_100g_f5_150"
run_case 300 0.3   "${PREFIX}_300g_f5_150"
run_case 500 0.5   "${PREFIX}_500g_f5_150"

echo ""
echo "=== overlay plot $(date) ==="
OVERLAY_ARGS=(--preset f5-150 --variant "$PAPER_OVERLAY" --out-dir "$OUT_DIR" --slug "$OVERLAY_SLUG" --with-trans)
python3 scripts/plot_comsol_vld_payload_overlay.py "${OVERLAY_ARGS[@]}" \
  || echo "WARN: overlay incomplete (some CSVs missing)"

echo "=== batch done $(date) ==="
ls -lh "$OUT_DIR"/* 2>/dev/null || true
