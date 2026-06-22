#!/usr/bin/env bash
# Submit multiple HuBaiLab Abaqus jobs serially (one finishes, then the next).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CPUS=32
MEMORY_MB=131072
SLUGS=()
WAIT_FOR=""

usage() {
  echo "Usage: $0 [--cpus N] [--memory-mb N] [--wait-for SLUG] --slug SLUG [--slug SLUG ...]"
  echo "       $0 [--cpus N] [--memory-mb N] [--wait-for SLUG] --slugs-csv a,b,c"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpus) CPUS="$2"; shift 2 ;;
    --memory-mb) MEMORY_MB="$2"; shift 2 ;;
    --slug) SLUGS+=("$2"); shift 2 ;;
    --slugs-csv) IFS=',' read -ra _csv <<< "$2"; SLUGS+=("${_csv[@]}"); shift 2 ;;
    --wait-for) WAIT_FOR="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
done

[[ ${#SLUGS[@]} -gt 0 ]] || usage

trim() { local x="$1"; x="${x#"${x%%[![:space:]]*}"}"; x="${x%"${x##*[![:space:]]}"}"; printf '%s' "$x"; }

if [[ -n "$WAIT_FOR" ]]; then
  LCK="$ROOT/output/jobs/$WAIT_FOR/${WAIT_FOR}.lck"
  echo "=== Waiting for $WAIT_FOR (no .lck) ==="
  while [[ -f "$LCK" ]]; do
    echo "$(date '+%H:%M:%S')  still running: $WAIT_FOR"
    sleep 30
  done
  echo "=== $WAIT_FOR finished ==="
fi

for raw in "${SLUGS[@]}"; do
  s="$(trim "$raw")"
  [[ -n "$s" ]] || continue
  echo "========== $s cpus=$CPUS mem=${MEMORY_MB}MB =========="
  bash "$SCRIPT_DIR/submit_job.sh" --slug "$s" --cpus "$CPUS" --memory-mb "$MEMORY_MB" || {
    echo "[WARN] Job failed: $s (continuing queue)"
  }
done

echo "=== Queue finished ==="
