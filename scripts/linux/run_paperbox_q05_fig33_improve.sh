#!/usr/bin/env bash
# Q0.5 Fig.3.3 improvement sweep (structure verified OK — tune material / contact / dt).
#
# Variants (serial by default):
#   1. fig33_v2_paper      Neo-Hooke + STORE OFFSETS (vs fig33_v2_el elastic baseline)
#   2. fig33_v2_ep         elastic-plastic + STORE OFFSETS
#   3. paperbox_settle5p   5% ContactSettle + paper (skip if already COMPLETED)
#   4. fig33_v2_paper_dt1e4  paper + dt=1e-4 fixed + no mass scaling
#
#   nohup bash scripts/linux/run_paperbox_q05_fig33_improve.sh \
#     >> output/logs/paperbox_q05_fig33_improve.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports

LOG="output/logs/paperbox_q05_fig33_improve.log"
STATE="output/logs/paperbox_q05_fig33_improve_state.json"
LOCK="$ROOT/output/logs/paperbox_q05_fig33_improve.lock"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"
EVAL="scripts/evaluate_paperbox_q05_trend.py"

CPUS="${Q05_IMPROVE_CPUS:-48}"
MEM="${Q05_IMPROVE_MEMORY_MB:-262144}"
POLL_SEC="${Q05_IMPROVE_POLL_SEC:-120}"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Q05 improve sweep already running (lock $LOCK)" >> "$LOG"
  exit 0
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

slug_for() {
  echo "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${1}"
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
  pgrep -f "/bin/explicit.*${slug}" >/dev/null 2>&1
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

postpull_and_eval() {
  local suffix="$1"
  local slug
  slug="$(slug_for "$suffix")"
  if ! job_completed "$slug"; then
    return 0
  fi
  if ! csv_ready "$slug"; then
    bash "$POSTPULL" "$slug" >> "$LOG" 2>&1 || { log "WARN postpull failed $slug"; return 1; }
  fi
  if [[ -f "$EVAL" ]]; then
    local evjson="output/logs/eval_q05_${suffix}.json"
    python3 "$EVAL" --slug "$slug" --write-json "$evjson" >> "$LOG" 2>&1 || log "WARN eval failed $slug"
  fi
}

run_variant() {
  local suffix="$1"
  shift
  local slug
  slug="$(slug_for "$suffix")"

  if job_completed "$slug"; then
    log "SKIP completed $suffix slug=$slug"
    postpull_and_eval "$suffix"
    return 0
  fi

  if job_running "$slug"; then
    log "RESUME running $suffix slug=$slug"
    wait_for_slug "$slug" || return 1
    postpull_and_eval "$suffix"
    return 0
  fi

  log "RUN Q=0.5 variant=$suffix cpus=$CPUS slug=$slug"
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --export-only "$@"
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --submit-background --submit-only "$@" || log "WARN submit returned nonzero $suffix"

  wait_for_slug "$slug" || return 1
  postpull_and_eval "$suffix"
  log "DONE $suffix slug=$slug"
}

init_state() {
  python3 -c "
import json, datetime
print(json.dumps({
  'policy': 'Q05 fig33 improve sweep',
  'variants': ['fig33_v2_paper', 'fig33_v2_ep', 'paperbox_settle5p', 'fig33_v2_paper_dt1e4'],
  'cpus': $CPUS,
  'memory_mb': $MEM,
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

log "=== Q05 fig33 improve sweep start cpus=$CPUS mem_mb=$MEM ==="
init_state

# P0: Neo-Hooke (paper default FE material)
run_variant "fig33_v2_paper" \
  --contact-store-offsets \
  --material-model paper || log "WARN fig33_v2_paper failed"

# P0: elastic-plastic (yield 4.69 MPa)
run_variant "fig33_v2_ep" \
  --contact-store-offsets \
  --material-model elastic_plastic || log "WARN fig33_v2_ep failed"

# P1: ContactSettle 5% (early stiffness + contact pre-load)
run_variant "paperbox_settle5p" \
  --contact-store-offsets \
  --contact-settle --contact-settle-fraction 0.05 --contact-settle-soft-s0 0.02 \
  --material-model paper || log "WARN paperbox_settle5p failed"

# P1: sharper dynamics (no mass scaling)
run_variant "fig33_v2_paper_dt1e4" \
  --contact-store-offsets \
  --material-model paper \
  --explicit-dt 0.0001 --explicit-dt-mode fixed --no-mass-scaling || log "WARN fig33_v2_paper_dt1e4 failed"

finish_state
log "=== Q05 fig33 improve sweep finished ==="

python3 -c "
import json, datetime, os
from pathlib import Path
variants = ['fig33_v2_paper', 'fig33_v2_ep', 'paperbox_settle5p', 'fig33_v2_paper_dt1e4']
base = 'hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox'
rows = []
for v in variants:
    slug = f'{base}_{v}'
    sta = Path(f'output/jobs/{slug}/{slug}.sta')
    csv = Path(f'output/post/{slug}/{slug}_stress_strain.csv')
    done = sta.is_file() and 'COMPLETED SUCCESSFULLY' in sta.read_text(encoding='utf-8', errors='ignore')
    rows.append({'suffix': v, 'slug': slug, 'completed': done, 'csv_ready': csv.is_file()})
out = {'variants': rows, 'all_ready': all(r['csv_ready'] for r in rows), 'updated_at': datetime.datetime.now().isoformat(timespec='seconds')}
Path('output/logs/q05_fig33_improve_ready.json').write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print('Wrote output/logs/q05_fig33_improve_ready.json')
" >> "$LOG" 2>&1
