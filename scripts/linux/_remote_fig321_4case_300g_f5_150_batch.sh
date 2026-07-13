#!/usr/bin/env bash
# Fig.3.21 all four structures: P1 + 300g, 5-150 Hz step 5.
# Every case follows the BCC pipeline:
#   mesh_p1 (build-only, no payload) → mesh_p1_300g (patch) → f5_150 sweep + postprocess.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

FREQ_MIN="${FREQ_MIN:-5}"
FREQ_MAX="${FREQ_MAX:-150}"
FREQ_STEP="${FREQ_STEP:-5}"
PAYLOAD_KG="${PAYLOAD_KG:-0.3}"
NP="${NP:-32}"
# mesh_p1 build matches _remote_phase_coupling.sh PHASE=1 (same as BCC).
MESH_P1_FREQ_MIN="${MESH_P1_FREQ_MIN:-10}"
MESH_P1_FREQ_MAX="${MESH_P1_FREQ_MAX:-300}"
MESH_P1_FREQ_STEP="${MESH_P1_FREQ_STEP:-10}"
TOTAL=$(( (FREQ_MAX - FREQ_MIN) / FREQ_STEP + 1 ))
BATCH_LOG="output/logs/fig321_4case_300g_f5_150_batch.log"

mkdir -p output/logs output/comsol_jobs/fig321_composite

exec > >(tee -a "$BATCH_LOG") 2>&1
echo "=== Fig.3.21 four-case 300g f5-150 batch $(date) ==="
echo "freq=${FREQ_MIN}-${FREQ_MAX} step=${FREQ_STEP} (${TOTAL} pts/case)"
echo "mesh_p1 build: ${MESH_P1_FREQ_MIN}-${MESH_P1_FREQ_MAX} step=${MESH_P1_FREQ_STEP} (BCC pipeline)"

CASES=(
  "0|comsol_fig321_bcc_444|output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step"
  "0.5|comsol_fig321_af2q05_444|output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
  "1|comsol_fig321_af2q1_444|output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
  "1.5|comsol_fig321_af2q15_444|output/cad/verified/hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step"
)

