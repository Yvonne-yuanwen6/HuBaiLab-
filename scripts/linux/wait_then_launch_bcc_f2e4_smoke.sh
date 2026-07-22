#!/usr/bin/env bash
# Wait until 批量构型 paperbox jobs finish, then launch ONE f2e4 smoke.
# Avoid touching /media/art/file until launch (FUSE can hang).
set -uo pipefail
ROOT=/media/art/file/XiangLang/Lattice/LWY/HuBaiLab
LOG=/tmp/bcc_qs_marlow_ss077_fast2e4_wait_launch.log

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" >>"$LOG"
}

batch_busy() {
  pgrep -af analysis.pyc 2>/dev/null | grep -F 'cae_tet0p6mm80_5mmin_paperbox' | grep -v grep >/dev/null 2>&1
}

bcc_busy() {
  pgrep -af analysis.pyc 2>/dev/null | grep -F 'bcc_marlow_ss077' | grep -v grep >/dev/null 2>&1
}

: >"$LOG"
log 'wait: f2e4 after batch clears (no fuse until launch)'
while batch_busy; do
  log 'batch still running; sleep 120'
  sleep 120
done
if bcc_busy; then
  log 'WARN another bcc_marlow job alive; abort'
  exit 1
fi
log 'clear; cd ROOT and launch f2e4 (cpus=32)'
cd "$ROOT" || {
  log 'FAIL cd ROOT'
  exit 1
}
rm -rf output/jobs/bcc_marlow_ss077_f2e4
export BCC_QS_PROBE_CPUS=32
bash scripts/linux/launch_bcc_qs_marlow_ss077_fast2e4_smoke.sh >>"$LOG" 2>&1
log "f2e4 launcher finished rc=$?"
