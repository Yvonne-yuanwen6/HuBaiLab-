#!/usr/bin/env bash
# Test-subarray CAE compression queue (332/333/442/443 x four Q).
#
# Reuses existing CAE meshes under output/export/test/{size}/{cid}/$RUN_SLUG/
# Exports compression INPs with --nx/--ny/--nz (stroke = 0.8*nz*L), then submits.
#
# Prerequisites on server:
#   - synced meshes: output/export/test/.../*_cae_mesh.inp
#   - synced STEPs:  output/cad/test/{size}/{cid}_{size}.step
#
# Usage:
#   bash scripts/linux/run_test_subarray_cae_sim_queue.sh
#   BATCH_SIM_EXPORT_ONLY=1 bash scripts/linux/run_test_subarray_cae_sim_queue.sh
#   BATCH_SIM_SUBMIT_ONLY=1 bash scripts/linux/run_test_subarray_cae_sim_queue.sh
#   BATCH_SIM_ONLY="332/af2q0_deq2_k1 442/af2q1_deq2_k1" bash scripts/linux/run_test_subarray_cae_sim_queue.sh
#   BATCH_SIM_FORCE_EXPORT=1 BATCH_SIM_MAX_PARALLEL=2 bash scripts/linux/run_test_subarray_cae_sim_queue.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PY="${BATCH_COMSOL_PYTHON:-${PYTHON:-python3}}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

RUN_SLUG="${BATCH_SIM_RUN_SLUG:-cae_tet0p6mm80_5mmin_paperbox}"
BATCH_NAME="test"
CPUS="${BATCH_SIM_CPUS:-48}"
MEM="${BATCH_SIM_MEMORY_MB:-262144}"
MAX_PARALLEL="${BATCH_SIM_MAX_PARALLEL:-2}"
POLL_SEC="${BATCH_SIM_POLL_SEC:-45}"
EXPORT_ONLY="${BATCH_SIM_EXPORT_ONLY:-0}"
SUBMIT_ONLY="${BATCH_SIM_SUBMIT_ONLY:-0}"
FORCE_EXPORT="${BATCH_SIM_FORCE_EXPORT:-0}"
ALLOW_SOLVE_RETRY="${BATCH_SIM_ALLOW_SOLVE_RETRY:-0}"
ONLY="${BATCH_SIM_ONLY:-}"

LOG_DIR="$ROOT/output/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/test_subarray_cae_sim_queue.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

SIZES=(332 333 442 443)
CASES=(af2q0_deq2_k1 af2q0p5_deq2_k1 af2q1_deq2_k1 af2q1p5_deq2_k1)

build_ready() {
  local size cid key mesh
  READY=()
  if [[ -n "$ONLY" ]]; then
    # shellcheck disable=SC2206
    READY=($ONLY)
    return 0
  fi
  for size in "${SIZES[@]}"; do
    for cid in "${CASES[@]}"; do
      key="${size}/${cid}"
      mesh="$ROOT/output/export/${BATCH_NAME}/${size}/${cid}/${RUN_SLUG}/${RUN_SLUG}_cae_mesh.inp"
      if [[ -f "$mesh" && "$(wc -c <"$mesh" | tr -d ' ')" -gt 1000000 ]]; then
        READY+=("$key")
      else
        log "WARN skip (no mesh) $key"
      fi
    done
  done
}

case_roots() {
  local key="$1"
  export HU_BAI_EXPORT_ROOT="$ROOT/output/export/${BATCH_NAME}/${key}"
  export HU_BAI_JOBS_ROOT="$ROOT/output/jobs/${BATCH_NAME}/${key}"
  export HU_BAI_POST_ROOT="$ROOT/output/post/${BATCH_NAME}/${key}"
  mkdir -p "$HU_BAI_EXPORT_ROOT" "$HU_BAI_JOBS_ROOT" "$HU_BAI_POST_ROOT"
}

unset_case_roots() {
  unset HU_BAI_EXPORT_ROOT HU_BAI_JOBS_ROOT HU_BAI_POST_ROOT
}

