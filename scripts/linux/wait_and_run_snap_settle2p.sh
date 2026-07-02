#!/usr/bin/env bash
# Wait for fig33_snap_s78_el/s0_08/s0_12 to finish, then run settle2p serially.
#
#   nohup bash scripts/linux/wait_and_run_snap_settle2p.sh \
#     >> output/logs/paperbox_q05_fig33_snap_settle2p_tail.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

LOG="output/logs/paperbox_q05_fig33_snap_settle2p_tail.log"
VARIANT_SH="scripts/linux/run_paperbox_variant.sh"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"
EVAL="scripts/evaluate_paperbox_q05_trend.py"
SNAP="scripts/analyze_paperbox_snapthrough.py"
CPUS="${Q05_SNAP_CPUS:-48}"
MEM="${Q05_SNAP_MEMORY_MB:-262144}"
POLL_SEC="${Q05_SNAP_POLL_SEC:-120}"
TARGET_STRAIN="${Q05_SNAP_STRAIN:-0.78}"
SUFFIX="fig33_snap_s78_settle2p"
SLUG="hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${SUFFIX}"
OTHERS=(fig33_snap_s78_el fig33_snap_s78_s0_08 fig33_snap_s78_s0_12)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

slug_for() { echo "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_${1}"; }

job_completed() {
  [[ -f "output/jobs/${1}/${1}.sta" ]] && grep -q 'COMPLETED SUCCESSFULLY' "output/jobs/${1}/${1}.sta"
}

job_running() {
  local slug="$1"
  [[ -f "output/jobs/${slug}/${slug}.lck" ]] && return 0
  pgrep -f "mpiexec.hydra.*${slug}" >/dev/null 2>&1 || \
  pgrep -f "/bin/explicit.*${slug}" >/dev/null 2>&1
}

log "=== settle2p tail start ==="

while true; do
  pending=0
  for o in "${OTHERS[@]}"; do
    s="$(slug_for "$o")"
    if job_completed "$s"; then
      log "  done $o"
    elif job_running "$s"; then
      prog="$(grep -E '^[[:space:]]+[0-9]' "output/jobs/$s/$s.sta" 2>/dev/null | tail -1 | awk '{print $3}' || echo '?')"
      log "  run  $o sim=${prog}s"
      pending=$((pending + 1))
    else
      log "  wait $o (not started or stopped)"
      pending=$((pending + 1))
    fi
  done
  [[ "$pending" -eq 0 ]] && break
  sleep "$POLL_SEC"
done

log "parallel trio finished — prepare settle2p"

if job_completed "$SLUG"; then
  log "SKIP settle2p already COMPLETED"
  exit 0
fi

if job_running "$SLUG"; then
  log "settle2p already running — exit (manual watch)"
  exit 0
fi

# Drop incomplete settle2p attempt (parallel misfire left partial dir)
if [[ -d "output/jobs/${SLUG}" ]] && ! job_completed "$SLUG"; then
  log "clean incomplete settle2p job dir"
  rm -rf "output/jobs/${SLUG}"
fi

log "export + submit settle2p (serial, 48c, strain=$TARGET_STRAIN)"
bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --export-only --strain "$TARGET_STRAIN" \
  --contact-store-offsets --material-model elastic \
  --contact-settle --contact-settle-fraction 0.02 --contact-settle-soft-s0 0.02

bash "$VARIANT_SH" --Q 0.5 --variant-suffix "$SUFFIX" \
  --cpus "$CPUS" --memory-mb "$MEM" \
  --submit-only --strain "$TARGET_STRAIN" \
  --contact-store-offsets --material-model elastic \
  --contact-settle --contact-settle-fraction 0.02 --contact-settle-soft-s0 0.02

log "settle2p submitted (foreground submit returns when job ends)"

if job_completed "$SLUG"; then
  bash "$POSTPULL" "$SLUG" >> "$LOG" 2>&1 || true
  python3 "$EVAL" --slug "$SLUG" --write-json "output/logs/eval_q05_${SUFFIX}.json" >> "$LOG" 2>&1 || true
  python3 "$SNAP" --slug "$SLUG" --write-json "output/logs/snap_${SUFFIX}.json" >> "$LOG" 2>&1 || true
  log "=== settle2p tail done ==="
else
  log "WARN settle2p did not COMPLETED — check $SLUG.sta"
  exit 1
fi
