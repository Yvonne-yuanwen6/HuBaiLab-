#!/usr/bin/env bash
# Q1.5 Fig.3.3 auto-orchestrator: monitor, recover, skip V1 if needed.
#
#   nohup bash scripts/linux/paperbox_q15_fig33_auto_orchestrator.sh \
#     >> output/logs/q15_fig33_orchestrator.log 2>&1 &
#
# Policy (user 2026-06):
#   - V1 (no self-contact): ONE shot; skip on FE/infra failure or trend fail
#   - V2+ always keep self-contact ON
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports

LOCK="$ROOT/output/logs/q15_fig33_orchestrator.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] orchestrator already running (lock $LOCK)" >&2
  exit 0
fi

LOG="output/logs/q15_fig33_orchestrator.log"
STATE="output/logs/q15_fig33_orchestrator_state.json"
TRIAL="output/logs/q15_fig33_self_contact_trial.json"
POLL="${Q15_ORCH_POLL_SEC:-120}"
CPUS="${Q15_FIG33_CPUS:-24}"
MEM="${Q15_FIG33_MEMORY_MB:-131072}"

VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
EVAL="scripts/evaluate_paperbox_q15_trend.py"
PLOT="scripts/plot_q15_fig33_vs_sim.py"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"

BASE="cae_tet0p6mm80_5mmin_paperbox"
TAG="sfbls_af2q1p5"

slug_for() {
  echo "hu_bai_${TAG}_L20_4x4x4_solid_cad_f_${BASE}_$1"
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

init_state() {
  if [[ ! -f "$STATE" ]]; then
    python3 -c "
import json, datetime
print(json.dumps({
  'phase': 'v2_pending',
  'v1': {'suffix': 'q15_v1_ns_el', 'status': 'skipped_distorted', 'reason': '140 distorted elements @ t=0, no self-contact'},
  'active': None,
  'completed': {},
  'winner': None,
  'updated_at': datetime.datetime.now().isoformat(timespec='seconds'),
}, indent=2))
" > "$STATE"
  fi
}

save_state() {
  python3 -c "
import json, datetime
s=json.load(open('$STATE'))
s['updated_at']=datetime.datetime.now().isoformat(timespec='seconds')
json.dump(s, open('$STATE','w'), indent=2, ensure_ascii=False)
"
}

job_status() {
  local slug="$1"
  local sta="$ROOT/output/jobs/$slug/${slug}.sta"
  local lck="$ROOT/output/jobs/$slug/${slug}.lck"
  local odb="$ROOT/output/jobs/$slug/${slug}.odb"
  if [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"; then
    echo COMPLETED
  elif [[ -f "$lck" ]]; then
    echo RUNNING
  elif [[ -f "$sta" ]]; then
    if grep -q 'THE ANALYSIS HAS NOT BEEN COMPLETED' "$sta" || \
       grep -q 'excessively distorted' "$sta" || \
       grep -q 'part map file' "$sta" || \
       grep -q 'FOR0064' "$sta"; then
      echo FAILED
    elif [[ -f "$odb" ]] && [[ $(wc -c < "$odb") -gt 1000000 ]]; then
      echo STOPPED
    else
      echo FAILED
    fi
  elif [[ -f "$ROOT/output/export/$slug/${slug}.inp" ]]; then
    echo QUEUED
  else
    echo WAITING
  fi
}

sim_progress() {
  local slug="$1"
  local sta="$ROOT/output/jobs/$slug/${slug}.sta"
  [[ -f "$sta" ]] || return 0
  local line
  line="$(grep -E '^[[:space:]]+[0-9]+[[:space:]]+' "$sta" | tail -1 || true)"
  [[ -n "$line" ]] || return 0
  echo "$line" | awk '{printf "inc=%s sim=%s wall=%s", $1, $3, $4}'
}

submit_v2() {
  local suffix="q15_v2_el"
  local slug
  slug="$(slug_for "$suffix")"
  log "Submit V2: self-contact ON, linear elastic, nosettle ($suffix)"
  if [[ ! -f "$ROOT/output/export/$slug/${slug}.inp" ]]; then
    bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$suffix" \
      --cpus "$CPUS" --memory-mb "$MEM" \
      --contact-store-offsets \
      --material-model elastic \
      --export-only
  fi
  bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --contact-store-offsets \
    --material-model elastic \
    --submit-only --submit-background
  python3 -c "
import json, datetime
s=json.load(open('$STATE'))
s['phase']='monitor_v2'
s['active']={'suffix':'$suffix','slug':'$slug','variant':'v2'}
json.dump(s, open('$STATE','w'), indent=2, ensure_ascii=False)
"
  python3 -c "
import json, datetime
d={'policy':'v1_skipped','v1_status':'skipped_distorted','v2_suffix':'$suffix','last_status':'v2_submitted','updated_at':datetime.datetime.now().isoformat(timespec='seconds')}
json.dump(d, open('$TRIAL','w'), indent=2, ensure_ascii=False)
"
}

submit_v4() {
  local suffix="q15_v4_rd4"
  local slug
  slug="$(slug_for "$suffix")"
  log "Submit V4: self-contact ON, linear, rods-per-diameter=4 ($suffix)"
  if [[ ! -f "$ROOT/output/export/$slug/${slug}.inp" ]]; then
    bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$suffix" \
      --cpus "$CPUS" --memory-mb "$MEM" \
      --cae-rods-per-diameter 4 \
      --contact-store-offsets \
      --material-model elastic \
      --export-only
  fi
  bash "$VARIANT_SH" --Q 1.5 --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --cae-rods-per-diameter 4 \
    --contact-store-offsets \
    --material-model elastic \
    --submit-only --submit-background
  python3 -c "
import json
s=json.load(open('$STATE'))
s['phase']='monitor_v4'
s['active']={'suffix':'$suffix','slug':'$slug','variant':'v4'}
json.dump(s, open('$STATE','w'), indent=2, ensure_ascii=False)
"
}

postpull_eval() {
  local suffix="$1"
  local slug
  slug="$(slug_for "$suffix")"
  log "Postpull $slug"
  if ! bash "$POSTPULL" "$slug"; then
    log "Postpull failed for $slug"
    return 1
  fi
  log "Evaluate trend $suffix"
  if python3 "$EVAL" --variant-suffix "$suffix" --write-json "output/logs/q15_fig33_eval_${suffix}.json"; then
    python3 "$PLOT" --variant "" --variant "$suffix" \
      --png "output/reports/q15_fig33_exp_vs_sim_${suffix}.png" || true
    python3 -c "
import json
s=json.load(open('$STATE'))
s['winner']={'suffix':'$suffix','slug':'$slug'}
s['phase']='done'
s['completed']['$suffix']='trend_pass'
json.dump(s, open('$STATE','w'), indent=2, ensure_ascii=False)
"
    log "Q15 TREND PASS with $suffix"
    return 0
  fi
  python3 -c "
import json
s=json.load(open('$STATE'))
s['completed']['$suffix']='trend_fail'
json.dump(s, open('$STATE','w'), indent=2, ensure_ascii=False)
"
  log "Q15 trend FAIL for $suffix"
  return 1
}

monitor_active() {
  local suffix slug st prog
  suffix="$(python3 -c "import json; print(json.load(open('$STATE')).get('active',{}).get('suffix',''))")"
  [[ -n "$suffix" ]] || return 1
  slug="$(slug_for "$suffix")"
  st="$(job_status "$slug")"
  prog="$(sim_progress "$slug" || true)"
  log "[$suffix] $st ${prog:-}"
  case "$st" in
    RUNNING|QUEUED|WAITING) return 0 ;;
    COMPLETED)
      if postpull_eval "$suffix"; then return 2; fi
      return 3
      ;;
    *)
      log "Job $suffix ended: $st"
      return 3
      ;;
  esac
}

