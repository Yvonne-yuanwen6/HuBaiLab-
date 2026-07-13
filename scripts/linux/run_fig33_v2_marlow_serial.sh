#!/usr/bin/env bash
# Fig.3.3 fan-out: V2 Marlow (Fig.2.5 WPD + ContactSettle 5%, self-contact ON).
# Order: Q1.5 -> Q0.5 -> Q1 -> BCC. Serial (default) or parallel via FIG33_V2_MAX_PARALLEL.
#
#   bash scripts/linux/run_fig33_v2_marlow_serial.sh
#   nohup bash scripts/linux/run_fig33_v2_marlow_serial.sh \
#     >> output/logs/fig33_v2_marlow_serial.log 2>&1 &
#   FIG33_V2_MAX_PARALLEL=2 nohup bash scripts/linux/run_fig33_v2_marlow_serial.sh ...
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports

LOG="output/logs/fig33_v2_marlow_serial.log"
STATE="output/logs/fig33_v2_marlow_serial_state.json"
LOCK="$ROOT/output/logs/fig33_v2_marlow_serial.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] fig33_v2_marlow serial already running (lock $LOCK)" >> "$LOG"
  exit 0
fi

VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"
FIG25="data/hu_bai_tpu_fig25_tensile_traced.json"

CPUS="${FIG33_V2_CPUS:-48}"
MEM="${FIG33_V2_MEMORY_MB:-262144}"
VARIANT_SUFFIX="${FIG33_V2_VARIANT_SUFFIX:-fig33_v2_marlow}"
POLL_SEC="${FIG33_V2_POLL_SEC:-120}"
MAX_PARALLEL="${FIG33_V2_MAX_PARALLEL:-1}"
QUEUE=(1.5 0.5 1 0)

V2_EXTRA=(
  --contact-store-offsets
  --contact-settle
  --contact-settle-fraction 0.05
  --contact-settle-soft-s0 0.02
  --material-model marlow
  --tpu-fig25-json "$FIG25"
)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

[[ -f "$FIG25" ]] || { log "ERROR missing $FIG25 — sync data/ from local"; exit 1; }

slug_for_q() {
  local q="$1" suffix="$2"
  python3 -c "
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G
q=float('$q')
suffix='$suffix'
base='cae_tet0p6mm80_5mmin_paperbox'
tag=G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=q).variant_name.lower()
print(f'hu_bai_{tag}_L20_4x4x4_solid_cad_f_{base}_{suffix}')
"
}

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

wait_for_slug() {
  local slug="$1"
  while job_running "$slug"; do
    local prog=""
    if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
      prog="$(tail -1 "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-80 || true)"
    fi
    log "WAIT $slug running ${prog:+( $prog )}"
    sleep "$POLL_SEC"
  done
  if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]] && ! job_completed "$slug"; then
    log "ERROR $slug stopped without COMPLETED"
    return 1
  fi
  return 0
}

postpull_slug() {
  local slug="$1"
  if csv_ready "$slug"; then
    return 0
  fi
  if [[ -f "$ROOT/output/jobs/${slug}/${slug}.odb" ]] || job_completed "$slug"; then
    bash "$POSTPULL" "$slug" >> "$LOG" 2>&1 || log "WARN postpull failed $slug"
  fi
}

needs_work() {
  local q="$1" slug
  slug="$(slug_for_q "$q" "$VARIANT_SUFFIX")"
  if job_completed "$slug" && csv_ready "$slug"; then
    return 1
  fi
  return 0
}

count_running_queue() {
  local q slug n=0
  for q in "${QUEUE[@]}"; do
    slug="$(slug_for_q "$q" "$VARIANT_SUFFIX")"
    if job_running "$slug"; then
      n=$((n + 1))
    fi
  done
  echo "$n"
}