wait_solve() {
  local slug=$1
  local solved="output/comsol_jobs/${slug}/${slug}_solved.mph"
  local blog="output/comsol_jobs/${slug}/${slug}_batch.log"
  while true; do
    if [[ -f "$solved" ]] && [[ $(stat -c%s "$solved" 2>/dev/null || echo 0) -gt 100000000 ]]; then
      echo "  solved ready: $slug $(date)"
      return 0
    fi
    if ! pgrep -f "${slug}.*std_freq" >/dev/null 2>&1; then
      if [[ -f "$solved" ]]; then
        return 0
      fi
      echo "ERROR: $slug ended without solved mph"
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

check_mesh_p1_build_log() {
  local log=$1
  local slug=$2
  if [[ ! -f "$log" ]]; then
    echo "ERROR: missing mesh_p1 build log for ${slug}: $log"
    return 1
  fi
  if ! grep -q 'Form assembly: imprint=on' "$log"; then
    echo "ERROR: ${slug} mesh_p1 build missing imprint=on (plate bonding not applied)"
    return 1
  fi
  if grep -q 'expected identity pair ap2 missing' "$log"; then
    echo "ERROR: ${slug} mesh_p1 build missing ap2 (plate–lattice identity pair)"
    return 1
  fi
  if grep -q 'Interface coupling: p1_continuity' "$log"; then
    return 0
  fi
  echo "ERROR: ${slug} mesh_p1 build missing p1_continuity marker"
  return 1
}

recover_mesh_p1_build() {
  local build_rc=$1
  local p1_mph=$2
  local build_log=$3
  local p1_slug=$4

  if [[ "$build_rc" -eq 0 ]]; then
    return 0
  fi

  # MPh teardown sometimes segfaults (exit 139) after a successful save — same as BCC rebuild chain.
  if [[ -f "$p1_mph" ]] \
    && grep -q 'Form assembly: imprint=on' "$build_log" \
    && grep -qE "Saved model:.*${p1_slug}\\.mph|Saved model: ${p1_mph}" "$build_log"; then
    echo "  WARN: mesh_p1 build exited ${build_rc} (likely MPh segfault) but mph saved with imprint — continuing" >&2
    return 0
  fi

  if [[ -f "$p1_mph" ]]; then
    local sz
    sz=$(stat -c%s "$p1_mph" 2>/dev/null || echo 0)
    if [[ "$sz" -gt 1000000 ]] && grep -q 'Form assembly: imprint=on' "$build_log"; then
      echo "  WARN: mesh_p1 build exited ${build_rc}; mph exists (${sz} bytes) with imprint — continuing" >&2
      return 0
    fi
    echo "ERROR: mesh_p1 build exited ${build_rc}; mph exists but imprint/save markers missing" >&2
    return 1
  fi

  echo "ERROR: mesh_p1 build failed for ${p1_slug} (exit ${build_rc})" >&2
  return 1
}

run_mesh_p1_build() {
  local q=$1
  local prefix=$2
  local cad=$3
  local p1_slug=$4
  local build_log=$5

  python3 scripts/comsol_run_hu_bai.py \
    --Q "$q" --cells 4 --cad "$cad" --slug "$p1_slug" \
    --interface-coupling p1_continuity \
    --freq-only --excitation-axis z --base-accel 0.98 \
    --no-top-payload \
    --physics-controlled-mesh \
    --freq-min "$MESH_P1_FREQ_MIN" --freq-max "$MESH_P1_FREQ_MAX" --freq-step "$MESH_P1_FREQ_STEP" \
    --np 1 --build-only 2>&1 | tee -a "$build_log"
  return "${PIPESTATUS[0]}"
}

ensure_mesh_p1_mph() {
  local q=$1
  local prefix=$2
  local cad=$3
  local p1_slug="${prefix}_mesh_p1"
  local p1_mph="output/comsol_jobs/${p1_slug}/${p1_slug}.mph"
  local build_log="output/logs/${p1_slug}_build.log"
  local stamp="output/logs/${p1_slug}_geom_ok.stamp"

  if [[ -f "$p1_mph" && -f "$stamp" ]]; then
    echo "  mesh_p1 ready: $p1_mph" >&2
    echo "$p1_mph"
    return 0
  fi

  if [[ -f "$p1_mph" && ! -f "$stamp" ]]; then
    if check_mesh_p1_build_log "$build_log" "$p1_slug"; then
      touch "$stamp"
      echo "  mesh_p1 ready (stamped): $p1_mph" >&2
      echo "$p1_mph"
      return 0
    fi
    echo "  WARN: stale mesh_p1 without geom stamp — rebuilding ${p1_slug}" >&2
    rm -f "$p1_mph"
  fi

  echo "  building mesh_p1: ${p1_slug} (BCC pipeline)..." >&2
  mkdir -p "output/comsol_jobs/${p1_slug}" output/logs
  : >"$build_log"

  local build_rc=0
  local attempt
  for attempt in 1 2; do
    set +e
    run_mesh_p1_build "$q" "$prefix" "$cad" "$p1_slug" "$build_log"
    build_rc=$?
    set -e

    if recover_mesh_p1_build "$build_rc" "$p1_mph" "$build_log" "$p1_slug"; then
      break
    fi

    if [[ "$attempt" -eq 1 && "$build_rc" -eq 139 && ! -f "$p1_mph" ]]; then
      echo "  WARN: mesh_p1 build segfault before save — retry ${p1_slug} (attempt 2/2)" >&2
      sleep 5
      continue
    fi
    return 1
  done

  if [[ ! -f "$p1_mph" ]]; then
    echo "ERROR: mesh_p1 mph missing after build: $p1_mph" >&2
    return 1
  fi

  check_mesh_p1_build_log "$build_log" "$p1_slug"
  touch "$stamp"
  echo "$p1_mph"
}

ensure_base_300g_mph() {
  local q=$1
  local prefix=$2
  local cad=$3
  local p1_slug="${prefix}_mesh_p1"
  local p1_mph="output/comsol_jobs/${p1_slug}/${p1_slug}.mph"
  local base_slug="${prefix}_mesh_p1_300g"
  local base_mph="output/comsol_jobs/${base_slug}/${base_slug}.mph"
  local alt="output/comsol_jobs/${prefix}_mesh_p1_300g_f1_300/${prefix}_mesh_p1_300g_f1_300.mph"

  ensure_mesh_p1_mph "$q" "$prefix" "$cad" >/dev/null

  # Drop base mph created by the old CAD shortcut (no mesh_p1 parent).
  if [[ -f "$base_mph" && ! -f "$p1_mph" ]]; then
    echo "  WARN: removing stale base mph (no mesh_p1 parent): $base_mph" >&2
    rm -f "$base_mph"
  fi
  # Repatch when mesh_p1 was rebuilt after the 300g base was created.
  if [[ -f "$base_mph" && -f "$p1_mph" && "$p1_mph" -nt "$base_mph" ]]; then
    echo "  mesh_p1 newer than base mph — repatching ${base_slug}" >&2
    rm -f "$base_mph"
  fi

  if [[ -f "$base_mph" ]]; then
    echo "  base mph exists: $base_mph" >&2
    echo "$base_mph"
    return 0
  fi

  if [[ -f "$alt" ]]; then
    mkdir -p "output/comsol_jobs/${base_slug}"
    cp -f "$alt" "$base_mph"
    echo "  copied payload mph: $alt -> $base_mph" >&2
    echo "$base_mph"
    return 0
  fi

  if [[ ! -f "$p1_mph" ]]; then
    echo "ERROR: mesh_p1 mph missing: $p1_mph" >&2
    return 1
  fi

  echo "  patching mesh_p1 -> mesh_p1_300g from ${p1_slug}..." >&2
  mkdir -p "output/comsol_jobs/${base_slug}"
  python3 scripts/_patch_payload_and_freq.py \
    "$p1_mph" "$base_mph" \
    --payload-kg "$PAYLOAD_KG" \
    --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" >&2
  echo "$base_mph"
}

for entry in "${CASES[@]}"; do
  IFS='|' read -r Q PREFIX CAD <<< "$entry"
  SWEEP_SLUG="${PREFIX}_mesh_p1_300g_f5_150"
  SWEEP_MPH="output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}.mph"
  SWEEP_SOLVED="output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}_solved.mph"
  SWEEP_BATCH="output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}_batch.log"
  SWEEP_VALID="output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}_validation.txt"
  PLOT_META="output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}_harmonic_plotgroups.json"

  echo ""
  echo "========== ${SWEEP_SLUG} $(date) =========="

  if [[ -f "${SWEEP_SOLVED}" ]] \
    && [[ -f "output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}_transmissibility.csv" ]] \
    && [[ -f "$PLOT_META" ]] \
    && grep -q '"reference_probe": "pb_base"' "$PLOT_META" 2>/dev/null \
    && grep -q 'RESULT: PASS' "$SWEEP_VALID" 2>/dev/null; then
    echo "  SKIP: solved + CSV + harmonic plot groups + pb_top PASS"
    continue
  fi
  if [[ -f "${SWEEP_SOLVED}" ]] && [[ -f "output/comsol_jobs/${SWEEP_SLUG}/${SWEEP_SLUG}_transmissibility.csv" ]]; then
    if grep -q 'RESULT: PASS' "$SWEEP_VALID" 2>/dev/null; then
      echo "  WARN: missing/outdated harmonic plot groups — re-running postprocess"
    else
      echo "  WARN: solved CSV exists but pb_top validation missing/failed — re-running postprocess chain"
    fi
  fi

  BASE_MPH=$(ensure_base_300g_mph "$Q" "$PREFIX" "$CAD")
  mkdir -p "output/comsol_jobs/${SWEEP_SLUG}"
  cp -f "$BASE_MPH" "$SWEEP_MPH"

  python3 scripts/_patch_freq_plist.py "$SWEEP_MPH" \
    --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP"

  if [[ ! -f "${SWEEP_SOLVED}" ]] || ! grep -q 'RESULT: PASS' "$SWEEP_VALID" 2>/dev/null; then
    rm -f "$SWEEP_SOLVED" "${SWEEP_SOLVED}.recovery" "$SWEEP_BATCH"

    python3 scripts/comsol_run_hu_bai.py \
      --Q "$Q" --cells 4 --slug "$SWEEP_SLUG" \
      --interface-coupling p1_continuity \
      --freq-only --excitation-axis z --base-accel 0.98 \
      --freq-min "$FREQ_MIN" --freq-max "$FREQ_MAX" --freq-step "$FREQ_STEP" \
      --solve-only "$SWEEP_MPH" \
      --np "$NP" --background

    wait_solve "$SWEEP_SLUG"
  else
    echo "  SKIP solve: valid solved mph present"
  fi

  python3 scripts/_validate_pb_top.py "$SWEEP_SOLVED" "$COMSOL_BIN" \
    | tee "$SWEEP_VALID"
  if ! grep -q 'RESULT: PASS' "$SWEEP_VALID"; then
    echo "ERROR: pb_top validation failed for ${SWEEP_SLUG} — check mesh_p1 bonding"
    exit 1
  fi

  bash scripts/linux/_remote_postprocess_slug.sh "$SWEEP_SLUG"
  echo "  done ${SWEEP_SLUG}"
done

echo ""
echo "=== batch compare Table 3.3 $(date) ==="
python3 scripts/compare_table33_vs_paper.py --batch || true
for KEY in bcc af2q05 af2q1 af2q15; do
  python3 scripts/compare_freq_peaks_vs_paper.py --key "$KEY" || true
done

echo "=== Fig.3.21 four-case batch done $(date) ==="