job_dir() { echo "$ROOT/output/jobs/${BATCH_NAME}/$1/${RUN_SLUG}"; }
export_dir() { echo "$ROOT/output/export/${BATCH_NAME}/$1/${RUN_SLUG}"; }
mesh_inp_path() { echo "$(export_dir "$1")/${RUN_SLUG}_cae_mesh.inp"; }
comp_inp_path() { echo "$(export_dir "$1")/${RUN_SLUG}.inp"; }
sta_path() { echo "$(job_dir "$1")/${RUN_SLUG}.sta"; }

inp_ready() { [[ -f "$(comp_inp_path "$1")" && "$(wc -c <"$(comp_inp_path "$1")" | tr -d ' ')" -gt 1000000 ]]; }
job_running() { [[ -f "$(job_dir "$1")/${RUN_SLUG}.lck" ]]; }
job_completed() {
  local sta
  sta="$(sta_path "$1")"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_failed() {
  local key="$1" jd sta slog
  job_running "$key" && return 1
  job_completed "$key" && return 1
  jd="$(job_dir "$key")"
  sta="$jd/${RUN_SLUG}.sta"
  slog="$jd/${RUN_SLUG}_submit.log"
  if [[ -f "$sta" ]] && grep -qE \
      'THE ANALYSIS HAS BEEN ABORTED|Abaqus/Analysis exited with errors|Excessive distortion' \
      "$sta" 2>/dev/null; then
    return 0
  fi
  if [[ -f "$slog" ]] && grep -qE \
      'Abaqus/Analysis exited with errors|Abaqus/Explicit Analysis exited with an error' \
      "$slog" 2>/dev/null; then
    return 0
  fi
  return 1
}

parse_key() {
  # sets SIZE CID NX NY NZ Af Q deq STEP
  local key="$1"
  SIZE="${key%%/*}"
  CID="${key#*/}"
  NX="${SIZE:0:1}"
  NY="${SIZE:1:1}"
  NZ="${SIZE:2:1}"
  read -r Af Q deq <<<"$("$PY" - <<PY
import re
cid = "${CID}"
m = re.match(r"^af([\\dp]+)q([\\dp]+)_deq([\\dp]+)_k([\\dp]+)\$", cid)
if not m:
    raise SystemExit(f"bad case {cid}")
def p(s):
    return float(s.replace("p", "."))
print(p(m.group(1)), p(m.group(2)), p(m.group(3)))
PY
)"
  STEP="$ROOT/output/cad/${BATCH_NAME}/${SIZE}/${CID}_${SIZE}.step"
}

export_one() {
  local key="$1"
  local mesh_inp comp
  parse_key "$key"
  mesh_inp="$(mesh_inp_path "$key")"
  comp="$(comp_inp_path "$key")"

  if [[ ! -f "$mesh_inp" ]]; then
    log "ERROR no mesh $key"
    return 1
  fi
  if [[ ! -f "$STEP" ]]; then
    log "ERROR no STEP $STEP"
    return 1
  fi
  if inp_ready "$key" && [[ "$FORCE_EXPORT" != "1" ]]; then
    log "SKIP export (inp exists) $key"
    return 0
  fi

  case_roots "$key"
  log "EXPORT $key ${NX}x${NY}x${NZ} Q=$Q deq=$deq stroke=$(awk "BEGIN{print 0.8*$NZ*20}")mm"
  local -a args=(
    scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
    --nx "$NX" --ny "$NY" --nz "$NZ" --L 20
    --Q "$Q" --Af "$Af" --rod-diameter "$deq"
    --profile fast
    --cad "$STEP"
    --cae-seed 0.6
    --cae-element-type C3D4
    --cae-mesh-quality lattice_contact
    --strain 0.80 --load-rate-mm-min 5
    --explicit-dt 0.0005 --explicit-dt-mode automatic
    --material-model paper
    --contact-store-offsets
    --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02
    --slug-mode short
    --short-slug "$RUN_SLUG"
    --mesh-locally
    --cae-mesh-inp "$mesh_inp"
  )
  local elog
  elog="$(export_dir "$key")/cae_export_queue.log"
  mkdir -p "$(export_dir "$key")"
  if ! "$PY" "${args[@]}" >>"$elog" 2>&1; then
    log "EXPORT FAIL $key (see $elog)"
    unset_case_roots
    return 1
  fi
  if ! inp_ready "$key"; then
    log "EXPORT FAIL $key — no compression INP"
    unset_case_roots
    return 1
  fi
  log "EXPORT OK $key -> $comp"
  unset_case_roots
  return 0
}

