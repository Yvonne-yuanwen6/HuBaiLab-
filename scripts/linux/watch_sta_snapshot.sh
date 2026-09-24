#!/usr/bin/env bash
# Remote one-shot snapshot for Abaqus Explicit job status (.lck / .sta / procs).
# Called from Windows: scripts/watch_remote_abaqus_progress.ps1
# Usage: watch_sta_snapshot.sh <job_dir> <slug> [case_id]
set +e
JOB="${1:?job_dir}"
SLUG="${2:?slug}"
CASE="${3:-}"
echo "HOST=$(hostname)"
echo "NOW=$(date '+%F %T')"
if [ -f "$JOB/$SLUG.lck" ]; then echo LCK=1; else echo LCK=0; fi
if [ -n "$CASE" ] && pgrep -f "$CASE/$SLUG" >/dev/null 2>&1; then
  echo ALIVE=1
elif pgrep -f "$JOB" >/dev/null 2>&1; then
  echo ALIVE=1
else
  echo ALIVE=0
fi
if [ -n "$CASE" ]; then
  EXPLICIT_N=$(pgrep -fc "explicit.*$CASE/$SLUG" 2>/dev/null || echo 0)
else
  EXPLICIT_N=$(pgrep -fc "explicit.*$SLUG" 2>/dev/null || echo 0)
fi
echo "EXPLICIT_N=$EXPLICIT_N"
ODB_MB=0
if [ -f "$JOB/$SLUG.odb" ]; then ODB_MB=$(du -m "$JOB/$SLUG.odb" | cut -f1); fi
echo "ODB_MB=$ODB_MB"
JOB_MB=$(du -sm "$JOB" 2>/dev/null | cut -f1)
echo "JOB_MB=$JOB_MB"
MEM_LINE=$(free -g | sed -n '2p')
echo "MEM_LINE=$MEM_LINE"
LOAD=$(cut -d' ' -f1 /proc/loadavg)
echo "LOAD1=$LOAD"
if [ -f "$JOB/$SLUG.sta" ]; then
  echo HAS_STA=1
  echo '---STA_TAIL---'
  tail -n 40 "$JOB/$SLUG.sta"
  echo '---STA_END---'
else
  echo HAS_STA=0
fi
