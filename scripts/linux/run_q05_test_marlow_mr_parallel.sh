#!/usr/bin/env bash
# SFBLS Q=0.5 4×4×4 full compression: Marlow vs Mooney-Rivlin (test data) in parallel.
#
#   bash scripts/linux/run_q05_test_marlow_mr_parallel.sh
#   nohup bash scripts/linux/run_q05_test_marlow_mr_parallel.sh \
#     >> output/logs/q05_test_marlow_mr_parallel.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/q05_test_marlow_mr output/post

LOG="output/logs/q05_test_marlow_mr_parallel.log"
LOCK="$ROOT/output/logs/q05_test_marlow_mr_parallel.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] q05_test_marlow_mr already running (lock $LOCK)" | tee -a "$LOG"
  exit 0
fi
HEALTH_WAIT_SEC="${Q05_TEST_HEALTH_WAIT_SEC:-180}"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"
CAD="output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step"
BASELINE_SLUG="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
BASELINE_MESH="output/export/${BASELINE_SLUG}/${BASELINE_SLUG}_cae_mesh.inp"
LATTICE_PREFIX="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f"

CPUS="${Q05_TEST_CPUS:-32}"
MEM="${Q05_TEST_MEMORY_MB:-196608}"
POLL_SEC="${Q05_TEST_POLL_SEC:-120}"

SLUG_MARLOW="${LATTICE_PREFIX}_test_marlow"
SLUG_MR="${LATTICE_PREFIX}_test_MR"

