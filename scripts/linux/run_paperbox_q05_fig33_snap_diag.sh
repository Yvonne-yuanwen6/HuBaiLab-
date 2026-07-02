#!/usr/bin/env bash
# Q0.5 snap-through diagnostic sweep (elastic baseline, strain to 0.78, contact variants).
#
#   nohup bash scripts/linux/run_paperbox_q05_fig33_snap_diag.sh \
#     >> output/logs/paperbox_q05_fig33_snap_diag.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/logs output/reports/fig33_snap_diag

LOG="output/logs/paperbox_q05_fig33_snap_diag.log"
LOCK="$ROOT/output/logs/paperbox_q05_fig33_snap_diag.lock"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"
EVAL="scripts/evaluate_paperbox_q05_trend.py"
SNAP="scripts/analyze_paperbox_snapthrough.py"

CPUS="${Q05_SNAP_CPUS:-48}"
MEM="${Q05_SNAP_MEMORY_MB:-262144}"
POLL_SEC="${Q05_SNAP_POLL_SEC:-120}"
TARGET_STRAIN="${Q05_SNAP_STRAIN:-0.78}"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] snap diag already running (lock $LOCK)" >> "$LOG"
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
  local boot_wait=0
  local boot_max=600

  # After --submit-background, .lck may appear seconds later; do not treat as done.
  while ! job_running "$slug"; do
    if job_completed "$slug"; then
      return 0
    fi
    if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]] && \
       grep -qE 'NOT BEEN COMPLETED|exited with errors|MPI_Abort' "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null; then
      log "ERROR $slug failed during startup"
      return 1
    fi
    if [[ "$boot_wait" -ge "$boot_max" ]]; then
      log "ERROR $slug never acquired .lck within ${boot_max}s after submit"
      return 1
    fi
    log "WAIT $slug waiting for job start (${boot_wait}s)"
    sleep 10
    boot_wait=$((boot_wait + 10))
  done

  while job_running "$slug"; do
    local prog=""
    if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]]; then
      prog="$(tail -1 "$ROOT/output/jobs/${slug}/${slug}.sta" 2>/dev/null | tr -s ' ' | cut -c1-80 || true)"
    fi
    log "WAIT $slug ${prog:+( $prog )}"
    sleep "$POLL_SEC"
  done
  if [[ -f "$ROOT/output/jobs/${slug}/${slug}.sta" ]] && ! job_completed "$slug"; then
    log "ERROR $slug stopped without COMPLETED"
    return 1
  fi
  return 0
}

wait_for_other_snap_jobs() {
  local -a others=("fig33_snap_s78_el" "fig33_snap_s78_s0_08" "fig33_snap_s78_s0_12")
  log "wait for parallel batch to finish before settle2p"
  while true; do
    local pending=0
    for suffix in "${others[@]}"; do
      local slug
      slug="$(slug_for "$suffix")"
      if job_completed "$slug"; then
        continue
      fi
      if job_running "$slug"; then
        pending=$((pending + 1))
        continue
      fi
      log "WARN $suffix not running and not completed — still waiting"
      pending=$((pending + 1))
    done
    if [[ "$pending" -eq 0 ]]; then
      log "parallel batch done — ok to start settle2p"
      return 0
    fi
    log "parallel batch pending=$pending (sleep ${POLL_SEC}s)"
    sleep "$POLL_SEC"
  done
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
    python3 "$EVAL" --slug "$slug" --write-json "output/logs/eval_q05_${suffix}.json" >> "$LOG" 2>&1 || true
  fi
  if [[ -f "$SNAP" ]]; then
    python3 "$SNAP" --slug "$slug" --write-json "output/logs/snap_${suffix}.json" >> "$LOG" 2>&1 || true
  fi
}

run_variant() {
  local suffix="$1"
  shift
  local slug
  slug="$(slug_for "$suffix")"

  if job_completed "$slug"; then
    log "SKIP completed $suffix"
    postpull_and_eval "$suffix"
    return 0
  fi

  if job_running "$slug"; then
    log "RESUME running $suffix"
    wait_for_slug "$slug" || return 1
    postpull_and_eval "$suffix"
    return 0
  fi

  log "RUN Q=0.5 snap variant=$suffix strain=$TARGET_STRAIN cpus=$CPUS"
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --export-only --strain "$TARGET_STRAIN" "$@"
  bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$suffix" \
    --cpus "$CPUS" --memory-mb "$MEM" \
    --submit-background --submit-only --strain "$TARGET_STRAIN" "$@" || log "WARN submit $suffix"

  wait_for_slug "$slug" || return 1
  postpull_and_eval "$suffix"
  log "DONE $suffix"
}

log "=== Q05 snap diag start strain=$TARGET_STRAIN cpus=$CPUS ==="

# 1) elastic baseline (fig33_v2_el config, shorter stroke to snap band)
run_variant "fig33_snap_s78_el" \
  --contact-store-offsets \
  --material-model elastic || log "WARN fig33_snap_s78_el failed"

# 2) larger soft contact clearance (allow earlier slip / layer collapse)
run_variant "fig33_snap_s78_s0_08" \
  --contact-store-offsets \
  --material-model elastic \
  --contact-soft-clearance 0.08 || log "WARN fig33_snap_s78_s0_08 failed"

run_variant "fig33_snap_s78_s0_12" \
  --contact-store-offsets \
  --material-model elastic \
  --contact-soft-clearance 0.12 || log "WARN fig33_snap_s78_s0_12 failed"

# 3) minimal ContactSettle (2%) — serial after el/s0_08/s0_12 finish
wait_for_other_snap_jobs
run_variant "fig33_snap_s78_settle2p" \
  --contact-store-offsets \
  --material-model elastic \
  --contact-settle --contact-settle-fraction 0.02 --contact-settle-soft-s0 0.02 || log "WARN fig33_snap_s78_settle2p failed"

log "=== Q05 snap diag finished ==="

python3 -c "
import json, datetime
from pathlib import Path
variants = ['fig33_snap_s78_el', 'fig33_snap_s78_s0_08', 'fig33_snap_s78_s0_12', 'fig33_snap_s78_settle2p']
base = 'hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox'
rows = []
for v in variants:
    slug = f'{base}_{v}'
    sta = Path(f'output/jobs/{slug}/{slug}.sta')
    csv = Path(f'output/post/{slug}/{slug}_stress_strain.csv')
    done = sta.is_file() and 'COMPLETED SUCCESSFULLY' in sta.read_text(encoding='utf-8', errors='ignore')
    rows.append({'suffix': v, 'slug': slug, 'completed': done, 'csv_ready': csv.is_file()})
out = {'variants': rows, 'all_ready': all(r['csv_ready'] for r in rows), 'updated_at': datetime.datetime.now().isoformat(timespec='seconds')}
Path('output/logs/q05_fig33_snap_diag_ready.json').write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
" >> "$LOG" 2>&1
