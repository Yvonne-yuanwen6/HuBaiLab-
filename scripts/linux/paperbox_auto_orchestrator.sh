#!/usr/bin/env bash
# Overnight orchestrator: wait for Q1/Q0.5 leads, evaluate vs paper, fan-out or optimize.
#
#   nohup bash scripts/linux/paperbox_auto_orchestrator.sh >> output/logs/paperbox_orchestrator.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports

LOG="output/logs/paperbox_orchestrator.log"
STATE="output/logs/paperbox_orchestrator_state.json"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"
EVAL="scripts/evaluate_paperbox_paper_trend.py"

CPUS="${PAPERBOX_FANOUT_CPUS:-24}"
MEM="${PAPERBOX_FANOUT_MEMORY_MB:-131072}"
MAX_PARALLEL="${PAPERBOX_MAX_PARALLEL:-3}"
POLL_SEC="${PAPERBOX_POLL_SEC:-120}"

# Winning variant (settle5p @ 24c — same as current Q1/Q0.5 lead jobs)
WIN_VARIANT="paperbox_settle5p"
WIN_ARGS=(--contact-store-offsets --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02)

BASE="cae_tet0p6mm80_5mmin_paperbox"
BCC_REF="hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_${BASE}"
Q05_REF="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_${BASE}"

LEAD_CANDIDATES=(
  "1|${WIN_VARIANT}|hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_${BASE}_${WIN_VARIANT}"
  "0.5|${WIN_VARIANT}|hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_${BASE}_${WIN_VARIANT}"
  "0.5|paperbox_q05_rods4|hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_${BASE}_paperbox_q05_rods4"
)

FANOUT_QS=(0 0.5 1 1.5)

log() { echo "[$(date)] $*" | tee -a "$LOG"; }

init_state() {
  if [[ ! -f "$STATE" ]]; then
    python3 -c "
import json
print(json.dumps({
  'phase': 'monitoring',
  'winner': None,
  'evaluated': {},
  'fanout_started': {},
  'last_update': '',
}, indent=2))
" > "$STATE"
  fi
}

job_completed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' "$sta"
}

job_failed() {
  local slug="$1"
  local sta="$ROOT/output/jobs/${slug}/${slug}.sta"
  [[ -f "$sta" ]] && grep -q 'THE ANALYSIS HAS NOT BEEN COMPLETED' "$sta"
}

