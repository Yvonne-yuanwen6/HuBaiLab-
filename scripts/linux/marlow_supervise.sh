#!/usr/bin/env bash
# Background supervisor: poll marlow job, live-pull at milestones, resubmit on failure.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

SLUG="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_marlow"
LOG="output/logs/marlow_supervise.log"
POLL="${MARLOW_POLL_SEC:-120}"
SETTLE_S=38.4
STEP_TOTAL=806.4
# compression milestones (total sim time s): ~10% / ~25% strain on lattice
M1=$(python3 -c "print(${SETTLE_S} + 768*0.10/0.80)")   # ~134s ~10% strain
M2=$(python3 -c "print(${SETTLE_S} + 768*0.25/0.80)")   # ~278s ~25% strain
STALL_MIN="${MARLOW_STALL_MIN:-45}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

job_running() {
  pgrep -f "mpiexec.hydra.*${SLUG}" >/dev/null 2>&1 || \
  pgrep -f "/bin/explicit.*${SLUG}" >/dev/null 2>&1
}

job_completed() {
  [[ -f "output/jobs/$SLUG/$SLUG.sta" ]] && \
    grep -q 'COMPLETED SUCCESSFULLY' "output/jobs/$SLUG/$SLUG.sta"
}

job_failed() {
  local sta="output/jobs/$SLUG/$SLUG.sta"
  [[ -f "$sta" ]] || return 1
  grep -qE 'NOT BEEN COMPLETED|SIGTERM|MPI_Abort|excessively distorted' "$sta" && \
    ! job_completed
}

last_sim_s() {
  grep -E '^[[:space:]]+[1-9]' "output/jobs/$SLUG/$SLUG.sta" 2>/dev/null | tail -1 | awk '{print $3}'
}

last_ke() {
  grep -E '^[[:space:]]+[1-9]' "output/jobs/$SLUG/$SLUG.sta" 2>/dev/null | tail -1 | awk '{print $7}'
}

pull_partial() {
  local tag="$1"
  log "=== live pull ($tag) ==="
  if bash scripts/linux/marlow_live_pull_server.sh "$SLUG" >> "$LOG" 2>&1; then
    log "pull ok -> output/post/$SLUG/${SLUG}_stress_strain_partial.csv"
    wc -l "output/post/$SLUG/${SLUG}_stress_strain_partial.csv" 2>/dev/null | tee -a "$LOG" || true
  else
    log "WARN pull failed ($tag)"
  fi
}

resubmit() {
  log "=== RESUBMIT marlow settle5p ==="
  bash scripts/linux/resubmit_marlow_settle5p.sh >> "$LOG" 2>&1 || log "ERROR resubmit failed"
  LAST_SIM=""
  STALL_SINCE=""
  PULLED_M1=0
  PULLED_M2=0
}

log "=== marlow supervisor start poll=${POLL}s milestones=${M1}s,${M2}s ==="
LAST_SIM=""
STALL_SINCE=""
PULLED_M1=0
PULLED_M2=0
PULLED_DONE=0

while true; do
  if job_completed; then
    log "COMPLETED"
    if [[ "$PULLED_DONE" -eq 0 ]]; then
      pull_partial "final"
      PULLED_DONE=1
    fi
    bash scripts/linux/postpull_paperbox_server.sh "$SLUG" >> "$LOG" 2>&1 || true
    log "=== supervisor done ==="
    exit 0
  fi

  if job_failed && ! job_running; then
    log "FAILED/STOPPED detected"
    resubmit
    sleep 60
    continue
  fi

  sim="$(last_sim_s || echo 0)"
  ke="$(last_ke || echo 0)"

  if job_running; then
    if [[ -n "$LAST_SIM" && "$sim" == "$LAST_SIM" ]]; then
      STALL_SINCE="${STALL_SINCE:-$(date +%s)}"
      stall_min=$(( ($(date +%s) - STALL_SINCE) / 60 ))
      if [[ "$stall_min" -ge "$STALL_MIN" ]]; then
        log "STALL ${stall_min}min at sim=${sim}s ke=${ke} — kill + resubmit"
        ps aux | awk -v s="$SLUG" '/\/bin\/explicit/ && $0 ~ s {print $2}' | xargs -r kill -KILL 2>/dev/null || true
        sleep 5
        resubmit
        sleep 60
        continue
      fi
    else
      STALL_SINCE=""
      LAST_SIM="$sim"
    fi
    pct="$(python3 -c "s=float('${sim}'); print(int(min(100,100*s/${STEP_TOTAL})))" 2>/dev/null || echo 0)"
    log "RUNNING sim=${sim}s ke=${ke} (~${pct}%)"

    # post-settle sanity: compression started but RF still ~0
    if python3 -c "exit(0 if float('${sim}') > ${SETTLE_S} + 30 and float('${ke}') < 1e-6 else 1)" 2>/dev/null; then
      log "WARN sim past settle but KE~0 — possible contact hang (watching)"
    fi

    if [[ "$PULLED_M1" -eq 0 ]] && python3 -c "exit(0 if float('${sim}') >= ${M1} else 1)" 2>/dev/null; then
      pull_partial "~10pct_strain"
      PULLED_M1=1
    fi
    if [[ "$PULLED_M2" -eq 0 ]] && python3 -c "exit(0 if float('${sim}') >= ${M2} else 1)" 2>/dev/null; then
      pull_partial "~25pct_strain"
      PULLED_M2=1
    fi
  else
    log "NOT RUNNING sim=${sim}s — waiting or resubmit"
    if [[ -f "output/jobs/$SLUG/$SLUG.sta" ]] && ! job_completed; then
      resubmit
    fi
  fi

  sleep "$POLL"
done
