#!/usr/bin/env bash
# Preflight CPU/RAM before submitting an Abaqus job on the shared workstation.
# Called from submit_job.sh; override thresholds via env (see below).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=hubai_env.sh
. "$SCRIPT_DIR/hubai_env.sh"

ROOT="${ROOT:-$HU_BAI_REMOTE_ROOT}"
CPUS=8
MEMORY_MB=8192
FORCE=0

# Minimum GiB free beyond job memory request (default 32).
HEADROOM_GB="${HU_BAI_SUBMIT_HEADROOM_GB:-32}"
# Reject if (load_1min + requested_cpus) > nproc * this fraction (default 0.90).
MAX_LOAD_FRAC="${HU_BAI_SUBMIT_MAX_LOAD_FRAC:-0.90}"

usage() {
  echo "Usage: $0 [--root PATH] --cpus N --memory-mb N [--force]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEMORY_MB="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ "$CPUS" =~ ^[0-9]+$ && "$MEMORY_MB" =~ ^[0-9]+$ ]] || usage

if [[ "$FORCE" -eq 1 || "${HU_BAI_SKIP_RESOURCE_CHECK:-0}" == "1" ]]; then
  echo "[check_submit_resources] skipped (--force or HU_BAI_SKIP_RESOURCE_CHECK=1)"
  exit 0
fi

free_gb() {
  free -g | awk 'NR==2 {print $(NF)}'
}

nproc_total="$(nproc)"
load_1="$(awk '{print $1}' /proc/loadavg)"
avail_gb="$(free_gb)"
need_gb=$(( (MEMORY_MB + 1023) / 1024 + HEADROOM_GB ))
max_load="$(awk -v n="$nproc_total" -v f="$MAX_LOAD_FRAC" 'BEGIN { printf "%.1f", n * f }')"
projected_load="$(awk -v l="$load_1" -v c="$CPUS" 'BEGIN { printf "%.1f", l + c }')"
running_lck=0
if [[ -d "$ROOT/output/jobs" ]]; then
  running_lck="$(find "$ROOT/output/jobs" -name '*.lck' 2>/dev/null | wc -l | tr -d ' ')"
fi
running_abaqus="$(pgrep -fc 'explicit|standard' 2>/dev/null || true)"
running_abaqus="${running_abaqus:-0}"

echo "=== submit resource preflight $(date) ==="
echo "  request: cpus=$CPUS memory=${MEMORY_MB}MB (~$(( (MEMORY_MB + 1023) / 1024 ))GiB job heap)"
echo "  host:    nproc=$nproc_total load_1min=$load_1 projected_load=${projected_load} (limit~${max_load})"
echo "  memory:  available=${avail_gb}GiB need>=${need_gb}GiB (job+headroom=${HEADROOM_GB}GiB)"
echo "  running: abaqus_solvers=$running_abaqus hu_bai_lck=$running_lck"

mem_ok=0
cpu_ok=0
[[ "$avail_gb" -ge "$need_gb" ]] && mem_ok=1

# load_1min + requested cpus is a conservative proxy on shared hosts
if awk -v p="$projected_load" -v m="$max_load" 'BEGIN { exit (p <= m) ? 0 : 1 }'; then
  cpu_ok=1
fi

if [[ "$mem_ok" -eq 0 ]]; then
  echo "[ABORT] insufficient memory: ${avail_gb}GiB available < ${need_gb}GiB required"
  echo "  Wait for other jobs to finish or reduce --memory-mb / --cpus."
  echo "  Override: $0 --force ...  or  HU_BAI_SKIP_RESOURCE_CHECK=1"
  exit 2
fi

if [[ "$cpu_ok" -eq 0 ]]; then
  echo "[ABORT] insufficient CPU headroom: projected load ${projected_load} > ${max_load} (${nproc_total} cores * ${MAX_LOAD_FRAC})"
  echo "  Other users/jobs may be using the machine. Retry later or lower --cpus."
  echo "  Override: $0 --force ...  or  HU_BAI_SKIP_RESOURCE_CHECK=1"
  exit 2
fi

echo "=== preflight OK ==="