main_loop() {
  init_state
  phase="$(python3 -c "import json; print(json.load(open('$STATE')).get('phase','v2_pending'))")"
  log "Orchestrator start phase=$phase"

  if [[ "$phase" == "v2_pending" ]]; then
    submit_v2
    phase="monitor_v2"
  fi

  while true; do
    phase="$(python3 -c "import json; print(json.load(open('$STATE')).get('phase',''))")"
    if [[ "$phase" == "done" ]]; then
      log "All done. Winner: $(python3 -c "import json; print(json.load(open('$STATE')).get('winner'))")"
      break
    fi

    if [[ "$phase" == monitor_v2 ]]; then
      monitor_active
      rc=$?
      if [[ $rc -eq 2 ]]; then break; fi
      if [[ $rc -eq 3 ]]; then
        log "V2 failed; skip to V4"
        submit_v4
      fi
    elif [[ "$phase" == monitor_v4 ]]; then
      monitor_active
      rc=$?
      if [[ $rc -eq 2 ]]; then break; fi
      if [[ $rc -eq 3 ]]; then
        log "V4 failed; orchestrator stop"
        python3 -c "import json; s=json.load(open('$STATE')); s['phase']='failed'; json.dump(s,open('$STATE','w'),indent=2)"
        break
      fi
    else
      log "Unknown phase=$phase"
    fi
    save_state
    sleep "$POLL"
  done
  save_state
  log "Orchestrator exit"
}

main_loop "$@"
