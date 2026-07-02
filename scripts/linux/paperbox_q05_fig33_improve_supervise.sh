#!/usr/bin/env bash
# Overnight supervisor: resume Q05 fig33 improve sweep, retry crashed jobs, postpull/eval.
#
#   nohup bash scripts/linux/paperbox_q05_fig33_improve_supervise.sh \
#     >> output/logs/paperbox_q05_fig33_improve_supervise.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

IMPROVE="scripts/linux/run_paperbox_q05_fig33_improve.sh"
LOG="output/logs/paperbox_q05_fig33_improve_supervise.log"
LOCK="$ROOT/output/logs/paperbox_q05_fig33_improve.lock"
READY="output/logs/q05_fig33_improve_ready.json"
POLL="${Q05_IMPROVE_SUPERVISE_POLL_SEC:-180}"
STALL_MIN="${Q05_IMPROVE_STALL_MIN:-90}"
MAX_RESUBMIT="${Q05_IMPROVE_MAX_RESUBMIT:-2}"

BASE="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
VARIANTS=(fig33_v2_paper fig33_v2_ep paperbox_settle5p fig33_v2_paper_dt1e4)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

slug_for() { echo "${BASE}_${1}"; }

job_completed() {
  local slug="$1"
  [[ -f "output/jobs/${slug}/${slug}.sta" ]] && \
    grep -q 'COMPLETED SUCCESSFULLY' "output/jobs/${slug}/${slug}.sta"
}