EXPORT_COMMON=(
  scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py
  --cells 4 --Q 0.5 --profile fast
  --cad "$CAD"
  --cae-seed 0.6 --cae-element-type C3D4 --cae-mesh-quality lattice_contact
  --cae-virtual-topology --mesh-locally
  --cae-mesh-inp "$BASELINE_MESH"
  --strain 0.80 --load-rate-mm-min 5
  --explicit-dt 0.0005 --explicit-dt-mode automatic
  --contact-store-offsets
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02
  --tpu-fig25-json "$FIG25"
)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_running() {
  local slug="$1"
  [[ -f "$ROOT/output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "mpiexec.hydra.*${slug}" >/dev/null 2>&1 || \
  pgrep -f "/bin/explicit.*${slug}" >/dev/null 2>&1 || \
  pgrep -f "SMAPython.*-job ${slug}" >/dev/null 2>&1
}

csv_ready() {
  local slug="$1"
  [[ -f "$ROOT/output/post/${slug}/${slug}_stress_strain.csv" ]]
}

export_one() {
  local suffix="$1" model="$2"
  log "EXPORT suffix=$suffix model=$model"
  rm -rf "output/export/${LATTICE_PREFIX}_${suffix}" \
         "output/jobs/${LATTICE_PREFIX}_${suffix}"
  python3 "${EXPORT_COMMON[@]}" \
    --material-model "$model" \
    --case-suffix "$suffix"
  grep -A8 '^\*Material, name=TPU' \
    "output/export/${LATTICE_PREFIX}_${suffix}/${LATTICE_PREFIX}_${suffix}.inp" \
    | head -12 | tee -a "$LOG" || true
}

submit_one() {
  local slug="$1"
  if job_running "$slug"; then
    log "SKIP submit (already running): $slug"
    return 0
  fi
  if job_completed "$slug"; then
    log "SKIP submit (already completed): $slug"
    return 0
  fi
  log "SUBMIT $slug cpus=$CPUS mem=${MEM}MB"
  bash scripts/linux/submit_job.sh \
    --slug "$slug" \
    --cpus "$CPUS" \
    --memory-mb "$MEM" \
    --skip-resource-check \
    --background
}

health_check_slug() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  local msg="$ROOT/output/jobs/${slug}/${slug}.msg"
  sleep "$HEALTH_WAIT_SEC"
  if job_completed "$slug"; then
    log "HEALTH OK $slug completed during warmup"
    return 0
  fi
  if ! job_running "$slug"; then
    log "HEALTH FAIL $slug stopped before warmup (${HEALTH_WAIT_SEC}s)"
    [[ -f "$sta" ]] && tail -8 "$sta" | tee -a "$LOG" || true
    [[ -f "$msg" ]] && grep -i 'ERROR\|fatal\|20,000,000' "$msg" 2>/dev/null | tail -5 | tee -a "$LOG" || true
    return 1
  fi
  local inc_line=""
  inc_line="$(grep -E '^[[:space:]]+[0-9]+[[:space:]]+[0-9]' "$sta" 2>/dev/null | tail -1 || true)"
  if [[ -z "$inc_line" ]]; then
    log "HEALTH WARN $slug running but no increment line yet"
    return 0
  fi
  local inc
  inc="$(echo "$inc_line" | awk '{print $1}')"
  log "HEALTH OK $slug running increment=$inc line=${inc_line:0:80}"
  if [[ "${inc:-0}" -le 2 ]]; then
    log "HEALTH WARN $slug still at low increment after ${HEALTH_WAIT_SEC}s — watch closely"
  fi
  return 0
}

postpull_one() {
  local slug="$1"
  if csv_ready "$slug"; then
    log "CSV already present: $slug"
    return 0
  fi
  bash scripts/linux/postpull_paperbox_server.sh "$slug"
}

write_ready() {
  python3 - <<PY
import json
from pathlib import Path

root = Path(".")
slugs = [
    "${SLUG_MARLOW}",
    "${SLUG_MR}",
]
items = []
all_ready = True
for slug in slugs:
    sta = root / "output/jobs" / slug / f"{slug}.sta"
    csv = root / "output/post" / slug / f"{slug}_stress_strain.csv"
    completed = sta.is_file() and "COMPLETED SUCCESSFULLY" in sta.read_text(encoding="utf-8", errors="replace")
    csv_ok = csv.is_file()
    items.append({"slug": slug, "completed": completed, "csv_ready": csv_ok})
    all_ready = all_ready and completed and csv_ok

out = {"all_ready": all_ready, "cases": items}
path = root / "output/logs/q05_test_marlow_mr_ready.json"
path.write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
PY
}

exec > >(tee -a "$LOG") 2>&1

log "=== Q05 test_marlow + test_MR parallel start cpus=$CPUS mem=${MEM}MB mass_scaling=default ==="
[[ -f "$CAD" ]] || { log "ERROR missing CAD: $CAD"; exit 1; }
[[ -f "$BASELINE_MESH" ]] || { log "ERROR missing baseline mesh: $BASELINE_MESH"; exit 1; }
[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25"; exit 1; }

export_one test_marlow marlow
export_one test_MR polynomial

submit_one "$SLUG_MARLOW"
submit_one "$SLUG_MR"

health_check_slug "$SLUG_MARLOW" &
pid_h1=$!
health_check_slug "$SLUG_MR" &
pid_h2=$!
wait "$pid_h1" || { log "ERROR health check failed: $SLUG_MARLOW"; exit 1; }
wait "$pid_h2" || { log "ERROR health check failed: $SLUG_MR"; exit 1; }

while job_running "$SLUG_MARLOW" || job_running "$SLUG_MR"; do
  for slug in "$SLUG_MARLOW" "$SLUG_MR"; do
    if job_running "$slug"; then
      prog=""
      if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
        prog="$(tail -1 "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-90 || true)"
      fi
      log "RUNNING $slug ${prog:+( $prog )}"
    fi
  done
  write_ready || true
  sleep "$POLL_SEC"
done

failed=0
for slug in "$SLUG_MARLOW" "$SLUG_MR"; do
  if ! job_completed "$slug"; then
    log "ERROR $slug did not complete successfully"
    failed=1
  fi
done
[[ "$failed" -eq 0 ]] || exit 1

postpull_one "$SLUG_MARLOW"
postpull_one "$SLUG_MR"
write_ready
log "=== Q05 test_marlow + test_MR finished ==="