job_running() {
  local slug="$1"
  [[ -f "$ROOT/output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "$slug" >/dev/null 2>&1
}

count_running_paperbox() {
  find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | grep -c paperbox || true
}

slug_for_q_variant() {
  local q="$1" suffix="$2"
  local tag
  tag="$(python3 -c "from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G; print(G(cell_size=20,rod_diameter=2,amplitude=2,period_factor=float('$q')).variant_name.lower())")"
  echo "hu_bai_${tag}_L20_4x4x4_solid_cad_f_${BASE}_${suffix}"
}

stop_q1_sweep() {
  if pgrep -f run_paperbox_q1_diagnostic_sweep.sh >/dev/null 2>&1; then
    log "Stopping Q1 diagnostic sweep (winner found or Q1 lead done)"
    pkill -TERM -f run_paperbox_q1_diagnostic_sweep.sh 2>/dev/null || true
    sleep 3
  fi
}

evaluate_completed() {
  local q="$1" variant="$2" slug="$3"
  log "Evaluate $slug"
  bash "$POSTPULL" "$slug" >> "$LOG" 2>&1 || { log "postpull failed $slug"; return 1; }

  local cmp="${BCC_REF},${Q05_REF}"
  local evjson="output/logs/eval_${slug}.json"
  if python3 "$EVAL" --slug "$slug" --compare-slugs "$cmp" --write-json "$evjson" >> "$LOG" 2>&1; then
    log "PASS $slug (variant=$variant Q=$q)"
    python3 <<PY
import json
from datetime import datetime, timezone
s = json.load(open("$STATE"))
s["winner"] = {
    "Q": "$q",
    "variant": "$variant",
    "slug": "$slug",
    "eval": json.load(open("$evjson")),
}
s["phase"] = "fanout"
s["last_update"] = datetime.now().astimezone().isoformat()
json.dump(s, open("$STATE", "w"), indent=2)
PY
    return 0
  fi
  log "FAIL evaluate $slug — see $evjson"
  python3 -c "
import json
s=json.load(open('$STATE'))
s.setdefault('evaluated',{})['$slug']=json.load(open('$evjson'))
s['last_update']='$(date -Iseconds)'
json.dump(s, open('$STATE','w'), indent=2)
"
  return 1
}

submit_fanout_one() {
  local q="$1" variant="$2"
  local slug
  slug="$(slug_for_q_variant "$q" "$variant")"

  if job_completed "$slug"; then
    log "fanout skip done $slug"
    return 0
  fi
  if job_running "$slug"; then
    log "fanout skip running $slug"
    return 0
  fi

  local running
  running="$(count_running_paperbox)"
  while [[ "$running" -ge "$MAX_PARALLEL" ]]; do
    log "fanout wait slots ($running/$MAX_PARALLEL running)"
    sleep "$POLL_SEC"
    running="$(count_running_paperbox)"
  done

  log "fanout export+submit Q=$q variant=$variant cpus=$CPUS"
  local -a extra=("${WIN_ARGS[@]}")
  if [[ "$variant" == "paperbox_q05_rods4" ]]; then
    extra=(--force-remesh --cae-rods-per-diameter 4 --contact-store-offsets \
      --contact-settle --contact-settle-fraction 0.15 --contact-settle-soft-s0 0.02)
  fi
  bash "$VARIANT_SH" --Q "$q" --variant-suffix "$variant" \
    --cpus "$CPUS" --memory-mb "$MEM" --submit-background \
    "${extra[@]}" >> "$LOG" 2>&1 || log "fanout failed Q=$q"
}

run_fanout() {
  local variant="$1"
  stop_q1_sweep
  log "=== FANOUT variant=$variant cpus=$CPUS max_parallel=$MAX_PARALLEL ==="

  for q in "${FANOUT_QS[@]}"; do
    local slug
    slug="$(slug_for_q_variant "$q" "$variant")"
    if job_completed "$slug"; then
      continue
    fi
    submit_fanout_one "$q" "$variant"
    sleep 5
  done
  log "fanout queue launched"
}

progress_snapshot() {
  local f="output/logs/paperbox_progress_snapshot.txt"
  {
    echo "=== paperbox progress $(date) ==="
    echo "phase: $(python3 -c "import json; print(json.load(open('$STATE')).get('phase','?'))" 2>/dev/null || echo '?')"
    echo "winner: $(python3 -c "import json; w=json.load(open('$STATE')).get('winner'); print(w.get('slug') if w else 'none')" 2>/dev/null || echo none)"
    echo "running jobs:"
    find output/jobs -name '*.lck' 2>/dev/null | grep paperbox | while read -r lck; do
      slug=$(basename "$(dirname "$lck")")
      line=$(grep -E '^[[:space:]]+[0-9]+' "output/jobs/$slug/$slug.sta" 2>/dev/null | tail -1 || true)
      echo "  RUN $slug  ${line:-no sta}"
    done
    echo "completed today:"
    find output/jobs -name '*.sta' 2>/dev/null | grep paperbox | while read -r sta; do
      grep -q 'COMPLETED SUCCESSFULLY' "$sta" || continue
      slug=$(basename "$(dirname "$sta")")
      echo "  DONE $slug"
    done
    echo "load: $(uptime)"
  } > "$f"
}

init_state
log "=== orchestrator start ROOT=$ROOT cpus=$CPUS parallel=$MAX_PARALLEL ==="

while true; do
  progress_snapshot

  phase="$(python3 -c "import json; print(json.load(open('$STATE')).get('phase','monitoring'))")"
  if [[ "$phase" == "fanout" ]]; then
    winner_variant="$(python3 -c "import json; w=json.load(open('$STATE')).get('winner') or {}; print(w.get('variant','paperbox_settle5p'))")"
    run_fanout "$winner_variant"
    python3 -c "
import json
s=json.load(open('$STATE'))
s['phase']='monitoring_fanout'
s['last_update']='$(date -Iseconds)'
json.dump(s, open('$STATE','w'), indent=2)
"
    log "fanout phase done; continue monitoring"
  fi

  winner="$(python3 -c "import json; w=json.load(open('$STATE')).get('winner'); print('yes' if w else 'no')")"
  if [[ "$winner" == "no" ]]; then
    for entry in "${LEAD_CANDIDATES[@]}"; do
      IFS='|' read -r q variant slug <<< "$entry"
      [[ -n "$slug" ]] || continue

      if job_completed "$slug"; then
        evd="$(python3 -c "import json; e=json.load(open('$STATE')).get('evaluated',{}); print('yes' if '$slug' in e or (json.load(open('$STATE')).get('winner') or {}).get('slug')=='$slug' else 'no')" 2>/dev/null || echo no)"
        if [[ "$evd" == "no" ]]; then
          if evaluate_completed "$q" "$variant" "$slug"; then
            stop_q1_sweep
            break
          fi
        fi
        continue
      fi

      if job_failed "$slug"; then
        log "FAILED job $slug — try next candidate"
        continue
      fi

      if job_running "$slug"; then
        line="$(grep -E '^[[:space:]]+[0-9]+' "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tail -1 || true)"
        log "running $slug  ${line:-pre}"
      fi
    done
  fi

  # If only Q0.5 leads running and slots free, retry failed dt1e4 one-at-a-time (optional optimize queue)
  running="$(count_running_paperbox)"
  if [[ "$winner" == "no" && "$running" -lt "$MAX_PARALLEL" ]]; then
    for opt in paperbox_nosettle_dt1e4; do
      slug="$(slug_for_q_variant 0.5 "$opt")"
      if ! job_completed "$slug" && ! job_running "$slug" && ! job_failed "$slug" 2>/dev/null; then
        : # skip — only retry if explicitly queued
      fi
    done
  fi

  sleep "$POLL_SEC"
done