declare -A LAUNCHED=()
declare -A SKIPPED=()

submit_one() {
  local key="$1"
  if job_completed "$key"; then
    log "SKIP submit (completed) $key"
    return 0
  fi
  if job_running "$key"; then
    log "SKIP submit (running) $key"
    return 0
  fi
  if [[ -n "${LAUNCHED[$key]:-}" ]]; then
    log "SKIP submit (already launched) $key"
    return 0
  fi
  if [[ "$ALLOW_SOLVE_RETRY" != "1" ]] && job_failed "$key"; then
    log "SKIP submit (prior solve failed) $key"
    SKIPPED["$key"]=1
    return 0
  fi
  if ! inp_ready "$key"; then
    return 1
  fi
  case_roots "$key"
  LAUNCHED["$key"]=1
  log "SUBMIT $key cpus=$CPUS mem=$MEM"
  if ! bash scripts/linux/submit_job.sh \
      --slug "$RUN_SLUG" \
      --cpus "$CPUS" \
      --memory-mb "$MEM" \
      --background >>"$LOG" 2>&1; then
    log "ERROR submit failed $key"
    unset "LAUNCHED[$key]" || true
    unset_case_roots
    return 1
  fi
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    job_running "$key" && break
    sleep 1
  done
  unset_case_roots
  return 0
}

count_running() {
  local n=0 key
  for key in "${READY[@]}"; do
    job_running "$key" && n=$((n + 1))
  done
  echo "$n"
}

fill_submit_slots() {
  local key n
  n="$(count_running)"
  for key in "${READY[@]}"; do
    [[ -n "${SKIPPED[$key]:-}" ]] && continue
    job_completed "$key" && continue
    job_running "$key" && continue
    inp_ready "$key" || continue
    if [[ "$n" -ge "$MAX_PARALLEL" ]]; then
      break
    fi
    if submit_one "$key"; then
      n=$((n + 1))
    fi
  done
}

# ---- main ----
build_ready
if [[ ${#READY[@]} -eq 0 ]]; then
  log "ABORT: no cases with mesh under output/export/test/"
  exit 1
fi

log "=== test-subarray CAE sim queue start cases=${#READY[@]} export_only=$EXPORT_ONLY submit_only=$SUBMIT_ONLY parallel=$MAX_PARALLEL ==="
log "queue: ${READY[*]}"

if [[ "$SUBMIT_ONLY" != "1" ]]; then
  log "=== export phase ==="
  for key in "${READY[@]}"; do
    export_one "$key" || true
    fill_submit_slots || true
  done
fi

if [[ "$EXPORT_ONLY" == "1" ]]; then
  log "=== export-only done ==="
  exit 0
fi

log "=== submit/wait phase ==="
fill_submit_slots || true
while true; do
  fill_submit_slots || true
  pending=0
  for key in "${READY[@]}"; do
    [[ -n "${SKIPPED[$key]:-}" ]] && continue
    job_completed "$key" && continue
    if [[ "$ALLOW_SOLVE_RETRY" != "1" ]] && job_failed "$key"; then
      SKIPPED["$key"]=1
      continue
    fi
    if inp_ready "$key" || job_running "$key"; then
      # still waiting if not completed
      if ! job_completed "$key"; then
        pending=$((pending + 1))
      fi
    fi
  done
  running="$(count_running)"
  log "wait: running=$running pending~$pending"
  if [[ "$pending" -eq 0 && "$running" -eq 0 ]]; then
    break
  fi
  sleep "$POLL_SEC"
done

n_ok=0
n_fail=0
for key in "${READY[@]}"; do
  if job_completed "$key"; then
    n_ok=$((n_ok + 1))
  else
    n_fail=$((n_fail + 1))
    log "NOT OK $key"
  fi
done
log "=== DONE completed=$n_ok not_ok=$n_fail ==="
[[ "$n_fail" -eq 0 ]]