start_one() {
  local q="$1" background="${2:-0}"
  local slug submit_bg=()

  slug="$(slug_for_q "$q" "$VARIANT_SUFFIX")"
  if job_completed "$slug"; then
    log "SKIP Q=$q already COMPLETED ($VARIANT_SUFFIX) slug=$slug"
    postpull_slug "$slug"
    return 0
  fi

  if job_running "$slug"; then
    log "RESUME Q=$q job already running slug=$slug"
    if [[ "$background" -eq 0 ]]; then
      wait_for_slug "$slug"
      postpull_slug "$slug"
    fi
    return 0
  fi

  log "RUN Q=$q variant=$VARIANT_SUFFIX cpus=$CPUS mem_mb=$MEM slug=$slug bg=$background"
  bash "$VARIANT_SH" --Q "$q" --variant-suffix "$VARIANT_SUFFIX" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    "${V2_EXTRA[@]}" \
    --export-only
  if [[ "$background" -eq 1 ]]; then
    submit_bg=(--submit-background)
  fi
  bash "$VARIANT_SH" --Q "$q" --variant-suffix "$VARIANT_SUFFIX" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    "${V2_EXTRA[@]}" \
    --submit-only "${submit_bg[@]}"
  if [[ "$background" -eq 0 ]]; then
    log "DONE solve Q=$q slug=$slug"
    postpull_slug "$slug"
  else
    log "SUBMITTED bg Q=$q slug=$slug"
  fi
}

init_state() {
  python3 -c "
import json, datetime
print(json.dumps({
  'policy': 'fig33_v2_marlow fan-out',
  'variant_suffix': '$VARIANT_SUFFIX',
  'cpus': $CPUS,
  'memory_mb': $MEM,
  'max_parallel': $MAX_PARALLEL,
  'order': ['1.5', '0.5', '1', '0'],
  'phase': 'running',
  'started_at': datetime.datetime.now().isoformat(timespec='seconds'),
}, indent=2))
" > "$STATE"
}

finish_state() {
  python3 -c "
import json, datetime
s=json.load(open('$STATE'))
s['phase']='done'
s['finished_at']=datetime.datetime.now().isoformat(timespec='seconds')
json.dump(s, open('$STATE','w'), indent=2)
"
}

run_serial() {
  for q in "${QUEUE[@]}"; do
    start_one "$q" 0
  done
}

run_parallel() {
  local q slug running started
  while true; do
    running="$(count_running_queue)"
    started=0
    for q in "${QUEUE[@]}"; do
      slug="$(slug_for_q "$q" "$VARIANT_SUFFIX")"
      if needs_work "$q"; then
        if job_running "$slug"; then
          :
        elif [[ "$running" -lt "$MAX_PARALLEL" ]]; then
          start_one "$q" 1
          running=$((running + 1))
          started=1
        fi
      elif job_completed "$slug"; then
        postpull_slug "$slug"
      fi
    done

    running="$(count_running_queue)"
    local pending=0
    for q in "${QUEUE[@]}"; do
      needs_work "$q" && pending=1
    done
    if [[ "$pending" -eq 0 ]]; then
      break
    fi

    for q in "${QUEUE[@]}"; do
      slug="$(slug_for_q "$q" "$VARIANT_SUFFIX")"
      if job_running "$slug"; then
        if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
          prog="$(tail -1 "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-72 || true)"
          log "[$slug] RUNNING ${prog:+( $prog )}"
        fi
      fi
    done
    log "parallel tick running=$running max=$MAX_PARALLEL pending=$pending"
    sleep "$POLL_SEC"
  done

  for q in "${QUEUE[@]}"; do
    postpull_slug "$(slug_for_q "$q" "$VARIANT_SUFFIX")"
  done
}

log "=== fig33_v2_marlow start cpus=$CPUS mem_mb=$MEM max_parallel=$MAX_PARALLEL order=1.5,0.5,1,0 ==="
init_state

if [[ "$MAX_PARALLEL" -le 1 ]]; then
  run_serial
else
  run_parallel
fi

finish_state
log "=== fig33_v2_marlow finished ==="
