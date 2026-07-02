#!/usr/bin/env bash
# Poll fig33_v2_el fan-out until all CSVs ready; postpull stragglers; write ready manifest.
#
#   nohup bash scripts/linux/fig33_v2_el_morning_watch.sh \
#     >> output/logs/fig33_v2_el_morning_watch.log 2>&1 &
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"

LOG="output/logs/fig33_v2_el_morning_watch.log"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"
WRITE_READY="scripts/linux/fig33_v2_el_write_ready.sh"
POLL="${FIG33_V2_MORNING_POLL_SEC:-300}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

postpull_if_done() {
  python3 <<'PY'
import json
from pathlib import Path
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G

BASE = "cae_tet0p6mm80_5mmin_paperbox"
specs = [(1.5, "q15_v2_el"), (0.5, "fig33_v2_el"), (1.0, "fig33_v2_el"), (0.0, "fig33_v2_el")]
for q, suffix in specs:
    tag = G(cell_size=20, rod_diameter=2, amplitude=2, period_factor=q).variant_name.lower()
    print(f"hu_bai_{tag}_L20_4x4x4_solid_cad_f_{BASE}_{suffix}")
PY
}

log "morning watch start poll=${POLL}s"

while true; do
  for slug in $(postpull_if_done); do
    sta="$ROOT/output/jobs/${slug}/${slug}.sta"
    csv="$ROOT/output/post/${slug}/${slug}_stress_strain.csv"
    if [[ -f "$sta" ]] && grep -q 'COMPLETED SUCCESSFULLY' "$sta" && [[ ! -f "$csv" ]]; then
      log "postpull $slug"
      bash "$POSTPULL" "$slug" >> "$LOG" 2>&1 || log "WARN postpull $slug"
    fi
    if [[ -f "$ROOT/output/jobs/${slug}/${slug}.lck" ]]; then
      prog="$(tail -1 "$sta" 2>/dev/null | tr -s ' ' | cut -c1-72 || true)"
      log "RUNNING $slug ${prog:+( $prog )}"
    fi
  done

  bash "$WRITE_READY" >> "$LOG" 2>&1
  if python3 -c "import json; exit(0 if json.load(open('output/logs/fig33_v2_el_ready.json')).get('all_ready') else 1)"; then
    log "ALL READY — fig33_v2_el curves postpulled"
    break
  fi
  log "not all ready; sleep ${POLL}s"
  sleep "$POLL"
done

log "morning watch exit"
