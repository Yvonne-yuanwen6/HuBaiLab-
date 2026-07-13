#!/bin/bash
# Unattended supervisor: build → eigen solve → extract for comsol_fig321_bcc_444.
# Logs to output/logs/comsol_fig321_bcc_444_supervisor.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck source=hubai_env.sh
. "$(dirname "$0")/hubai_env.sh"
export PYTHONPATH="$ROOT"
export COMSOL_BIN="${COMSOL_BIN:-/home/art/APP/comsol56/multiphysics/bin/comsol}"
export PATH="${COMSOL_BIN%/comsol}:${PATH}"

SLUG="comsol_fig321_bcc_444"
SUP_LOG="output/logs/${SLUG}_supervisor.log"
WATCH_LOG="output/logs/${SLUG}_watch.log"
PIPE_LOG="output/logs/${SLUG}_comsol_pipeline.log"
JOB_DIR="output/comsol_jobs/${SLUG}"
MPH="${JOB_DIR}/${SLUG}.mph"
SOLVED="${JOB_DIR}/${SLUG}_solved.mph"

mkdir -p output/logs output/comsol_jobs

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SUP_LOG"; }

log "=== supervisor start slug=$SLUG (sequential domain mesh) ==="

if command -v python3 >/dev/null 2>&1; then
  python3 scripts/_tmp_step_bbox.py output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step \
    >> "$SUP_LOG" 2>&1 || true
  python3 - <<'PY' >> "$SUP_LOG" 2>&1 || true
from src.comsol.hu_bai_settings import HuBaiComsolSettings
s = HuBaiComsolSettings(Q=0, nx=4, ny=4, nz=4, include_shaker_fixture=True)
cx, cy, cz = s.paper_box_import_center_mm
print("recenter_mm", (-cx, -cy, -cz))
print("stack_z table", s.shaker_table_z_bottom_mm, "->", s.z_min_mm,
      "lattice", s.z_min_mm, "->", s.z_max_mm,
      "plate", s.z_max_mm, "->", s.z_max_mm + s.top_plate_thickness_mm)
PY
fi

pkill -f "comsol_run_hu_bai.py.*${SLUG}" 2>/dev/null || true
pkill -f "watch_comsol_job.sh ${SLUG}" 2>/dev/null || true
sleep 2

log "launch pipeline"
bash scripts/linux/run_comsol_fig321_bcc_continue.sh >> "$PIPE_LOG" 2>&1 &
PIPE_PID=$!
log "pipeline PID=$PIPE_PID"

nohup bash scripts/linux/watch_comsol_job.sh "$SLUG" 60 >> "$WATCH_LOG" 2>&1 &
WATCH_PID=$!
log "watch PID=$WATCH_PID interval=60s"

BUILT_LOGGED=0
# 48 h max (build mesh can take 10+ h)
for i in $(seq 1 2880); do
  if [[ -f "$SOLVED" ]]; then
    log "SUCCESS: $SOLVED"
    ls -lh "$JOB_DIR/" >> "$SUP_LOG" 2>&1 || true
    exit 0
  fi
  if [[ -f "$MPH" && "$BUILT_LOGGED" -eq 0 ]]; then
    log "BUILD OK: $(ls -lh "$MPH")"
    BUILT_LOGGED=1
  fi
  if ! kill -0 "$PIPE_PID" 2>/dev/null; then
    wait "$PIPE_PID" 2>/dev/null || RC=$?
    log "pipeline exited rc=${RC:-?}"
    if [[ -f "$SOLVED" ]]; then
      log "SUCCESS after pipeline exit: $SOLVED"
      exit 0
    fi
    tail -40 "output/logs/${SLUG}_build.log" >> "$SUP_LOG" 2>&1 || true
    log "FAIL: no solved mph — see build log"
    exit 1
  fi
  if (( i % 10 == 0 )); then
    log "heartbeat $((i*60))s pipe=$PIPE_PID built=$([[ -f $MPH ]] && echo yes || echo no)"
    free -h | awk 'NR==2{print "  mem:", $3"/"$2}' >> "$SUP_LOG" 2>&1 || true
    ps aux | grep -E '[m]phserver|[c]omsol batch' | awk '{printf "  rss=%.1fGB pid=%s\n", $6/1024/1024, $2}' \
      | head -3 >> "$SUP_LOG" 2>&1 || true
    tail -3 "output/logs/${SLUG}_build.log" 2>/dev/null | sed 's/^/    /' >> "$SUP_LOG" || true
  fi
  sleep 60
done

log "TIMEOUT after 48h — check $WATCH_LOG and $PIPE_LOG"
exit 2