job_running() {
  local slug="$1"
  [[ -f "output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "mpiexec.hydra.*${slug}" >/dev/null 2>&1 || \
  pgrep -f "/bin/explicit.*${slug}" >/dev/null 2>&1
}

job_failed() {
  local slug="$1"
  local sta="output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] || return 1
  grep -qE 'NOT BEEN COMPLETED|SIGTERM|MPI_Abort|excessively distorted|exited with errors' "$sta" && \
    ! job_completed "$slug"
}

last_sim_s() {
  local slug="$1"
  grep -E '^[[:space:]]+[1-9]' "output/jobs/${slug}/${slug}.sta" 2>/dev/null | tail -1 | awk '{print $3}'
}

kill_slug() {
  local slug="$1"
  ps aux | awk -v s="$slug" '/\/bin\/explicit/ && $0 ~ s {print $2}' | xargs -r kill -KILL 2>/dev/null || true
  rm -f "output/jobs/${slug}/${slug}.lck" 2>/dev/null || true
}

clear_stale_lock() {
  if [[ -f "$LOCK" ]] && ! pgrep -f 'bash scripts/linux/run_paperbox_q05_fig33_improve.sh' >/dev/null 2>&1; then
    log "clear stale improve lock"
    rm -f "$LOCK"
  fi
}

start_improve() {
  clear_stale_lock
  if pgrep -f 'bash scripts/linux/run_paperbox_q05_fig33_improve.sh' >/dev/null 2>&1; then
    log "improve orchestrator already running"
    return 0
  fi
  log "start improve sweep cpus=${Q05_IMPROVE_CPUS:-48}"
  Q05_IMPROVE_CPUS="${Q05_IMPROVE_CPUS:-48}" \
  Q05_IMPROVE_MEMORY_MB="${Q05_IMPROVE_MEMORY_MB:-262144}" \
    bash "$IMPROVE" >> output/logs/paperbox_q05_fig33_improve.log 2>&1 &
  sleep 5
}

resubmit_variant() {
  local suffix="$1"
  shift
  local slug
  slug="$(slug_for "$suffix")"
  local n="${RESUBMIT_COUNT[$suffix]:-0}"
  if [[ "$n" -ge "$MAX_RESUBMIT" ]]; then
    log "SKIP resubmit $suffix (max $MAX_RESUBMIT)"
    return 1
  fi
  RESUBMIT_COUNT[$suffix]=$((n + 1))
  log "RESUBMIT $suffix attempt=${RESUBMIT_COUNT[$suffix]}/$MAX_RESUBMIT"
  kill_slug "$slug"
  rm -rf "output/jobs/${slug}"
  bash scripts/linux/run_paperbox_variant.sh --Q 0.5 --variant-suffix "$suffix" \
    --cpus "${Q05_IMPROVE_CPUS:-48}" --memory-mb "${Q05_IMPROVE_MEMORY_MB:-262144}" \
    --export-only "$@"
  bash scripts/linux/run_paperbox_variant.sh --Q 0.5 --variant-suffix "$suffix" \
    --cpus "${Q05_IMPROVE_CPUS:-48}" --memory-mb "${Q05_IMPROVE_MEMORY_MB:-262144}" \
    --submit-background --submit-only "$@" || log "WARN resubmit submit $suffix"
}

declare -A RESUBMIT_COUNT
declare -A LAST_SIM
declare -A STALL_SINCE

VARIANT_ARGS=(
  "fig33_v2_paper|--contact-store-offsets|--material-model|paper"
  "fig33_v2_ep|--contact-store-offsets|--material-model|elastic_plastic"
  "paperbox_settle5p|--contact-store-offsets|--contact-settle|--contact-settle-fraction|0.05|--contact-settle-soft-s0|0.02|--material-model|paper"
  "fig33_v2_paper_dt1e4|--contact-store-offsets|--material-model|paper|--explicit-dt|0.0001|--explicit-dt-mode|fixed|--no-mass-scaling"
)

parse_variant_entry() {
  local entry="$1"
  suffix="${entry%%|*}"
  local rest="${entry#*|}"
  args=()
  IFS='|' read -ra args <<< "$rest"
}

log "=== Q05 fig33 improve supervisor start poll=${POLL}s stall=${STALL_MIN}min ==="
start_improve

while true; do
  if [[ -f "$READY" ]] && python3 -c "import json; print(json.load(open('$READY')).get('all_ready'))" 2>/dev/null | grep -q True; then
    log "all_ready=true — supervisor done"
    exit 0
  fi

  running_slug=""
  for entry in "${VARIANT_ARGS[@]}"; do
    parse_variant_entry "$entry"
    slug="$(slug_for "$suffix")"
    if job_completed "$slug"; then
      continue
    fi
    if job_running "$slug"; then
      running_slug="$slug"
      sim="$(last_sim_s "$slug" || echo 0)"
      if [[ -n "${LAST_SIM[$slug]:-}" && "$sim" == "${LAST_SIM[$slug]}" ]]; then
        STALL_SINCE[$slug]="${STALL_SINCE[$slug]:-$(date +%s)}"
        stall_min=$(( ($(date +%s) - STALL_SINCE[$slug]) / 60 ))
        if [[ "$stall_min" -ge "$STALL_MIN" ]]; then
          log "STALL ${stall_min}min $suffix sim=${sim}s — kill + resubmit"
          resubmit_variant "$suffix" "${args[@]}" || true
          STALL_SINCE[$slug]=""
          LAST_SIM[$slug]=""
        fi
      else
        STALL_SINCE[$slug]=""
        LAST_SIM[$slug]="$sim"
      fi
      pct="$(python3 -c "print(int(min(100,100*float('${sim}')/768)))" 2>/dev/null || echo 0)"
      log "RUN $suffix sim=${sim}s (~${pct}% strain progress)"
    elif job_failed "$slug" || { [[ -f "output/jobs/${slug}/${slug}.sta" ]] && ! job_completed "$slug"; }; then
      log "FAILED/STOP $suffix — resubmit"
      resubmit_variant "$suffix" "${args[@]}" || true
    fi
  done

  if [[ -z "$running_slug" ]] && ! pgrep -f 'bash scripts/linux/run_paperbox_q05_fig33_improve.sh' >/dev/null 2>&1; then
    pending=0
    for entry in "${VARIANT_ARGS[@]}"; do
      parse_variant_entry "$entry"
      job_completed "$(slug_for "$suffix")" || pending=$((pending + 1))
    done
    if [[ "$pending" -gt 0 ]]; then
      log "orchestrator idle with $pending pending — restart improve"
      start_improve
    fi
  fi

  sleep "$POLL"
done
